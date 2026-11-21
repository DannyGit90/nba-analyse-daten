import copy
import datetime as dt
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import personnel_records as pr

DAL = """Biberovic,
Tarik
Out
Injury/Illness
-
Right
Heel
Bursitis
Clayton
Jr.,
Walter
Questionable
Injury/Illness
-
Left
Patellar
Tendinitis
de
Larrea,
Sergio
Out
Injury/Illness
-
Right
Knee
Sprain
Howard,
Jett
Questionable
G
League
-
Two-
Way
Lawal,
Tobi
Out
Injury/Illness
-
Right
Groin
Strain
Lively
II,
Dereck
Out
Injury/Illness
-
Right
Foot
Surgery
Martin,
Caleb
Available
Injury/Illness
-
Right
Thumb
Splint
Washington,
P.J.
Doubtful
Injury/Illness
-
Illness"""
NYK = """Anunoby,
OG
Out
Injury/Illness
-
Left
Calf
Tightness
Clarkson,
Jordan
Out
Injury/Illness
-
Right
Plantar
Fasciitis
Towns,
Karl-
Anthony
Questionable
Injury/Illness
-
Illness"""


def section(raw=DAL, **changes):
    s={'game_date_et':'2026-11-21','away':'LAC','home':'DAL','team':'DAL','status':'reported_raw','raw_text':raw}
    s.update(changes);return s


def source():
    return {'schema':'official-personnel-v1','status':'captured_raw','betting_release':False,
        'source':'https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-21_04_45PM.pdf',
        'source_published_at_utc':'2026-11-21T21:45:00+00:00',
        'retrieved_at_utc':'2026-11-21T21:53:56+00:00','checked_at_utc':'2026-11-21T21:53:56+00:00',
        'pdf_sha256':'ba3ae734fb1021dac5b5743124fe7acc3a4c5e9b28191681ba9791b2bb319db0','sections':[section()]}


class PersonnelRecordTests(unittest.TestCase):
    def setUp(self):self.now=dt.datetime(2026,11,21,23,5,tzinfo=dt.timezone.utc)

    def test_captured_dallas_variants(self):
        r=pr.parse_section(section())
        self.assertTrue(r['parsing_complete'],r['errors']);self.assertEqual(len(r['players']),8)
        by_name={p['name_candidate']:p for p in r['players']}
        for name in ['Clayton Jr., Walter','de Larrea, Sergio','Lively II, Dereck','Washington, P.J.']:
            self.assertIn(name,by_name)
        self.assertEqual(by_name['Washington, P.J.']['status'],'Doubtful')
        self.assertIn('Two-Way',by_name['Howard, Jett']['reason_text'])
        self.assertTrue(all(p['player_id'] is None and not p['identity_verified'] for p in r['players']))

    def test_wrapped_first_name_and_reason_boundaries(self):
        r=pr.parse_section(section(NYK,away='POR',home='NYK',team='NYK'))
        self.assertTrue(r['parsing_complete']);self.assertEqual(len(r['players']),3)
        self.assertEqual(r['players'][-1]['name_candidate'],'Towns, Karl-Anthony')
        self.assertNotIn('Clarkson',r['players'][0]['reason_text'])

    def test_raw_text_and_source_line_replay(self):
        r=pr.parse_section(section());lines=DAL.splitlines()
        self.assertEqual(r['raw_text'],DAL)
        for p in r['players']:
            self.assertEqual(p['status_raw'],lines[p['source_status_line']-1])
            self.assertEqual(p['raw_reason_text'],'\n'.join(lines[p['source_status_line']:p['source_line_end']]))

    def test_unknown_status_not_guessed(self):
        r=pr.parse_section(section('Example,\nPlayer\nDay-to-day\nIllness'))
        self.assertFalse(r['parsing_complete']);self.assertEqual(r['players'],[])

    def test_unknown_trailing_player_not_hidden(self):
        r=pr.parse_section(section('Example,\nOne\nOut\nRest\nOther,\nTwo\nUnknown\nReason'))
        self.assertFalse(r['parsing_complete'])
        self.assertFalse(r['players'][0]['usable_for_identity_lookup'])

    def test_duplicate_or_conflicting_name_not_approved(self):
        r=pr.parse_section(section('Example,\nOne\nOut\nRest\nExample,\nOne\nAvailable\nRest'))
        self.assertIn('duplicate_name_candidate',r['errors'])
        self.assertFalse(any(p['usable_for_identity_lookup'] for p in r['players']))

    def test_not_submitted_not_healthy(self):
        r=pr.parse_section(section('NOT YET SUBMITTED',status='not_submitted'))
        self.assertTrue(r['parsing_complete']);self.assertEqual(r['players'],[])
        self.assertFalse(r['player_level_assessment_complete'])

    def test_upstream_unresolved_not_overridden(self):
        r=pr.parse_section(section(status='parse_unresolved'))
        self.assertFalse(r['parsing_complete']);self.assertEqual(r['players'],[])

    def test_source_guard_time_and_provenance(self):
        for key,value in [('status','unavailable'),('betting_release',True),('pdf_sha256','bad'),
                          ('source','https://example.com/report.pdf'),('source_published_at_utc','2026-11-21T21:30:00+00:00')]:
            s=source();s[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):pr.build(s,self.now)
        with self.assertRaises(ValueError):pr.build(source(),self.now+dt.timedelta(hours=8))
        with self.assertRaises(ValueError):pr.build(source(),self.now-dt.timedelta(hours=2))

    def test_earlier_run_input_rejected(self):
        with self.assertRaises(ValueError):pr.build(source(),self.now,'2026-11-21T22:00:00+00:00')

    def test_build_preserves_source_and_no_model_approval(self):
        s=source();before=copy.deepcopy(s);r=pr.build(s,self.now,'2026-11-21T21:50:00Z')
        self.assertEqual(s,before);self.assertEqual(r['player_record_count'],8)
        for key in ['identity_resolution_complete','player_level_assessment_complete','model_input_approved','betting_release']:
            self.assertFalse(r[key])

    def test_team_on_other_game_date_is_separate(self):
        s=source();s['sections'].append(section('NOT YET SUBMITTED',game_date_et='2026-11-22',away='DAL',home='UTA',status='not_submitted'))
        r=pr.build(s,self.now);self.assertTrue(r['parsing_complete'])
        self.assertEqual(r['not_submitted_section_count'],1)

    def test_duplicate_section_blocks_both_copies(self):
        s=source();s['sections'].append(copy.deepcopy(s['sections'][0]))
        r=pr.build(s,self.now)
        self.assertEqual(r['unresolved_section_count'],2)
        self.assertFalse(any(p['usable_for_identity_lookup'] for sec in r['sections'] for p in sec['players']))

    def test_invalid_section_identity_is_local(self):
        s=source();s['sections'].append(section(team=['DAL']))
        r=pr.build(s,self.now)
        self.assertEqual(r['unresolved_section_count'],1);self.assertEqual(r['player_record_count'],8)

    def test_compact_unsupported_text_is_not_invented(self):
        r=pr.parse_section(section('Example,PlayerOutRest'))
        self.assertFalse(r['parsing_complete']);self.assertEqual(r['players'],[])

    def test_public_report_escapes_markup(self):
        r=pr.build(source(),self.now);r['sections'][0]['players'][0]['reason_text']='<script>|test'
        with tempfile.TemporaryDirectory() as folder:
            pr.write_report(r,Path(folder))
            body=(Path(folder)/'players_latest.md').read_text()
            self.assertNotIn('<script>',body);self.assertIn('&lt;script&gt;&#124;test',body)

    def test_main_keeps_raw_json_and_binds_output_hash(self):
        fixed=self.now
        class Clock(dt.datetime):
            @classmethod
            def now(cls,tz=None):return fixed
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'reports/injury';root.mkdir(parents=True)
            raw=json.dumps(source()).encode();(root/'latest.json').write_bytes(raw)
            (root/'latest.md').write_text('# Raw\nPruefzeit UTC: '+source()['checked_at_utc']+'\n')
            cwd=os.getcwd()
            try:
                os.chdir(folder)
                with patch.object(pr.dt,'datetime',Clock),patch.dict(os.environ,{'PERSONNEL_RECORD_TESTS_OK':'success','NBA_PERSONNEL_RUN_STARTED_AT':'2026-11-21T21:50:00Z'}):
                    with self.assertRaises(SystemExit) as out:pr.main()
                self.assertEqual(out.exception.code,0)
                saved=json.loads((root/'players_latest.json').read_text())
                self.assertEqual(saved['source_snapshot_sha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual((root/'latest.json').read_bytes(),raw)
                self.assertIn('players_latest.md',(root/'latest.md').read_text())
            finally:os.chdir(cwd)


    def test_unsupported_comma_in_reason_keeps_section_unresolved(self):
        r=pr.parse_section(section('Example,\nOne\nOut\nPain, recurrent'))
        self.assertFalse(r['parsing_complete'])
        self.assertIn('unparsed_name_or_comma',r['errors'])

    def test_empty_or_invalid_source_sections_rejected(self):
        for sections in [[],None,['wrong type']]:
            s=source();s['sections']=sections
            with self.assertRaises(ValueError):pr.build(s,self.now)

    def test_submission_text_conflict_is_not_accepted(self):
        r=pr.parse_section(section('Example,\nPlayer\nAvailable',status='not_submitted'))
        self.assertFalse(r['parsing_complete']);self.assertEqual(r['players'],[])


if __name__=='__main__':
    unittest.main()
