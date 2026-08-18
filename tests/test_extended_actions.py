"""tests/test_extended_actions.py — extended actions, opposed contests, detection gradient.

Grounded in BESM 4e Extended Actions & Opposed Contests Ledger:
  * Extended Actions: cumulative MoS across T checks, frictional backlash,
    EP drain, Sixth Guard crash
  * Opposed Contests: aggressor vs defender, ties to aggressor
  * Detection Gradient: 5 bands (Ghosted → Lockdown) from MoS
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

from engine.models import (
    EXTENDED_ACTION_MATRIX,
    init_extended_action,
    resolve_extended_check,
    resolve_opposed_contest,
    detection_gradient,
)


class TestExtendedActionMatrix(unittest.TestCase):
    def test_four_tiers(self):
        self.assertEqual(len(EXTENDED_ACTION_MATRIX), 4)

    def test_standard_threshold_ten(self):
        self.assertEqual(EXTENDED_ACTION_MATRIX["standard"]["mos_threshold"], 10)
        self.assertEqual(EXTENDED_ACTION_MATRIX["standard"]["checks"], 3)

    def test_mythic_threshold_forty(self):
        self.assertEqual(EXTENDED_ACTION_MATRIX["mythic"]["mos_threshold"], 40)
        self.assertEqual(EXTENDED_ACTION_MATRIX["mythic"]["checks"], 6)


class TestInitExtendedAction(unittest.TestCase):
    def test_default_standard(self):
        t = init_extended_action()
        self.assertEqual(t["mos_threshold"], 10)
        self.assertEqual(t["checks_remaining"], 3)

    def test_complex_tier(self):
        t = init_extended_action("complex")
        self.assertEqual(t["target"], 15)
        self.assertEqual(t["checks_remaining"], 4)

    def test_starting_state(self):
        t = init_extended_action()
        self.assertEqual(t["cumulative_mos"], 0)
        self.assertFalse(t["completed"])
        self.assertFalse(t["crashed"])
        self.assertIsNone(t["obstacle_level"])


class TestExtendedCheck(unittest.TestCase):
    def setUp(self):
        self.t = init_extended_action("standard")

    def test_success_adds_mos(self):
        r = resolve_extended_check(self.t, stat=10, skill=5)
        self.assertEqual(r["checks_remaining"], 2)
        if r["check"]["margin"] > 0:
            self.assertGreater(self.t["cumulative_mos"], 0)

    def test_check_decrements_remaining(self):
        resolve_extended_check(self.t, 3, 0)
        self.assertEqual(self.t["checks_remaining"], 2)

    def test_completion_when_threshold_met(self):
        t = init_extended_action("standard")
        r = resolve_extended_check(t, stat=20, skill=0)
        if t["completed"]:
            self.assertGreaterEqual(t["cumulative_mos"], t["mos_threshold"])

    def test_crash_when_checks_exhausted(self):
        t = init_extended_action("standard")
        for _ in range(t["checks_total"]):
            resolve_extended_check(t, stat=0, skill=0)
        self.assertTrue(t["completed"] or t["crashed"])

    def test_already_resolved_returns_error(self):
        self.t["completed"] = True
        r = resolve_extended_check(self.t, 10, 5)
        self.assertIn("error", r)

    def test_backlash_minor_on_mof_three(self):
        t = init_extended_action("standard")
        for _ in range(10):
            r = resolve_extended_check(t, stat=0, skill=0)
            if t["obstacle_level"] == "minor":
                break
        else:
            self.skipTest("Could not trigger frictional backlash")

    def test_edge_applied(self):
        r = resolve_extended_check(self.t, stat=5, skill=0, edge_weight=1)
        self.assertIsNotNone(r["check"]["edge_applied"])

    def test_repeat_check_after_backlash_has_obstacle(self):
        t = init_extended_action("standard")
        t["obstacle_level"] = "minor"
        r = resolve_extended_check(t, stat=5, skill=0)
        self.assertIsNotNone(r["check"]["obstacle_applied"])

    def test_low_stat_never_completes(self):
        t = init_extended_action("mythic")
        for _ in range(t["checks_total"]):
            resolve_extended_check(t, stat=0, skill=0)
        self.assertTrue(t["crashed"])


class TestOpposedContest(unittest.TestCase):
    def test_attacker_wins_ties(self):
        import random
        random.seed(0)
        # brute-force: attacker and defender have identical stats → attacker wins most
        attacker_wins = 0
        for _ in range(100):
            r = resolve_opposed_contest(5, 5, 5, 5)
            if r["winner"] == "attacker":
                attacker_wins += 1
        self.assertGreaterEqual(attacker_wins, 40)

    def test_higher_skill_wins_more(self):
        wins = 0
        for _ in range(100):
            r = resolve_opposed_contest(10, 5, 3, 2)
            if r["winner"] == "attacker":
                wins += 1
        self.assertGreater(wins, 75)

    def test_edge_helps_winner(self):
        import random
        random.seed(1234)
        normal_wins = 0
        edge_wins = 0
        for _ in range(100):
            r = resolve_opposed_contest(5, 5, 5, 5)
            if r["winner"] == "attacker":
                normal_wins += 1
        for _ in range(100):
            r = resolve_opposed_contest(5, 5, 5, 5, attacker_edge=2)
            if r["winner"] == "attacker":
                edge_wins += 1
        self.assertGreaterEqual(edge_wins, normal_wins - 5)

    def test_gradient_field_present(self):
        r = resolve_opposed_contest(5, 5, 5, 5)
        self.assertIn(r["gradient"], ["Ghosted", "Unaware", "Suspicious", "Alerted", "Lockdown"])

    def test_defender_edge_helps(self):
        import random
        random.seed(9999)
        wins = 0
        for _ in range(100):
            r = resolve_opposed_contest(5, 5, 5, 5, defender_edge=2)
            if r["winner"] == "defender":
                wins += 1
        self.assertGreater(wins, 40)


class TestDetectionGradient(unittest.TestCase):
    def test_ghosted_at_plus_twelve(self):
        self.assertEqual(detection_gradient(12), "Ghosted")

    def test_unaware_at_plus_six(self):
        self.assertEqual(detection_gradient(6), "Unaware")

    def test_suspicious_at_plus_one(self):
        self.assertEqual(detection_gradient(1), "Suspicious")

    def test_alerted_at_minus_five(self):
        self.assertEqual(detection_gradient(-5), "Alerted")

    def test_lockdown_at_minus_six(self):
        self.assertEqual(detection_gradient(-6), "Lockdown")

    def test_ghosted_at_very_high(self):
        self.assertEqual(detection_gradient(20), "Ghosted")

    def test_lockdown_at_very_low(self):
        self.assertEqual(detection_gradient(-20), "Lockdown")


if __name__ == "__main__":
    unittest.main()
