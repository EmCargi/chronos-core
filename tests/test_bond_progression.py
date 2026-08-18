"""tests/test_bond_progression.py — Bond Progression Framework V2.0.
Trust scores (0-100), 4 phases, agency toggle, group mechanics.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.models import (
    BOND_PHASES,
    bond_phase,
    apply_trust,
    TRUST_GAINS,
    TRUST_LOSSES,
    gain_trust,
    lose_trust,
    shared_triumph,
    favoritism_tax,
    group_bond_stats,
)


class TestBondPhases(unittest.TestCase):
    def test_surface_range(self):
        self.assertEqual(bond_phase(0), "Surface")
        self.assertEqual(bond_phase(25), "Surface")
        self.assertEqual(bond_phase(50), "Surface")

    def test_warmth_range(self):
        self.assertEqual(bond_phase(51), "Warmth")
        self.assertEqual(bond_phase(75), "Warmth")

    def test_confidant_range(self):
        self.assertEqual(bond_phase(76), "Confidant")
        self.assertEqual(bond_phase(99), "Confidant")

    def test_soulbound(self):
        self.assertEqual(bond_phase(100), "Soulbound")

    def test_four_phases(self):
        self.assertEqual(len(BOND_PHASES), 4)


class TestApplyTrust(unittest.TestCase):
    def test_clamped_at_zero(self):
        self.assertEqual(apply_trust(10, -20), 0)

    def test_clamped_at_one_hundred(self):
        self.assertEqual(apply_trust(95, 10), 100)

    def test_normal_delta(self):
        self.assertEqual(apply_trust(30, 15), 45)


class TestTrustGains(unittest.TestCase):
    def test_kindness_gain(self):
        r = gain_trust(30, "kindness")
        self.assertEqual(r["new_trust"], 35)
        self.assertEqual(r["phase_before"], "Surface")
        self.assertEqual(r["phase_after"], "Surface")

    def test_protect_gain(self):
        r = gain_trust(45, "protect")
        self.assertEqual(r["new_trust"], 55)
        self.assertEqual(r["phase_after"], "Warmth")

    def test_intimacy_once_per_phase(self):
        # First intimacy
        r = gain_trust(55, "intimacy")
        self.assertEqual(r["delta"], 10)
        # Second intimacy in same phase — blocked
        r2 = gain_trust(r["new_trust"], "intimacy", already_in_phase=True)
        self.assertEqual(r2["delta"], 0)

    def test_vulnerable_gain(self):
        r = gain_trust(72, "vulnerable")
        self.assertEqual(r["new_trust"], 82)
        self.assertEqual(r["phase_after"], "Confidant")

    def test_trust_table_has_seven_gains(self):
        self.assertEqual(len(TRUST_GAINS), 7)


class TestTrustLosses(unittest.TestCase):
    def test_reckless_loss(self):
        r = lose_trust(60, "reckless")
        self.assertEqual(r["new_trust"], 45)
        self.assertEqual(r["phase_after"], "Surface")

    def test_betrayal_reset(self):
        r = lose_trust(95, "betrayal")
        self.assertEqual(r["new_trust"], 45)  # 95 - 50

    def test_broken_promise_loss(self):
        r = lose_trust(80, "broken_promise")
        self.assertEqual(r["new_trust"], 55)

    def test_loss_table_has_four_losses(self):
        self.assertEqual(len(TRUST_LOSSES), 4)


class TestSharedTriumph(unittest.TestCase):
    def test_hero_gets_plus_ten(self):
        bonds = {"Zarlen": 40, "Dillia": 50, "Nei": 20}
        result = shared_triumph(bonds, "Zarlen")
        self.assertEqual(result["Zarlen"], 50)
        self.assertEqual(result["Dillia"], 55)
        self.assertEqual(result["Nei"], 25)

    def test_witnesses_get_plus_five(self):
        bonds = {"A": 10, "B": 10, "C": 10}
        result = shared_triumph(bonds, "A")
        self.assertEqual(result["A"], 20)
        self.assertEqual(result["B"], 15)
        self.assertEqual(result["C"], 15)


class TestFavoritismTax(unittest.TestCase):
    def test_favored_unaffected(self):
        bonds = {"A": 50, "B": 50}
        result = favoritism_tax(bonds, "A")
        self.assertEqual(result["A"], 50)
        self.assertEqual(result["B"], 40)

    def test_neglected_lose_ten(self):
        bonds = {"Rosivelle": 75, "Dillia": 45, "Sefne": 60}
        result = favoritism_tax(bonds, "Rosivelle")
        self.assertEqual(result["Rosivelle"], 75)
        self.assertEqual(result["Dillia"], 35)
        self.assertEqual(result["Sefne"], 50)


class TestGroupBondStats(unittest.TestCase):
    def test_average_trust(self):
        bonds = {"A": 10, "B": 20, "C": 30}
        stats = group_bond_stats(bonds)
        self.assertEqual(stats["average"], 20)

    def test_lowest_member(self):
        bonds = {"A": 50, "B": 20, "C": 80}
        stats = group_bond_stats(bonds)
        self.assertEqual(stats["lowest_name"], "B")
        self.assertEqual(stats["lowest_trust"], 20)

    def test_empty_dict(self):
        stats = group_bond_stats({})
        self.assertEqual(stats["average"], 0)
        self.assertIsNone(stats["lowest_name"])


if __name__ == "__main__":
    unittest.main()
