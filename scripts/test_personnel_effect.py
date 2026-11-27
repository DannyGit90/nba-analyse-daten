import unittest
from personnel_effect_diagnostic import build_games, build_appearances, simulate, evaluate, rotation


def synth():
    teams = ['A', 'B', 'C', 'D']
    team_rows, player_rows = [], []
    gid = 0
    date = 0
    for rnd in range(120):
        for x, y in (('A', 'B'), ('C', 'D')) if rnd % 2 == 0 else (('A', 'C'), ('B', 'D')):
            gid += 1
            date += 1
            star_out = (x == 'A' and rnd % 4 == 0) or (y == 'A' and rnd % 4 == 0)
            ptsx, ptsy = 100, 100
            if x == 'A':
                ptsx += 0 if star_out else 8
                ptsy += 8 if star_out else 0
            if y == 'A':
                ptsy += 0 if star_out else 8
                ptsx += 8 if star_out else 0
            if ptsx == ptsy:
                ptsx += 1
            g = '002%07d' % gid
            d = '2023-%02d-%02d' % (1 + date // 28 % 12, 1 + date % 28)
            team_rows.append({'season': 2023, 'game_id': g, 'team_id': x, 'opp_team_id': y, 'game_date': d, 'pts': ptsx})
            team_rows.append({'season': 2023, 'game_id': g, 'team_id': y, 'opp_team_id': x, 'game_date': d, 'pts': ptsy})
            for t in (x, y):
                for p in range(8):
                    if t == 'A' and p == 0 and star_out:
                        continue
                    player_rows.append({'game_id': g, 'team_id': t, 'player_id': t + str(p), 'fga': 15 if p == 0 else 9})
    return team_rows, player_rows


class PersonnelEffectTest(unittest.TestCase):
    def test_rotation_requires_history(self):
        self.assertEqual(rotation([]), set())

    def test_star_absence_effect_detected(self):
        team_rows, player_rows = synth()
        games = build_games(team_rows)
        appear = build_appearances(player_rows)
        recs = simulate(games, appear, 10)
        self.assertEqual(len(recs), len(games))
        late = [r for r in recs[-60:] if r['absent_players'] > 0]
        self.assertTrue(late)
        base = sum(abs(r['actual'] - r['base']) for r in late)
        adj = sum(abs(r['actual'] - r['adjusted']) for r in late)
        self.assertLess(adj, base)

    def test_evaluate_runs_without_release(self):
        team_rows, player_rows = synth()
        result = evaluate(build_games(team_rows), build_appearances(player_rows))
        self.assertIn('candidates', result)


if __name__ == '__main__':
    unittest.main()
