import unittest
import personnel_records as pr
import test_personnel_records as baseline

OKC = """Caruso,
Alex
Out
Injury/Illness
-
Right
Hip
Soreness
Gilgeous-
Alexander,
Shai
Questionable
Injury/Illness
-
Low
Back
Contusion/
Neck
Strain
Holmgren,
Chet
Out
Injury/Illness
-
Right
Knee/
Injury
Recovery
Sorber,
Thomas
Out
Injury/Illness
-
Right
Knee
Surgery
Topic,
Nikola
Out
Injury/Illness
-
Left
Hip
Strain
Wallace,
Cason
Out
Injury/Illness
-
Left
Shoulder
Surgery
Williams,
Jalen
Out
Injury/Illness
-
Left
Ankle
Surgery
Williams,
Jaylin
Out
Injury/Illness
-
Low
Back
Spasms"""


class WrappedSurnameTests(unittest.TestCase):
    def test_captured_okc_name_and_previous_reason_boundary(self):
        r=pr.parse_section(baseline.section(OKC,game_date_et='2026-11-22',away='OKC',home='MIA',team='OKC'))
        self.assertTrue(r['parsing_complete'],r['errors'])
        self.assertEqual(len(r['players']),8)
        self.assertEqual(r['players'][1]['name_candidate'],'Gilgeous-Alexander, Shai')
        self.assertNotIn('Gilgeous',r['players'][0]['reason_text'])
        self.assertEqual(r['players'][1]['source_line_start'],9)
        self.assertTrue(r['players'][1]['raw_name_text'].startswith('Gilgeous-\nAlexander,'))
        self.assertTrue(all(p['player_id'] is None and not p['identity_verified'] for p in r['players']))

    def test_wrapped_surname_as_first_record(self):
        r=pr.parse_section(baseline.section('Finney-\nSmith,\nDorian\nOut\nRest'))
        self.assertTrue(r['parsing_complete']);self.assertEqual(r['players'][0]['name_candidate'],'Finney-Smith, Dorian')

    def test_bare_hyphen_does_not_become_name_prefix(self):
        r=pr.parse_section(baseline.section('First,\nOne\nOut\nRest\n-\nSecond,\nTwo\nOut\nRest'))
        self.assertEqual(r['players'][1]['name_candidate'],'Second, Two')
        self.assertEqual(r['players'][0]['reason_text'],'Rest -')

    def test_multiple_hyphen_fragments_and_suffix(self):
        r=pr.parse_section(baseline.section('Alpha-\nBeta-\nGamma\nJr.,\nOne\nOut\nRest'))
        self.assertTrue(r['parsing_complete'])
        self.assertEqual(r['players'][0]['name_candidate'],'Alpha-Beta-Gamma Jr., One')

    def test_reason_phrase_ending_hyphen_is_not_joined(self):
        r=pr.parse_section(baseline.section('First,\nOne\nOut\nInjury / Illness -\nSecond,\nTwo\nAvailable'))
        self.assertEqual(r['players'][1]['name_candidate'],'Second, Two')


if __name__=='__main__':
    unittest.main()
