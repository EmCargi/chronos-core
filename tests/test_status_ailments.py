"""tests/test_status_ailments.py — delivery vectors, decay ticks, treatment,
interruption rules, stun recovery, and cognitive subversion.

Extends the existing test_status_effects.py (shock / incapacitation / blight
checks) with the rest of the BESM Status Ailments Ledger:
  * Poison delivery vectors (injury/contact/ingested/inhaled + AR/gas immunity)
  * Continuing-poison ticks (20%/round), decay survival checks, field treatment
  * Sleep break rules vs paralysis/stone (magic-only)
  * Stun recovery at Body/hour
  * Mind Control gradient + break clause + exorcism clash
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

from engine.models import (
    CharacterSchema,
    resolve_poison_delivery,
    continuing_poison_tick,
    decay_survival_check,
    treat_poison,
    sleep_state_breaks,
    stun_recovery_per_hour,
    mind_control_gradient,
    mind_control_resistance,
    against_nature_break_check,
    exorcism_clash,
    DECAY_CHECK_TN,
)


def _char(body=5, mind=4, soul=4):
    return CharacterSchema(name="Test", stat_body=body, stat_mind=mind, stat_soul=soul)


class TestPoisonDeliveryVectors(unittest.TestCase):
    def test_injury_poison_blocked_by_armour(self):
        r = resolve_poison_delivery("injury", damage=10, target_ar=12)
        self.assertFalse(r["applies"])
        self.assertEqual(r["damage"], 0)

    def test_injury_poison_passes_when_armour_low(self):
        r = resolve_poison_delivery("injury", damage=10, target_ar=5)
        self.assertTrue(r["applies"])
        self.assertEqual(r["damage"], 10)

    def test_injury_blocked_by_force_field(self):
        r = resolve_poison_delivery("injury", damage=8, target_ar=0, force_field=10)
        self.assertFalse(r["applies"])

    def test_contact_ignores_armour(self):
        r = resolve_poison_delivery("contact", damage=6, target_ar=40)
        self.assertTrue(r["applies"])
        self.assertEqual(r["damage"], 6)

    def test_ingested_doubles_damage(self):
        r = resolve_poison_delivery("ingested", damage=7)
        self.assertEqual(r["damage"], 14)

    def test_inhaled_blocked_by_gas_mask(self):
        r = resolve_poison_delivery("inhaled", damage=9, has_gas_mask=True)
        self.assertFalse(r["applies"])

    def test_inhaled_applies_area(self):
        r = resolve_poison_delivery("inhaled", damage=9)
        self.assertTrue(r["applies"])

    def test_unknown_vector_rejected(self):
        r = resolve_poison_delivery("blood", damage=5)
        self.assertFalse(r["valid"])


class TestContinuingPoison(unittest.TestCase):
    def test_tick_is_twenty_percent(self):
        r = continuing_poison_tick(original_damage=50, assignments=3)
        self.assertEqual(r["tick_damage"], 10)

    def test_tick_minimum_one(self):
        r = continuing_poison_tick(original_damage=3, assignments=1)
        self.assertEqual(r["tick_damage"], 1)

    def test_rounds_match_assignments(self):
        r = continuing_poison_tick(original_damage=50, assignments=2)
        self.assertEqual(r["rounds_remaining_after_tick"], 1)

    def test_armour_no_protection(self):
        r = continuing_poison_tick(original_damage=50, assignments=1)
        self.assertFalse(r["armour_protected"])


class TestDecaySurvivalCheck(unittest.TestCase):
    def test_daily_is_minor_obstacle(self):
        r = decay_survival_check(stat_body=7, interval="daily")
        self.assertEqual(r["obstacle"], "minor")
        self.assertEqual(r["target"], DECAY_CHECK_TN)

    def test_hourly_is_major_obstacle(self):
        r = decay_survival_check(stat_body=7, interval="hourly")
        self.assertEqual(r["obstacle"], "major")


class TestFieldTreatment(unittest.TestCase):
    def test_blight_one_tn_12(self):
        r = treat_poison(healer_stat=6, skill_rank=2, blight_level=1)
        self.assertEqual(r["target"], 12)

    def test_blight_three_tn_18(self):
        r = treat_poison(healer_stat=6, skill_rank=2, blight_level=3)
        self.assertEqual(r["target"], 18)

    def test_success_neutralizes(self):
        r = treat_poison(healer_stat=10, skill_rank=5, blight_level=1)
        self.assertTrue(r["neutralized"])

    def test_failure_leaves_active(self):
        r = treat_poison(healer_stat=1, skill_rank=0, blight_level=3)
        self.assertFalse(r["neutralized"])


class TestInterruptionRules(unittest.TestCase):
    def test_sleep_breaks_on_damage(self):
        r = sleep_state_breaks("sleep", damage_taken=True)
        self.assertTrue(r["broken"])
        self.assertTrue(r["breakable"])

    def test_sleep_breaks_on_loud_noise(self):
        r = sleep_state_breaks("sleep", loud_noise=True)
        self.assertTrue(r["broken"])

    def test_sleep_unbroken_without_stimulus(self):
        r = sleep_state_breaks("sleep")
        self.assertFalse(r["broken"])
        self.assertIsNotNone(r["reason"])

    def test_paralysis_magic_only(self):
        r = sleep_state_breaks("paralyzed")
        self.assertFalse(r["breakable"])
        self.assertFalse(r["broken"])

    def test_stone_magic_only(self):
        r = sleep_state_breaks("stone")
        self.assertFalse(r["breakable"])

    def test_unknown_ailment_rejected(self):
        r = sleep_state_breaks("frog")
        self.assertFalse(r["breakable"])


class TestStunRecovery(unittest.TestCase):
    def test_recovers_body_per_hour(self):
        c = _char(body=6)
        self.assertEqual(stun_recovery_per_hour(c), 6)


class TestMindControl(unittest.TestCase):
    def test_gradient_level_labels(self):
        self.assertEqual(mind_control_gradient(1), "basic non-aggressive suggestions")
        self.assertEqual(mind_control_gradient(4), "aggressive commands")

    def test_defender_wins_with_edge(self):
        r = mind_control_resistance(defender_mind=8, defender_soul=5,
                                    controller_mind=4, mc_level=1)
        self.assertEqual(r["winner"], "defender")
        self.assertTrue(r["break_success"])

    def test_controller_wins_when_stronger(self):
        r = mind_control_resistance(defender_mind=2, defender_soul=2,
                                    controller_mind=8, mc_level=3)
        self.assertEqual(r["winner"], "controller")
        self.assertTrue(not r["break_success"])

    def test_mind_shield_adds_two_per_level(self):
        r = mind_control_resistance(defender_mind=4, defender_soul=4,
                                    controller_mind=6, mc_level=2,
                                    mind_shield_level=2)
        # defender: 4 + 4 = 8 vs controller 6 + 2 = 8 → tie goes to defender
        self.assertEqual(r["winner"], "defender")
        self.assertEqual(r["defender_total"], 8)

    def test_uses_higher_of_mind_or_soul(self):
        r = mind_control_resistance(defender_mind=2, defender_soul=7,
                                    controller_mind=5, mc_level=1)
        self.assertEqual(r["defender_stat"], 7)


class TestAgainstNatureBreak(unittest.TestCase):
    def test_lethal_command_major_edge(self):
        self.assertEqual(against_nature_break_check("attack your loved one"), 2)

    def test_humiliating_command_minor_edge(self):
        self.assertEqual(against_nature_break_check("a humiliating act"), 1)

    def test_benign_command_no_edge(self):
        self.assertEqual(against_nature_break_check("pass the salt"), 0)


class TestExorcismClash(unittest.TestCase):
    def test_exorcism_wins_clash(self):
        r = exorcism_clash(exorcist_soul=8, exorcism_level=3,
                           controller_soul=5, mc_level=2)
        self.assertTrue(r["success"])
        self.assertFalse(r["controller_alerted"])

    def test_controller_wins_alerts_exorcist(self):
        r = exorcism_clash(exorcist_soul=4, exorcism_level=1,
                           controller_soul=8, mc_level=4)
        self.assertFalse(r["success"])
        self.assertTrue(r["controller_alerted"])

    def test_formula_doubles_exorcism_level(self):
        r = exorcism_clash(exorcist_soul=5, exorcism_level=2,
                           controller_soul=5, mc_level=1)
        # 5 + 4 = 9 vs 5 + 1 = 6 → exorcist wins
        self.assertEqual(r["exorcist_total"], 9)


if __name__ == "__main__":
    unittest.main()