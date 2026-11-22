"""Exact database matching against supplied complete reference rows; no live lookup."""
import datetime as dt
import re
import unicodedata
from zoneinfo import ZoneInfo

NORMALIZATION = 'NFKC; casefold; whitespace; typographic apostrophe/hyphen equivalents; periods removed. No accents, suffixes or name components removed; no fuzzy or nickname matching.'


def normalized(value):
    if not isinstance(value,str):return None
    text=unicodedata.normalize('NFKC',value).translate(str.maketrans({'\u2019':"'",'\u2010':'-','\u2011':'-','\u2013':'-'}))
    text=' '.join(text.replace('.','').casefold().split())
    if not text or not any(c.isalpha() for c in text) or any(not (c.isalpha() or c in " '-") for c in text):return None
    return text


def day(value):
    if type(value) is dt.date:return value
    if isinstance(value,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):return dt.date.fromisoformat(value)
    raise ValueError('Calendar date required; no inferred intraday timestamp')


def resolve_candidate(candidate, players, rosters, team_id, game_date, published_at):
    """Caller must supply complete relevant references and verify their provenance.

    players: player_id,name rows for the full lookup catalog, including duplicates.
    rosters: season,player_id,team_id,as_of_date rows for relevant players/dates.
    A successful supplied-data match is not historical publication or model approval.
    """
    game_date=day(game_date)
    if not isinstance(published_at,dt.datetime) or published_at.tzinfo is None or published_at.utcoffset() is None:
        raise ValueError('Aware source publication time required')
    cutoff=min(game_date,published_at.astimezone(ZoneInfo('America/New_York')).date())
    season=game_date.year+int(game_date.month>=10)
    result={'player_id':None,'match_verified':False,'match_status':'invalid_name','lookup_name':None,
        'database_name':None,'name_match_count':0,'candidate_player_ids':[],
        'roster_as_of_date':None,'roster_team_id':None,'roster_cutoff_date_exclusive':cutoff.isoformat(),
        'normalization_policy':NORMALIZATION,'match_scope':'Supplied complete database catalog and supplied dated team references only.',
        'reference_provenance_verified':False,'historical_publication_verified':False,
        'model_input_approved':False,'betting_release':False}
    if not isinstance(candidate,str) or candidate.count(',')!=1:return result
    surname,given=candidate.split(',')
    if normalized(surname) is None or normalized(given) is None:return result
    key=normalized(given+' '+surname);result['lookup_name']=key
    matches=[p for p in players if normalized(p.get('name'))==key]
    result['name_match_count']=len(matches)
    result['candidate_player_ids']=sorted({p['player_id'] for p in matches if isinstance(p.get('player_id'),str) and p['player_id'].strip()})
    if not matches:result['match_status']='name_not_found';return result
    if len(matches)!=1:result['match_status']='ambiguous_name';return result
    match=matches[0];pid=match.get('player_id');result['database_name']=match.get('name')
    if not isinstance(pid,str) or not pid.strip():result['match_status']='invalid_database_id';return result
    if sum(p.get('player_id')==pid for p in players)!=1:
        result['match_status']='duplicate_database_id';return result
    if not isinstance(team_id,str) or not team_id.strip():result['match_status']='invalid_team_reference';return result
    relevant=[]
    for r in rosters:
        if r.get('player_id')!=pid:continue
        if type(r.get('season')) is not int:result['match_status']='invalid_roster_reference';return result
        if r['season']!=season:continue
        try:date=day(r.get('as_of_date'))
        except (TypeError,ValueError):result['match_status']='invalid_roster_reference';return result
        if date<cutoff:relevant.append((date,r))
    if not relevant:result['match_status']='prior_roster_missing';return result
    latest=max(date for date,r in relevant);latest_rows=[r for date,r in relevant if date==latest]
    result['roster_as_of_date']=latest.isoformat()
    if len(latest_rows)!=1:result['match_status']='prior_roster_ambiguous';return result
    roster_team=latest_rows[0].get('team_id');result['roster_team_id']=roster_team
    if not isinstance(roster_team,str) or not roster_team.strip():result['match_status']='invalid_roster_reference';return result
    if roster_team!=team_id:result['match_status']='roster_team_conflict';return result
    result.update(player_id=pid,match_verified=True,match_status='unique_exact_name_and_prior_team_reference')
    return result
