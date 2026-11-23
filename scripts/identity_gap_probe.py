"""Read-only diagnosis of unmatched personnel names; never changes matching policy."""
import datetime as dt
import hashlib
import json
import os
import unicodedata
from pathlib import Path
from personnel_identity import day, normalized
from player_source_probe import SOURCE, rows

LIMIT = 20
SPECIAL = str.maketrans({'\u0111':'d','\u00f8':'o','\u0142':'l','\u00df':'ss','\u00e6':'ae','\u0131':'i','\u00f0':'d','\u00fe':'th'})


def fold(value):
    text = normalized(value)
    if text is None:
        return None
    text = unicodedata.normalize('NFKD',text.translate(SPECIAL))
    return ''.join(c for c in text if not unicodedata.combining(c))


def lookup_key(candidate):
    if not isinstance(candidate,str) or candidate.count(',')!=1:
        return None
    surname,given = candidate.split(',')
    return given.strip()+' '+surname.strip()


def roster_relation(pid, expected_team, references):
    items = references.get(pid,[])
    if not items:
        return {'relation':'missing','as_of_date':None,'team_id':None}
    latest = max(r['as_of_date'] for r in items)
    newest = [r for r in items if r['as_of_date']==latest]
    if len(newest)!=1:
        return {'relation':'ambiguous','as_of_date':latest.isoformat(),'team_id':None}
    team = newest[0]['team_id']
    return {'relation':'matching_prior_team' if team==expected_team else 'different_prior_team','as_of_date':latest.isoformat(),'team_id':team}


def classify(record, catalog, references):
    key = lookup_key(record['name_candidate'])
    exact = [p for p in catalog if key is not None and normalized(p['name'])==normalized(key)]
    folded = [p for p in catalog if key is not None and fold(p['name'])==fold(key)]
    exact_ids = {p['player_id'] for p in exact}
    folded_only = [p for p in folded if p['player_id'] not in exact_ids]
    expected = record.get('expected_team_id')
    def describe(items):
        return [{'player_id':p['player_id'],'database_name':p['name'],**roster_relation(p['player_id'],expected,references)} for p in items]
    exact_d,folded_d = describe(exact),describe(folded_only)
    if len(exact_d)>1:
        label = 'duplicate_exact_names'
    elif not exact_d and len(folded_d)==1:
        label = 'single_accent_or_special_letter_difference'
    elif not exact_d and len(folded_d)>1:
        label = 'multiple_accent_folded_candidates'
    elif not exact_d:
        label = 'no_candidate_under_either_normalization'
    else:
        label = 'exact_match_not_unresolved'
    everyone = exact_d+folded_d
    matching = [p for p in everyone if p['relation']=='matching_prior_team']
    return {'name_candidate':record['name_candidate'],'team':record['team'],'game_date_et':record['game_date_et'],
        'expected_team_id':expected,'original_match_status':record['match']['match_status'],
        'reported_status':record['status'],'diagnosis':label,'exact_candidates':exact_d,'accent_folded_only_candidates':folded_d,
        'single_candidate_with_matching_prior_team':len(matching)==1 and len(everyone)==1,
        'match_verified_by_this_probe':False,'matching_policy_changed':False}


def load_references(con, ids, cutoff, season):
    ids = sorted(set(ids))
    if not ids:
        return {}
    marks = ','.join('?' for _ in ids)
    sql = ('WITH latest AS (SELECT player_id,max(as_of_date) AS as_of_date FROM nba.main.rosters_daily WHERE season=? AND as_of_date<? AND player_id IN ('+marks+') GROUP BY player_id) '
           'SELECT r.player_id,r.team_id,r.as_of_date FROM nba.main.rosters_daily r JOIN latest l ON r.player_id=l.player_id AND r.as_of_date=l.as_of_date WHERE r.season=? ORDER BY r.player_id,r.team_id LIMIT 1001')
    found = rows(con,sql,[season,cutoff]+ids+[season])
    if len(found)>1000:
        raise ValueError('Roster reference limit exceeded')
    grouped = {}
    for r in found:
        grouped.setdefault(r['player_id'],[]).append(r)
    return grouped


def diagnose(con, identities):
    if identities.get('execution_ok') is not True or identities.get('betting_release') is not False:
        raise ValueError('Unsuitable identity report')
    unresolved = [r for r in identities['records'] if r['match']['match_verified'] is not True]
    if len(unresolved)>LIMIT:
        raise ValueError('Too many unresolved records for bounded diagnosis')
    if not unresolved:
        return {'status':'nothing_to_diagnose','records':[]}
    catalog = rows(con,'SELECT player_id,name FROM nba.main.players ORDER BY player_id,name LIMIT 20001')
    if not catalog or len(catalog)>20000:
        raise ValueError('Empty or oversized player catalog')
    output = []
    for r in unresolved:
        try:
            cutoff = day(r['game_date_et'])
            season = cutoff.year+int(cutoff.month>=10)
            key = lookup_key(r['name_candidate'])
            ids = [p['player_id'] for p in catalog if key is not None and fold(p['name'])==fold(key)]
            output.append(classify(r,catalog,load_references(con,ids,cutoff,season)))
        except Exception as exc:
            output.append({'name_candidate':r.get('name_candidate'),'diagnosis':'diagnosis_error','error':str(exc)[:300],
                           'match_verified_by_this_probe':False,'matching_policy_changed':False})
    return {'status':'diagnosed','records':output,'catalog_rows':len(catalog),
            'catalog_sha256':hashlib.sha256(json.dumps(catalog,sort_keys=True,default=str).encode()).hexdigest()}


def main():
    now = dt.datetime.now(dt.timezone.utc)
    report = {'schema':'identity-gap-probe-v1','generated_at_utc':now.isoformat(),'source':SOURCE,'read_only':True,'execution_ok':False,
              'run_id':os.environ.get('GITHUB_RUN_ID'),'source_commit_sha':os.environ.get('GITHUB_SHA'),
              'matching_policy_changed':False,'model_input_approved':False,'betting_release':False}
    con = None
    try:
        body = (Path('reports/injury')/'identities_latest.json').read_bytes()
        if len(body)>2000000:
            raise ValueError('Identity report too large')
        identities = json.loads(body)
        report['identities_sha256'] = hashlib.sha256(body).hexdigest()
        report['identities_generated_at_utc'] = identities.get('generated_at_utc')
        import duckdb
        con = duckdb.connect()
        con.execute("ATTACH '"+SOURCE+"' AS nba (READ_ONLY)")
        report.update(diagnose(con,identities))
        report['execution_ok'] = True
    except Exception as exc:
        report['error'] = (type(exc).__name__+': '+str(exc))[:400]
    finally:
        if con is not None:
            con.close()
    folder = Path('probe-results')
    folder.mkdir(exist_ok=True)
    (folder/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False,default=str)+'\n')
    print(json.dumps(report,indent=2,allow_nan=False,default=str))
    return 0 if report['execution_ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
