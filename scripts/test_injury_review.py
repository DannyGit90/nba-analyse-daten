import copy
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import injury_review as ir

URL = 'https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-21_04_30AM.pdf'
TEXT = """Injury Report: 11/21/26 04:30 AM
Page 4 of 5
11/21/2026
10:00 (ET)
BOS@SAC
Boston Celtics
Mitchell, Dillon
Out
G League - Two-Way
Tatum, Jayson
Questionable
Rest
White, Derrick
Questionable
Injury/Illness - Left AC Joint
Contusion
Sacramento Kings
NOT YET SUBMITTED
11/22/2026
08:30 (ET)
BOS@GSW
Boston Celtics
NOT YET SUBMITTED
Injury Report: 11/21/26 04:30 AM
Page 5 of 5
Golden State Warriors
NOT YET SUBMITTED
"""


class PersonnelTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime.fromisoformat('2026-11-21T12:50:00+00:00')
        self.html = '<a href="'+URL+'">report</a>'

    def loader(self, url):
        if 'official.nba.com' in url:return self.html.encode()
        if url == URL:return b'%PDF-test-only'
        raise OSError('synthetic missing URL')

    def payload(self):
        return ir.collect(self.now,self.loader,lambda b:TEXT)

    def base(self, root):
        root=Path(root);(root/'daily').mkdir(parents=True)
        paper={'generated_at_utc':'2026-11-21T12:00:00+00:00','forecasts':[
            {'game_id':'0022600279','start_time_utc':'2026-11-22T03:00:00+00:00','away':'BOS','home':'SAC'}]}
        (root/'paper_latest.json').write_text(json.dumps(paper))
        text='# NBA-Tagesbericht 2026-11-21\n\nQuellstand UTC: 2026-11-21T12:00:00+00:00.\n'
        for name in ['latest.md','2026-11-21.md']:(root/'daily'/name).write_text(text)

    def test_official_url_and_eastern_timestamp(self):
        self.assertEqual(ir.published(URL).isoformat(),'2026-11-21T09:30:00+00:00')

    def test_untrusted_report_hosts_rejected(self):
        for url in [URL.replace('ak-static.cms.nba.com','example.com'),URL.replace('https:','http:')]:
            with self.assertRaises(ValueError):ir.published(url)

    def test_candidate_budget_and_no_future_urls(self):
        html=self.html+'<a href="'+URL.replace('04_30AM','11_30PM')+'">future</a>'
        urls=ir.candidates(html,self.now)
        self.assertLessEqual(len(urls),4)
        self.assertTrue(all(ir.published(u)<=self.now for u in urls))
        self.assertIn(URL,urls)

    def test_relative_index_links_are_retained(self):
        html='<a href="/referee/injury/Injury-Report_2026-11-21_04_30AM.pdf">report</a>'
        self.assertIn(URL,ir.candidates(html,self.now))

    def test_same_team_different_game_dates_not_overwritten(self):
        parts=ir.sections(TEXT)
        bos=[x for x in parts if x['team']=='BOS']
        self.assertEqual(len(bos),2)
        self.assertEqual(bos[0]['status'],'reported_raw')
        self.assertIn('Tatum, Jayson',bos[0]['raw_text'])
        self.assertEqual(bos[1]['status'],'not_submitted')

    def test_no_submission_is_not_healthy(self):
        sac=[x for x in ir.sections(TEXT) if x['team']=='SAC'][0]
        self.assertEqual(sac['status'],'not_submitted')
        self.assertFalse(sac['player_level_assessment_complete'])

    def test_unknown_team_section_format_stays_unresolved(self):
        text='11/21/2026 BOS@SAC Boston Celtics undocumented format'
        self.assertEqual(ir.sections(text)[0]['status'],'parse_unresolved')

    def test_duplicate_section_is_unresolved(self):
        text=TEXT+'\n11/21/2026 BOS@SAC Boston Celtics Tatum, Jayson Out Rest'
        bos=[x for x in ir.sections(text) if x['team']=='BOS' and x['game_date_et']=='2026-11-21'][0]
        self.assertEqual(bos['status'],'parse_unresolved')

    def test_page_headers_do_not_erase_matchup_context(self):
        gsw=[x for x in ir.sections(TEXT) if x['team']=='GSW'][0]
        self.assertEqual((gsw['game_date_et'],gsw['away'],gsw['home']),('2026-11-22','BOS','GSW'))

    def test_collection_checks_header_and_keeps_provenance(self):
        p=self.payload()
        self.assertEqual(p['status'],'captured_raw')
        self.assertEqual(p['source'],URL)
        self.assertEqual(len(p['pdf_sha256']),64)
        self.assertFalse(p['betting_release'])
        self.assertLessEqual(len(p['attempts']),4)

    def test_header_filename_mismatch_rejected(self):
        p=ir.collect(self.now,self.loader,lambda b:TEXT.replace('04:30 AM','04:15 AM'))
        self.assertEqual(p['status'],'unavailable')
        self.assertEqual(p['sections'],[])

    def test_source_failure_is_local_and_explicit(self):
        p=ir.collect(self.now,Mock(side_effect=OSError('offline')),lambda b:TEXT)
        self.assertEqual(p['status'],'unavailable')
        self.assertFalse(p['betting_release'])
        self.assertTrue(p['attempts'])

    def test_old_document_is_not_reported_as_fresh(self):
        p=ir.collect(self.now+dt.timedelta(hours=9),self.loader,lambda b:TEXT)
        self.assertEqual(p['status'],'stale')

    def test_non_pdf_response_rejected(self):
        with self.assertRaises(ValueError):ir.pdf_text(b'<html>blocked</html>')

    def test_eastern_game_date_join_not_utc_date(self):
        with tempfile.TemporaryDirectory() as folder:
            self.base(folder);ir.append_daily(folder,self.payload(),self.now)
            body=(Path(folder)/'daily/latest.md').read_text()
            self.assertIn('| BOS bei SAC | reported_raw | not_submitted |',body)

    def test_report_append_is_idempotent_and_keeps_archive_equal(self):
        with tempfile.TemporaryDirectory() as folder:
            self.base(folder);p=self.payload()
            ir.append_daily(folder,p,self.now);ir.append_daily(folder,p,self.now)
            body=(Path(folder)/'daily/latest.md').read_text()
            self.assertEqual(body.count('## Automatischer Personalstand'),1)
            self.assertEqual(body,(Path(folder)/'daily/2026-11-21.md').read_text())

    def test_mismatched_base_archive_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            self.base(folder);archive=Path(folder)/'daily/2026-11-21.md';archive.write_text('other snapshot')
            with self.assertRaises(ValueError):ir.append_daily(folder,self.payload(),self.now)
            self.assertEqual(archive.read_text(),'other snapshot')

    def test_unavailable_personnel_is_published_without_changing_model(self):
        with tempfile.TemporaryDirectory() as folder:
            self.base(folder);paper=Path(folder)/'paper_latest.json';before=paper.read_bytes()
            p={'checked_at_utc':self.now.isoformat(),'status':'unavailable','sections':[],'betting_release':False}
            ir.append_daily(folder,p,self.now)
            self.assertIn('Quellenstatus: unavailable',(Path(folder)/'daily/latest.md').read_text())
            self.assertEqual(before,paper.read_bytes())

    def test_source_regression_preserves_last_good_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'reports/injury';root.mkdir(parents=True)
            previous={'source_published_at_utc':'2026-11-21T09:45:00+00:00','sections':[{'retained':True}]}
            path=root/'last_good.json';path.write_text(json.dumps(previous));before=path.read_bytes()
            cwd=os.getcwd()
            try:
                os.chdir(folder)
                with patch.dict(os.environ,{'INJURY_TESTS_OK':'success'}),patch.object(ir,'collect',return_value=self.payload()),patch.object(ir,'append_daily'):
                    with self.assertRaises(SystemExit) as result:ir.main()
                self.assertEqual(result.exception.code,1)
                self.assertEqual(path.read_bytes(),before)
                latest=json.loads((root/'latest.json').read_text())
                self.assertEqual(latest['status'],'unavailable')
                self.assertIn('regressed',latest['error'])
            finally:os.chdir(cwd)

    def test_no_numeric_recommendation_created(self):
        p=self.payload()
        self.assertNotIn('probability',p)
        self.assertNotIn('recommendation',p)
        self.assertTrue(all(x['player_level_assessment_complete'] is False for x in p['sections']))


if __name__ == '__main__':
    unittest.main()
