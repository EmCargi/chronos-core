"""Tests for the card staging prep script (stage_cards.py).

Covers card discovery, idempotent SYSTEM DATA injection, and the no-stats
skip guard against the real corpus.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # dev/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))                                     # chronos-core/

import stage_cards


def _make_card(dst: Path, name: str, hp: int) -> None:
    """Write a minimal statted/lore-only card JSON into a <name> dir."""
    d = dst / name
    d.mkdir(parents=True, exist_ok=True)
    profile = "| Stat | Value |\n|------|-------|"
    table = f"| HP | {hp} |" if hp > 0 else "No stats available."
    card = {
        "spec": "chara_card_v2",
        "data": {
            "name": name,
            "description": (
                f"**Combat Profile:**\n\n{profile}\n{table}\n\n"
                "**Combat Role:** A mobile ranged attacker."
            ),
        },
    }
    (d / f"{name}_character_card.json").write_text(json.dumps(card), encoding="utf-8")


class TestFindCards:
    def test_finds_only_character_cards(self, tmp_path: Path):
        _make_card(tmp_path, "slime", 23)
        _make_card(tmp_path, "bee_fighter", 125)
        (tmp_path / "unrelated.txt").write_text("x")
        cards = stage_cards.find_cards(str(tmp_path))
        names = sorted(n for n, _ in cards)
        assert names == ["bee_fighter", "slime"]
        assert all(p.name.endswith("_character_card.json") for _, p in cards)


class TestInjectSystemData:
    def test_appends_block_to_plain_desc(self):
        desc = "flavor text"
        block = "[SYSTEM DATA: BESM 4E MECHANICS]\n[Stats: ...]"
        out = stage_cards.inject_system_data(desc, block)
        assert out == "flavor text\n\n[SYSTEM DATA: BESM 4E MECHANICS]\n[Stats: ...]"

    def test_idempotent_when_block_already_present(self):
        desc = "flavor\n\n[SYSTEM DATA: BESM 4E MECHANICS]\n[Stats: ...]"
        assert stage_cards.inject_system_data(desc, desc) == desc


class TestCardScreening:
    def test_statted_card_detected(self, tmp_path: Path):
        _make_card(tmp_path, "slime", 23)
        name, card_path = stage_cards.find_cards(str(tmp_path))[0]
        card = json.loads(card_path.read_text())
        desc = card["data"]["description"]
        assert stage_cards.extract_game_hp(desc) == 23

    def test_lore_only_card_hp_zero(self, tmp_path: Path):
        _make_card(tmp_path, "abaddon", 0)
        name, card_path = stage_cards.find_cards(str(tmp_path))[0]
        card = json.loads(card_path.read_text())
        desc = card["data"]["description"]
        assert stage_cards.extract_game_hp(desc) == 0
        assert "No stats" in desc

    def test_real_corpus_screens_consistently(self):
        """Against the shipped persona-etl corpus: 94 statted / 245 lore-only."""
        cards = stage_cards.find_cards(stage_cards.DEFAULT_SOURCE)
        assert len(cards) == 339
        statted = 0
        for name, card_path in cards:
            card = json.loads(card_path.read_text())
            desc = card["data"]["description"]
            if stage_cards.extract_game_hp(desc) > 0:
                statted += 1
        assert statted == 94