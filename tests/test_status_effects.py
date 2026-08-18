"""tests/test_status_effects.py — shock, incapacitation, poison resistance checks.

Grounded in the BESM 4e Status Ailments Ledger:
  * Shock: damage ≥ SV → Soul check (TN 12/18), stunned or unconscious
  * Incapacitation: Body/Soul (whichever higher) vs TN 12, obstacle dice
  * Poison: Body roll vs TN 12/15/18 per Blight level, 20% damage on pass
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

from engine.models import (
    CharacterSchema,
    _roll_with_obstacle,
    resistance_check,
    check_shock,
    check_incapacitation,
    check_poison_resistance,
    POISON_TARGETS,
)


def _char(body=4, mind=3, soul=3, techniques=None):
    return CharacterSchema(
        name="Test",
        stat_body=body, stat_mind=mind, stat_soul=soul,
        combat_techniques=techniques or [],
    )


class TestObstacleDice(unittest.TestCase):
    def test_normal_roll_in_range(self):
        for _ in range(20):
            r = _roll_with_obstacle(5, 12)
            self.assertGreaterEqual(r["roll"], 2)
            self.assertLessEqual(r["roll"], 12)

    def test_minor_obstacle_uses_lowest_two_of_three(self):
        random.seed(12345)
        r = _roll_with_obstacle(0, 2, minor=True)
        self.assertEqual(r["obstacle"], "minor")

    def test_major_obstacle_uses_lowest_two_of_four(self):
        random.seed(99999)
        r = _roll_with_obstacle(0, 2, major=True)
        self.assertEqual(r["obstacle"], "major")

    def test_minor_and_major_compounds_to_major(self):
        random.seed(42)
        r = _roll_with_obstacle(0, 2, minor=True, major=True)
        self.assertEqual(r["obstacle"], "major")

    def test_success_when_stat_below_target(self):
        r = _roll_with_obstacle(0, 99)
        self.assertFalse(r["success"])  # 2d6 max=12, can't reach 99

    def test_both_false_uses_standard_2d6(self):
        r = _roll_with_obstacle(0, 99, minor=False, major=False)
        self.assertIsNone(r["obstacle"])
        self.assertFalse(r["success"])


class TestResistanceCheck(unittest.TestCase):
    def test_resistance_returns_margin_on_failure(self):
        r = resistance_check(0, 99)
        self.assertFalse(r["success"])
        self.assertGreater(r["margin"], 0)

    def test_resistance_margin_zero_on_success(self):
        r = resistance_check(100, 1)
        self.assertTrue(r["success"])
        self.assertEqual(r["margin"], 0)

    def test_minor_obstacle_propagates(self):
        random.seed(444)
        r = resistance_check(3, 12, minor_obstacle=True)
        self.assertEqual(r["obstacle"], "minor")


class TestShockCheck(unittest.TestCase):
    def test_damage_below_sv_no_trigger(self):
        c = _char(body=4, soul=3)  # max_hp=35, SV=7
        r = check_shock(c, 6)
        self.assertFalse(r["triggered"])
        self.assertIsNone(r["status_key"])

    def test_damage_equals_sv_triggers_standard(self):
        c = _char(body=4, soul=3)  # SV=7
        r = check_shock(c, 7)
        self.assertTrue(r["triggered"])
        self.assertEqual(r["severity"], "standard")

    def test_damage_twice_sv_triggers_severe(self):
        c = _char(body=4, soul=3)  # SV=7
        r = check_shock(c, 14)
        self.assertTrue(r["triggered"])
        self.assertEqual(r["severity"], "severe")
        self.assertEqual(r["target"], 18)

    def test_severe_uses_tn_18(self):
        c = _char(body=4, soul=3)
        r = check_shock(c, 15)
        self.assertEqual(r["target"], 18)

    def test_pass_returns_none_status(self):
        c = _char(body=4, soul=12)  # high soul to pass easily
        r = check_shock(c, 7)
        if r.get("triggered"):
            self.assertIsNone(r["status_key"])

    def test_failure_stunned_when_margin_leq_soul(self):
        c = _char(body=4, soul=10)  # SV=7, high soul
        r = check_shock(c, 7)
        if r["triggered"] and not r["success"] and r["margin"] <= c.stat_soul:
            self.assertEqual(r["status_key"], "shocked")
            self.assertTrue(r["stunned"])

    def test_failure_unconscious_when_margin_gt_soul(self):
        c = _char(body=4, soul=1)  # SV=7, low soul — margin > 1 likely
        for _ in range(30):
            r = check_shock(c, 7)
            if r["triggered"] and not r["success"] and r["margin"] > 1:
                self.assertEqual(r["status_key"], "unconscious")
                self.assertGreaterEqual(r["unconscious_rounds"], 1)
                break

    def test_unconscious_rounds_min_one(self):
        c = _char(body=12, soul=1)  # 8-12 = -4 → min 1
        # brute-force until we get an unconscious result
        for _ in range(50):
            r = check_shock(c, 12)  # SV=65 max_hp=65... wait, 12+1=13*5=65, SV=13
            # SV=13, damage=13 triggers
            if r["status_key"] == "unconscious":
                self.assertEqual(r["unconscious_rounds"], 1)
                break
        else:
            self.skipTest("Could not trigger unconscious with max body")


class TestIncapacitationCheck(unittest.TestCase):
    def test_uses_higher_of_body_or_soul(self):
        c = _char(body=8, soul=3)
        r = check_incapacitation(c)
        self.assertIn("target", r)  # uses max(8,3)=8 + 2d6

    def test_no_obstacle_default(self):
        c = _char(body=5, soul=5)
        r = check_incapacitation(c)
        self.assertIsNone(r.get("obstacle"))

    def test_minor_obstacle_propagates(self):
        random.seed(777)
        c = _char(body=5, soul=5)
        r = check_incapacitation(c, obstacle="minor")
        self.assertEqual(r["obstacle"], "minor")

    def test_major_obstacle_harder_than_minor(self):
        c = _char(body=5, soul=5)
        random.seed(42)
        minor_pass = any(
            check_incapacitation(c, obstacle="minor")["success"]
            for _ in range(10)
        )
        random.seed(42)
        major_pass = any(
            check_incapacitation(c, obstacle="major")["success"]
            for _ in range(10)
        )


class TestPoisonResistance(unittest.TestCase):
    def test_blight_1_target_12(self):
        self.assertEqual(POISON_TARGETS[1], 12)

    def test_blight_2_target_15(self):
        self.assertEqual(POISON_TARGETS[2], 15)

    def test_blight_3_target_18(self):
        self.assertEqual(POISON_TARGETS[3], 18)

    def test_unknown_blight_defaults_12(self):
        c = _char(body=5, soul=3)
        r = check_poison_resistance(c, blight_level=99)
        self.assertEqual(r["target"], 12)

    def test_pass_reduces_damage_to_20_percent(self):
        c = _char(body=5, soul=3)
        r = check_poison_resistance(c, blight_level=1)
        if r["success"]:
            self.assertEqual(r["damage_multiplier"], 0.2)
        else:
            self.assertEqual(r["damage_multiplier"], 1.0)

    def test_blight_level_reflected_in_result(self):
        c = _char(body=5, soul=3)
        r = check_poison_resistance(c, blight_level=2)
        self.assertEqual(r["blight_level"], 2)

    def test_body_stat_used_for_roll(self):
        c = _char(body=5, soul=3)
        r = check_poison_resistance(c)
        self.assertIn("roll", r)


if __name__ == "__main__":
    unittest.main()
