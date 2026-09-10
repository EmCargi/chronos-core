"""tests/test_verify_dungeon.py — validate the campaign module structural validator."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

from engine.verify_dungeon import verify_dungeon_structure

MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"


class TestValidModules(unittest.TestCase):
    def test_five_room_dungeon_v1_passes(self):
        self.assertTrue(
            verify_dungeon_structure(str(MODULES_DIR / "five_room_dungeon_v1.json")),
        )

    def test_forest_labyrinth_stratum1_passes(self):
        self.assertTrue(
            verify_dungeon_structure(str(MODULES_DIR / "forest_labyrinth_stratum1.json")),
        )

    def test_c_rank_trial_passes(self):
        self.assertTrue(
            verify_dungeon_structure(str(MODULES_DIR / "c_rank_trial.json")),
        )


class TestRequiredRoomDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )

    def tearDown(self):
        self.tmp.close()
        os.unlink(self.tmp.name)

    def _write(self, data: dict) -> str:
        self.tmp.seek(0)
        self.tmp.truncate()
        json.dump(data, self.tmp)
        self.tmp.flush()
        return self.tmp.name

    def test_missing_guardian_fails(self):
        data = {
            "nodes": {
                "node_01_puzzle": {"title": "Puzzle"},
                "node_02_setback": {"title": "Setback"},
                "node_03_climax": {"title": "Climax"},
                "node_04_reward": {"title": "Reward"},
            }
        }
        self.assertFalse(verify_dungeon_structure(self._write(data)))

    def test_missing_puzzle_fails(self):
        data = {
            "nodes": {
                "node_01_guardian": {"title": "Guardian"},
                "node_02_setback": {"title": "Setback"},
                "node_03_climax": {"title": "Climax"},
                "node_04_reward": {"title": "Reward"},
            }
        }
        self.assertFalse(verify_dungeon_structure(self._write(data)))

    def test_all_rooms_present_passes(self):
        data = {
            "nodes": {
                "node_01_guardian": {"title": "Guardian"},
                "node_02_puzzle": {"title": "Puzzle"},
                "node_03_setback": {"title": "Setback"},
                "node_04_climax": {"title": "Climax"},
                "node_05_reward": {"title": "Reward"},
            }
        }
        self.assertTrue(verify_dungeon_structure(self._write(data)))

    def test_room_match_case_insensitive(self):
        data = {
            "nodes": {
                "node_01_GUARDIAN": {"title": "Guardian"},
                "node_02_PUZZLE": {"title": "Puzzle"},
                "node_03_SETBACK": {"title": "Setback"},
                "node_04_CLIMAX": {"title": "Climax"},
                "node_05_REWARD": {"title": "Reward"},
            }
        }
        self.assertTrue(verify_dungeon_structure(self._write(data)))


class TestRequiredCheckValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )

    def tearDown(self):
        self.tmp.close()
        os.unlink(self.tmp.name)

    def _write(self, data: dict) -> str:
        self.tmp.seek(0)
        self.tmp.truncate()
        json.dump(data, self.tmp)
        self.tmp.flush()
        return self.tmp.name

    def _valid_rooms(self) -> dict:
        return {
            "node_01_guardian": {"title": "Guardian"},
            "node_02_puzzle": {"title": "Puzzle"},
            "node_03_setback": {"title": "Setback"},
            "node_04_climax": {"title": "Climax"},
            "node_05_reward": {"title": "Reward"},
        }

    def test_complete_required_check_passes(self):
        rooms = self._valid_rooms()
        rooms["node_01_guardian"]["required_check"] = {
            "stat": "body",
            "skill": "athletics",
            "dv": 4,
            "fail_damage": "1d6 bludgeoning",
        }
        self.assertTrue(verify_dungeon_structure(self._write({"nodes": rooms})))

    def test_missing_stat_fails(self):
        rooms = self._valid_rooms()
        rooms["node_01_guardian"]["required_check"] = {
            "skill": "athletics",
            "dv": 4,
            "fail_damage": "1d6",
        }
        self.assertFalse(verify_dungeon_structure(self._write({"nodes": rooms})))

    def test_missing_skill_fails(self):
        rooms = self._valid_rooms()
        rooms["node_01_guardian"]["required_check"] = {
            "stat": "body",
            "dv": 4,
            "fail_damage": "1d6",
        }
        self.assertFalse(verify_dungeon_structure(self._write({"nodes": rooms})))

    def test_missing_dv_fails(self):
        rooms = self._valid_rooms()
        rooms["node_01_guardian"]["required_check"] = {
            "stat": "body",
            "skill": "athletics",
            "fail_damage": "1d6",
        }
        self.assertFalse(verify_dungeon_structure(self._write({"nodes": rooms})))

    def test_missing_fail_damage_fails(self):
        rooms = self._valid_rooms()
        rooms["node_01_guardian"]["required_check"] = {
            "stat": "body",
            "skill": "athletics",
            "dv": 4,
        }
        self.assertFalse(verify_dungeon_structure(self._write({"nodes": rooms})))

    def test_none_required_check_passes(self):
        rooms = self._valid_rooms()
        rooms["node_01_guardian"]["required_check"] = None
        self.assertTrue(verify_dungeon_structure(self._write({"nodes": rooms})))

    def test_empty_required_check_passes(self):
        """Empty dict is truthy — still counts as a check, requires keys."""
        rooms = self._valid_rooms()
        rooms["node_01_guardian"]["required_check"] = {}
        self.assertFalse(verify_dungeon_structure(self._write({"nodes": rooms})))


class TestFileErrors(unittest.TestCase):
    def test_nonexistent_file_fails(self):
        self.assertFalse(verify_dungeon_structure("/tmp/no_such_module_99999.json"))

    def test_invalid_json_fails(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            tmp.write("not json {{{[[[")
            tmp_path = tmp.name
        try:
            self.assertFalse(verify_dungeon_structure(tmp_path))
        finally:
            os.unlink(tmp_path)

    def test_no_nodes_key_fails(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            json.dump({"module_name": "test"}, tmp)
            tmp_path = tmp.name
        try:
            self.assertFalse(verify_dungeon_structure(tmp_path))
        finally:
            os.unlink(tmp_path)


def _build_labyrinth() -> dict:
    """A valid branching labyrinth matching the besm_labyrinth_architect.md contract.
    6 nodes, 3 stratums, branching + a chest dead-end + a Symbol Monster gate."""
    return {
        "module_name": "Test Labyrinth",
        "stratum_count": 3,
        "starting_node": "node_01_entrance",
        "nodes": {
            "node_01_entrance": {
                "node_id": "node_01_entrance",
                "title": "Entrance",
                "stratum": 1,
                "node_type": "entrance",
                "exits": {"north": "node_02_encounter"},
                "required_check": None,
            },
            "node_02_encounter": {
                "node_id": "node_02_encounter",
                "title": "Feral Slimes",
                "stratum": 1,
                "node_type": "encounter",
                "exits": {"north": "node_03_gate", "east": "node_04_chest"},
                "required_check": {
                    "stat": "stat_body", "skill": 0, "dv": 10, "fail_damage": 4,
                },
            },
            "node_04_chest": {
                "node_id": "node_04_chest",
                "title": "Chest Room",
                "stratum": 1,
                "node_type": "chest",
                "chest": {"tier": "gold", "contents": ["Potion"]},
                "exits": {"west": "node_02_encounter"},
                "required_check": None,
            },
            "node_03_gate": {
                "node_id": "node_03_gate",
                "title": "Second Stratum Gate",
                "stratum": 2,
                "node_type": "gate",
                "exits": {"north": "node_05_symbol", "south": "node_02_encounter"},
                "required_check": {
                    "stat": "stat_mind", "skill": 0, "dv": 12, "fail_damage": 6,
                },
            },
            "node_05_symbol": {
                "node_id": "node_05_symbol",
                "title": "Symbol Monster",
                "stratum": 2,
                "node_type": "symbol_monster",
                "symbol": True,
                "exits": {"south": "node_03_gate", "north": "node_06_climax"},
                "required_check": {
                    "stat": "stat_body", "skill": 0, "dv": 14, "fail_damage": 10,
                },
            },
            "node_06_climax": {
                "node_id": "node_06_climax",
                "title": "Capstone Boss",
                "stratum": 3,
                "node_type": "climax",
                "exits": {"west": "node_05_symbol"},
                "required_check": {
                    "stat": "stat_soul", "skill": 0, "dv": 16, "fail_damage": 12,
                },
            },
        },
    }


class TestLabyrinthPath(unittest.TestCase):
    """Relaxed-union labyrinth branch — 12 cases (CP-1..CP-4 amendments)."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )

    def tearDown(self):
        self.tmp.close()
        os.unlink(self.tmp.name)

    def _write(self, data: dict) -> str:
        self.tmp.seek(0)
        self.tmp.truncate()
        json.dump(data, self.tmp)
        self.tmp.flush()
        return self.tmp.name

    def test_valid_labyrinth_passes(self):
        self.assertTrue(verify_dungeon_structure(self._write(_build_labyrinth())))

    def test_cyclic_labyrinth_passes(self):
        """CP-2: a shortcut looping back to the entrance must not crash the traversal."""
        data = _build_labyrinth()
        data["nodes"]["node_07_shortcut"] = {
            "node_id": "node_07_shortcut",
            "title": "Shortcut Back",
            "stratum": 3,
            "node_type": "shortcut",
            "exits": {"south": "node_01_entrance", "north": "node_06_climax"},
            "required_check": None,
        }
        data["nodes"]["node_06_climax"]["exits"]["north"] = "node_07_shortcut"
        self.assertTrue(verify_dungeon_structure(self._write(data)))

    def test_labyrinth_over_7_nodes_passes(self):
        """CP-1: no upper node cap; 8 nodes accepted."""
        data = _build_labyrinth()
        data["nodes"]["node_08_lore"] = {
            "node_id": "node_08_lore",
            "title": "Lore Room",
            "stratum": 1,
            "node_type": "lore",
            "exits": {"north": "node_02_encounter"},
            "required_check": None,
        }
        data["nodes"]["node_02_encounter"]["exits"]["west"] = "node_08_lore"
        self.assertTrue(verify_dungeon_structure(self._write(data)))

    def test_missing_starting_node_fails(self):
        """Megane ruling: starting_node is hard-required, no first-key fallback."""
        data = _build_labyrinth()
        del data["starting_node"]
        self.assertFalse(verify_dungeon_structure(self._write(data)))

    def test_orphan_node_fails(self):
        data = _build_labyrinth()
        data["nodes"]["node_99_orphan"] = {
            "node_id": "node_99_orphan",
            "title": "Unreachable",
            "stratum": 1,
            "node_type": "encounter",
            "exits": {},
            "required_check": {"stat": "stat_body", "skill": 0, "dv": 10, "fail_damage": 4},
        }
        self.assertFalse(verify_dungeon_structure(self._write(data)))

    def test_open_exit_fails(self):
        data = _build_labyrinth()
        data["nodes"]["node_01_entrance"]["exits"]["north"] = "node_missing"
        self.assertFalse(verify_dungeon_structure(self._write(data)))

    def test_invalid_node_type_fails(self):
        data = _build_labyrinth()
        data["nodes"]["node_04_chest"]["node_type"] = "treasure_vault"
        self.assertFalse(verify_dungeon_structure(self._write(data)))

    def test_stratum_out_of_range_fails(self):
        data = _build_labyrinth()
        data["nodes"]["node_06_climax"]["stratum"] = 9
        self.assertFalse(verify_dungeon_structure(self._write(data)))

    def test_combat_node_missing_required_check_fails(self):
        data = _build_labyrinth()
        del data["nodes"]["node_05_symbol"]["required_check"]["dv"]
        self.assertFalse(verify_dungeon_structure(self._write(data)))

    def test_lore_node_null_check_passes(self):
        """CP-3: lore is a valid node_type with a null required_check."""
        data = _build_labyrinth()
        data["nodes"]["node_08_lore"] = {
            "node_id": "node_08_lore",
            "title": "Lore Room",
            "stratum": 1,
            "node_type": "lore",
            "exits": {"north": "node_02_encounter"},
            "required_check": None,
        }
        data["nodes"]["node_02_encounter"]["exits"]["west"] = "node_08_lore"
        self.assertTrue(verify_dungeon_structure(self._write(data)))

    def test_symbol_true_on_non_symbol_fails(self):
        data = _build_labyrinth()
        data["nodes"]["node_04_chest"]["symbol"] = True
        self.assertFalse(verify_dungeon_structure(self._write(data)))

    def test_dv_dip_warns_but_passes(self):
        """CP-4: a DV dip is advisory — warns and still returns True."""
        data = _build_labyrinth()
        data["nodes"]["node_06_climax"]["required_check"]["dv"] = 8  # below stratum 2's 14
        with self.assertLogs(level="WARNING"):
            self.assertTrue(verify_dungeon_structure(self._write(data)))


if __name__ == "__main__":
    unittest.main()
