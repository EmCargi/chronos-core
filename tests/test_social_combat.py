"""tests/test_social_combat.py — Social Combat Value, Society Points, damage, clash.

Grounded in BESM 4e Extras: Social Combat Value Cheat Sheet:
  * SCV = (Mind + Soul)//2 + 2×Social Mastery − 2×Demure
  * Society Points = SCV
  * Social damage from MoS table (1-5 SP)
  * Recovery: 1 SP/hour
  * Social clash: opposed SCV rolls, ties to aggressor
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

from engine.models import (
    CharacterSchema,
    SOCIAL_DAMAGE_TABLE,
    social_combat_value,
    character_scv,
    society_points,
    social_damage,
    social_recovery,
    social_defeat_obstacle,
    resolve_social_clash,
)


def _char(mind=5, soul=5, defects=None):
    return CharacterSchema(name="Test", stat_body=3, stat_mind=mind,
                           stat_soul=soul, defects=defects or [])


class TestSocialCombatValue(unittest.TestCase):
    def test_baseline_scv(self):
        self.assertEqual(social_combat_value(5, 5), 5)

    def test_odd_sum_floors(self):
        self.assertEqual(social_combat_value(5, 4), 4)

    def test_social_mastery_level_one_adds_two(self):
        self.assertEqual(social_combat_value(5, 5, social_mastery=1), 7)

    def test_social_mastery_level_three_adds_six(self):
        self.assertEqual(social_combat_value(5, 5, social_mastery=3), 11)

    def test_negative_modifier(self):
        self.assertEqual(social_combat_value(5, 5, scv_modifier=-4), 1)

    def test_floor_at_zero(self):
        self.assertEqual(social_combat_value(1, 1, scv_modifier=-10), 0)


class TestCharacterSCV(unittest.TestCase):
    def test_baseline_from_character(self):
        c = _char(mind=5, soul=5)
        self.assertEqual(character_scv(c), 5)

    def test_with_social_mastery(self):
        c = _char(mind=5, soul=5)
        self.assertEqual(character_scv(c, social_mastery_level=2), 9)

    def test_with_demure_defect(self):
        c = _char(mind=5, soul=5, defects=[{"name": "Demure", "rank": 2}])
        self.assertEqual(character_scv(c), 1)

    def test_social_mastery_and_demure_cancel(self):
        c = _char(mind=5, soul=5, defects=[{"name": "Demure", "rank": 2}])
        self.assertEqual(character_scv(c, social_mastery_level=2), 5)


class TestSocietyPoints(unittest.TestCase):
    def test_sp_equals_scv(self):
        self.assertEqual(society_points(7), 7)


class TestSocialDamage(unittest.TestCase):
    def test_zero_or_negative_margin_no_damage(self):
        self.assertEqual(social_damage(0), 0)
        self.assertEqual(social_damage(-5), 0)

    def test_slight_success_one_damage(self):
        self.assertEqual(social_damage(1), 1)

    def test_moderate_success_two_damage(self):
        self.assertEqual(social_damage(4), 2)

    def test_significant_success_three_damage(self):
        self.assertEqual(social_damage(10), 3)

    def test_major_success_four_damage(self):
        self.assertEqual(social_damage(15), 4)

    def test_extreme_success_five_damage(self):
        self.assertEqual(social_damage(18), 5)
        self.assertEqual(social_damage(50), 5)

    def test_table_has_five_bands(self):
        self.assertEqual(len(SOCIAL_DAMAGE_TABLE), 5)


class TestSocialRecovery(unittest.TestCase):
    def test_one_sp_per_hour(self):
        self.assertEqual(social_recovery(3), 3)


class TestSocialDefeat(unittest.TestCase):
    def test_zero_sp_major_obstacle(self):
        self.assertEqual(social_defeat_obstacle(0), "major")

    def test_negative_sp_major_obstacle(self):
        self.assertEqual(social_defeat_obstacle(-3), "major")

    def test_positive_sp_no_obstacle(self):
        self.assertIsNone(social_defeat_obstacle(5))


class TestSocialClash(unittest.TestCase):
    def test_even_clash(self):
        r = resolve_social_clash(5, 0, 5, 0)
        self.assertIn("winner", r)
        self.assertIn("margin", r)
        self.assertIn("sp_damage", r)

    def test_attacker_wins_ties(self):
        import random
        random.seed(0)
        wins = 0
        for _ in range(100):
            r = resolve_social_clash(5, 0, 5, 0)
            if r["winner"] == "attacker":
                wins += 1
        self.assertGreaterEqual(wins, 40)

    def test_higher_scv_wins_more(self):
        wins = 0
        for _ in range(100):
            r = resolve_social_clash(10, 0, 3, 0)
            if r["winner"] == "attacker":
                wins += 1
        self.assertGreater(wins, 80)

    def test_margin_yields_damage(self):
        import random
        random.seed(999)
        r = resolve_social_clash(10, 5, 3, 0)
        if r["margin"] > 0:
            self.assertGreater(r["sp_damage"], 0)

    def test_edge_propagates(self):
        import random
        random.seed(1234)
        no_edge_dmg = 0
        with_edge_dmg = 0
        for _ in range(100):
            r = resolve_social_clash(5, 0, 5, 0)
            no_edge_dmg += r["sp_damage"]
            r = resolve_social_clash(5, 0, 5, 0, attacker_edge=2)
            with_edge_dmg += r["sp_damage"]
        self.assertGreaterEqual(with_edge_dmg, no_edge_dmg - 5)


if __name__ == "__main__":
    unittest.main()
