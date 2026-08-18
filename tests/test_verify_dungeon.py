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

    def test_forest_labyrinth_v1_passes(self):
        self.assertTrue(
            verify_dungeon_structure(str(MODULES_DIR / "forest_labyrinth_v1.json")),
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


if __name__ == "__main__":
    unittest.main()
