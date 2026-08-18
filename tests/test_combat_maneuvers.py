"""tests/test_combat_maneuvers.py — tactical stances, called shots, grappling.

Grounded in BESM Extras Combat Maneuvers & Tactical Stances Cheat Sheet:
tactical actions (one per round), two-weapon attacks, strike to wound,
touch attacks, called shots, grappling states, and multi-target dispersion.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

from engine.models import (
    TACTICAL_ACTIONS_PER_ROUND,
    CALLED_SHOTS,
    resolve_tactical_stance,
    two_weapon_attack,
    strike_to_wound,
    touch_attack,
    resolve_called_shot,
    grapple_attack_edges,
    grabbed_condition,
    escape_grapple,
    pin_condition,
    multi_target_dispersion,
)


class TestTacticalActions(unittest.TestCase):
    def test_aim_round_one_minor_edge(self):
        r = resolve_tactical_stance("aim", has_ranged=True, consecutive_rounds=1)
        self.assertEqual(r["attack_edge"], 1)
        self.assertTrue(r["valid"])

    def test_aim_round_two_major_edge(self):
        r = resolve_tactical_stance("aim", has_ranged=True, consecutive_rounds=2)
        self.assertEqual(r["attack_edge"], 2)

    def test_aim_requires_ranged(self):
        r = resolve_tactical_stance("aim", has_ranged=False)
        self.assertFalse(r["valid"])
        self.assertIn("ranged", r["reason"])

    def test_wait_for_opening(self):
        r = resolve_tactical_stance("wait", consecutive_rounds=1)
        self.assertEqual(r["attack_edge"], 1)
        self.assertTrue(r["valid"])

    def test_total_defence_major_edge_no_attack(self):
        r = resolve_tactical_stance("total_defence")
        self.assertEqual(r["defence_edge"], 2)
        self.assertFalse(r["can_attack"])

    def test_unknown_stance_rejected(self):
        r = resolve_tactical_stance("dodge")
        self.assertFalse(r["valid"])

    def test_underscore_alias_accepted(self):
        r = resolve_tactical_stance("total_defence")
        self.assertTrue(r["valid"])

    def test_one_tactical_action_per_round(self):
        self.assertEqual(TACTICAL_ACTIONS_PER_ROUND, 1)


class TestTwoWeaponAttack(unittest.TestCase):
    def test_single_target_minor_obstacle(self):
        r = two_weapon_attack(same_target=True)
        self.assertEqual(r["obstacle"], 1)

    def test_two_targets_major_obstacle(self):
        r = two_weapon_attack(same_target=False)
        self.assertEqual(r["obstacle"], 2)

    def test_technique_negates_penalty(self):
        techniques = [{"name": "Two Weapons", "level": 1}]
        r = two_weapon_attack(same_target=False, techniques=techniques)
        self.assertEqual(r["obstacle"], 0)
        self.assertTrue(r["negated"])

    def test_meister_correction_for_single_target(self):
        techniques = [{"name": "Two Weapons", "level": 1}]
        r = two_weapon_attack(same_target=True, techniques=techniques)
        self.assertEqual(r["obstacle"], 0)


class TestStrikeToWound(unittest.TestCase):
    def test_flat_damage_minimum_one(self):
        r = strike_to_wound(8)
        self.assertEqual(r["damage"], 8)
        self.assertTrue(r["flat"])

    def test_minimum_of_one(self):
        r = strike_to_wound(0)
        self.assertEqual(r["damage"], 1)

    def test_rejects_area(self):
        self.assertFalse(strike_to_wound(8, has_area=True)["valid"])

    def test_rejects_autofire(self):
        self.assertFalse(strike_to_wound(8, has_autofire=True)["valid"])

    def test_rejects_spreading(self):
        self.assertFalse(strike_to_wound(8, has_spreading=True)["valid"])


class TestTouchAttack(unittest.TestCase):
    def test_passive_minor_edge(self):
        r = touch_attack()
        self.assertEqual(r["edge"], 1)

    def test_called_touch_requires_called_shot(self):
        r = touch_attack(called_spot=True)
        self.assertTrue(r["requires_called_shot"])


class TestCalledShots(unittest.TestCase):
    def test_disarm_melee_minor_obstacle(self):
        r = resolve_called_shot("disarm_melee")
        self.assertEqual(r["obstacle"], 1)
        self.assertEqual(r["body_tn"], 15)
        self.assertFalse(r["hp_damage"])

    def test_disarm_ranged_major_obstacle(self):
        r = resolve_called_shot("disarm_ranged")
        self.assertEqual(r["obstacle"], 2)

    def test_reduce_armour_halves(self):
        r = resolve_called_shot("reduce_armour")
        self.assertEqual(r["ar_effect"], "half")

    def test_bypass_armour_ignores(self):
        r = resolve_called_shot("bypass_armour")
        self.assertEqual(r["ar_effect"], "ignore")

    def test_vital_spot_doubles_damage(self):
        r = resolve_called_shot("vital_spot")
        self.assertEqual(r["multiplier"], 2)

    def test_weak_point_tiny_gives_defender_edge(self):
        r = resolve_called_shot("weak_point_tiny")
        self.assertEqual(r["defender_edge"], 1)

    def test_weak_point_large_minor_obstacle(self):
        r = resolve_called_shot("weak_point_large")
        self.assertEqual(r["obstacle"], 1)

    def test_precise_aim_reduces_obstacle(self):
        # Major obstacle (bypass armour) downgrades only at technique level 2
        # (engine convention: reduction ≥2 → major→minor).
        techniques = [{"name": "Precise Aim", "level": 2}]
        r = resolve_called_shot("bypass_armour", techniques=techniques)
        self.assertEqual(r["obstacle"], 1)

    def test_unknown_shot_rejected(self):
        r = resolve_called_shot("eyeball")
        self.assertFalse(r["valid"])

    def test_underscore_alias_accepted(self):
        r = resolve_called_shot("weak_point_small")
        self.assertTrue(r["valid"])


class TestGrappling(unittest.TestCase):
    def test_free_hand_minor_edge(self):
        r = grapple_attack_edges(3, 0)
        self.assertEqual(r["edge"], 1)

    def test_four_free_hands_major_edge(self):
        r = grapple_attack_edges(4, 0)
        self.assertEqual(r["edge"], 2)

    def test_size_overload_marks_much_weaker(self):
        r = grapple_attack_edges(2, 1, size_rank_delta=3)
        self.assertTrue(r["much_weaker"])

    def test_grabbed_minor_melee_obstacle(self):
        r = grabbed_condition(grappler_body=5, target_body=5)
        self.assertEqual(r["melee_obstacle"], 1)
        self.assertEqual(r["task_obstacle"], 2)
        self.assertTrue(r["can_act"])

    def test_much_stronger_reduces_one_tier(self):
        r = grabbed_condition(grappler_body=5, target_body=5,
                              target_much_stronger=True)
        self.assertEqual(r["melee_obstacle"], 0)
        self.assertEqual(r["task_obstacle"], 1)

    def test_much_weaker_paralyzed(self):
        r = grabbed_condition(grappler_body=5, target_body=5,
                              target_much_weaker=True)
        self.assertTrue(r["paralyzed"])
        self.assertFalse(r["can_act"])

    def test_escape_threshold_is_five_times_body(self):
        r = escape_grapple(target_body=6, grappler_body=4)
        self.assertEqual(r["threshold"], 20)

    def test_pain_dissociation_auto_escape(self):
        r = escape_grapple(target_body=6, grappler_body=4, damage_dealt=21)
        self.assertTrue(r["auto_escape"])

    def test_insufficient_damage_no_auto_escape(self):
        r = escape_grapple(target_body=6, grappler_body=4, damage_dealt=19)
        self.assertFalse(r["auto_escape"])

    def test_pin_blocks_actions(self):
        r = pin_condition()
        self.assertFalse(r["can_attack"])
        self.assertFalse(r["can_defend"])
        self.assertEqual(r["escape_obstacle"], 2)


class TestMultiTargetDispersion(unittest.TestCase):
    def test_single_target_no_penalty(self):
        r = multi_target_dispersion(1)
        self.assertEqual(r["obstacle"], 0)
        self.assertEqual(r["defender_edge"], 0)

    def test_two_targets_minor_obstacle(self):
        r = multi_target_dispersion(2)
        self.assertEqual(r["obstacle"], 1)

    def test_three_targets_major_obstacle(self):
        r = multi_target_dispersion(3)
        self.assertEqual(r["obstacle"], 2)

    def test_four_targets_defender_minor_edge(self):
        r = multi_target_dispersion(4)
        self.assertEqual(r["defender_edge"], 1)

    def test_five_targets_defender_major_edge(self):
        r = multi_target_dispersion(5)
        self.assertEqual(r["defender_edge"], 2)

    def test_multiple_targets_technique_reduces(self):
        # Major obstacle (3+ targets) downgrades at technique level 2.
        techniques = [{"name": "Multiple Targets", "level": 2}]
        r = multi_target_dispersion(3, techniques=techniques)
        self.assertEqual(r["obstacle"], 1)

    def test_unified_roll_flag(self):
        self.assertTrue(multi_target_dispersion(3)["unified_roll"])


if __name__ == "__main__":
    unittest.main()