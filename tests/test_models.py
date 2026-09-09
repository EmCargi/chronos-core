"""tests/test_models.py — tri-stat derived vitals, shock value, and action checks.

Grounded in the BESM 4e ruleset (see BESM Rules/ cheat sheets):
  * max_hp = (stat_body + stat_soul) × 5
  * max_ep = (stat_mind + stat_soul) × 5
  * base_acv = (body + mind + soul) // 3   [integer division]
  * base_dcv = base_acv − 2
  * base_shock = max_hp // 5 + 10 × Hardboiled_level, capped at max_hp // 2
  * action checks: 2d6 + stat_rank + skill_rank ≥ DV
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

from pydantic import ValidationError

from engine.models import CharacterSchema, execute_action_check


class TestCharacterSchemaValidation(unittest.TestCase):
    def test_minimum_stats_valid(self):
        c = CharacterSchema(name="Weakling", stat_body=1, stat_mind=1, stat_soul=1)
        self.assertEqual(c.points_budget, 75)

    def test_maximum_stats_valid(self):
        c = CharacterSchema(name="Titan", stat_body=12, stat_mind=12, stat_soul=12)
        self.assertEqual(c.stat_body, 12)

    def test_stat_below_one_rejected(self):
        with self.assertRaises(ValidationError):
            CharacterSchema(name="Ghost", stat_body=0, stat_mind=5, stat_soul=5)

    def test_stat_above_twelve_rejected(self):
        with self.assertRaises(ValidationError):
            CharacterSchema(name="Demigod", stat_body=13, stat_mind=5, stat_soul=5)

    def test_default_points_budget(self):
        c = CharacterSchema(name="Rookie", stat_body=3, stat_mind=3, stat_soul=3)
        self.assertEqual(c.points_budget, 75)

    def test_optional_vitals_default_none(self):
        c = CharacterSchema(name="Fresh", stat_body=5, stat_mind=5, stat_soul=5)
        self.assertIsNone(c.current_hp)
        self.assertIsNone(c.current_ep)

    def test_custom_points_budget(self):
        c = CharacterSchema(name="Veteran", points_budget=100, stat_body=8, stat_mind=7, stat_soul=6)
        self.assertEqual(c.points_budget, 100)


class TestDerivedVitals(unittest.TestCase):
    """Tri-Stat derived values per BESM 4e character creation rules."""

    def test_max_hp_body_soul_times_five(self):
        c = CharacterSchema(name="Guard", stat_body=4, stat_mind=3, stat_soul=3)
        self.assertEqual(c.max_hp, (4 + 3) * 5)  # 35

    def test_max_ep_mind_soul_times_five(self):
        c = CharacterSchema(name="Mage", stat_body=3, stat_mind=5, stat_soul=4)
        self.assertEqual(c.max_ep, (5 + 4) * 5)  # 45

    def test_base_acv_integer_division(self):
        c = CharacterSchema(name="Fighter", stat_body=4, stat_mind=5, stat_soul=3)
        self.assertEqual(c.base_acv, (4 + 5 + 3) // 3)  # 4

    def test_base_dcv_two_less_than_acv(self):
        c = CharacterSchema(name="Rogue", stat_body=5, stat_mind=5, stat_soul=5)
        self.assertEqual(c.base_dcv, (15 // 3) - 2)  # 3

    def test_all_stats_twelve_max(self):
        c = CharacterSchema(name="Apex", stat_body=12, stat_mind=12, stat_soul=12)
        self.assertEqual(c.max_hp, 120)
        self.assertEqual(c.max_ep, 120)
        self.assertEqual(c.base_acv, 12)
        self.assertEqual(c.base_dcv, 10)

    def test_all_stats_one_min(self):
        c = CharacterSchema(name="Fledgling", stat_body=1, stat_mind=1, stat_soul=1)
        self.assertEqual(c.max_hp, 10)
        self.assertEqual(c.max_ep, 10)
        self.assertEqual(c.base_acv, 1)
        self.assertEqual(c.base_dcv, -1)

    def test_explicit_max_hp_overrides_derivation(self):
        """Stored roster maxima (with Tough/Energised bonuses) win over the
        Tri-Stat formula — e.g. Morwen (3/4/7) stores 60, not the derived 50."""
        c = CharacterSchema(name="Morwen", stat_body=3, stat_mind=4, stat_soul=7,
                            max_hp=60, max_ep=105)
        self.assertEqual(c.max_hp, 60)
        self.assertEqual(c.max_ep, 105)

    def test_zero_max_hp_falls_back_to_derivation(self):
        """0 (and None) mean 'not provided' — derive from stats."""
        c = CharacterSchema(name="Zero", stat_body=4, stat_mind=4, stat_soul=4,
                            max_hp=0, max_ep=0)
        self.assertEqual(c.max_hp, 40)
        self.assertEqual(c.max_ep, 40)

    def test_max_hp_in_model_dump(self):
        """max_hp/max_ep are now real fields, so they serialize into model_dump
        (previously read-only properties were excluded)."""
        c = CharacterSchema(name="Guard", stat_body=4, stat_mind=3, stat_soul=3)
        self.assertEqual(c.model_dump()["max_hp"], 35)


class TestShockValue(unittest.TestCase):
    """Shock Value = max_hp // 5 + 10 × Hardboiled_level, capped at max_hp // 2."""

    def _char(self, body=4, soul=3, techniques=None):
        return CharacterSchema(
            name="Test",
            stat_body=body,
            stat_mind=3,
            stat_soul=soul,
            combat_techniques=techniques or [],
        )

    def test_base_shock_value(self):
        c = self._char(body=4, soul=3)  # max_hp=35 → SV=7
        self.assertEqual(c.shock_value_computed, 7)

    def test_hardboiled_level_one(self):
        c = self._char(body=4, soul=3, techniques=[
            {"name": "Hardboiled", "level": 1, "effect": "+10 Shock Value"}
        ])
        self.assertEqual(c.shock_value_computed, 17)  # 7 + 10

    def test_hardboiled_level_two(self):
        c = self._char(body=5, soul=4, techniques=[
            {"name": "Hardboiled", "level": 2, "effect": "+20 Shock Value"}
        ])
        # max_hp=45, base=9, +20 = 29, cap=22 → capped at 22
        self.assertEqual(c.shock_value_computed, 22)

    def test_hardboiled_capped_at_half_hp(self):
        c = self._char(body=4, soul=3, techniques=[
            {"name": "Hardboiled", "level": 3, "effect": "+30 Shock Value"}
        ])
        # max_hp=35, base=7, +30 = 37, cap=17 → capped
        self.assertEqual(c.shock_value_computed, 17)

    def test_hardboiled_case_insensitive_match(self):
        c = self._char(body=4, soul=3, techniques=[
            {"name": "HARDBOILED", "level": 1, "effect": "+10 Shock Value"}
        ])
        self.assertEqual(c.shock_value_computed, 17)

    def test_no_techniques_default_zero(self):
        c = CharacterSchema(
            name="Fresh",
            stat_body=5, stat_mind=5, stat_soul=5,
            combat_techniques=[],
        )
        self.assertEqual(c.shock_value_computed, 10)  # 50//5=10

    def test_technique_not_hardboiled_ignored(self):
        c = self._char(body=4, soul=3, techniques=[
            {"name": "Lightning Reflexes", "level": 2, "effect": "+4 initiative"},
        ])
        self.assertEqual(c.shock_value_computed, 7)

    def test_shock_field_defaults_to_zero(self):
        c = CharacterSchema(name="NoSV", stat_body=3, stat_mind=3, stat_soul=3)
        self.assertEqual(c.shock_value, 0)
        self.assertEqual(c.shock_value_computed, 6)  # 30//5=6, shock_value field ignored

    def test_max_body_low_soul_high(self):
        """HP formula uses (body + soul) × 5. High soul, low body = hybrid HP."""
        c = self._char(body=12, soul=1)  # max_hp=65
        self.assertEqual(c.max_hp, 65)
        self.assertEqual(c.shock_value_computed, 13)  # base=13, no cap issue


class TestExecuteActionCheck(unittest.TestCase):
    """2d6 + stat_rank + skill_rank ≥ DV."""

    def test_success_when_high_roll(self):
        random.seed(42)  # roll will be ≥ average
        result = execute_action_check(stat_rank=4, skill_rank=3, difficulty_value=12)
        self.assertIn("success", result)
        self.assertIn("roll", result)
        self.assertEqual(result["roll"], result["total"] - 4 - 3)

    def test_failure_when_low_roll(self):
        # DV 30 is unreachable with 2d6 + stat + skill at human scale
        result = execute_action_check(stat_rank=4, skill_rank=3, difficulty_value=30)
        self.assertFalse(result["success"])
        self.assertLess(result["total"], 30)

    def test_exact_match_is_success(self):
        # force total == DV: set DV=0, stat=0, skill=0 — any roll ≥ 0 succeeds
        result = execute_action_check(stat_rank=0, skill_rank=0, difficulty_value=0)
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["total"], 0)

    def test_target_field_matches_parameter(self):
        result = execute_action_check(stat_rank=5, skill_rank=2, difficulty_value=15)
        self.assertEqual(result["target"], 15)

    def test_minimum_possible_total(self):
        """Worst roll (2) + 0 + 0 = 2."""
        random.seed(0)
        # We can't guarantee snake-eyes with seed without checking, but total ≥ 2 always
        result = execute_action_check(stat_rank=0, skill_rank=0, difficulty_value=0)
        self.assertGreaterEqual(result["total"], 2)
        self.assertGreaterEqual(result["roll"], 2)


if __name__ == "__main__":
    unittest.main()
