"""Tests for the character card importer (engine/batch_ingest.py).

Redirects RAW_DIR/PROCESSED_DIR/FAILED_DIR to tmp staging, and points the
roster DB at a throwaway path — the real data/ DB and staging/ are untouched.

METHOD 1 cards (SYSTEM DATA block) parse fully deterministically. METHOD 2
(LLM) is stubbed to fail so tests stay offline and fall through to METHOD 3.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # dev/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))                                     # chronos-core/

import engine.batch_ingest as bi
import engine.guild_roster as gr


def _card(name: str, description: str, spec: str = "chara_card_v2") -> dict:
    return {"spec": spec, "spec_version": "2.0", "data": {"name": name, "description": description}}


def _write_card(raw: Path, card: dict) -> str:
    payload = card.get("data", card)
    filename = f"{payload['name'].replace(' ', '_')}_character_card.json"
    (raw / filename).write_text(json.dumps(card), encoding="utf-8")
    return filename


SYSTEM_BLOCK = (
    "[SYSTEM DATA: BESM 4E MECHANICS]\n"
    "[Setting: besm_disc]\n"
    "[Rank: Tier 3]\n"
    "[Points Budget: 82 / 82 CP]\n"
    "[Stats: Body 6, Mind 7, Soul 4]\n"
    "[Combat Values: ACV 5, DCV 3. HP 50. EP 55.]\n"
)

LORE_DESC = (
    "**Physical Description:** A luminous gatekeeper.\n"
    "**Combat Profile:** Abaddon's stats are not yet decoded from BESM Disc.\n"
)


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    """Redirect batch_ingest dirs + roster DB to tmp, stub the LLM bridge offline."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    staging = tmp_path / "staging"
    (staging / "raw").mkdir(parents=True)
    (staging / "processed").mkdir()
    (staging / "failed").mkdir()

    monkeypatch.setattr(gr, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(gr, "ROSTER_PATH", str(data_dir / "test_roster.db"))
    monkeypatch.setattr(bi, "RAW_DIR", str(staging / "raw"))
    monkeypatch.setattr(bi, "PROCESSED_DIR", str(staging / "processed"))
    monkeypatch.setattr(bi, "FAILED_DIR", str(staging / "failed"))
    gr.init_roster_db()

    class OfflineBridge:
        def dispatch_ollama_turn(self, *a, **kw):
            raise RuntimeError("no network in tests")

    monkeypatch.setattr(bi, "LLMBridge", OfflineBridge)
    return {"staging": staging, "raw": staging / "raw",
            "processed": staging / "processed", "failed": staging / "failed"}


class TestMethod1SystemData:
    def test_system_data_card_ingested(self, env):
        desc = "**Combat Profile:** flavor.\n\n" + SYSTEM_BLOCK
        _write_card(env["raw"], _card("Candy_Shooter" if False else "Candy Shooter", desc))
        res = bi.run_auto_ingest()
        assert "Candy_Shooter_character_card.json" in res["processed"]
        c = gr.get_character("besm_disc", "Candy Shooter")
        assert c["stat_body"] == 6 and c["stat_mind"] == 7 and c["stat_soul"] == 4
        assert c["acv"] == 5 and c["dcv"] == 3
        assert c["max_hp"] == 50 and c["max_ep"] == 55
        assert c["points_budget"] == 82
        assert c["rank_label"] == "Tier 3"

    def test_files_move_to_processed(self, env):
        _write_card(env["raw"], _card("Slime", "**Combat Profile:** hi\n\n" + SYSTEM_BLOCK))
        bi.run_auto_ingest()
        assert len(list(env["raw"].glob("*.json"))) == 0
        assert len(list(env["processed"].glob("*.json"))) == 1

    def test_method1_beats_llm_for_statted_cards(self, env):
        """A statted card must never hit the offline stub (METHOD 2 path)."""
        _write_card(env["raw"], _card("Goblin", "**Combat Profile:**\n\n" + SYSTEM_BLOCK))
        res = bi.run_auto_ingest()
        assert len(res["processed"]) == 1 and not res["failed"]


class TestMethod3OfflineFallback:
    def test_lore_only_card_falls_to_heuristic(self, env):
        """No SYSTEM DATA + offline LLM → METHOD 3 rank heuristic, still ingested."""
        _write_card(env["raw"], _card("Abaddon", LORE_DESC))
        res = bi.run_auto_ingest()
        assert len(res["processed"]) == 1, res
        c = gr.get_character(gr.DEFAULT_SETTINGS and "guild_rpg" or "guild_rpg", "Abaddon")
        assert c is not None
        assert c["stat_body"] == 6 and c["stat_soul"] == 7  # C-Rank defaults


class TestFailurePaths:
    def test_invalid_json_sent_to_failed(self, env):
        (env["raw"] / "broken_character_card.json").write_text("{not json", encoding="utf-8")
        res = bi.run_auto_ingest()
        assert len(res["failed"]) == 1
        assert len(list(env["failed"].glob("*.json"))) == 1
        assert len(list(env["raw"].glob("*.json"))) == 0

    def test_stat_out_of_bounds_fails_validation(self, env):
        desc = SYSTEM_BLOCK.replace("[Stats: Body 6, Mind 7, Soul 4]", "[Stats: Body 99, Mind 7, Soul 4]")
        _write_card(env["raw"], _card("Overdrive", "**Combat Profile:**\n\n" + desc))
        res = bi.run_auto_ingest()
        assert len(res["failed"]) == 1
        assert len(list(env["failed"].glob("*.json"))) == 1

    def test_empty_raw_returns_empty(self, env):
        res = bi.run_auto_ingest()
        assert res == {"processed": [], "failed": []}


class TestSettingDetection:
    def test_custom_setting_respected(self, env):
        block = SYSTEM_BLOCK.replace("[Setting: besm_disc]", "[Setting: test_realm]")
        gr.register_setting("test_realm", "Test Realm", "sandbox")
        _write_card(env["raw"], _card("Candy Shooter", "**Combat Profile:**\n\n" + block))
        bi.run_auto_ingest()
        assert gr.get_character("test_realm", "Candy Shooter") is not None

    def test_rank_parses_from_system_block(self, env):
        _write_card(env["raw"], _card("Slime", "**Combat Profile:**\n\n" + SYSTEM_BLOCK))
        bi.run_auto_ingest()
        assert gr.get_character("besm_disc", "Slime")["rank_label"] == "Tier 3"

    def test_power_packs_registered(self, env):
        block = SYSTEM_BLOCK + "[Power Packs: Berserk + Lifesteal + None]\n"
        _write_card(env["raw"], _card("Battle Ant", "**Combat Profile:**\n\n" + block))
        bi.run_auto_ingest()
        packs = gr.get_character_power_packs("besm_disc", "Battle Ant")
        assert [p["pack_name"] for p in packs] == ["Berserk", "Lifesteal"]