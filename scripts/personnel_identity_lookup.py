"""Same-run read-only identity lookup. Database matches are not model approvals."""
import datetime as dt
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo
from personnel_identity import day, resolve_candidate
from personnel_records import build as replay, stamp, cell
from player_source_probe import SOURCE, rows


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True,default=str,separators=(',',':')).encode()).hexdigest()


def validate_inputs(raw_bytes, parsed_bytes, now, started):
    if any(not isinstance(x,bytes) or len(x)>2000000 for x in (raw_bytes,parsed_bytes)):
        raise ValueError('Input byte-size guard exceeded')
    raw=json.loads(raw_bytes);parsed=json.loads(parsed_bytes)
    if not isinstance(parsed,dict) or parsed.get('execution_ok') is not True:raise ValueError('Player parser did not succeed')
    if parsed.get('source_snapshot_sha256')!=hashlib.sha256(raw_bytes).hexdigest():raise ValueError('Raw source hash mismatch')
    if not stamp(started)<=stamp(parsed['generated_at_utc'])<=now:raise ValueError('Player data not from this run')
    expected=replay(raw,now,started)
    if any(parsed.get(k)!=v for k,v in expected.items() if k!='generated_at_utc'):
        raise ValueError('Player records differ from replayed source')
    if expected['section_count']>100 or expected['player_record_count']>1000:raise ValueError('Record resource guard exceeded; no truncation allowed')
    return raw,parsed


def resolve_rows(con, parsed, now):
    published=stamp(parsed['source_published_at_utc']);entries=[];work=[]
    for si,s in enumerate(parsed['sections']):
        for pi,p in enumerate(s['players']):
            e={k:s[k] for k in ('game_date_et','away','home','team')}
            e.update(section_index=si,source_record_index=pi,name_candidate=p['name_candidate'],status=p['status'],
                match={'player_id':None,'match_verified':False,'match_status':'parser_unresolved'})
            entries.append(e)
            if s['parsing_complete'] and not s['errors'] and p.get('usable_for_identity_lookup') is True:
                d=day(s['game_date_et']);cut=min(d,published.astimezone(ZoneInfo('America/New_York')).date())
                work.append((e,d,d.year+int(d.month>=10),cut))
    catalog=[];proofs=[]
    if work:
        catalog=rows(con,'SELECT player_id,name FROM nba.main.players ORDER BY player_id,name LIMIT 20001')
        if not catalog or len(catalog)>20000:raise ValueError('Empty or oversized player catalog; no truncated matching')
        groups={};requests=defaultdict(set)
        for e,d,season,cut in work:
            if season not in groups:
                groups[season]=rows(con,'SELECT nba_abbrev,team_id FROM nba.main.team_seasons WHERE season=? AND is_nba=true ORDER BY nba_abbrev,team_id',[season])
            team=[r['team_id'] for r in groups[season] if r['nba_abbrev']==e['team']]
            tid=team[0] if len(team)==1 and isinstance(team[0],str) and team[0].strip() else None
            e['team_mapping_status']='unique' if tid is not None else 'missing_or_ambiguous'
            e['expected_team_id']=tid
            e['match']=resolve_candidate(e['name_candidate'],catalog,[],tid,d,published)
            if e['match']['match_status']=='prior_roster_missing':
                requests[(season,cut)].update(e['match']['candidate_player_ids'])
        if len(requests)>4:raise ValueError('Too many roster lookup groups; no partial matching')
        roster_sets={}
        for (season,cut),ids in sorted(requests.items()):
            ids=sorted(ids);marks=','.join('?' for _ in ids)
            sql='WITH latest AS (SELECT player_id,max(as_of_date) AS as_of_date FROM nba.main.rosters_daily WHERE season=? AND as_of_date<? AND player_id IN ('+marks+') GROUP BY player_id) SELECT r.season,r.player_id,r.team_id,r.as_of_date FROM nba.main.rosters_daily r JOIN latest l ON r.player_id=l.player_id AND r.as_of_date=l.as_of_date WHERE r.season=? ORDER BY r.player_id,r.as_of_date,r.team_id'
            roster_sets[(season,cut)]=rows(con,sql,[season,cut]+ids+[season])
            proof={'season':season,'cutoff_exclusive':cut.isoformat(),'player_ids_requested':len(ids),
                'rows_read':len(roster_sets[(season,cut)]),'rows_sha256':digest(roster_sets[(season,cut)])}
            proofs.append(proof)
        for e,d,season,cut in work:
            if e['match']['match_status']=='prior_roster_missing':
                e['match']=resolve_candidate(e['name_candidate'],catalog,roster_sets[(season,cut)],e['expected_team_id'],d,published)
    collisions=defaultdict(list)
    for e in entries:
        if e['match']['match_verified']:collisions[(e['section_index'],e['match']['player_id'])].append(e)
    for values in collisions.values():
        if len(values)>1:
            for e in values:e['match'].update(player_id=None,match_verified=False,match_status='duplicate_id_in_section')
    matched=sum(e['match']['match_verified'] for e in entries)
    return {'schema':'personnel-identities-v1','generated_at_utc':now.isoformat(),'execution_ok':True,
        'database_source':SOURCE,'database_read_only':True,'catalog_rows':len(catalog),'catalog_sha256':digest(catalog),
        'roster_query_proofs':proofs,'records':entries,'record_count':len(entries),'matched_records':matched,
        'unmatched_records':len(entries)-matched,'all_reported_records_matched':bool(entries) and matched==len(entries) and parsed['unresolved_section_count']==0,
        'match_status_counts':dict(Counter(e['match']['match_status'] for e in entries)),
        'unresolved_source_sections':parsed['unresolved_section_count'],'not_submitted_source_sections':parsed['not_submitted_section_count'],
        'source_published_at_utc':parsed['source_published_at_utc'],'parser_generated_at_utc':parsed['generated_at_utc'],
        'historical_publication_verified':False,'player_level_assessment_complete':False,'model_input_approved':False,'betting_release':False,
        'limitations':['Only named source records are matched, not all roster players. Missing source entries do not mean healthy.',
            'Database matches use the exact policy from 5a and earlier dated team references; not independent identity-registry or historical publication verification.',
            'Resource limits reject the lookup instead of silently omitting records. No probabilities, injury weights or recommendations.']}


def lookup(raw_bytes, parsed_bytes, now, started, connector=None):
    raw,parsed=validate_inputs(raw_bytes,parsed_bytes,now,started)
    con=None
    try:
        if connector is None:
            import duckdb
            connector=duckdb.connect
        con=connector();con.execute("ATTACH '"+SOURCE+"' AS nba (READ_ONLY)")
        result=resolve_rows(con,parsed,now)
    finally:
        if con is not None:con.close()
    result['source']=raw['source'];result['source_pdf_sha256']=raw['pdf_sha256']
    result['source_checked_at_utc']=raw['checked_at_utc']
    result['raw_snapshot_sha256']=hashlib.sha256(raw_bytes).hexdigest()
    result['player_snapshot_sha256']=hashlib.sha256(parsed_bytes).hexdigest()
    return result


def write_report(result, root=Path('reports/injury')):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    (root/'identities_latest.json').write_text(json.dumps(result,ensure_ascii=False,default=str,indent=2)+'\n',encoding='utf-8')
    text=['# Spieler-ID-Zuordnungen','', 'Verarbeitungszeit UTC: '+result['generated_at_utc'],
        'Ausfuehrung erfolgreich: '+str(result['execution_ok']),
        'Datenbankabgleich, keine sportliche Bewertung und keine Wettfreigabe.','']
    if result.get('error'):text+=['Fehler: '+cell(result['error']),'']
    if result['execution_ok']:
        text+=['Datensaetze: '+str(result['record_count'])+'; zugeordnet: '+str(result['matched_records'])+'; offen: '+str(result['unmatched_records']),
            'Ungeklaerte Quellabschnitte: '+str(result['unresolved_source_sections'])+'; nicht eingereicht: '+str(result['not_submitted_source_sections']),
            '[Quellen und Abgleichdetails](identities_latest.json) | [Spielerstatus](players_latest.md)','',
            '| Spieltag ET / Partie / Team | Namenskandidat | Datenbankname | Spieler-ID (DB) | Abgleichstatus | Kaderdatum |',
            '|---|---|---|---|---|---|']
        for e in result['records']:
            m=e['match'];values=[' '.join(e[k] for k in ('game_date_et','away','home','team')),e['name_candidate'],m.get('database_name') or '-',m.get('player_id') or '-',m['match_status'],m.get('roster_as_of_date') or '-']
            text+=['| '+' | '.join(cell(v) for v in values)+' |']
        text+=['']+result['limitations']
    (root/'identities_latest.md').write_text('\n'.join(text)+'\n',encoding='utf-8')


def main():
    folder=Path('reports/injury');now=dt.datetime.now(dt.timezone.utc);parsed={}
    try:
        if os.environ.get('PERSONNEL_IDENTITY_TESTS_OK')!='success' or os.environ.get('PERSONNEL_LOOKUP_TESTS_OK')!='success':
            raise ValueError('Identity test prerequisites not successful')
        raw=(folder/'latest.json').read_bytes();typed=(folder/'players_latest.json').read_bytes();parsed=json.loads(typed)
        result=lookup(raw,typed,now,os.environ.get('NBA_PERSONNEL_RUN_STARTED_AT'))
    except Exception as exc:
        result={'schema':'personnel-identities-v1','generated_at_utc':now.isoformat(),'execution_ok':False,
            'error':(type(exc).__name__+': '+str(exc))[:400],'records':[],'model_input_approved':False,'betting_release':False}
    write_report(result,folder)
    try:
        path=folder/'players_latest.md';body=path.read_text()
        if not isinstance(parsed,dict) or ('Verarbeitungszeit UTC: '+str(parsed.get('generated_at_utc'))) not in body:
            raise ValueError('Player report snapshot mismatch')
        marker='\n## Spieler-ID-Abgleich\n'
        path.write_text(body.split(marker)[0].rstrip()+marker+'\n[Zuordnungsbericht](identities_latest.md) | [Abgleichdaten](identities_latest.json)\n\nKeine Rollen-, Modell- oder Wettfreigabe.\n',encoding='utf-8')
        result['player_report_linked']=True
    except Exception:result['player_report_linked']=False
    write_report(result,folder)
    raise SystemExit(0 if result['execution_ok'] and result['player_report_linked'] else 1)


if __name__=='__main__':
    main()
