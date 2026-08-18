"""Tests for diceless BESM resolution (engine/models.py).

Covers the Total Combat Roll formula (Extras Ch.9 p135 — every term rounds
down), Table-15 Margin of Success mapping, the Kozoh vs Azok canonical
example, and the auto-7 hedging path for non-combat checks (BESM4 p182).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # dev/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))                                     # chronos-core/

from engine.models import (
    compute_tcr,
    resolve_diceless_combat,
    diceless_battle,
    hedged_check,
    EDGE_TCR_VALUE,
    OBSTACLE_TCR_VALUE,
)


class TestComputeTcr:
    def test_baseline_cv_only(self):
        r = compute_tcr(combat_value=10)
        assert r["tcr"] == 10

    def test_damage_rounds_down(self):
        # +1 per full 10 damage: 21 → +2, 19 → +1
        assert compute_tcr(10, weapon_damage=21)["tcr"] == 12
        assert compute_tcr(10, weapon_damage=19)["tcr"] == 11

    def test_hp_rounds_down(self):
        # +1 per full 20 HP: 80 → +4, 65 → +3
        assert compute_tcr(10, current_hp=80)["tcr"] == 14
        assert compute_tcr(10, current_hp=65)["tcr"] == 13

    def test_extra_actions_double(self):
        assert compute_tcr(10, extra_actions=1)["tcr"] == 12
        assert compute_tcr(10, extra_actions=3)["tcr"] == 16

    def test_mulligans_flat(self):
        assert compute_tcr(10, mulligans=3)["tcr"] == 13

    def test_ep_rounds_down(self):
        # +1 per full 10 EP: 20 → +2, 9 → +0
        assert compute_tcr(10, ep_expended=20)["tcr"] == 12
        assert compute_tcr(10, ep_expended=9)["tcr"] == 10

    def test_edge_modifiers(self):
        assert compute_tcr(10, edge="minor")["tcr"] == 11
        assert compute_tcr(10, edge="major")["tcr"] == 12

    def test_defender_armour_subtracts(self):
        # -1 per full 10 AR on the target
        assert compute_tcr(10, target_ar=21)["tcr"] == 8
        assert compute_tcr(10, target_ar=19)["tcr"] == 9

    def test_target_extra_defences_double(self):
        assert compute_tcr(10, target_extra_defences=2)["tcr"] == 6

    def test_obstacle_modifiers(self):
        assert compute_tcr(10, obstacle="minor")["tcr"] == 9
        assert compute_tcr(10, obstacle="major")["tcr"] == 8

    def test_full_stack_totals(self):
        r = compute_tcr(combat_value=10, weapon_damage=22, current_hp=70,
                        extra_actions=1, mulligans=1, ep_expended=20,
                        edge="minor", target_ar=10, target_extra_defences=1,
                        obstacle="minor")
        # 10 +2 +3 +2 +1 +2 +1 -1 -2 -1 = 17
        assert r["tcr"] == 17

    def test_unknown_edge_ignored(self):
        assert compute_tcr(10, edge="colossal")["tcr"] == 10


class TestResolveDicelessCombat:
    def test_tie_is_stalemate(self):
        r = resolve_diceless_combat(10, 10)
        assert r["band"] == "stalemate"
        assert r["mos"] == 0
        assert r["attacker_wins"] is True

    def test_slight_success(self):
        r = resolve_diceless_combat(19, 17)
        assert r["band"] == "slight_success"
        assert r["mos"] == 2

    def test_moderate_success(self):
        r = resolve_diceless_combat(15, 11)
        assert r["band"] == "moderate_success"
        assert r["mos"] == 4

    def test_significant_success(self):
        r = resolve_diceless_combat(20, 12)
        assert r["band"] == "significant_success"
        assert r["mos"] == 8

    def test_major_success(self):
        r = resolve_diceless_combat(20, 5)
        assert r["band"] == "major_success"
        assert r["mos"] == 15

    def test_extreme_success(self):
        r = resolve_diceless_combat(30, 5)
        assert r["band"] == "extreme_success"
        assert r["mos"] == 25

    def test_defender_can_win(self):
        r = resolve_diceless_combat(10, 14)
        assert r["attacker_wins"] is False
        assert r["mos"] == 4
        assert r["band"] == "moderate_success"

    def test_hp_loss_percentages(self):
        r = resolve_diceless_combat(20, 12)
        assert r["victor_hp_loss_pct"] == 10
        assert r["opponent_hp_loss_pct"] == 75

    def test_stalemate_symmetric_loss(self):
        r = resolve_diceless_combat(9, 9)
        assert r["victor_hp_loss_pct"] == 10
        assert r["opponent_hp_loss_pct"] == 10


class TestDicelessBattle:
    def test_kozoh_vs_azok_canonical(self):
        # Extras Ch.9 worked example: Kozoh 19 vs Azok 17 → Slight Success.
        kozoh = {
            "combat_value": 10,
            "weapon_damage": 21,
            "current_hp": 80,
            "ep_expended": 20,
            "edge": "minor",
        }
        azok = {
            "combat_value": 10,
            "weapon_damage": 22,
            "current_hp": 70,
            "extra_actions": 1,
        }
        r = diceless_battle(kozoh, azok)
        assert r["attacker_tcr"] == 19
        assert r["defender_tcr"] == 17
        assert r["band"] == "slight_success"
        assert r["attacker_wins"] is True

    def test_battle_returns_both_tcrs(self):
        r = diceless_battle({"combat_value": 5}, {"combat_value": 8})
        assert r["attacker_tcr"] == 5
        assert r["defender_tcr"] == 8
        assert r["attacker_wins"] is False


class TestHedgedCheck:
    def test_baseline_seven(self):
        r = hedged_check(stat=5, target=12)  # 7 + 5 = 12
        assert r["rolled"] == 7
        assert r["total"] == 12
        assert r["success"] is True

    def test_fail_when_below_target(self):
        r = hedged_check(stat=3, target=12)  # 7 + 3 = 10
        assert r["total"] == 10
        assert r["success"] is False

    def test_minor_edge_eight(self):
        r = hedged_check(stat=5, target=13, edge="minor")  # 8 + 5 = 13
        assert r["rolled"] == 8
        assert r["success"] is True

    def test_major_edge_nine(self):
        r = hedged_check(stat=5, target=14, edge="major")  # 9 + 5 = 14
        assert r["rolled"] == 9
        assert r["success"] is True

    def test_minor_obstacle_six(self):
        r = hedged_check(stat=5, target=11, obstacle="minor")  # 6 + 5 = 11
        assert r["rolled"] == 6
        assert r["success"] is True

    def test_major_obstacle_five(self):
        r = hedged_check(stat=5, target=10, obstacle="major")  # 5 + 5 = 10
        assert r["rolled"] == 5
        assert r["success"] is True

    def test_net_edge_and_obstacle_cancel(self):
        r = hedged_check(stat=5, target=12, edge="minor", obstacle="minor")  # 7 + 5 = 12
        assert r["rolled"] == 7
        assert r["success"] is True


class TestModifierTables:
    def test_edge_value_table(self):
        assert EDGE_TCR_VALUE == {"minor": 1, "major": 2}

    def test_obstacle_value_table(self):
        assert OBSTACLE_TCR_VALUE == {"minor": -1, "major": -2}


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])