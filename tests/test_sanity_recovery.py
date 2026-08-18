"""tests/test_sanity_recovery.py — sanity points, catastrophic damage,
hemorrhage, natural recovery.

Grounded in BESM 4e Meat-Grinder Physics Ledger:
  * Sanity: SP = Mind+Soul+2×Unassailable-2×Unsettled, TN 12-24 checks,
    spiral penalties SP≤4 minor / SP≤2 major, 4 recovery methods
  * Catastrophic: damage ≥ max_hp → Soul TN 12 or instant death
  * Hemorrhage: damage ≥ SV → -1 HP/round, First Aid TN 12, Surgery TN 15
  * Recovery: HP = Body/day, EP = (Mind+Soul)//2/hour, Stun = Body/hour
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

from engine.models import (
    CharacterSchema,
    SANITY_TRAUMA_TABLE,
    max_sanity_points,
    check_sanity,
    sanity_obstacle,
    sanity_recovery,
    check_catastrophic_damage,
    hemorrhage_tick,
    first_aid_check,
    surgery_check,
    hp_recovery,
    ep_recovery,
    stun_recovery_rate,
    stat_drain_recovery_rate,
)


def _char(body=4, mind=3, soul=3):
    return CharacterSchema(name="Test", stat_body=body, stat_mind=mind, stat_soul=soul)


class TestMaxSanityPoints(unittest.TestCase):
    def test_baseline_mind_plus_soul(self):
        self.assertEqual(max_sanity_points(5, 5), 10)

    def test_unassailable_adds_two_per_level(self):
        self.assertEqual(max_sanity_points(5, 5, unassailable=2), 14)

    def test_unsettled_subtracts_two_per_rank(self):
        self.assertEqual(max_sanity_points(5, 5, unsettled=3), 4)

    def test_combined_modifiers(self):
        self.assertEqual(max_sanity_points(5, 5, unassailable=1, unsettled=2), 8)

    def test_floor_at_zero(self):
        self.assertEqual(max_sanity_points(5, 5, unassailable=0, unsettled=10), 0)


class TestSanityTraumaTable(unittest.TestCase):
    def test_five_magnitudes(self):
        self.assertEqual(len(SANITY_TRAUMA_TABLE), 5)

    def test_mild_target_twelve(self):
        self.assertEqual(SANITY_TRAUMA_TABLE["mild"]["target"], 12)

    def test_catastrophic_target_twenty_four(self):
        self.assertEqual(SANITY_TRAUMA_TABLE["catastrophic"]["target"], 24)

    def test_moderate_loss_one(self):
        self.assertEqual(SANITY_TRAUMA_TABLE["moderate"]["sp_loss"], 1)

    def test_severe_loss_three(self):
        self.assertEqual(SANITY_TRAUMA_TABLE["severe"]["sp_loss"], 3)


class TestSanityCheck(unittest.TestCase):
    def test_check_returns_expected_keys(self):
        r = check_sanity(5, 5, 10, "mild")
        for k in ("passed", "sp_loss", "new_sp", "target", "trauma"):
            self.assertIn(k, r)

    def test_unknown_trauma_defaults_mild(self):
        r = check_sanity(5, 5, 10, "nonexistent")
        self.assertEqual(r["target"], 12)

    def test_pass_no_sp_loss(self):
        r = check_sanity(5, 5, 10, "mild")
        if r["passed"]:
            self.assertEqual(r["sp_loss"], 0)

    def test_high_stat_passes_easily(self):
        passed = 0
        for _ in range(50):
            if check_sanity(20, 20, 20, "mild")["passed"]:
                passed += 1
        self.assertGreaterEqual(passed, 40)


class TestSanityObstacle(unittest.TestCase):
    def test_healthy_no_obstacle(self):
        self.assertIsNone(sanity_obstacle(10))

    def test_sp_five_no_obstacle(self):
        self.assertIsNone(sanity_obstacle(5))

    def test_sp_four_minor(self):
        self.assertEqual(sanity_obstacle(4), "minor")

    def test_sp_two_major(self):
        self.assertEqual(sanity_obstacle(2), "major")

    def test_sp_zero_major(self):
        self.assertEqual(sanity_obstacle(0), "major")

    def test_sp_negative_major(self):
        self.assertEqual(sanity_obstacle(-3), "major")


class TestSanityRecovery(unittest.TestCase):
    def test_therapy_restores_one(self):
        r = sanity_recovery("therapy")
        self.assertEqual(r["sp_restored"], 1)
        self.assertEqual(r["tn"], 15)

    def test_reassurance_restores_one_no_tn(self):
        r = sanity_recovery("reassurance")
        self.assertEqual(r["sp_restored"], 1)
        self.assertEqual(r["tn"], 0)

    def test_supernatural_range(self):
        r = sanity_recovery("supernatural")
        self.assertGreaterEqual(r["sp_restored"], 2)
        self.assertLessEqual(r["sp_restored"], 4)

    def test_unknown_returns_zero(self):
        r = sanity_recovery("banana")
        self.assertEqual(r["sp_restored"], 0)


class TestCatastrophicDamage(unittest.TestCase):
    def test_damage_below_max_no_trigger(self):
        c = _char(body=5, soul=5)  # max_hp=50
        r = check_catastrophic_damage(c, 30)
        self.assertFalse(r["triggered"])
        self.assertTrue(r["passed"])

    def test_damage_equals_max_triggers(self):
        c = _char(body=5, soul=5)  # max_hp=50
        r = check_catastrophic_damage(c, 50)
        self.assertTrue(r["triggered"])

    def test_result_structure(self):
        c = _char(body=5, soul=5)
        r = check_catastrophic_damage(c, 100)
        self.assertIn("total", r)
        self.assertEqual(r["target"], 12)


class TestHemorrhage(unittest.TestCase):
    def test_one_injury_one_hp_per_round(self):
        self.assertEqual(hemorrhage_tick(1), 1)

    def test_three_injuries_cumulative(self):
        self.assertEqual(hemorrhage_tick(3), 3)

    def test_first_aid_check(self):
        r = first_aid_check(5, 3)
        self.assertIn("success", r)

    def test_surgery_check(self):
        r = surgery_check(5, 3)
        self.assertIn("success", r)


class TestNaturalRecovery(unittest.TestCase):
    def test_hp_body_per_day(self):
        self.assertEqual(hp_recovery(5, 3), 15)

    def test_hp_medical_doubles(self):
        self.assertEqual(hp_recovery(5, 3, has_medical=True), 30)

    def test_hp_not_resting_halves(self):
        self.assertEqual(hp_recovery(8, 1, not_resting=True), 4)

    def test_ep_formula(self):
        self.assertEqual(ep_recovery(5, 5, 4), 20)  # (5+5)//2=5 * 4

    def test_ep_with_inspire(self):
        self.assertEqual(ep_recovery(5, 5, 3, inspire_level=2), 21)  # (5+2)*3

    def test_stun_recovery(self):
        self.assertEqual(stun_recovery_rate(6), 6)

    def test_stat_drain_recovery(self):
        self.assertEqual(stat_drain_recovery_rate(), 1)


if __name__ == "__main__":
    unittest.main()
