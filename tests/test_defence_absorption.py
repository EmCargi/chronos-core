"""tests/test_defence_absorption.py — defensive absorption layers 1-4.

Grounded in BESM 4e Defensive Absorption Ledger:
  * Layer 1: Active Parry/Shield — opposed defence roll, Potent edges
  * Layer 2: Force Field — flat AR, Crash Rule, Piercing, Regeneration
  * Layer 3: Physical Armour — flat AR, Penetrating/Non-Penetrating, gaps
  * Layer 4: Absorption — 5 dmg/level → HP/EP, 2× max cap, complex bypass
  * Full pipeline: resolve_attack_damage() runs layers 2-4 in sequence
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

from engine.models import (
    resolve_active_defence,
    resolve_force_field,
    resolve_armour,
    resolve_absorption,
    resolve_attack_damage,
    resolve_modifier_stack,
)


class TestActiveDefence(unittest.TestCase):
    def test_no_shield_no_edge(self):
        r = resolve_active_defence(dcv=7)
        self.assertIsNone(r["edge_applied"])
        self.assertIsNone(r["obstacle_applied"])
        self.assertIn("defence_total", r)

    def test_potent_minor_edge(self):
        r = resolve_active_defence(dcv=7, shield_edge=1)
        self.assertEqual(r["edge_applied"], "minor")

    def test_potent_major_edge(self):
        r = resolve_active_defence(dcv=7, shield_edge=2)
        self.assertEqual(r["edge_applied"], "major")

    def test_defending_other_adds_obstacle(self):
        r = resolve_active_defence(dcv=7, defending_other=True)
        self.assertEqual(r["obstacle_applied"], "minor")

    def test_interpose_body_cancels_defending_obstacle(self):
        r = resolve_active_defence(dcv=7, defending_other=True, interpose_body=True)
        self.assertIsNone(r["obstacle_applied"])

    def test_edge_clamped_to_two(self):
        r = resolve_active_defence(dcv=7, shield_edge=5)
        self.assertEqual(r["edge_applied"], "major")


class TestForceField(unittest.TestCase):
    def test_no_ar_passes_all_damage(self):
        r = resolve_force_field(50, 0)
        self.assertEqual(r["remaining_damage"], 50)
        self.assertFalse(r["degraded"])

    def test_ar_reduces_damage(self):
        r = resolve_force_field(50, 30)
        self.assertEqual(r["remaining_damage"], 20)
        self.assertTrue(r["degraded"])

    def test_ar_blocks_all_no_degradation(self):
        r = resolve_force_field(20, 30)
        self.assertEqual(r["remaining_damage"], 0)
        self.assertFalse(r["degraded"])

    def test_piercing_reduces_ar(self):
        r = resolve_force_field(50, 30, piercing_ranks=1)
        self.assertEqual(r["effective_ar"], 20)
        self.assertEqual(r["remaining_damage"], 30)

    def test_piercing_caps_ar_at_zero(self):
        r = resolve_force_field(50, 10, piercing_ranks=3)
        self.assertEqual(r["effective_ar"], 0)
        self.assertEqual(r["remaining_damage"], 50)


class TestArmour(unittest.TestCase):
    def test_flat_reduction(self):
        r = resolve_armour(35, 20)
        self.assertEqual(r["remaining_damage"], 15)
        self.assertEqual(r["effective_ar"], 20)

    def test_penetrating_reduces_ar(self):
        r = resolve_armour(45, 20, penetrating_ranks=1)
        self.assertEqual(r["effective_ar"], 10)
        self.assertEqual(r["remaining_damage"], 35)

    def test_non_penetrating_boosts_target_ar(self):
        r = resolve_armour(30, 10, non_penetrating=True)
        self.assertEqual(r["effective_ar"], 20)
        self.assertEqual(r["remaining_damage"], 10)

    def test_gap_half_ar(self):
        r = resolve_armour(30, 20, gap_half=True)
        self.assertEqual(r["effective_ar"], 10)
        self.assertEqual(r["remaining_damage"], 20)

    def test_gap_bypass_zero_ar(self):
        r = resolve_armour(30, 20, gap_bypass=True)
        self.assertEqual(r["effective_ar"], 0)
        self.assertEqual(r["remaining_damage"], 30)

    def test_combined_penetrating_and_gap_half(self):
        r = resolve_armour(30, 20, penetrating_ranks=1, gap_half=True)
        self.assertEqual(r["effective_ar"], 5)  # (20-10)//2
        self.assertEqual(r["remaining_damage"], 25)


class TestAbsorption(unittest.TestCase):
    def test_no_absorption_passes_through(self):
        r = resolve_absorption(30, 0, 50, 100, 50, 100)
        self.assertEqual(r["final_damage"], 30)
        self.assertEqual(r["hp_gained"], 0)

    def test_absorbs_five_per_level(self):
        r = resolve_absorption(15, 2, 50, 100, 50, 100)
        self.assertEqual(r["final_damage"], 5)  # 15 - 10 = 5
        self.assertEqual(r["hp_gained"], 10)

    def test_heals_to_max_hp_then_spills_to_ep(self):
        # lvl 4 = 20 absorb. HP needs 5, remainder 15 → EP. final = 30-20 = 10
        r = resolve_absorption(30, 4, 95, 100, 50, 100)
        self.assertEqual(r["hp_gained"], 5)
        self.assertEqual(r["ep_gained"], 15)
        self.assertEqual(r["final_damage"], 10)

    def test_spills_to_ep_after_hp_full(self):
        r = resolve_absorption(30, 4, 100, 100, 50, 100)
        self.assertEqual(r["hp_gained"], 0)
        self.assertEqual(r["ep_gained"], 20)
        self.assertEqual(r["final_damage"], 10)

    def test_capped_at_two_times_max(self):
        r = resolve_absorption(50, 4, 190, 100, 190, 100)
        self.assertEqual(r["hp_gained"], 0)   # HP already > max, no healing
        self.assertEqual(r["ep_gained"], 10)  # 200-190 = 10 room
        self.assertEqual(r["final_damage"], 30)

    def test_complex_weapon_bypasses(self):
        r = resolve_absorption(30, 4, 50, 100, 50, 100, is_complex_weapon=True)
        self.assertEqual(r["final_damage"], 30)
        self.assertEqual(r["hp_gained"], 0)


class TestAttackDamagePipeline(unittest.TestCase):
    def test_rosivelle_example_from_rules(self):
        """Rosivelle vs Abyssal Behemoth from the ledger example."""
        r = resolve_attack_damage(
            incoming_damage=45,
            armour_rating=20,
            penetrating_ranks=1,
            current_hp=60, max_hp=60,
            current_ep=50, max_ep=50,
        )
        self.assertEqual(r["incoming"], 45)
        self.assertEqual(r["effective_armour_ar"], 10)
        self.assertEqual(r["after_armour"], 35)
        self.assertEqual(r["net_damage"], 35)

    def test_full_pipeline_with_force_field(self):
        r = resolve_attack_damage(
            incoming_damage=60,
            force_field_ar=30,
            armour_rating=20,
            absorption_level=2,
            current_hp=80, max_hp=100,
            current_ep=80, max_ep=100,
        )
        self.assertEqual(r["after_force_field"], 30)  # 60 - 30
        self.assertEqual(r["after_armour"], 10)        # 30 - 20
        self.assertLessEqual(r["net_damage"], 10)       # absorbs 10 → 0 net
        self.assertEqual(r["hp_absorbed"], 10)
        self.assertTrue(r["force_field_degraded"])

    def test_no_defences_passes_through(self):
        r = resolve_attack_damage(100)
        self.assertEqual(r["net_damage"], 100)

    def test_gap_bypass_example(self):
        r = resolve_attack_damage(40, armour_rating=20, gap_bypass=True)
        self.assertEqual(r["effective_armour_ar"], 0)
        self.assertEqual(r["after_armour"], 40)

    def test_non_penetrating_vs_plate(self):
        r = resolve_attack_damage(30, armour_rating=20, non_penetrating=True)
        self.assertEqual(r["effective_armour_ar"], 30)  # 20 + 10
        self.assertEqual(r["after_armour"], 0)


if __name__ == "__main__":
    unittest.main()
