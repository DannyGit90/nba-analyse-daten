import copy
import datetime as dt
import unittest
from personnel_identity import normalized,resolve_candidate


class PersonnelIdentityTests(unittest.TestCase):
    def setUp(self):
        self.players=[{'player_id':'P1','name':'Shai Gilgeous-Alexander'}]
        self.rosters=[{'season':2027,'player_id':'P1','team_id':'T1','as_of_date':'2026-11-20'}]
        self.published=dt.datetime.fromisoformat('2026-11-21T23:30:00+00:00')

    def resolve(self,name='Gilgeous-Alexander, Shai',game='2026-11-22'):
        return resolve_candidate(name,self.players,self.rosters,'T1',game,self.published)

    def test_unique_match_is_not_model_or_provenance_approval(self):
        r=self.resolve();self.assertTrue(r['match_verified']);self.assertEqual(r['player_id'],'P1')
        for key in ['reference_provenance_verified','historical_publication_verified','model_input_approved','betting_release']:
            self.assertFalse(r[key])

    def test_missing_surname_component_not_fuzzily_matched(self):
        r=self.resolve('Alexander, Shai');self.assertEqual(r['match_status'],'name_not_found');self.assertIsNone(r['player_id'])

    def test_typographic_normalization_and_suffix_kept(self):
        self.assertEqual(normalized('  P.J.   Washington '),normalized('PJ Washington'))
        self.assertEqual(normalized('Gilgeous\u2011Alexander'),normalized('Gilgeous-Alexander'))
        self.assertEqual(normalized('O\u2019Neale'),normalized("O'Neale"))
        self.assertNotEqual(normalized('Trey Murphy III'),normalized('Trey Murphy'))
        self.assertNotEqual(normalized('Vit Krejci'),normalized('Vít Krejčí'))

    def test_aliases_and_initials_not_expanded(self):
        self.players[0]['name']='Gregory Jackson'
        self.assertEqual(self.resolve('Jackson, GG')['match_status'],'name_not_found')

    def test_duplicate_normalized_names_not_disambiguated_by_team(self):
        self.players.append({'player_id':'P2','name':'SHAI GILGEOUS-ALEXANDER'})
        r=self.resolve();self.assertEqual(r['match_status'],'ambiguous_name');self.assertIsNone(r['player_id'])

    def test_duplicate_id_with_different_catalog_name_is_blocked(self):
        self.players.append({'player_id':'P1','name':'Other Name'})
        self.assertEqual(self.resolve()['match_status'],'duplicate_database_id')

    def test_missing_or_non_string_database_id_blocked(self):
        for pid in [None,'',1]:
            self.players[0]['player_id']=pid
            self.assertEqual(self.resolve()['match_status'],'invalid_database_id')

    def test_latest_prior_team_conflict_not_replaced_by_older_match(self):
        self.rosters.append({'season':2027,'player_id':'P1','team_id':'T2','as_of_date':'2026-11-21'})
        self.published=dt.datetime.fromisoformat('2026-11-22T23:30:00+00:00')
        self.assertEqual(self.resolve(game='2026-11-23')['match_status'],'roster_team_conflict')

    def test_same_day_and_future_rosters_not_used(self):
        self.rosters=[{'season':2027,'player_id':'P1','team_id':'T1','as_of_date':'2026-11-21'},
                      {'season':2027,'player_id':'P1','team_id':'T1','as_of_date':'2026-11-22'}]
        self.assertEqual(self.resolve()['match_status'],'prior_roster_missing')

    def test_cutoff_uses_eastern_publication_date_not_utc_date(self):
        self.published=dt.datetime.fromisoformat('2026-11-22T00:15:00+00:00')
        self.assertEqual(self.resolve()['roster_cutoff_date_exclusive'],'2026-11-21')

    def test_duplicate_and_multiteam_rosters_blocked(self):
        self.rosters.append(dict(self.rosters[0]))
        self.assertEqual(self.resolve()['match_status'],'prior_roster_ambiguous')
        self.rosters[1]['team_id']='T2'
        self.assertEqual(self.resolve()['match_status'],'prior_roster_ambiguous')

    def test_missing_roster_not_inferred(self):
        self.rosters=[];self.assertEqual(self.resolve()['match_status'],'prior_roster_missing')

    def test_invalid_roster_date_or_season_blocked(self):
        self.rosters[0]['as_of_date']='unknown'
        self.assertEqual(self.resolve()['match_status'],'invalid_roster_reference')
        self.rosters[0]['season']=None
        self.assertEqual(self.resolve()['match_status'],'invalid_roster_reference')

    def test_aware_timestamp_required_and_datetime_not_calendar_date(self):
        with self.assertRaises(ValueError):resolve_candidate('A, B',[],[],'T1','2026-11-22',dt.datetime(2026,11,21))
        with self.assertRaises(ValueError):resolve_candidate('A, B',[],[],'T1',self.published,self.published)

    def test_invalid_names_not_interpreted(self):
        for name in [None,'Shai Alexander','A, B, C','A,','<script>, Person']:
            self.assertEqual(self.resolve(name)['match_status'],'invalid_name')

    def test_input_rows_not_modified(self):
        before=copy.deepcopy((self.players,self.rosters));self.resolve()
        self.assertEqual(before,(self.players,self.rosters))

    def test_explicit_alias_requires_prior_team(self):
        players=[{'player_id':'1630249','name':'Vít Krejčí'}]
        rosters=[{'season':2027,'player_id':'1630249','team_id':'POR','as_of_date':'2026-11-22'}]
        published=dt.datetime.fromisoformat('2026-11-23T05:00:00+00:00')
        r=resolve_candidate('Krejci, Vit',players,rosters,'POR','2026-11-23',published)
        self.assertTrue(r['match_verified'])
        self.assertEqual(r['match_status'],'unique_explicit_alias_and_prior_team_reference')
        self.assertFalse(r['betting_release'])

    def test_all_three_explicit_aliases(self):
        cases=[('Schroder, Dennis','Dennis Schröder','203471','CHA'),('Krejci, Vit','Vít Krejčí','1630249','POR'),('Markovic, Bogoljub','Bogoljub Marković','1642881','MIL')]
        published=dt.datetime.fromisoformat('2026-11-23T05:00:00+00:00')
        for candidate,name,pid,team in cases:
            r=resolve_candidate(candidate,[{'player_id':pid,'name':name}],[{'season':2027,'player_id':pid,'team_id':team,'as_of_date':'2026-11-22'}],team,'2026-11-23',published)
            with self.subTest(candidate=candidate):self.assertTrue(r['match_verified'])

    def test_alias_keeps_duplicate_and_wrong_team_blocked(self):
        published=dt.datetime.fromisoformat('2026-11-23T05:00:00+00:00')
        players=[{'player_id':'1','name':'Dennis Schröder'},{'player_id':'2','name':'Dennis Schröder'}]
        roster=[{'season':2027,'player_id':'1','team_id':'CHA','as_of_date':'2026-11-22'}]
        self.assertEqual(resolve_candidate('Schroder, Dennis',players,roster,'CHA','2026-11-23',published)['match_status'],'ambiguous_name')
        self.assertEqual(resolve_candidate('Schroder, Dennis',[players[0]],[dict(roster[0],team_id='OTHER')],'CHA','2026-11-23',published)['match_status'],'roster_team_conflict')

    def test_non_allowlisted_spelling_and_nickname_stay_unmatched(self):
        pub=dt.datetime.fromisoformat('2026-11-23T05:00:00+00:00')
        self.assertEqual(resolve_candidate('Saraf, Ben',[{'player_id':'1','name':'Ben Sáraff'}],[{'season':2027,'player_id':'1','team_id':'BKN','as_of_date':'2026-11-22'}],'BKN','2026-11-23',pub)['match_status'],'name_not_found')
        self.assertEqual(resolve_candidate('Jackson, GG',[{'player_id':'1','name':'Gregory Jackson'}],[{'season':2027,'player_id':'1','team_id':'BKN','as_of_date':'2026-11-22'}],'BKN','2026-11-23',pub)['match_status'],'name_not_found')


if __name__ == '__main__':
    unittest.main()
