import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from public_daily_report import publish, cell


class PublicReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = dt.datetime.fromisoformat('2026-11-21T12:00:00+00:00')
        self.started = '2026-11-21T11:00:00+00:00'
        header = {'generated_at_utc': '2026-11-21T11:01:00+00:00',
                  'protocol': 'season-prior10-paper-v1', 'execution_ok': True}
        fixture = {'game_id': '0022600279', 'away': 'BOS', 'home': 'SAC',
                   'start_time_utc': '2026-11-22T03:00:00+00:00', 'offer_count': 54}
        self.payloads = {
            'paper_latest.json': dict(header, forecasts=[fixture], skipped_games=[], upcoming_schedule_games=1),
            'chat_index.json': dict(header, fixtures=[fixture], actual_offer_count=54, computed_offer_count=54),
            'pipeline_readiness.json': dict(header, fixtures=[]),
            'paper_health.json': {'source_generated_at_utc': header['generated_at_utc'], 'status': 'ready_paper_only'}}
        self.save()

    def save(self):
        for name, value in self.payloads.items():
            (self.root / name).write_text(json.dumps(value))

    def run_report(self, status='success'):
        return publish(self.root, self.now, self.started, status)

    def body(self):
        return (self.root / 'daily/latest.md').read_text()

    def test_success_writes_public_report_and_archive(self):
        self.assertTrue(self.run_report())
        self.assertIn('BOS bei SAC', self.body())
        self.assertIn('22.11. 04:00', self.body())
        self.assertTrue((self.root/'daily/2026-11-21.md').exists())
        self.assertIn('2026-11-21.md',(self.root/'daily/README.md').read_text())
        self.assertIn('nicht dokumentiert',self.body())
        self.assertNotIn('AUSLASSEN |',self.body())

    def test_stale_checkout_never_appears_as_new_day(self):
        self.payloads['paper_latest.json']['generated_at_utc']='2026-11-21T10:00:00+00:00'
        self.save()
        self.assertFalse(self.run_report())
        self.assertIn('Kein nachgewiesener neuer Datenstand',self.body())
        self.assertNotIn('BOS bei SAC',self.body())

    def test_failed_run_retains_matching_partial_results(self):
        self.assertFalse(self.run_report('failure'))
        self.assertIn('nicht erfolgreich: failure',self.body())
        self.assertIn('BOS bei SAC',self.body())

    def test_missing_input_publishes_failure_report(self):
        (self.root/'chat_index.json').unlink()
        self.assertFalse(self.run_report())
        self.assertIn('fehlt oder ist unlesbar',self.body())

    def test_corrupt_json_publishes_failure_report(self):
        (self.root/'pipeline_readiness.json').write_text('{')
        self.assertFalse(self.run_report())
        self.assertTrue((self.root/'daily/latest.md').exists())

    def test_mismatched_protocol_does_not_merge_data(self):
        self.payloads['chat_index.json']['protocol']='other'
        self.save()
        self.assertFalse(self.run_report())
        self.assertNotIn('BOS bei SAC',self.body())

    def test_upstream_failure_never_appears_as_successful_data(self):
        self.payloads['paper_latest.json']['execution_ok']=False
        self.save()
        self.assertFalse(self.run_report())
        self.assertIn('Teilbericht meldet Ausfuehrungsfehler',self.body())

    def test_day_archive_is_preserved(self):
        folder=self.root/'daily';folder.mkdir()
        (folder/'2026-11-20.md').write_text('previous day')
        self.run_report()
        self.assertEqual((folder/'2026-11-20.md').read_text(),'previous day')
        self.assertIn('2026-11-20.md',(folder/'README.md').read_text())

    def test_markup_is_escaped(self):
        self.assertEqual(cell('<script>|x'),'&lt;script&gt;&#124;x')

    def test_future_generation_is_not_current(self):
        self.payloads['paper_latest.json']['generated_at_utc']='2026-11-22T00:00:00+00:00'
        self.save()
        self.assertFalse(self.run_report())

    def test_berlin_date_not_utc_date_selects_archive(self):
        self.now=dt.datetime.fromisoformat('2026-11-21T23:30:00+00:00')
        self.run_report()
        self.assertTrue((self.root/'daily/2026-11-22.md').exists())

    def test_invalid_time_rejected(self):
        with self.assertRaises(ValueError):publish(self.root,self.now,'2026-11-22T00:00:00+00:00','success')


if __name__ == '__main__':
    unittest.main()
