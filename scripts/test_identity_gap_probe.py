import datetime as dt
import unittest
import duckdb
from identity_gap_probe import classify,diagnose,fold,load_references,lookup_key

D = dt.date(2026,11,22)


def record(name='Schroder, Dennis',status='name_not_found',team_id='T1'):
    return {'name_candidate':name,'team':'CHA','game_date_et':'2026-11-23','status':'Out','expected_team_id':team_id,
            'match':{'match_verified':False,'match_status':status}}


def refs(**teams):
    return {pid:[{'player_id':pid,'team_id':team,'as_of_date':D}] for pid,team in teams.items()}


class IdentityGapProbeTests(unittest.TestCase):
    def test_fold_handles_accents_and_special_letters_but_not_other_names(self):
        self.assertEqual(fold('Dennis Schr\u00f6der'),'dennis schroder')
        self.assertEqual(fold('Vit Krej\u010d\u00ed'),'vit krejci')
        self.assertEqual(fold('Marko Rado\u0111evi\u0107'),'marko radodevic')
        self.assertNotEqual(fold('Ben Saraf'),fold('Ben Sarif'))
        self.assertIsNone(fold('R2 D2'))

    def test_lookup_key_requires_single_comma(self):
        self.assertEqual(lookup_key('Schroder, Dennis'),'Dennis Schroder')
        self.assertIsNone(lookup_key('Schroder Dennis'))
        self.assertIsNone(lookup_key('A, B, C'))

    def test_single_accent_difference_is_reported_but_not_verified(self):
        r = classify(record(),[{'player_id':'1','name':'Dennis Schr\u00f6der'}],refs(**{'1':'T1'}))
        self.assertEqual(r['diagnosis'],'single_accent_or_special_letter_difference')
        self.assertTrue(r['single_candidate_with_matching_prior_team'])
        self.assertFalse(r['match_verified_by_this_probe'])
        self.assertFalse(r['matching_policy_changed'])

    def test_wrong_team_missing_roster_and_no_candidate(self):
        wrong = classify(record(),[{'player_id':'1','name':'Dennis Schr\u00f6der'}],refs(**{'1':'OTHER'}))
        self.assertFalse(wrong['single_candidate_with_matching_prior_team'])
        self.assertEqual(wrong['accent_folded_only_candidates'][0]['relation'],'different_prior_team')
        missing = classify(record(),[{'player_id':'1','name':'Dennis Schr\u00f6der'}],{})
        self.assertEqual(missing['accent_folded_only_candidates'][0]['relation'],'missing')
        none = classify(record('Nobody, Test'),[{'player_id':'1','name':'Other Person'}],{})
        self.assertEqual(none['diagnosis'],'no_candidate_under_either_normalization')

    def test_duplicate_exact_names_list_every_candidate(self):
        r = classify(record('Saraf, Ben','ambiguous_name'),[{'player_id':'1','name':'Ben Saraf'},{'player_id':'2','name':'Ben Saraf'}],refs(**{'1':'T1','2':'OTHER'}))
        self.assertEqual(r['diagnosis'],'duplicate_exact_names')
        self.assertEqual({c['player_id'] for c in r['exact_candidates']},{'1','2'})
        self.assertFalse(r['single_candidate_with_matching_prior_team'])

    def test_multiple_folded_candidates_not_resolved(self):
        cat = [{'player_id':'1','name':'Dennis Schr\u00f6der'},{'player_id':'2','name':'Dennis Schr\u0151der'}]
        r = classify(record(),cat,refs(**{'1':'T1','2':'T1'}))
        self.assertEqual(r['diagnosis'],'multiple_accent_folded_candidates')
        self.assertFalse(r['single_candidate_with_matching_prior_team'])

    def test_sql_and_bounds_with_real_duckdb(self):
        con = duckdb.connect();self.addCleanup(con.close)
        con.execute("ATTACH ':memory:' AS nba")
        con.execute('CREATE TABLE nba.main.players(player_id VARCHAR,name VARCHAR)')
        con.execute('CREATE TABLE nba.main.rosters_daily(season INTEGER,player_id VARCHAR,team_id VARCHAR,as_of_date DATE)')
        con.execute("INSERT INTO nba.main.players VALUES('1','Dennis Schr\u00f6der'),('2','Ben Saraf'),('3','Ben Saraf')")
        con.execute("INSERT INTO nba.main.rosters_daily VALUES(2027,'1','OLD','2026-11-20'),(2027,'1','T1','2026-11-21'),(2027,'1','FUTURE','2026-11-23')")
        found = load_references(con,['1'],dt.date(2026,11,23),2027)
        self.assertEqual(found['1'][0]['team_id'],'T1')
        identities = {'execution_ok':True,'betting_release':False,'records':[record(),record('Saraf, Ben','ambiguous_name')]}
        out = diagnose(con,identities)
        self.assertEqual({r['diagnosis'] for r in out['records']},{'single_accent_or_special_letter_difference','duplicate_exact_names'})
        identities['records'] = [record() for _ in range(21)]
        with self.assertRaises(ValueError):diagnose(con,identities)
        identities['betting_release'] = True
        with self.assertRaises(ValueError):diagnose(con,identities)

    def test_nothing_to_diagnose_and_matched_records_skipped(self):
        con = duckdb.connect();self.addCleanup(con.close)
        matched = record();matched['match']['match_verified'] = True
        out = diagnose(con,{'execution_ok':True,'betting_release':False,'records':[matched]})
        self.assertEqual(out['status'],'nothing_to_diagnose')


if __name__ == '__main__':
    unittest.main()
