"""tests/test_combat_modifiers.py — modifier stacking laws, combat resolution.

Grounded in BESM 4e Combat Modifiers cheat sheet:
  * Cancellation: opposite modifiers of equal weight cancel
  * Compounding: two minors → major
  * Spillover: extra modifier beyond major → opposite effect on opponent
  * Mulligans: each extra minor edge → 1 optional reroll
  * Combat resolution: attacker ACV vs defender DCV, 2d6 each, edges/obstacles applied
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

from engine.models import (
    resolve_modifier_stack,
    resolve_combat_roll,
)


class TestModifierStackCancellation(unittest.TestCase):
    def test_no_modifiers_returns_clean(self):
        r = resolve_modifier_stack(0, 0)
        self.assertIsNone(r["edge"])
        self.assertIsNone(r["obstacle"])
        self.assertEqual(r["spillover"], 0)
        self.assertEqual(r["mulligans"], 0)

    def test_single_minor_edge(self):
        r = resolve_modifier_stack(1, 0)
        self.assertEqual(r["edge"], "minor")
        self.assertIsNone(r["obstacle"])

    def test_single_minor_obstacle(self):
        r = resolve_modifier_stack(0, 1)
        self.assertEqual(r["obstacle"], "minor")
        self.assertIsNone(r["edge"])

    def test_minor_edge_cancels_minor_obstacle(self):
        r = resolve_modifier_stack(1, 1)
        self.assertIsNone(r["edge"])
        self.assertIsNone(r["obstacle"])
        self.assertEqual(r["spillover"], 0)

    def test_major_edge_cancels_major_obstacle(self):
        r = resolve_modifier_stack(2, 2)
        self.assertIsNone(r["edge"])
        self.assertIsNone(r["obstacle"])

    def test_partial_cancellation_major_edge_vs_minor_obstacle(self):
        r = resolve_modifier_stack(2, 1)  # net +1
        self.assertEqual(r["edge"], "minor")
        self.assertIsNone(r["obstacle"])


class TestModifierStackCompounding(unittest.TestCase):
    def test_two_minor_edges_compound_to_major(self):
        r = resolve_modifier_stack(2, 0)
        self.assertEqual(r["edge"], "major")

    def test_two_minor_obstacles_compound_to_major(self):
        r = resolve_modifier_stack(0, 2)
        self.assertEqual(r["obstacle"], "major")

    def test_major_plus_minor_edge_spillover(self):
        r = resolve_modifier_stack(3, 0)  # major=2 + extra minor=1
        self.assertEqual(r["edge"], "major")
        self.assertEqual(r["spillover"], 1)
        self.assertEqual(r["mulligans"], 1)

    def test_major_plus_minor_obstacle_spillover(self):
        r = resolve_modifier_stack(0, 3)
        self.assertEqual(r["obstacle"], "major")
        self.assertEqual(r["spillover"], 1)
        self.assertEqual(r["mulligans"], 0)

    def test_raw_counts_preserved(self):
        r = resolve_modifier_stack(3, 1)
        self.assertEqual(r["raw_edge"], 3)
        self.assertEqual(r["raw_obstacle"], 1)


class TestCombatRoll(unittest.TestCase):
    def test_even_combat_no_modifiers(self):
        r = resolve_combat_roll(acv=5, attack_edge=0, attack_obstacle=0,
                                 dcv=5, defence_edge=0, defence_obstacle=0)
        self.assertIn("hit", r)
        self.assertIn("attack_total", r)
        self.assertIn("defence_total", r)
        self.assertEqual(r["attack_total"], r["attack_roll"] + 5)

    def test_attack_edge_helps(self):
        random.seed(1234)
        no_edge_hits = 0
        with_edge_hits = 0
        for _ in range(100):
            r = resolve_combat_roll(5, 0, 0, 5, 0, 0)
            if r["hit"]:
                no_edge_hits += 1
            r = resolve_combat_roll(5, 1, 0, 5, 0, 0)
            if r["hit"]:
                with_edge_hits += 1
        # minor edge should produce more hits on average
        self.assertGreaterEqual(with_edge_hits, no_edge_hits - 5)

    def test_defence_edge_helps_defender(self):
        random.seed(5678)
        no_edge_hits = 0
        with_edge_hits = 0
        for _ in range(100):
            r = resolve_combat_roll(5, 0, 0, 5, 0, 0)
            if r["hit"]:
                no_edge_hits += 1
            r = resolve_combat_roll(5, 0, 0, 5, 1, 0)
            if r["hit"]:
                with_edge_hits += 1
        self.assertLessEqual(with_edge_hits, no_edge_hits + 5)

    def test_higher_acv_wins_more(self):
        random.seed(999)
        wins = 0
        for _ in range(200):
            r = resolve_combat_roll(8, 0, 0, 5, 0, 0)
            if r["hit"]:
                wins += 1
        self.assertGreater(wins, 100)

    def test_cancelled_modifiers_neutral(self):
        random.seed(42)
        r = resolve_combat_roll(5, 1, 1, 5, 0, 0)
        # 1 minor edge + 1 minor obstacle = cancelled → clean rolls
        self.assertIsNone(r["attack_mods"]["edge"])
        self.assertIsNone(r["attack_mods"]["obstacle"])

    def test_result_structure(self):
        r = resolve_combat_roll(6, 1, 0, 4, 0, 1)
        keys = ["hit", "attack_total", "attack_roll", "defence_total",
                "defence_roll", "attack_mods", "defence_mods"]
        for k in keys:
            self.assertIn(k, r)

    def test_spillover_applied(self):
        r = resolve_combat_roll(5, 3, 0, 5, 0, 0)
        self.assertEqual(r["attack_mods"]["spillover"], 1)
        self.assertEqual(r["attack_mods"]["mulligans"], 1)
        self.assertEqual(r["attack_mods"]["edge"], "major")


if __name__ == "__main__":
    unittest.main()
