"""Synthetic selection tests only; no real-archive acceptance."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from paper_forecast_selection import build, main


def forecast(gid='0022600253', p=0.4, **changes):
    row = {'game_id': gid, 'start_time_utc': '2026-11-18T00:30:00+00:00',
           'home_team_id': '1610612761', 'away_team_id': '1610612752', 'home': 'TOR', 'away': 'NYK',
           'p_home_experimental': p, 'p_away_experimental': 1 - p}
    row.update(changes)
    return row


def snapshot(generated='2026-11-17T20:00:00+00:00', forecasts=None, **changes):
    data = {'protocol': 'season-prior10-paper-v1', 'execution_ok': True,
            'generated_at_utc': generated, 'forecasts': [forecast()] if forecasts is None else forecasts}
    data.update(changes)
    return data


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def game(self, gid='0022600253', result=None):
        return next(g for g in (result or build(self.root))['games'] if g['game_id'] == gid)

    def test_earliest_by_time_not_by_filename(self):
        self.write('a_late_name_early_time.json', snapshot('2026-11-17T18:00:00+00:00', [forecast(p=0.3)]))
        self.write('0_early_name_late_time.json', snapshot('2026-11-17T19:00:00+00:00', [forecast(p=0.7)]))
        game = self.game()
        self.assertEqual(game['status'], 'selected')
        self.assertEqual(game['forecast']['p_home_experimental'], 0.3)
        self.assertEqual(game['valid_candidate_count'], 2)

    def test_new_snapshots_and_games_are_discovered(self):
        self.write('one.json', snapshot())
        self.assertEqual(build(self.root)['selected_count'], 1)
        self.write('two.json', snapshot('2026-11-17T21:00:00+00:00', [forecast('0022600254'), forecast()]))
        result = build(self.root)
        self.assertEqual(result['selected_count'], 2)
        self.assertEqual(self.game(result=result)['valid_candidate_count'], 2)

    def test_after_start_or_wrong_protocol_not_selected(self):
        self.write('late.json', snapshot('2026-11-18T00:30:00+00:00'))
        self.write('wrong.json', snapshot(protocol='other'))
        self.write('failed.json', snapshot(execution_ok=False))
        result = build(self.root)
        self.assertEqual(result['selected_count'], 0)
        self.assertEqual(self.game(result=result)['status'], 'no_valid_forecast')

    def test_later_valid_forecast_used_when_earlier_invalid(self):
        self.write('bad.json', snapshot('2026-11-17T18:00:00+00:00', [forecast(p_away_experimental=0.1)]))
        self.write('good.json', snapshot('2026-11-17T19:00:00+00:00', [forecast(p=0.6)]))
        game = self.game()
        self.assertEqual(game['status'], 'selected')
        self.assertEqual(game['forecast']['p_home_experimental'], 0.6)

    def test_identity_conflict_is_not_selected(self):
        self.write('a.json', snapshot('2026-11-17T18:00:00+00:00'))
        self.write('b.json', snapshot('2026-11-17T19:00:00+00:00', [forecast(home_team_id='1610612700')]))
        self.assertEqual(self.game()['status'], 'conflict')
        self.assertEqual(build(self.root)['status'], 'complete_with_issues')

    def test_start_time_conflict_uses_utc_instants(self):
        self.write('a.json', snapshot('2026-11-17T18:00:00+00:00'))
        same = forecast(start_time_utc='2026-11-18T01:30:00+01:00')
        self.write('b.json', snapshot('2026-11-17T19:00:00+00:00', [same]))
        self.assertEqual(self.game()['status'], 'selected')
        other = forecast(start_time_utc='2026-11-18T00:45:00+00:00')
        self.write('c.json', snapshot('2026-11-17T19:30:00+00:00', [other]))
        self.assertEqual(self.game()['status'], 'conflict')

    def test_simultaneous_identical_ok_and_different_conflict(self):
        stamp = '2026-11-17T18:00:00+00:00'
        self.write('a.json', snapshot(stamp))
        self.write('b.json', snapshot(stamp))
        self.assertEqual(self.game()['status'], 'selected')
        self.write('c.json', snapshot(stamp, [forecast(p=0.55)]))
        self.assertEqual(self.game()['status'], 'conflict')

    def test_timezone_offsets_are_normalized(self):
        self.write('later.json', snapshot('2026-11-17T20:30:00+00:00', [forecast(p=0.7)]))
        self.write('earlier.json', snapshot('2026-11-17T21:00:00+02:00', [forecast(p=0.3)]))
        self.assertEqual(self.game()['forecast']['p_home_experimental'], 0.3)

    def test_duplicate_game_in_one_snapshot_is_invalid(self):
        self.write('dup.json', snapshot(forecasts=[forecast(), forecast(p=0.5)]))
        self.assertEqual(self.game()['status'], 'no_valid_forecast')

    def test_corrupt_files_are_local_and_unnamed_counted(self):
        self.write('good.json', snapshot(forecasts=[forecast(), 5]))
        (self.root / 'broken.json').write_text('{')
        (self.root / 'list.json').write_text('[]')
        result = build(self.root)
        self.assertEqual(result['selected_count'], 1)
        self.assertEqual(len(result['unreadable_files']), 2)
        self.assertEqual(result['forecasts_without_game_id'], 1)
        self.assertEqual(result['status'], 'complete_with_issues')

    def test_empty_missing_and_symlink(self):
        self.assertEqual(build(self.root)['status'], 'empty')
        self.assertEqual(build(self.root / 'absent')['status'], 'source_error')
        target = self.write('target.txt', snapshot())
        (self.root / 'link.json').symlink_to(target)
        self.assertEqual(len(build(self.root)['unreadable_files']), 1)

    def test_repeatable_read_only_and_no_outcome_use(self):
        self.write('a.json', snapshot())
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        first = build(self.root)
        self.assertEqual(first, build(self.root))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        self.assertFalse(first['outcomes_used'])
        self.assertFalse(first['betting_release'])
        self.assertEqual(first['forecast_validation'], 'not_assessed')

    def test_cli_exit_codes(self):
        self.write('a.json', snapshot())
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([str(self.root)]), 0)
        self.assertEqual(json.loads(output.getvalue())['selected_count'], 1)
        (self.root / 'bad.json').write_text('{')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(self.root)]), 1)


if __name__ == '__main__':
    unittest.main()
