import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
import injury_review as ir


class MidnightAppendTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime.fromisoformat('2026-11-22T00:25:00+00:00')
        self.source='2026-11-21T21:53:20.612221+00:00'
        self.created='2026-11-21T22:53:31+01:00'
        self.day='2026-11-21'
        self.payload={'checked_at_utc':'2026-11-22T00:20:33+00:00','status':'unavailable','sections':[],'betting_release':False}

    def fixture(self, folder, heading=None, created=None):
        root=Path(folder);(root/'daily').mkdir()
        (root/'paper_latest.json').write_text(json.dumps({'generated_at_utc':self.source,'forecasts':[]}))
        day=self.day if heading is None else heading
        created=self.created if created is None else created
        body='# NBA-Tagesbericht '+day+'\n\n'
        if created:body+='Bericht erstellt: '+created+' (Europe/Berlin).\n'
        body+='Quellstand UTC: '+self.source+'.\n'
        for name in ['latest.md',day+'.md']:(root/'daily'/name).write_text(body)
        return root,body

    def test_existing_fresh_report_survives_midnight_without_redating(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_=self.fixture(folder);before=(root/'paper_latest.json').read_bytes()
            ir.append_daily(root,self.payload,self.now)
            body=(root/'daily/latest.md').read_text()
            self.assertTrue(body.startswith('# NBA-Tagesbericht 2026-11-21'))
            self.assertEqual(body,(root/'daily/2026-11-21.md').read_text())
            self.assertFalse((root/'daily/2026-11-22.md').exists())
            self.assertEqual(before,(root/'paper_latest.json').read_bytes())

    def test_generation_before_midnight_creation_after_midnight(self):
        self.source='2026-11-21T22:59:58+00:00';self.created='2026-11-22T00:00:01+01:00';self.day='2026-11-22'
        with tempfile.TemporaryDirectory() as folder:
            root,_=self.fixture(folder);ir.append_daily(root,self.payload,self.now)
            self.assertIn('Automatischer Personalstand',(root/'daily/2026-11-22.md').read_text())

    def test_wrong_heading_day_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            root,body=self.fixture(folder,heading='2026-11-22')
            with self.assertRaises(ValueError):ir.append_daily(root,self.payload,self.now)
            self.assertEqual(body,(root/'daily/latest.md').read_text())

    def test_stale_source_stays_blocked(self):
        self.source=(self.now-dt.timedelta(hours=8,seconds=1)).isoformat()
        with tempfile.TemporaryDirectory() as folder:
            root,_=self.fixture(folder)
            with self.assertRaises(ValueError):ir.append_daily(root,self.payload,self.now)

    def test_future_source_stays_blocked(self):
        self.source=(self.now+dt.timedelta(seconds=1)).isoformat()
        with tempfile.TemporaryDirectory() as folder:
            root,_=self.fixture(folder)
            with self.assertRaises(ValueError):ir.append_daily(root,self.payload,self.now)

    def test_future_creation_and_creation_before_source_rejected(self):
        for created in ['2026-11-22T02:00:00+01:00','2026-11-21T20:00:00+01:00']:
            with self.subTest(created=created),tempfile.TemporaryDirectory() as folder:
                root,_=self.fixture(folder,created=created)
                with self.assertRaises(ValueError):ir.append_daily(root,self.payload,self.now)

    def test_malformed_or_duplicate_creation_metadata_rejected(self):
        for created in ['not-a-time','2026-11-21T22:53:31']:
            with tempfile.TemporaryDirectory() as folder:
                root,_=self.fixture(folder,created=created)
                with self.assertRaises(ValueError):ir.append_daily(root,self.payload,self.now)
        with tempfile.TemporaryDirectory() as folder:
            root,body=self.fixture(folder)
            body+='Bericht erstellt: '+self.created+' (Europe/Berlin).\n'
            for name in ['latest.md',self.day+'.md']:(root/'daily'/name).write_text(body)
            with self.assertRaises(ValueError):ir.append_daily(root,self.payload,self.now)

    def test_archive_and_source_bindings_stay_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_=self.fixture(folder);archive=root/'daily'/(self.day+'.md');archive.write_text('different')
            with self.assertRaises(ValueError):ir.append_daily(root,self.payload,self.now)
            self.assertEqual(archive.read_text(),'different')
        with tempfile.TemporaryDirectory() as folder:
            root,body=self.fixture(folder)
            body=body.replace('Quellstand UTC: '+self.source,'Quellstand UTC: 2026-11-21T21:00:00Z')
            for name in ['latest.md',self.day+'.md']:(root/'daily'/name).write_text(body)
            with self.assertRaises(ValueError):ir.append_daily(root,self.payload,self.now)

    def test_minimal_legacy_report_binds_to_source_date(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_=self.fixture(folder,created='');ir.append_daily(root,self.payload,self.now)
            self.assertTrue((root/'daily/2026-11-21.md').exists())

    def test_repeated_append_keeps_one_section(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_=self.fixture(folder)
            ir.append_daily(root,self.payload,self.now);ir.append_daily(root,self.payload,self.now)
            self.assertEqual((root/'daily/latest.md').read_text().count('## Automatischer Personalstand'),1)


    def test_append_failure_detail_is_visible_and_escaped(self):
        payload=dict(self.payload, daily_report_appended=False, append_error_detail='Bad <snapshot>')
        rendered=ir.render(payload)
        self.assertIn('Tagesbericht ergaenzt: False',rendered)
        self.assertIn('Bad &lt;snapshot&gt;',rendered)


if __name__=='__main__':
    unittest.main()
