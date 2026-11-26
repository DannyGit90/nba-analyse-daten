import json
import tempfile
import unittest
from pathlib import Path

import missing_game_log_diagnostic as d


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


class DiagnosticTests(unittest.TestCase):
    def make_root(self):
        root = Path(tempfile.mkdtemp())
        write(root / "schedule" / "season=2027.jsonl", [
            {"game_id": "A", "game_date": "2026-11-01"}, {"game_id": "B", "game_date": "2026-11-01"},
            {"game_id": "C", "game_date": "2026-12-30"}, {"game_id": "0012600001", "game_date": "2026-10-01"}])
        write(root / "team_game_logs" / "season=2027.jsonl", [
            {"game_id": "A", "game_date": "2026-11-01"}, {"game_id": "A", "game_date": "2026-11-01"}])
        return root

    def test_missing_game_is_explained(self):
        res = d.diagnose(self.make_root(), ["B"], "2026-11-26")
        g = res["games"][0]
        self.assertTrue(g["in_schedule"])
        self.assertEqual(g["log_rows"], 0)
        self.assertEqual(g["same_day_schedule_games"], 2)
        self.assertEqual(g["same_day_games_with_logs"], 1)
        self.assertEqual(res["completed_before_today_without_logs"], ["B"])

    def test_preseason_is_hidden_but_counted(self):
        res = d.diagnose(self.make_root(), [], "2026-11-26")
        self.assertNotIn("0012600001", res["completed_before_today_without_logs"])
        self.assertEqual(res["preseason_without_logs_hidden_count"], 1)

    def test_unknown_game_and_future_game(self):
        res = d.diagnose(self.make_root(), ["Z"], "2026-11-26")
        self.assertFalse(res["games"][0]["in_schedule"])
        self.assertNotIn("C", res["completed_before_today_without_logs"])

    def test_no_schedule_reports_error(self):
        res = d.diagnose(Path(tempfile.mkdtemp()), [], "2026-11-26")
        self.assertIn("error", res)
        self.assertIn("Fehler", d.render_md(res))


if __name__ == "__main__":
    unittest.main()
