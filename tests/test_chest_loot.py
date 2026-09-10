"""tests/test_chest_loot.py — The Pydantic Weaver: generative chest loot.

Grounding:
  * NodeSchema must carry chest/stratum/node_type into the runtime dict.
  * ChestLootSchema rejects hallucinated effect keys, sub-field-less effects,
    over-cap CP, and effects on non-consumables.
  * Pricing stays in Python: Fibonacci silver (guild) vs gold model (SxM1).
  * loot_only rows are hidden from /shop (list_catalog) but visible in inventory.
  * Deposit is a single transaction (CP-2) — no orphan item rows.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

import engine.economy as economy
from engine.models import NodeSchema, ChestLootSchema, ChestEffect
from engine import state_manager

VALID_HEAL = ('[LOOT PAYLOAD] {"name":"Goblin Berry Tonic","item_type":"consumable",'
              '"description":"A tart crimson tonic.","item_cp":2,'
              '"effect_json":{"kind":"heal","hp":10}} [/LOOT PAYLOAD]')
VALID_GEAR = ('[LOOT PAYLOAD] {"name":"Copper Circlet","item_type":"gear",'
              '"description":"A warm circlet.","item_cp":3,"effect_json":{}} '
              '[/LOOT PAYLOAD]')
VALID_VALUABLE = ('[LOOT PAYLOAD] {"name":"Moon-Silver Figurine","item_type":"valuable",'
                  '"description":"A relic of the old tower.","item_cp":2,"effect_json":{}} '
                  '[/LOOT PAYLOAD]')


class TestNodeSchemaChestMetadata(unittest.TestCase):
    def test_round_trips_chest_and_stratum(self):
        node = NodeSchema(node_id="n1", title="Stratum Cleared", description="d",
                          exits={}, node_type="reward", stratum=1,
                          chest={"tier": "wooden"})
        d = node.model_dump()
        self.assertEqual(d["chest"], {"tier": "wooden"})
        self.assertEqual(d["stratum"], 1)
        self.assertEqual(d["node_type"], "reward")

    def test_legacy_nodes_still_build(self):
        node = NodeSchema(node_id="n1", title="t", description="d", exits={"north": "n2"})
        self.assertIsNone(node.chest)
        self.assertIsNone(node.stratum)
        self.assertIsNone(node.node_type)


class TestChestCapScaling(unittest.TestCase):
    def test_wooden_stratum1(self):
        self.assertEqual(economy.loot_cap_for("wooden", 1), 3)

    def test_wooden_deep_stratum(self):
        self.assertEqual(economy.loot_cap_for("wooden", 3), 7)

    def test_platinum_stratum5(self):
        self.assertEqual(economy.loot_cap_for("platinum", 5), 18)

    def test_unknown_tier_defaults_wooden(self):
        self.assertEqual(economy.loot_cap_for("mithril", 1), 3)


class TestPricingHelpers(unittest.TestCase):
    def test_gold_price_model(self):
        self.assertEqual(economy.gold_price(1, 1), 50)
        self.assertEqual(economy.gold_price(3, 2), 300)

    def test_currency_for_setting(self):
        self.assertEqual(economy.currency_for_setting("shota_x_monsters"), "gold")
        self.assertEqual(economy.currency_for_setting("guild_rpg"), "silver")

    def test_rank_label_for_cp_ladder(self):
        self.assertEqual(economy.rank_label_for_cp(1), "D")
        self.assertEqual(economy.rank_label_for_cp(2), "D")
        self.assertEqual(economy.rank_label_for_cp(3), "C")
        self.assertEqual(economy.rank_label_for_cp(7), "B")
        self.assertEqual(economy.rank_label_for_cp(8), "A")
        self.assertEqual(economy.rank_label_for_cp(13), "S")


class TestParseChestLoot(unittest.TestCase):
    def test_valid_consumable_parses(self):
        item = economy.parse_chest_loot(VALID_HEAL, "wooden", 1)
        self.assertIsInstance(item, ChestLootSchema)
        self.assertEqual(item.item_cp, 2)
        self.assertEqual(item.effect_json.kind, "heal")
        self.assertEqual(item.effect_json.hp, 10)

    def test_prose_before_payload_ignored(self):
        item = economy.parse_chest_loot(
            "You prise the lid open. Inside sits a single vial.\n" + VALID_HEAL, "wooden", 1)
        self.assertEqual(item.name, "Goblin Berry Tonic")

    def test_hallucinated_effect_key_rejected(self):
        raw = ('[LOOT PAYLOAD] {"name":"X","item_type":"consumable","description":"d",'
               '"item_cp":1,"effect_json":{"kind":"fire_damage","amount":10}} [/LOOT PAYLOAD]')
        with self.assertRaises(ValueError):
            economy.parse_chest_loot(raw, "wooden", 1)

    def test_zero_heal_effect_rejected(self):
        raw = ('[LOOT PAYLOAD] {"name":"X","item_type":"consumable","description":"d",'
               '"item_cp":2,"effect_json":{"kind":"heal"}} [/LOOT PAYLOAD]')
        with self.assertRaises(ValueError):
            economy.parse_chest_loot(raw, "wooden", 1)

    def test_over_cap_rejected(self):
        raw = ('[LOOT PAYLOAD] {"name":"X","item_type":"consumable","description":"d",'
               '"item_cp":9,"effect_json":{"kind":"heal","hp":10}} [/LOOT PAYLOAD]')
        with self.assertRaises(ValueError):
            economy.parse_chest_loot(raw, "wooden", 1)

    def test_gear_with_effect_rejected(self):
        raw = ('[LOOT PAYLOAD] {"name":"X","item_type":"gear","description":"d",'
               '"item_cp":2,"effect_json":{"kind":"heal","hp":10}} [/LOOT PAYLOAD]')
        with self.assertRaises(ValueError):
            economy.parse_chest_loot(raw, "wooden", 1)

    def test_gear_empty_effect_ok(self):
        item = economy.parse_chest_loot(VALID_GEAR, "gold", 1)
        self.assertEqual(item.item_type, "gear")
        self.assertEqual(item.effect_json, {})

    def test_missing_payload_block_rejected(self):
        with self.assertRaises(ValueError):
            economy.parse_chest_loot("The chest is empty.", "wooden", 1)

    def test_invalid_json_rejected(self):
        raw = '[LOOT PAYLOAD] {"name": [/LOOT PAYLOAD]'
        with self.assertRaises(Exception):
            economy.parse_chest_loot(raw, "wooden", 1)


class ChestLootDBTestCase(unittest.TestCase):
    """tmp DBs, fresh init per test — mirrors test_besm_catalog.py."""

    def setUp(self):
        self.tmp_roster = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_session = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_roster.close()
        self.tmp_session.close()
        self._patchers = [
            patch.object(economy, "ACTIVE_ROSTER_PATH", self.tmp_roster.name),
            patch.object(economy, "SESSION_PATH", self.tmp_session.name),
        ]
        for p in self._patchers:
            p.start()
        economy.init_economy_db()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        os.unlink(self.tmp_roster.name)
        os.unlink(self.tmp_session.name)

    def _items_table(self):
        with sqlite3.connect(self.tmp_roster.name) as conn:
            return conn.execute("SELECT * FROM items WHERE item_id LIKE 'chest_%'").fetchall()


class TestDepositChestLoot(ChestLootDBTestCase):
    def test_guild_consumable_deposited_as_loot_only(self):
        item = economy.parse_chest_loot(VALID_HEAL, "wooden", 1)
        item_id = economy.deposit_chest_loot("guild_rpg", "Miri", item, 1)
        with sqlite3.connect(self.tmp_roster.name) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT item_id, currency, price_class, price_silver, loot_only, rank_label, besm_points "
                "FROM items WHERE item_id = ?", (item_id,)).fetchone()
        self.assertEqual(row["currency"], "silver")
        self.assertEqual(row["price_class"], "consumable")
        self.assertEqual(row["price_silver"], 6)  # D-rank bracket midpoint (3+10)//2
        self.assertEqual(row["loot_only"], 1)
        self.assertEqual(row["rank_label"], "D")
        self.assertEqual(row["besm_points"], 4)   # item_cp * 2

    def test_guild_gear_priced_fibonacci(self):
        item = economy.parse_chest_loot(VALID_GEAR, "gold", 1)
        item_id = economy.deposit_chest_loot("guild_rpg", "Sylvara", item, 1)
        with sqlite3.connect(self.tmp_roster.name) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT price_class, price_silver, currency FROM items WHERE item_id = ?",
                               (item_id,)).fetchone()
        self.assertEqual(row["price_class"], "permanent")
        self.assertEqual(row["price_silver"], economy.fibonacci_price(3))  # 400 sp
        self.assertEqual(row["currency"], "silver")

    def test_sxm1_deposit_is_gold(self):
        item = economy.parse_chest_loot(VALID_VALUABLE, "wooden", 1)
        item_id = economy.deposit_chest_loot("shota_x_monsters", "Watt", item, 1)
        with sqlite3.connect(self.tmp_roster.name) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT price_class, price_silver, currency FROM items WHERE item_id = ?",
                               (item_id,)).fetchone()
        self.assertEqual(row["currency"], "gold")
        self.assertEqual(row["price_class"], "priceless")
        self.assertIsNone(row["price_silver"])

    def test_sxm1_consumable_priced_via_gold_model(self):
        item = economy.parse_chest_loot(VALID_HEAL, "wooden", 1)
        economy.deposit_chest_loot("shota_x_monsters", "Watt", item, 1)
        with sqlite3.connect(self.tmp_roster.name) as conn:
            price = conn.execute(
                "SELECT price_silver FROM items WHERE setting_id='shota_x_monsters' AND name='Goblin Berry Tonic'"
            ).fetchone()[0]
        self.assertEqual(price, 100)  # 50 * 2 CP * 1

    def test_deposit_lands_in_inventory(self):
        item = economy.parse_chest_loot(VALID_HEAL, "wooden", 1)
        economy.deposit_chest_loot("guild_rpg", "Miri", item, 1)
        inv = economy.get_inventory("guild_rpg", "Miri")
        self.assertEqual(len(inv), 1)
        self.assertEqual(inv[0]["name"], "Goblin Berry Tonic")
        self.assertEqual(inv[0]["qty"], 1)

    def test_loot_only_hidden_from_shop_but_kept_in_inventory(self):
        item = economy.parse_chest_loot(VALID_HEAL, "wooden", 1)
        economy.deposit_chest_loot("guild_rpg", "Miri", item, 1)
        catalog = economy.list_catalog("guild_rpg")
        self.assertNotIn("Goblin Berry Tonic", [c["name"] for c in catalog])
        self.assertTrue(economy.get_inventory("guild_rpg", "Miri"))

    def test_deposit_atomic_rolls_back_orphan_row(self):
        """CP-2: a failed inventory deposit must not leave an orphan items row."""
        class _BoomClock:
            @staticmethod
            def now():
                raise RuntimeError("boom")
        item = economy.parse_chest_loot(VALID_HEAL, "wooden", 1)
        with patch.object(economy, "datetime", _BoomClock):
            with self.assertRaises(RuntimeError):
                economy.deposit_chest_loot("guild_rpg", "Miri", item, 1)
        self.assertEqual(self._items_table(), [])

    def test_generate_chest_loot_full_pipeline(self):
        item_id = economy.generate_chest_loot("guild_rpg", "Miri", "wooden", 1, VALID_HEAL)
        self.assertTrue(item_id.startswith("chest_"))
        self.assertEqual(len(self._items_table()), 1)
        self.assertTrue(economy.get_inventory("guild_rpg", "Miri"))


class TestOpenedChests(unittest.TestCase):
    def setUp(self):
        self.tmp_session = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_session.close()
        state_manager.set_active_db_path(self.tmp_session.name)
        state_manager.init_db()

    def tearDown(self):
        os.unlink(self.tmp_session.name)

    def test_mark_then_is_opened(self):
        self.assertFalse(state_manager.is_chest_opened("s1", "node_x"))
        state_manager.mark_chest_opened("s1", "node_x")
        self.assertTrue(state_manager.is_chest_opened("s1", "node_x"))

    def test_unmark_rolls_back(self):
        state_manager.mark_chest_opened("s1", "node_x")
        state_manager.unmark_chest_opened("s1", "node_x")
        self.assertFalse(state_manager.is_chest_opened("s1", "node_x"))

    def test_idempotent_mark(self):
        state_manager.mark_chest_opened("s1", "node_x")
        state_manager.mark_chest_opened("s1", "node_x")
        state_manager.mark_chest_opened("s1", "node_x")
        self.assertTrue(state_manager.is_chest_opened("s1", "node_x"))


if __name__ == "__main__":
    unittest.main()