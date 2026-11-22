import copy
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import duckdb
import personnel_records as pr
from personnel_identity_lookup import validate_inputs,resolve_rows,lookup,write_report


class IdentityLookupTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,11,21,23,5,tzinfo=dt.timezone.utc)
        self.started='2026-11-21T21:50:00Z'
        self.source={'schema':'official-personnel-v1','status':'captured_raw','betting_release':False,
            'source':'https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-21_04_45PM.pdf',
            'source_published_at_utc':'2026-11-21T21:45:00+00:00','retrieved_at_utc':'2026-11-21T21:53:56+00:00',
            'checked_at_utc':'2026-11-21T21:53:56+00:00','pdf_sha256':'a'*64,
            'sections':[{'game_date_et':'2026-11-21','away':'BOS','home':'SAC','team':'BOS','status':'reported_raw',
                         'raw_text':'Example,\nOne\nOut\nRest'}]}
        self.refresh()
        self.con=duckdb.connect();self.addCleanup(self.con.close)
        self.con.execute("ATTACH ':memory:' AS nba")
        self.con.execute('CREATE TABLE nba.players(player_id VARCHAR,name VARCHAR)')
        self.con.execute('CREATE TABLE nba.team_seasons(season INTEGER,nba_abbrev VARCHAR,team_id VARCHAR,is_nba BOOLEAN)')
        self.con.execute('CREATE TABLE nba.rosters_daily(season INTEGER,player_id VARCHAR,team_id VARCHAR,as_of_date DATE)')
        self.con.execute("INSERT INTO nba.players VALUES ('P1','One Example')")
        self.con.execute("INSERT INTO nba.team_seasons VALUES (2027,'BOS','T1',true)")
        self.con.execute("INSERT INTO nba.rosters_daily VALUES (2027,'P1','T1','2026-11-20')")

    def refresh(self):
        self.raw=json.dumps(self.source).encode()
        self.parsed=pr.build(self.source,self.now-dt.timedelta(seconds=10),self.started)
        self.parsed['source_snapshot_sha256']=hashlib.sha256(self.raw).hexdigest()
        self.typed=json.dumps(self.parsed).encode()

    def run_lookup(self):
        validate_inputs(self.raw,self.typed,self.now,self.started)
        return resolve_rows(self.con,self.parsed,self.now)

    def test_real_parser_replay_and_sql_assign_database_id(self):
        r=self.run_lookup();self.assertEqual(r['matched_records'],1)
        self.assertEqual(r['records'][0]['match']['player_id'],'P1')
        self.assertFalse(r['model_input_approved']);self.assertFalse(r['historical_publication_verified'])
        self.assertFalse(r['records'][0]['match']['reference_provenance_verified'])

    def test_tampered_player_name_rejected_before_connection(self):
        p=copy.deepcopy(self.parsed);p['sections'][0]['players'][0]['name_candidate']='Other, Person'
        connector=Mock()
        with self.assertRaises(ValueError):lookup(self.raw,json.dumps(p).encode(),self.now,self.started,connector)
        connector.assert_not_called()

    def test_raw_hash_mismatch_and_earlier_run_rejected(self):
        with self.assertRaises(ValueError):validate_inputs(self.raw+b' ',self.typed,self.now,self.started)
        with self.assertRaises(ValueError):validate_inputs(self.raw,self.typed,self.now,'2026-11-21T23:04:55Z')

    def test_missing_name_is_local_unresolved(self):
        self.con.execute("UPDATE nba.players SET name='Other Person'")
        r=self.run_lookup();self.assertTrue(r['execution_ok']);self.assertEqual(r['matched_records'],0)
        self.assertEqual(r['records'][0]['match']['match_status'],'name_not_found')

    def test_duplicate_catalog_names_not_selected_by_roster(self):
        self.con.execute("INSERT INTO nba.players VALUES ('P2','ONE EXAMPLE')")
        self.assertEqual(self.run_lookup()['records'][0]['match']['match_status'],'ambiguous_name')

    def test_duplicate_team_mapping_not_guessed(self):
        self.con.execute("INSERT INTO nba.team_seasons VALUES (2027,'BOS','T2',true)")
        r=self.run_lookup();self.assertEqual(r['matched_records'],0)
        self.assertEqual(r['records'][0]['team_mapping_status'],'missing_or_ambiguous')

    def test_latest_team_conflict_not_replaced_by_older_match(self):
        self.con.execute("INSERT INTO nba.rosters_daily VALUES (2027,'P1','T2','2026-11-20')")
        self.con.execute("DELETE FROM nba.rosters_daily WHERE team_id='T1'")
        self.assertEqual(self.run_lookup()['records'][0]['match']['match_status'],'roster_team_conflict')

    def test_duplicate_roster_rows_are_preserved(self):
        self.con.execute('INSERT INTO nba.rosters_daily SELECT * FROM nba.rosters_daily')
        r=self.run_lookup();self.assertEqual(r['roster_query_proofs'][0]['rows_read'],2)
        self.assertEqual(r['records'][0]['match']['match_status'],'prior_roster_ambiguous')

    def test_same_day_roster_is_not_used(self):
        self.con.execute("DELETE FROM nba.rosters_daily")
        self.con.execute("INSERT INTO nba.rosters_daily VALUES (2027,'P1','T1','2026-11-21')")
        self.assertEqual(self.run_lookup()['records'][0]['match']['match_status'],'prior_roster_missing')

    def test_partial_section_does_not_block_other_section(self):
        s=copy.deepcopy(self.source['sections'][0]);s['team']='SAC'
        s['raw_text']='Example,\nOne\nOut\nRest\nOther,\nName\nUnknown'
        self.source['sections'].append(s);self.refresh()
        r=self.run_lookup();self.assertEqual(r['matched_records'],1)
        self.assertEqual(r['records'][-1]['match']['match_status'],'parser_unresolved')

    def test_two_source_names_cannot_assign_same_id_in_section(self):
        self.source['sections'][0]['raw_text']='Example,\nP.J.\nOut\nRest\nExample,\nPJ\nAvailable\nRest'
        self.con.execute("UPDATE nba.players SET name='PJ Example'");self.refresh()
        r=self.run_lookup();self.assertEqual(r['matched_records'],0)
        self.assertTrue(all(e['match']['match_status']=='duplicate_id_in_section' for e in r['records']))

    def test_original_input_objects_not_changed(self):
        before=copy.deepcopy(self.parsed);self.run_lookup();self.assertEqual(self.parsed,before)

    def test_read_only_attach_and_close_on_failure(self):
        con=Mock();con.execute.side_effect=OSError('offline')
        with self.assertRaises(OSError):lookup(self.raw,self.typed,self.now,self.started,Mock(return_value=con))
        self.assertIn('READ_ONLY',con.execute.call_args.args[0]);con.close.assert_called_once()

    def test_public_report_lists_status_and_escapes_name(self):
        r=self.run_lookup();r['records'][0]['name_candidate']='<script>|Name'
        with tempfile.TemporaryDirectory() as folder:
            write_report(r,Path(folder));body=(Path(folder)/'identities_latest.md').read_text()
            self.assertIn('&lt;script&gt;&#124;Name',body);self.assertIn('P1',body)

    def test_catalog_overflow_fails_without_partial_matching(self):
        self.con.execute("INSERT INTO nba.players SELECT 'X'||i::VARCHAR,'Synthetic'||i::VARCHAR FROM range(20001) t(i)")
        with self.assertRaises(ValueError):self.run_lookup()

    def test_not_submitted_section_does_not_create_healthy_players(self):
        self.source['sections'][0].update(status='not_submitted',raw_text='NOT YET SUBMITTED');self.refresh()
        r=self.run_lookup();self.assertEqual(r['record_count'],0)
        self.assertEqual(r['not_submitted_source_sections'],1);self.assertFalse(r['all_reported_records_matched'])


if __name__=='__main__':
    unittest.main()
