import unittest
from editorial_score import reaction_peaks, opening_quality
from earnings_report import required_views


class EditorialTests(unittest.TestCase):
    def test_loudness_change_not_constant_background_or_silence(self):
        self.assertEqual(reaction_peaks([0.] * 120, rate=20), [])
        self.assertEqual(reaction_peaks([.2] * 120, rate=20), [])
        self.assertEqual(reaction_peaks([.01] * 60 + [.2] * 10 + [.01] * 50, rate=20), [3.])

    def test_opening_penalizes_filler_without_matching_substrings(self):
        self.assertLess(opening_quality([(0,1,"um"),(1,2,"wait")]), opening_quality([(0,1,"unbelievable")]))
        self.assertLess(opening_quality([(4,5,"look")]), opening_quality([(0,1,"look")]))

    def test_profit_math_includes_costs_and_rejects_zero_rate(self):
        self.assertEqual(required_views(500, .90), 555556)
        self.assertEqual(required_views(500, .10, 20), 5200000)
        with self.assertRaises(ValueError):
            required_views(500,0)
