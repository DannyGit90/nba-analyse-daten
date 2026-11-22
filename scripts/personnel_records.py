"""Parse official personnel text into name candidates, never player identities or tips."""
import datetime as dt
import hashlib
import json
import os
import re
import unicodedata
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

STATUSES = {s.casefold():s for s in ('Out','Questionable','Doubtful','Probable','Available')}
SUFFIXES = {'jr.','sr.','jr','sr','ii','iii','iv'}
PARTICLES = {'de','da','del','di','dos','van','von'}
TEAMS = set('ATL BOS BKN CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHX POR SAC SAS TOR UTA WAS'.split())
SOURCE_URL = re.compile(r'https://ak-static\.cms\.nba\.com/referee/injury/Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)\.pdf')


def stamp(value):
    if not isinstance(value,str):raise ValueError('Timestamp string required')
    t=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('Timezone required')
    return t


def joined(parts):
    text=' '.join(' '.join(parts).split())
    return re.sub(r'-\s+(?=[^\W\d_])','-',unicodedata.normalize('NFKC',text))


def name_part(text):
    return bool(text) and any(c.isalpha() for c in text) and all(c.isalpha() or c in " '-.\u2019" for c in text)


def parse_section(section):
    result={k:section.get(k) for k in ('game_date_et','away','home','team','status','raw_text')}
    result.update(players=[],errors=[],parsing_complete=False,player_level_assessment_complete=False)
    try:
        dt.date.fromisoformat(result['game_date_et'])
        if result['away'] not in TEAMS or result['home'] not in TEAMS or result['away']==result['home'] or result['team'] not in (result['away'],result['home']):
            raise ValueError('Invalid section identity')
    except (ValueError,TypeError):
        result['errors']=['invalid_section_identity'];return result
    raw=result['raw_text']
    if not isinstance(raw,str):result['errors']=['invalid_raw_text'];return result
    if result['status']=='not_submitted':
        result['parsing_complete']=' '.join(raw.split())=='NOT YET SUBMITTED'
        if not result['parsing_complete']:result['errors']=['submission_status_text_mismatch']
        return result
    if result['status']!='reported_raw':result['errors']=['upstream_section_unresolved'];return result
    original=raw.splitlines()
    numbered=[(i+1,line.strip()) for i,line in enumerate(original) if line.strip()]
    lines=[line for _,line in numbered];starts=[];claimed=set();previous=-1
    for index,line in enumerate(lines):
        if line.casefold() not in STATUSES:continue
        commas=[j for j in range(previous+1,index) if ',' in lines[j]]
        previous=index
        if len(commas)!=1 or lines[commas[0]].count(',')!=1:
            result['errors'].append('status_without_unique_name');continue
        comma=commas[0];start=comma
        surname,inline=lines[comma].split(',',1)
        if surname.casefold() in SUFFIXES:
            if start==0:result['errors'].append('surname_suffix_without_base');continue
            start-=1;surname=lines[start]+' '+surname
        while start>0:
            fragment=lines[start-1]
            if not fragment.endswith('-') or not name_part(fragment[:-1]) or any(c.isspace() for c in fragment):break
            start-=1;surname=fragment+surname
        while start>0 and lines[start-1].casefold() in PARTICLES:
            start-=1;surname=lines[start]+' '+surname
        given=joined([inline]+lines[comma+1:index]);surname=joined([surname])
        if not name_part(surname) or not name_part(given):
            result['errors'].append('invalid_name_candidate');continue
        starts.append((start,index,surname+', '+given))
        claimed.update(range(start,index))
    if not starts:result['errors'].append('no_supported_player_records')
    if starts and starts[0][0]!=0:result['errors'].append('unparsed_leading_text')
    if any(',' in line and i not in claimed for i,line in enumerate(lines)):
        result['errors'].append('unparsed_name_or_comma')
    names=set()
    for n,(start,status_index,name) in enumerate(starts):
        end=starts[n+1][0] if n+1<len(starts) else len(lines)
        first=numbered[start][0];status_line=numbered[status_index][0]
        last=numbered[end-1][0]
        if name.casefold() in names:result['errors'].append('duplicate_name_candidate')
        names.add(name.casefold())
        result['players'].append({'name_candidate':name,'status':STATUSES[lines[status_index].casefold()],
            'status_raw':lines[status_index],'reason_text':joined(original[status_line:last]),
            'source_line_start':first,'source_status_line':status_line,'source_line_end':last,
            'raw_name_text':'\n'.join(original[first-1:status_line-1]),
            'raw_reason_text':'\n'.join(original[status_line:last]),
            'player_id':None,'identity_verified':False})
    result['errors']=sorted(set(result['errors']))
    result['parsing_complete']=bool(result['players']) and not result['errors']
    for player in result['players']:player['usable_for_identity_lookup']=result['parsing_complete']
    return result


def build(source, now, run_started=None):
    if now.tzinfo is None:raise ValueError('Aware processing time required')
    if not isinstance(source,dict):raise ValueError('Source object required')
    if source.get('schema')!='official-personnel-v1' or source.get('status')!='captured_raw' or source.get('betting_release') is not False:
        raise ValueError('Source snapshot not successfully captured')
    published=stamp(source['source_published_at_utc']);retrieved=stamp(source['retrieved_at_utc']);checked=stamp(source['checked_at_utc'])
    if not published<=retrieved<=checked<=now or now-published>dt.timedelta(hours=8):
        raise ValueError('Source time stale, future or inconsistent')
    if run_started is not None and checked<stamp(run_started):raise ValueError('Source snapshot is from an earlier run')
    match=SOURCE_URL.fullmatch(source.get('source',''))
    if not match or not re.fullmatch(r'[0-9a-f]{64}',source.get('pdf_sha256','')):raise ValueError('Source provenance missing')
    url_time=dt.datetime.strptime(' '.join(match.groups()),'%Y-%m-%d %I %M %p').replace(tzinfo=ZoneInfo('America/New_York'))
    if url_time.replace(fold=0).utcoffset()!=url_time.replace(fold=1).utcoffset() or url_time!=published:
        raise ValueError('Source URL/publication time mismatch')
    sections=source.get('sections')
    if not isinstance(sections,list) or not sections or any(not isinstance(x,dict) for x in sections):
        raise ValueError('Source sections missing')
    output=[];seen={}
    for section in sections:
        parsed=parse_section(section);key=json.dumps([parsed[k] for k in ('game_date_et','away','home','team')],sort_keys=True)
        if key in seen:
            for item in (output[seen[key]],parsed):
                item['errors']=sorted(set(item['errors']+['duplicate_section_key']))
                item['parsing_complete']=False
                for p in item['players']:p['usable_for_identity_lookup']=False
        else:seen[key]=len(output)
        output.append(parsed)
    return {'schema':'personnel-records-v1','generated_at_utc':now.isoformat(),'execution_ok':True,
        'source':source['source'],'source_checked_at_utc':source['checked_at_utc'],
        'source_published_at_utc':source['source_published_at_utc'],'source_retrieved_at_utc':source['retrieved_at_utc'],'source_pdf_sha256':source['pdf_sha256'],
        'sections':output,'section_count':len(output),'player_record_count':sum(len(s['players']) for s in output),
        'unresolved_section_count':sum(not s['parsing_complete'] for s in output),
        'not_submitted_section_count':sum(s['status']=='not_submitted' for s in output),
        'parsing_complete':all(s['parsing_complete'] for s in output),
        'identity_resolution_complete':False,'player_level_assessment_complete':False,'model_input_approved':False,
        'betting_release':False,'limitations':['Parsing completeness is not roster coverage, verified identity, personal impact assessment or recommendation.',
            'Only statuses explicitly present in the official source are represented. An omitted player is not inferred healthy.']}


def cell(value):
    return escape(str(value)).replace('|','&#124;').replace('\n',' ')


def write_report(result, root=Path('reports/injury')):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    (root/'players_latest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# Strukturierte Spielerstatus-Daten','', 'Verarbeitungszeit UTC: '+result['generated_at_utc'],
        'Ausfuehrung erfolgreich: '+str(result['execution_ok']),
        'Namenskandidaten ohne verifizierte Spieler-ID. Keine Rollenbewertung oder Wettfreigabe.','']
    if result.get('error'):lines+=['Fehler: '+cell(result['error']),'']
    if result['execution_ok']:
        lines+=['Quellenzeit UTC: '+result['source_published_at_utc'],
            'Datensaetze: '+str(result['player_record_count'])+'; ungeklaerte Abschnitte: '+str(result['unresolved_section_count']),
            '[Vollstaendige Datensaetze und Originaltext](players_latest.json) | [Quellbericht](latest.json)','']
        for s in result['sections']:
            lines+=['## '+cell(' '.join(str(s[k]) for k in ('game_date_et','away','home','team'))),
                'Quellenstatus: '+cell(s['status'])+'; Parser vollstaendig: '+str(s['parsing_complete']),
                'Offene Parserbefunde: '+cell(', '.join(s['errors']) or 'keine'),'',
                '| Namenskandidat | Gemeldeter Status | Quellgrund |','|---|---|---|']
            lines+=['| '+' | '.join(cell(p[k]) for k in ('name_candidate','status','reason_text'))+' |' for p in s['players']]
            lines+=['']
    (root/'players_latest.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    folder=Path('reports/injury');now=dt.datetime.now(dt.timezone.utc);raw=None;source={}
    try:
        raw=(folder/'latest.json').read_bytes();source=json.loads(raw)
        if os.environ.get('PERSONNEL_RECORD_TESTS_OK')!='success':raise ValueError('Player parser tests not successful')
        started=os.environ.get('NBA_PERSONNEL_RUN_STARTED_AT')
        if not started:raise ValueError('Run start binding missing')
        result=build(source,now,started)
    except Exception as exc:
        result={'schema':'personnel-records-v1','generated_at_utc':now.isoformat(),'execution_ok':False,
            'error':(type(exc).__name__+': '+str(exc))[:300],'sections':[],'betting_release':False,'model_input_approved':False}
    result['source_snapshot_sha256']=hashlib.sha256(raw).hexdigest() if raw is not None else None
    write_report(result,folder)
    try:
        path=folder/'latest.md';body=path.read_text()
        if not isinstance(source,dict) or ('Pruefzeit UTC: '+str(source.get('checked_at_utc'))) not in body:
            raise ValueError('Raw report snapshot mismatch')
        marker='\n## Strukturierte Spielerstatus-Daten\n'
        body=body.split(marker)[0].rstrip()+marker+'\n[Spielerstatus-Bericht](players_latest.md) | [Datensaetze](players_latest.json)\n\nKeine Spieler-ID-, Rollen- oder Modellfreigabe.\n'
        path.write_text(body,encoding='utf-8');result['raw_report_linked']=True
    except Exception:
        result['raw_report_linked']=False
    write_report(result,folder)
    raise SystemExit(0 if result['execution_ok'] and result['raw_report_linked'] else 1)


if __name__=='__main__':
    main()
