import copy
import unittest
from push_pricing import empirical_integer_probabilities, residual_total_probabilities, price_reference


class PushPricingTests(unittest.TestCase):
    def setUp(self):
        self.rules = {'bookmaker':'Synthetic', 'jurisdiction':'TEST', 'market':'total',
                      'market_scope':'full_game', 'includes_overtime':True,
                      'push_settlement':'cash_stake_refund', 'rules_verified':True,
                      'rules_source':'https://example.org/rules', 'verified_at_utc':'2026-11-18T19:00:00Z'}
        self.as_of = '2026-11-18T20:00:00Z'
        self.samples = [228] * 80 + [230] * 30 + [232] * 90

    def distribution(self, side='over'):
        return empirical_integer_probabilities(self.samples, 'total', side, 230)

    def test_three_outcomes_and_correct_price(self):
        d = self.distribution()
        self.assertEqual(d['counts'], {'win':90,'push':30,'loss':80})
        p = price_reference(d, 2., self.rules, self.as_of)
        self.assertAlmostEqual(p['ev_per_unit_stake'], .05)
        self.assertAlmostEqual(p['fair_decimal_odds'], 1 + .4 / .45)
        self.assertAlmostEqual(p['break_even_p_win_unconditional'], .425)
        self.assertAlmostEqual(p['p_win_given_no_push'], .45 / .85)
        self.assertIsNone(p['recommendation'])
        self.assertFalse(p['betting_release'])

    def test_opposite_sides_swap_win_loss_keep_push(self):
        a, b = self.distribution(), self.distribution('under')
        self.assertEqual(a['p_win'], b['p_loss'])
        self.assertEqual(a['p_loss'], b['p_win'])
        self.assertEqual(a['p_push'], b['p_push'])

    def test_bin_estimate_explicitly_unvalidated(self):
        errors = [-2.2] * 80 + [.1] * 30 + [1.8] * 90
        d = residual_total_probabilities(230, errors, 'over', 230)
        self.assertEqual(d['counts'], self.distribution()['counts'])
        self.assertEqual(d['probability_validation'], 'unvalidated')
        self.assertEqual(d['method'], 'experimental_total_residual_bins_v1')
        for x in (-.5,.5):
            with self.subTest(boundary=x), self.assertRaises(ValueError):
                residual_total_probabilities(230, [x] * 200, 'over', 230)

    def test_discrete_spread_and_zero_handicap(self):
        samples = [-4] * 80 + [-2] * 30 + [4] * 90
        h = empirical_integer_probabilities(samples, 'spread', 'home', 2)
        a = empirical_integer_probabilities(samples, 'spread', 'away', -2)
        self.assertEqual(h['p_push'], .15)
        self.assertEqual(h['p_win'], a['p_loss'])
        self.assertEqual(empirical_integer_probabilities(samples, 'spread', 'home', 0)['p_push'], 0)
        with self.assertRaises(ValueError):
            empirical_integer_probabilities([0] * 200, 'spread', 'home', 0)

    def test_invalid_samples_lines_and_values(self):
        for samples, market, side, line in [([230]*199,'total','over',230),
                ([230.1]*200,'total','over',230), ([-1]*200,'total','over',230),
                ([230]*200,'total','over',230.25),([230]*200,'total','over',230.5),
                ([True]*200,'total','over',230),([float('nan')]*200,'total','over',230),
                ([230]*200,'total','home',230),([230]*200,'total','over',True)]:
            with self.subTest(market=market,side=side,line=line),self.assertRaises(ValueError):
                empirical_integer_probabilities(samples,market,side,line)
        with self.assertRaises(ValueError):
            residual_total_probabilities(230,[-300]*200,'over',230)

    def test_unknown_or_mismatched_rules_blocked(self):
        changes = [{'rules_verified':False},{'jurisdiction':''},{'market':'spread'},
                   {'includes_overtime':False},{'push_settlement':'stake_lost'},
                   {'market_scope':'first_half'},{'rules_source':'http://example.org'},
                   {'verified_at_utc':'2026-11-18T21:00:00Z'},
                   {'verified_at_utc':'2026-11-18T19:00:00'}]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):
                price_reference(self.distribution(),2.,dict(self.rules,**change),self.as_of)

    def test_probability_and_odds_validation(self):
        for change in [{'p_win':.9},{'p_push':-.1},{'p_loss':float('inf')},{'p_win':True}]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                price_reference(dict(self.distribution(),**change),2.,self.rules,self.as_of)
        for q in [1,0,True,'2.0',float('nan')]:
            with self.subTest(odds=q),self.assertRaises(ValueError):
                price_reference(self.distribution(),q,self.rules,self.as_of)

    def test_edge_cases_and_no_push_regression(self):
        for win,push,loss,expected,state in [(0,1,0,0,'all_push'),(0,.2,.8,-.8,'no_finite_fair_price'),
                                           (.6,0,.4,.2,'finite'),(1,0,0,1,'finite')]:
            d = dict(self.distribution(),p_win=win,p_push=push,p_loss=loss)
            p = price_reference(d,2.,self.rules,self.as_of)
            self.assertAlmostEqual(p['ev_per_unit_stake'],expected)
            self.assertEqual(p['price_state'],state)
        p = price_reference(dict(self.distribution(),p_win=.6,p_push=0,p_loss=.4),1.9,self.rules,self.as_of)
        self.assertAlmostEqual(p['ev_per_unit_stake'],.6*1.9-1)
        self.assertAlmostEqual(p['fair_decimal_odds'],1/.6)

    def test_probability_grid_price_identities(self):
        for push_count in range(21):
            for win_count in range(21-push_count):
                win, push = win_count/20, push_count/20
                loss = (20-push_count-win_count)/20
                d = {'market':'total','side':'over','line':230,'method':'synthetic_unit_test',
                     'p_win':win,'p_push':push,'p_loss':loss}
                p = price_reference(d,1.91,self.rules,self.as_of)
                self.assertAlmostEqual(p['ev_per_unit_stake'],win*1.91-(1-push))
                if win:
                    self.assertAlmostEqual(win*(p['fair_decimal_odds']-1)-loss,0)

    def test_input_immutability(self):
        d = self.distribution()
        before = copy.deepcopy((self.samples,d,self.rules))
        p = price_reference(d,2.,self.rules,self.as_of)
        p['rules_context']['bookmaker']='Changed'
        self.assertEqual((self.samples,d,self.rules),before)


if __name__=='__main__':
    unittest.main()
