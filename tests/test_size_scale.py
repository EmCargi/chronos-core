"""tests/test_size_scale.py — size rank grid, strength, armour, knockback, collapse.

Grounded in BESM 4e Scale & Size Physics Ledger:
  * 10 size ranks (-3 Diminutive → +6 Colossal) with multipliers for
    strength, damage, AR, ranged mod, range/speed
  * Absolute Knockback: attacker ≥ 2 sizes larger → auto 10m per rank
  * Collapse Damage: AR = 10 × size_rank, collapse at 5× AR
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

from engine.models import (
    SIZE_GRID,
    size_lookup,
    size_strength_damage,
    size_armour_rating,
    size_ranged_modifier,
    size_range_multiplier,
    size_knockback,
    size_collapse_damage,
)


class TestSizeGrid(unittest.TestCase):
    def test_ten_ranks(self):
        self.assertEqual(len(SIZE_GRID), 10)

    def test_medium_is_baseline(self):
        m = SIZE_GRID[0]
        self.assertEqual(m["strength_damage"], 0)
        self.assertEqual(m["armour"], 0)
        self.assertEqual(m["ranged_mod"], 0)
        self.assertEqual(m["range_mult"], 1)

    def test_colossal_max_damage(self):
        c = SIZE_GRID[6]
        self.assertEqual(c["strength_damage"], 60)
        self.assertEqual(c["armour"], 60)
        self.assertEqual(c["ranged_mod"], -12)

    def test_diminutive_fragility(self):
        d = SIZE_GRID[-3]
        self.assertEqual(d["armour"], -30)  # damage taken bonus
        self.assertEqual(d["ranged_mod"], 6)  # hard to hit

    def test_size_lookup_unknown_returns_none(self):
        self.assertIsNone(size_lookup(99))


class TestSizeStrengthDamage(unittest.TestCase):
    def test_medium_no_bonus(self):
        self.assertEqual(size_strength_damage(0, 10), 10)

    def test_large_plus_ten(self):
        self.assertEqual(size_strength_damage(1, 10), 20)

    def test_colossal_base_damage_only(self):
        self.assertEqual(size_strength_damage(6, 0), 60)

    def test_negative_damage_clamped_to_zero(self):
        self.assertEqual(size_strength_damage(-3, 0), 0)


class TestSizeArmourRating(unittest.TestCase):
    def test_medium_zero_ar(self):
        self.assertEqual(size_armour_rating(0), 0)

    def test_huge_twenty_ar(self):
        self.assertEqual(size_armour_rating(2), 20)

    def test_diminutive_negative_ar(self):
        self.assertEqual(size_armour_rating(-3), -30)

    def test_gargantuan_fifty_ar(self):
        self.assertEqual(size_armour_rating(5), 50)


class TestSizeRangedModifier(unittest.TestCase):
    def test_large_negative_mod_hit(self):
        self.assertEqual(size_ranged_modifier(1), -2)

    def test_tiny_positive_mod_hit(self):
        self.assertEqual(size_ranged_modifier(-2), 4)

    def test_medium_zero(self):
        self.assertEqual(size_ranged_modifier(0), 0)


class TestSizeRangeMultiplier(unittest.TestCase):
    def test_colossal_sixty_times(self):
        self.assertEqual(size_range_multiplier(6), 60)

    def test_diminutive_eighth(self):
        self.assertEqual(size_range_multiplier(-3), 1/8)

    def test_medium_baseline(self):
        self.assertEqual(size_range_multiplier(0), 1)


class TestSizeKnockback(unittest.TestCase):
    def test_same_size_no_knockback(self):
        r = size_knockback(0, 0)
        self.assertFalse(r["auto_knockback"])

    def test_one_rank_larger_not_auto(self):
        r = size_knockback(1, 0)
        self.assertFalse(r["auto_knockback"])

    def test_two_ranks_larger_auto_knockback(self):
        r = size_knockback(2, 0)
        self.assertTrue(r["auto_knockback"])
        self.assertEqual(r["distance_meters"], 20)

    def test_colossal_vs_medium_thirty_meters(self):
        r = size_knockback(6, 0)
        self.assertTrue(r["auto_knockback"])
        self.assertEqual(r["distance_meters"], 60)

    def test_large_vs_diminutive_five_ranks(self):
        r = size_knockback(1, -3)
        self.assertTrue(r["auto_knockback"])
        self.assertEqual(r["distance_meters"], 40)


class TestSizeCollapse(unittest.TestCase):
    def test_medium_structure_ar_ten(self):
        r = size_collapse_damage(0)
        self.assertEqual(r["structure_ar"], 10)
        self.assertEqual(r["collapse_threshold"], 50)
        self.assertEqual(r["fallout_damage"], 5)

    def test_mammoth_structure_ar_thirty(self):
        r = size_collapse_damage(3)
        self.assertEqual(r["structure_ar"], 30)
        self.assertEqual(r["collapse_threshold"], 150)
        self.assertEqual(r["fallout_damage"], 15)

    def test_colossal_structure_min_ten(self):
        r = size_collapse_damage(-5)
        self.assertEqual(r["structure_ar"], 10)


if __name__ == "__main__":
    unittest.main()
