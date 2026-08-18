"""tests/test_defects.py — defect enforcement: Fragile HP, Reduced Damage,
Achilles Heel, Bane, Weak Point, Unsettled, Demure, No Healing/Nightmares,
Shortcoming, Sensory Impairment, Phobia, Easily Distracted.

Grounded in BESM 4e Defects & Vulnerabilities Reference Card (31 defects).
Focus on the 12 with clear mechanical hooks — the rest are narrative/GM discretion.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

from engine.models import (
    CharacterSchema,
    _defect_rank,
    defect_hp_modifier,
    defect_damage_modifier,
    defect_achilles_multiplier,
    defect_bane_damage,
    defect_weak_point_multiplier,
    defect_sanity_modifier,
    defect_social_modifier,
    defect_blocks_recovery,
    defect_shortcoming_obstacle,
    defect_sensory_obstacle,
    defect_phobia_check,
    defect_distraction_check,
)


def _char(body=4, mind=3, soul=3):
    return CharacterSchema(name="Test", stat_body=body, stat_mind=mind, stat_soul=soul)


class TestDefectRank(unittest.TestCase):
    def test_empty_returns_zero(self):
        self.assertEqual(_defect_rank([], "fragile"), 0)

    def test_case_insensitive(self):
        self.assertEqual(_defect_rank(
            [{"name": "FRAGILE", "rank": 2}], "fragile"), 2)

    def test_highest_rank(self):
        defects = [
            {"name": "Fragile", "rank": 1},
            {"name": "Fragile", "rank": 3},
        ]
        self.assertEqual(_defect_rank(defects, "fragile"), 3)

    def test_not_present(self):
        self.assertEqual(_defect_rank(
            [{"name": "Fragile", "rank": 1}], "bane"), 0)


class TestFragileHP(unittest.TestCase):
    def test_no_defect_zero(self):
        self.assertEqual(defect_hp_modifier([]), 0)

    def test_rank_one_minus_ten(self):
        self.assertEqual(defect_hp_modifier([{"name": "Fragile", "rank": 1}]), -10)

    def test_rank_two_minus_twenty(self):
        self.assertEqual(defect_hp_modifier([{"name": "Fragile", "rank": 2}]), -20)

    def test_rank_three_minus_thirty(self):
        self.assertEqual(defect_hp_modifier([{"name": "Fragile", "rank": 3}]), -30)


class TestReducedDamage(unittest.TestCase):
    def test_no_defect_zero(self):
        self.assertEqual(defect_damage_modifier([]), 0)

    def test_rank_two_minus_two(self):
        self.assertEqual(defect_damage_modifier(
            [{"name": "Reduced Damage", "rank": 2}]), -2)


class TestAchillesHeel(unittest.TestCase):
    def test_present_returns_double(self):
        self.assertEqual(defect_achilles_multiplier(
            [{"name": "Achilles Heel", "rank": 2}], "silver"), 2.0)

    def test_absent_returns_one(self):
        self.assertEqual(defect_achilles_multiplier([], "silver"), 1.0)


class TestBane(unittest.TestCase):
    def test_rank_one_ten_damage(self):
        self.assertEqual(defect_bane_damage([{"name": "Bane", "rank": 1}]), 10)

    def test_rank_three_thirty_damage(self):
        self.assertEqual(defect_bane_damage([{"name": "Bane", "rank": 3}]), 30)

    def test_no_defect_zero_damage(self):
        self.assertEqual(defect_bane_damage([]), 0)


class TestWeakPoint(unittest.TestCase):
    def test_present_double_and_bypass(self):
        mult, bypass = defect_weak_point_multiplier(
            [{"name": "Weak Point", "rank": 1}])
        self.assertEqual(mult, 2.0)
        self.assertTrue(bypass)

    def test_absent_normal(self):
        mult, bypass = defect_weak_point_multiplier([])
        self.assertEqual(mult, 1.0)
        self.assertFalse(bypass)


class TestUnsettled(unittest.TestCase):
    def test_rank_two_minus_four_sp(self):
        self.assertEqual(defect_sanity_modifier([{"name": "Unsettled", "rank": 2}]), -4)

    def test_no_defect_zero(self):
        self.assertEqual(defect_sanity_modifier([]), 0)


class TestDemure(unittest.TestCase):
    def test_rank_one_minus_two_scv(self):
        self.assertEqual(defect_social_modifier([{"name": "Demure", "rank": 1}]), -2)


class TestBlocksRecovery(unittest.TestCase):
    def test_nightmares_blocks_rest(self):
        r = defect_blocks_recovery([{"name": "Nightmares", "rank": 2}])
        self.assertTrue(r["rest"])
        self.assertFalse(r["hp"])

    def test_no_healing_blocks_hp(self):
        r = defect_blocks_recovery([{"name": "No Healing", "rank": 1}])
        self.assertTrue(r["hp"])
        self.assertFalse(r["rest"])

    def test_no_defects_blocks_nothing(self):
        r = defect_blocks_recovery([])
        self.assertFalse(r["hp"])
        self.assertFalse(r["rest"])


class TestShortcoming(unittest.TestCase):
    def test_major_aspect_minor_obstacle(self):
        self.assertEqual(
            defect_shortcoming_obstacle(
                [{"name": "Shortcoming", "rank": 1}], "strength"), "minor")

    def test_minor_aspect_major_obstacle(self):
        self.assertEqual(
            defect_shortcoming_obstacle(
                [{"name": "Shortcoming", "rank": 1}], "memory"), "major")

    def test_no_defect_none(self):
        self.assertIsNone(defect_shortcoming_obstacle([], "strength"))


class TestSensoryImpairment(unittest.TestCase):
    def test_present_major_obstacle(self):
        self.assertEqual(
            defect_sensory_obstacle([{"name": "Sensory Impairment", "rank": 2}]), "major")

    def test_absent_none(self):
        self.assertIsNone(defect_sensory_obstacle([]))


class TestPhobia(unittest.TestCase):
    def test_no_trigger_passes(self):
        c = _char(soul=3)
        r = defect_phobia_check(c, [{"name": "Phobia", "rank": 1}],
                                phobia_trigger=False)
        self.assertFalse(r["triggered"])
        self.assertTrue(r["passed"])

    def test_no_defect_passes(self):
        c = _char(soul=3)
        r = defect_phobia_check(c, [], phobia_trigger=True)
        self.assertFalse(r["triggered"])

    def test_triggered_with_defect(self):
        c = _char(soul=3)
        r = defect_phobia_check(c, [{"name": "Phobia", "rank": 2}],
                                phobia_trigger=True)
        self.assertTrue(r["triggered"])
        if not r["passed"]:
            self.assertEqual(r["obstacle_on_fail"], "major")


class TestEasilyDistracted(unittest.TestCase):
    def test_no_trigger_passes(self):
        c = _char(mind=3, soul=3)
        r = defect_distraction_check(c, [{"name": "Easily Distracted", "rank": 1}],
                                     trigger_present=False)
        self.assertFalse(r["triggered"])

    def test_triggered_with_defect(self):
        c = _char(mind=3, soul=3)
        r = defect_distraction_check(c, [{"name": "Easily Distracted", "rank": 2}],
                                     trigger_present=True)
        self.assertTrue(r["triggered"])

    def test_uses_higher_of_mind_or_soul(self):
        c = _char(mind=10, soul=1)
        r = defect_distraction_check(c, [{"name": "Easily Distracted", "rank": 1}],
                                     trigger_present=True)
        self.assertTrue(r["triggered"])


if __name__ == "__main__":
    unittest.main()
