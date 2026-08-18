"""tests/test_combat_physics.py — edge dice, wound penalties, falling damage, range.

Grounded in BESM 4e cheat sheets:
  * Edge dice: 3d6/4d6 keep highest 2 (Combat Modifiers §1)
  * Wound penalties: HP ≤ 50% Minor, HP < SV Major (Meat Grinder §3)
  * Falling: distance → HP table, Acrobatics halves (Environmental Hazards)
  * Range: Effective/Intermediate/Remote bands (Combat Modifiers §3)
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

from engine.models import (
    CharacterSchema,
    _roll_with_edge,
    _roll_with_obstacle,
    wound_obstacle,
    falling_damage,
    range_obstacle,
    FALLING_DAMAGE_TABLE,
)


def _char(body=4, mind=3, soul=3, hp=None, techniques=None):
    return CharacterSchema(
        name="Test",
        stat_body=body, stat_mind=mind, stat_soul=soul,
        current_hp=hp,
        combat_techniques=techniques or [],
    )


class TestEdgeDice(unittest.TestCase):
    def test_minor_edge_uses_highest_two_of_three(self):
        random.seed(555)
        r = _roll_with_edge(0, 2, minor=True)
        self.assertEqual(r["edge"], "minor")

    def test_major_edge_uses_highest_two_of_four(self):
        random.seed(99999)
        r = _roll_with_edge(0, 2, major=True)
        self.assertEqual(r["edge"], "major")

    def test_minor_and_major_compounds_to_major(self):
        random.seed(42)
        r = _roll_with_edge(0, 2, minor=True, major=True)
        self.assertEqual(r["edge"], "major")

    def test_no_edge_uses_standard_2d6(self):
        r = _roll_with_edge(0, 99)
        self.assertIsNone(r["edge"])
        self.assertFalse(r["success"])

    def test_edge_is_easier_than_obstacle(self):
        random.seed(42)
        edge = _roll_with_edge(3, 12, major=True)["total"]
        random.seed(42)
        obst = _roll_with_obstacle(3, 12, major=True)["total"]
        self.assertGreaterEqual(edge, obst)

    def test_normal_roll_in_range(self):
        for _ in range(20):
            r = _roll_with_edge(5, 12)
            self.assertGreaterEqual(r["roll"], 2)
            self.assertLessEqual(r["roll"], 12)

    def test_high_stat_almost_always_succeeds_with_edge(self):
        for _ in range(100):
            r = _roll_with_edge(10, 12, major=True)
            if not r["success"]:
                self.assertGreaterEqual(r["roll"], 2)


class TestWoundObstacle(unittest.TestCase):
    def test_healthy_no_obstacle(self):
        c = _char(body=5, soul=5, hp=50)  # max_hp=50, SV=10
        self.assertIsNone(wound_obstacle(c))

    def test_hp_at_half_minor_obstacle(self):
        c = _char(body=5, soul=5, hp=25)  # max=50, hp=25 exactly half
        self.assertEqual(wound_obstacle(c), "minor")

    def test_hp_below_sv_major_obstacle(self):
        c = _char(body=5, soul=5, hp=5)  # SV=10, hp=5 < SV
        self.assertEqual(wound_obstacle(c), "major")

    def test_hp_zero_or_negative_major_obstacle(self):
        c = _char(body=5, soul=5, hp=0)
        self.assertEqual(wound_obstacle(c), "major")

    def test_current_hp_none_returns_none(self):
        c = _char(body=5, soul=5, hp=None)
        self.assertIsNone(wound_obstacle(c))

    def test_severely_wounded_below_sv(self):
        c = _char(body=12, soul=1, hp=10)  # max=65, SV=13, hp=10 < 13
        self.assertEqual(wound_obstacle(c), "major")


class TestFallingDamage(unittest.TestCase):
    def test_less_than_two_meters_no_damage(self):
        self.assertEqual(falling_damage(1.5), 0)

    def test_exactly_two_meters_in_first_band(self):
        self.assertEqual(falling_damage(2), 10)

    def test_five_meters(self):
        self.assertEqual(falling_damage(5), 15)

    def test_ten_meters(self):
        self.assertEqual(falling_damage(10), 25)

    def test_twenty_meters(self):
        self.assertEqual(falling_damage(20), 30)

    def test_fifty_meters(self):
        self.assertEqual(falling_damage(50), 40)

    def test_hundred_meters(self):
        self.assertEqual(falling_damage(100), 50)

    def test_two_hundred_meters(self):
        self.assertEqual(falling_damage(200), 80)

    def test_five_hundred_meters(self):
        self.assertEqual(falling_damage(500), 100)

    def test_one_kilometer_caps_at_max(self):
        self.assertEqual(falling_damage(1000), 150)

    def test_table_has_ten_bands(self):
        self.assertEqual(len(FALLING_DAMAGE_TABLE), 10)


class TestRangeObstacle(unittest.TestCase):
    def test_effective_range_no_obstacle(self):
        self.assertIsNone(range_obstacle(100, 10))  # 1/10 of range

    def test_effective_boundary_no_obstacle(self):
        self.assertIsNone(range_obstacle(100, 20))  # exactly 1/5

    def test_intermediate_range_minor_obstacle(self):
        self.assertEqual(range_obstacle(100, 30), "minor")

    def test_intermediate_boundary_minor_obstacle(self):
        self.assertEqual(range_obstacle(100, 50), "minor")  # exactly 1/2

    def test_remote_range_major_obstacle(self):
        self.assertEqual(range_obstacle(100, 75), "major")

    def test_at_max_range_major_obstacle(self):
        self.assertEqual(range_obstacle(100, 100), "major")

    def test_beyond_range_returns_none(self):
        """Beyond max range = out of range, not an obstacle."""
        self.assertIsNone(range_obstacle(100, 101))

    def test_zero_distance_no_obstacle(self):
        self.assertIsNone(range_obstacle(100, 0))

    def test_negative_distance_no_obstacle(self):
        self.assertIsNone(range_obstacle(100, -10))

    def test_longbow_range_bands(self):
        self.assertIsNone(range_obstacle(200, 20))
        self.assertEqual(range_obstacle(200, 60), "minor")
        self.assertEqual(range_obstacle(200, 150), "major")


if __name__ == "__main__":
    unittest.main()
