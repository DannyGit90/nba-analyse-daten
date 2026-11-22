import copy
import json
import unittest
from decimal import Decimal
from playing_time_checks import compare_values,compare_rows


def log(**changes):
    r={'season':2027,'game_id':'0022600001','player_id':'P1','team_id':'T1','min':30.0};r.update(changes);return r


def box(**changes):
    r={'season':2027,'game_id':'0022600001','player_id':'P1','team_id':'T1','seconds_played':1800};r.update(changes);return r


class PlayingTimeCheckTests(unittest.TestCase):
    def test_decimal_match_still_not_unit_or_model_approval(self):
        r=compare_values(30.0,1800)
        self.assertEqual(r['status'],'decimal_value_match');self.assertEqual(r['delta_seconds_decimal'],'0')
        for field in ('units_verified','model_input_approved','betting_release'):self.assertFalse(r[field])

    def test_float_representation_is_distinguished_without_tolerance(self):
        r=compare_values(1/60,1)
        self.assertEqual(r['status'],'float_roundtrip_match')
        self.assertNotEqual(Decimal(r['delta_seconds_decimal']),0)

    def test_half_second_difference_not_rounded_away(self):
        r=compare_values(0.125,8)
        self.assertEqual(r['status'],'observed_difference')
        self.assertEqual(Decimal(r['delta_seconds_decimal']),Decimal('-0.5'))

    def test_tiny_real_difference_not_accepted_by_epsilon(self):
        r=compare_values(30.000000000001,1800)
        self.assertEqual(r['status'],'observed_difference');self.assertFalse(r['float_roundtrip_matches'])

    def test_invalid_minutes(self):
        for value in [None,True,'30',-1,float('nan'),float('inf'),10**400]:
            with self.subTest(value=repr(value)[:50]):
                self.assertIn('min',compare_values(value,1800)['invalid_fields'])

    def test_invalid_seconds_and_integer_schema(self):
        for value in [None,True,'1800',1800.0,-1,2147483648,float('nan')]:
            with self.subTest(value=repr(value)):
                self.assertIn('seconds_played',compare_values(30,value)['invalid_fields'])

    def test_zero_not_interpreted_as_absence(self):
        r=compare_values(0,0)
        self.assertEqual(r['status'],'decimal_value_match')
        self.assertNotIn('played',r);self.assertNotIn('healthy',r)

    def test_overtime_minutes_not_capped_at_48(self):
        self.assertEqual(compare_values(53.5,3210)['status'],'decimal_value_match')

    def test_all_key_fields_must_match(self):
        for field,value in [('season',2026),('game_id','0022600002'),('player_id','P2'),('team_id','T2')]:
            with self.subTest(field=field):
                r=compare_rows([log()],[box(**{field:value})])
                self.assertEqual(len(r['records']),2)
                self.assertEqual(set(r['status_counts']),{'missing_log_row','missing_box_row'})

    def test_duplicates_never_cartesian_match_or_silently_deduplicate(self):
        for left,right in [([log(),log()],[box()]),([log()],[box(),box()]),([log(),log()],[box(),box()])]:
            r=compare_rows(left,right)
            self.assertEqual(len(r['records']),1);self.assertEqual(r['records'][0]['status'],'ambiguous_key')
            self.assertNotIn('delta_seconds_decimal',r['records'][0])

    def test_missing_values_not_imputed(self):
        r=compare_rows([log(min=None)],[box()])
        self.assertEqual(r['records'][0]['status'],'invalid_value')
        self.assertEqual(compare_rows([log()],[])['records'][0]['status'],'missing_box_row')

    def test_invalid_keys_are_reported_separately(self):
        for changed in [dict(player_id=None),dict(team_id=['T1']),dict(season=True),dict(game_id=' 0022600001')]:
            r=compare_rows([log(**changed)],[box()])
            self.assertEqual(len(r['invalid_key_rows']),1)
            self.assertNotIn('decimal_value_match',r['status_counts'])

    def test_input_rows_unchanged(self):
        left=[log()];right=[box()];before=copy.deepcopy((left,right))
        compare_rows(left,right);self.assertEqual((left,right),before)

    def test_nonfinite_diagnostics_are_json_safe(self):
        r=compare_rows([log(min=float('nan'))],[box()])
        json.dumps(r,allow_nan=False)

    def test_no_comparison_of_empty_inputs_claimed(self):
        r=compare_rows([],[]);self.assertEqual(r['records'],[])
        self.assertFalse(r['units_verified']);self.assertFalse(r['model_input_approved'])

    def test_rows_without_lists_rejected(self):
        with self.assertRaises(ValueError):compare_rows(None,[])


if __name__=='__main__':
    unittest.main()
