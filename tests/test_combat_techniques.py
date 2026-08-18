"""tests/test_combat_techniques.py — technique obstacle reduction, edge injection,
critical damage multiplier, knockback, rush attack.

Grounded in BESM 4e Combat Techniques Ledger (23 techniques).
Only Hardboiled was previously enforced; now 8 more have engine hooks.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

from engine.models import (
    _has_technique,
    technique_obstacle_reduction,
    apply_obstacle_reduction,
    technique_edge_bonus,
    critical_damage_multiplier,
    enhanced_knockback,
    rush_attack_damage_multiplier,
)


class TestHasTechnique(unittest.TestCase):
    def test_empty_list_returns_zero(self):
        self.assertEqual(_has_technique([], "hardboiled"), 0)

    def test_none_list_returns_zero(self):
        self.assertEqual(_has_technique(None, "hardboiled"), 0)

    def test_case_insensitive_match(self):
        self.assertEqual(_has_technique(
            [{"name": "HARDBOILED", "level": 2}], "hardboiled"), 2)

    def test_highest_level_returned(self):
        techniques = [
            {"name": "Lightning Reflexes", "level": 1},
            {"name": "Lightning Reflexes", "level": 2},
        ]
        self.assertEqual(_has_technique(techniques, "lightning reflexes"), 2)

    def test_not_present_returns_zero(self):
        self.assertEqual(_has_technique(
            [{"name": "Hardboiled", "level": 1}], "far shot"), 0)


class TestTechniqueObstacleReduction(unittest.TestCase):
    def test_far_shot_range(self):
        techniques = [{"name": "Far Shot", "level": 1}]
        self.assertEqual(technique_obstacle_reduction(techniques, "range"), 1)

    def test_dead_eye_movement(self):
        techniques = [{"name": "Dead Eye", "level": 1}]
        self.assertEqual(technique_obstacle_reduction(techniques, "movement"), 1)

    def test_precise_aim_called_shot(self):
        techniques = [{"name": "Precise Aim", "level": 1}]
        self.assertEqual(technique_obstacle_reduction(techniques, "called_shot"), 1)

    def test_multiple_targets(self):
        techniques = [{"name": "Multiple Targets", "level": 1}]
        self.assertEqual(technique_obstacle_reduction(techniques, "multi_target"), 1)

    def test_steady_hand_sprint_ranged(self):
        techniques = [{"name": "Steady Hand", "level": 1}]
        self.assertEqual(technique_obstacle_reduction(techniques, "sprint_ranged"), 1)

    def test_blind_fighting_darkness(self):
        techniques = [{"name": "Blind Fighting", "level": 1}]
        self.assertEqual(technique_obstacle_reduction(techniques, "darkness"), 3)

    def test_blind_shooting_darkness(self):
        techniques = [{"name": "Blind Shooting", "level": 1}]
        self.assertEqual(technique_obstacle_reduction(techniques, "darkness"), 3)

    def test_unknown_type_returns_zero(self):
        self.assertEqual(technique_obstacle_reduction([], "banana"), 0)


class TestApplyObstacleReduction(unittest.TestCase):
    def test_no_obstacle_no_change(self):
        self.assertEqual(apply_obstacle_reduction(0, 2), 0)

    def test_reduction_one_minor_to_none(self):
        self.assertEqual(apply_obstacle_reduction(1, 1), 0)

    def test_reduction_one_major_stays_major(self):
        self.assertEqual(apply_obstacle_reduction(2, 1), 2)

    def test_reduction_two_major_to_minor(self):
        self.assertEqual(apply_obstacle_reduction(2, 2), 1)

    def test_reduction_two_minor_to_none(self):
        self.assertEqual(apply_obstacle_reduction(1, 2), 0)


class TestTechniqueEdgeBonus(unittest.TestCase):
    def test_lightning_reflexes_level_one(self):
        techniques = [{"name": "Lightning Reflexes", "level": 1}]
        self.assertEqual(technique_edge_bonus(techniques, "initiative"), 1)

    def test_lightning_reflexes_level_two(self):
        techniques = [{"name": "Lightning Reflexes", "level": 2}]
        self.assertEqual(technique_edge_bonus(techniques, "initiative"), 2)

    def test_precise_aim_amplifies(self):
        techniques = [{"name": "Precise Aim", "level": 1}]
        self.assertEqual(technique_edge_bonus(techniques, "amplify_aim"), 2)

    def test_no_technique_returns_zero(self):
        self.assertEqual(technique_edge_bonus([], "initiative"), 0)

    def test_lightning_reflexes_capped_at_major(self):
        techniques = [{"name": "Lightning Reflexes", "level": 3}]
        self.assertEqual(technique_edge_bonus(techniques, "initiative"), 2)


class TestCriticalDamageMultiplier(unittest.TestCase):
    def test_normal_no_crit(self):
        self.assertEqual(critical_damage_multiplier(7, 5), 1)

    def test_standard_mos_12_double(self):
        self.assertEqual(critical_damage_multiplier(7, 12), 2)

    def test_standard_mos_18_triple(self):
        self.assertEqual(critical_damage_multiplier(7, 18), 3)

    def test_natural_12_auto_double(self):
        self.assertEqual(critical_damage_multiplier(12, 3), 2)

    def test_critical_strike_mos_12_triple(self):
        self.assertEqual(critical_damage_multiplier(7, 12, has_critical_strike=True), 3)

    def test_critical_strike_mos_18_quadruple(self):
        self.assertEqual(critical_damage_multiplier(7, 18, has_critical_strike=True), 4)


class TestEnhancedKnockback(unittest.TestCase):
    def test_no_technique_zero(self):
        self.assertEqual(enhanced_knockback(5), 0)

    def test_with_technique_double_acv(self):
        self.assertEqual(enhanced_knockback(5, has_technique=True), 10)


class TestRushAttack(unittest.TestCase):
    def test_no_technique_no_bonus(self):
        dmg, obs = rush_attack_damage_multiplier(has_rush_attack=False, hit=True)
        self.assertEqual(dmg, 0)
        self.assertFalse(obs)

    def test_rush_attack_hit_bonus(self):
        dmg, obs = rush_attack_damage_multiplier(has_rush_attack=True, hit=True)
        self.assertEqual(dmg, 1)
        self.assertFalse(obs)

    def test_rush_attack_miss_penalty(self):
        dmg, obs = rush_attack_damage_multiplier(has_rush_attack=True, hit=False)
        self.assertEqual(dmg, 0)
        self.assertTrue(obs)


if __name__ == "__main__":
    unittest.main()
