import copy
import datetime as dt
import unittest
import duckdb
from replacement_review import assess,load_roster,enrich

CUT = dt.date(2026,11,22)


def profile(pid='P'):
    return {'player_id':pid,'observed_records':3,'mean_per_record':{'fga':10.,'fg3a':3.,'ast':5.,'reb':4.}}


def personnel(status='Available',verified=True):
    return {'status':'reported_statuses_only','records':[{'player_id':'P','database_match_verified':verified,'source_name':'Player','reported_status':status}]}


def roster(team='T'):
    return [{'player_id':'P','team_id':team,'as_of_date':dt.date(2026,11,21)}]


class ReplacementReviewTests(unittest.TestCase):
    def test_only_explicit_available_becomes_review_input(self):
        for status,count in [('Available',1),('Out',0),('Probable',0),('Questionable',0),('Doubtful',0)]:
            with self.subTest(status=status):
                r = assess([profile()],personnel(status),roster(),'T',CUT)
                self.assertEqual(r['candidate_count'],count)
                self.assertFalse(r['role_assessment_complete'])
                self.assertFalse(r['players'][0]['replacement_confirmed'])
                self.assertFalse(r['players'][0]['current_team_membership_verified'])

    def test_missing_status_does_not_mean_available(self):
        for p in [{},{'status':'not_submitted'},personnel(verified=False)]:
            r = assess([profile()],p,roster(),'T',CUT)
            self.assertEqual(r['candidate_count'],0)
            self.assertEqual(r['players'][0]['availability_evidence'],'not_verified')

    def test_roster_missing_ambiguous_or_other_team(self):
        for refs in [[],roster()*2,roster('OTHER')]:
            self.assertEqual(assess([profile()],personnel(),refs,'T',CUT)['candidate_count'],0)

    def test_same_day_reference_rejected(self):
        refs = roster();refs[0]['as_of_date'] = CUT
        with self.assertRaises(ValueError):assess([profile()],personnel(),refs,'T',CUT)

    def test_no_profile_not_promoted(self):
        r = assess([],personnel(),roster(),'T',CUT)
        self.assertEqual(r['candidate_count'],0)
        self.assertIsNone(r['players'][0]['recent_profile'])

    def test_duplicate_inputs_rejected(self):
        with self.assertRaises(ValueError):assess([profile(),profile()],personnel(),roster(),'T',CUT)
        p = personnel();p['records'] *= 2
        with self.assertRaises(ValueError):assess([profile()],p,roster(),'T',CUT)

    def test_dimension_evidence_not_compensation(self):
        p = personnel('Out')
        p['records'].append({'player_id':'Q','database_match_verified':True,'source_name':'Other','reported_status':'Available'})
        refs = roster()+[{'player_id':'Q','team_id':'T','as_of_date':dt.date(2026,11,21)}]
        before = copy.deepcopy(p)
        r = assess([profile(),profile('Q')],p,refs,'T',CUT)
        dimension = r['contribution_dimensions']['ast']
        self.assertEqual(dimension['reported_out_observed_contributors'][0]['player_id'],'P')
        self.assertEqual(dimension['review_candidates_with_observed_contribution'][0]['player_id'],'Q')
        self.assertFalse(dimension['capacity_or_compensation_proven'])
        self.assertIsNone(r['replacement_assignment'])
        self.assertEqual(p,before)

    def test_sql_retains_latest_team_conflicts_and_excludes_same_day(self):
        con = duckdb.connect();self.addCleanup(con.close)
        con.execute("ATTACH ':memory:' AS nba")
        con.execute('CREATE TABLE nba.main.rosters_daily(season INTEGER,player_id VARCHAR,team_id VARCHAR,as_of_date DATE)')
        con.execute("INSERT INTO nba.main.rosters_daily VALUES(2027,'P','OLD','2026-11-20'),(2027,'P','NEW','2026-11-21'),(2027,'P','FUTURE','2026-11-22')")
        r = load_roster(con,2027,['P'],CUT)
        self.assertEqual(len(r),1)
        self.assertEqual(r[0]['team_id'],'NEW')
        con.execute("INSERT INTO nba.main.rosters_daily VALUES(2027,'P','OTHER','2026-11-21')")
        self.assertEqual(len(load_roster(con,2027,['P'],CUT)),2)

    def test_missing_personnel_does_not_open_source(self):
        def forbidden():raise AssertionError('Unexpected source access')
        r = enrich({'fixtures':[]},dt.datetime(2026,11,22,tzinfo=dt.timezone.utc),forbidden)
        self.assertEqual(r['replacement_review']['status'],'blocked')
        self.assertFalse(r['replacement_review']['source_read_attempted'])


if __name__ == '__main__':
    unittest.main()
