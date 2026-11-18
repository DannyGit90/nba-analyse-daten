import copy
import unittest
import test_daily_review as existing
from daily_review import score


class RuleBindingScoringTests(unittest.TestCase):
    def setUp(self):
        fixture = existing.DailyReviewTests()
        fixture.setUp()
        self.now, self.paper, self.d = fixture.now, fixture.paper, fixture.d
        self.offers = fixture.offers

    def offer_with_rule_evidence(self):
        offer = next(o for o in self.offers() if o['market'] == 'total')
        offer.update(line=220, rules_verified=True, jurisdiction='TEST',
                     market_scope='full_game', includes_overtime=True)
        offer['push_rules'] = {'bookmaker':offer['bookmaker'], 'jurisdiction':'TEST',
                              'market':'total', 'market_scope':'full_game', 'includes_overtime':True,
                              'push_settlement':'cash_stake_refund', 'rules_verified':True,
                              'rules_source':'https://example.org/rules',
                              'verified_at_utc':'2026-11-18T15:30:00Z'}
        return offer

    def test_scoring_matches_rule_metadata_without_enabling_push(self):
        offer = self.offer_with_rule_evidence()
        before = copy.deepcopy(offer)
        row = score(self.paper,self.d,[offer],self.now)[0]
        self.assertEqual(row['push_blockers'],['push_integration_pending'])
        self.assertEqual(row['push_rule_check']['offer_binding_check'],'supplied_metadata_only')
        self.assertEqual(row['calculation_status'],'not_computed')
        self.assertNotIn('push_rule_binding_error',row)
        self.assertNotIn('p_experimental',row)
        self.assertNotIn('paper_ev',row)
        self.assertFalse(row['betting_release'])
        self.assertIsNone(row['recommendation'])
        row['push_rule_check']['offer_binding']['jurisdiction']='Changed'
        self.assertEqual(offer,before)

    def test_scoring_reports_rule_binding_errors(self):
        base = self.offer_with_rule_evidence()
        for change in [{'bookmaker':'Other'},{'jurisdiction':'OTHER'},{'market':'spread'},
                       {'includes_overtime':False},{'push_settlement':'stake_lost'},
                       {'rules_source':'https:///missing-host'},
                       {'verified_at_utc':'2026-11-18T17:00:00Z'}]:
            offer = copy.deepcopy(base);offer['push_rules'].update(change)
            with self.subTest(change=change):
                row = score(self.paper,self.d,[offer],self.now)[0]
                self.assertIn('rule_to_offer_binding_pending',row['push_blockers'])
                self.assertTrue(row['push_rule_binding_error'])
                self.assertNotIn('push_rule_check',row)
                self.assertEqual(row['calculation_status'],'not_computed')

    def test_scoring_rule_check_never_calls_price_calculation(self):
        from unittest.mock import patch
        offer = self.offer_with_rule_evidence()
        with patch('push_pricing.price_reference',side_effect=AssertionError('Pricing must not run')):
            row = score(self.paper,self.d,[offer],self.now)[0]
        self.assertIn('push_rule_check',row)
        self.assertEqual(row['push_blockers'],['push_integration_pending'])


if __name__ == '__main__':
    unittest.main()
