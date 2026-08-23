"""tests/test_economy.py — Fibonacci pricing, rank brackets, wallets, inventory.

Grounded in the BESM 4e economy rules:
  * Fibonacci permanent pricing: 1 CP = 100 sp, sequence 100,100,200,300,500...
  * Rank-bracket consumable pricing: D(3-10), C(15-40), B(50-200), A(300-800)
  * Wallet CRUD with atomicity, inventory stacking, buy/spend guardrails
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
from engine import state_manager


class TestFibonacciPrice(unittest.TestCase):
    def test_zero_cp_returns_zero(self):
        self.assertEqual(economy.fibonacci_price(0), 0)

    def test_negative_cp_returns_zero(self):
        self.assertEqual(economy.fibonacci_price(-5), 0)

    def test_one_cp_returns_100(self):
        self.assertEqual(economy.fibonacci_price(1), 100)

    def test_two_cp_returns_200(self):
        self.assertEqual(economy.fibonacci_price(2), 200)

    def test_three_cp_returns_400(self):
        self.assertEqual(economy.fibonacci_price(3), 400)

    def test_four_cp_returns_700(self):
        self.assertEqual(economy.fibonacci_price(4), 700)

    def test_five_cp_returns_1200(self):
        self.assertEqual(economy.fibonacci_price(5), 1200)

    def test_six_cp_returns_2000(self):
        self.assertEqual(economy.fibonacci_price(6), 2000)

    def test_eight_cp_returns_5400(self):
        self.assertEqual(economy.fibonacci_price(8), 5400)


class TestRankBrackets(unittest.TestCase):
    def test_d_rank(self):
        self.assertEqual(economy.bracket_for_rank("D"), (3, 10))

    def test_c_rank(self):
        self.assertEqual(economy.bracket_for_rank("C"), (15, 40))

    def test_b_rank(self):
        self.assertEqual(economy.bracket_for_rank("B"), (50, 200))

    def test_a_rank(self):
        self.assertEqual(economy.bracket_for_rank("A"), (300, 800))

    def test_s_rank_has_no_bracket(self):
        self.assertEqual(economy.bracket_for_rank("S"), (None, None))

    def test_unknown_rank_returns_none(self):
        self.assertEqual(economy.bracket_for_rank("X"), (None, None))

    def test_c_rank_with_space_suffix(self):
        self.assertEqual(economy.bracket_for_rank("C Monster Slayer"), (15, 40))

    def test_case_insensitive(self):
        self.assertEqual(economy.bracket_for_rank("c"), (15, 40))


class TestComputePrice(unittest.TestCase):
    def test_permanent_uses_fibonacci(self):
        item = {"price_class": "permanent", "item_cp": 3, "price_silver": 999}
        self.assertEqual(economy.compute_price(item), 400)

    def test_consumable_uses_stored_price(self):
        item = {"price_class": "consumable", "item_cp": 1, "price_silver": 4}
        self.assertEqual(economy.compute_price(item), 4)

    def test_priceless_returns_none(self):
        item = {"price_class": "priceless", "item_cp": 99, "price_silver": None}
        self.assertIsNone(economy.compute_price(item))


class EconomyDBTestCase(unittest.TestCase):
    """Base: patches DB paths to temp files. Each test starts fresh."""

    def setUp(self):
        self.tmp_roster = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_session = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_roster.close()
        self.tmp_session.close()
        self._patchers = [
            patch.object(economy, "ROSTER_PATH", self.tmp_roster.name),
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


class TestWalletOperations(EconomyDBTestCase):
    def test_unregistered_wallet_returns_zero(self):
        self.assertEqual(economy.get_wallet("guild_rpg", "Newbie"), 0)

    def test_grant_silver_creates_wallet(self):
        bal = economy.grant_silver("guild_rpg", "Hero", 500)
        self.assertEqual(bal, 500)
        self.assertEqual(economy.get_wallet("guild_rpg", "Hero"), 500)

    def test_grant_silver_stacks(self):
        economy.grant_silver("guild_rpg", "Hero", 100)
        bal = economy.grant_silver("guild_rpg", "Hero", 50)
        self.assertEqual(bal, 150)

    def test_spend_silver_success(self):
        economy.grant_silver("guild_rpg", "Hero", 200)
        self.assertTrue(economy.spend_silver("guild_rpg", "Hero", 150))
        self.assertEqual(economy.get_wallet("guild_rpg", "Hero"), 50)

    def test_spend_silver_insufficient_fails(self):
        economy.grant_silver("guild_rpg", "Hero", 30)
        self.assertFalse(economy.spend_silver("guild_rpg", "Hero", 100))
        self.assertEqual(economy.get_wallet("guild_rpg", "Hero"), 30)

    def test_grant_negative_amount(self):
        """Grant natively writes negative silver — no guard, by design."""
        bal = economy.grant_silver("guild_rpg", "Broke", -50)
        self.assertEqual(bal, -50)


class TestItemCRUD(EconomyDBTestCase):
    def test_add_and_get_item(self):
        economy.add_item("guild_rpg", {
            "item_id": "test_sword",
            "name": "Test Sword",
            "item_type": "weapon",
            "rank_label": "B",
            "besm_points": 8,
            "item_cp": 4,
            "price_class": "permanent",
            "description": "A test weapon.",
        })
        item = economy.get_item("guild_rpg", "test_sword")
        self.assertIsNotNone(item)
        self.assertEqual(item["name"], "Test Sword")
        self.assertEqual(item["rank_label"], "B")

    def test_add_item_upserts_idempotent(self):
        base = {"item_id": "idem_test", "name": "First", "item_cp": 1}
        economy.add_item("guild_rpg", base)
        base["name"] = "Second"
        economy.add_item("guild_rpg", base)
        item = economy.get_item("guild_rpg", "idem_test")
        self.assertEqual(item["name"], "Second")

    def test_get_nonexistent_item(self):
        self.assertIsNone(economy.get_item("guild_rpg", "does_not_exist"))


class TestCatalogOperations(EconomyDBTestCase):
    def test_seed_catalog_has_items(self):
        catalog = economy.list_catalog("guild_rpg")
        self.assertGreaterEqual(len(catalog), 8)

    def test_list_catalog_resolves_prices(self):
        catalog = economy.list_catalog("guild_rpg")
        sword = [i for i in catalog if i["item_id"] == "arming_sword"][0]
        self.assertEqual(economy.compute_price(sword), 400)

    def test_jaxon_d_shelf_has_beast_repellent(self):
        """Beast-Repellent Powder is a documented 5 sp D-Rank Jaxon item."""
        catalog = economy.list_catalog("guild_rpg")
        powder = [i for i in catalog if i["item_id"] == "beast_repellent_powder"][0]
        self.assertEqual(powder["rank_label"], "D")
        self.assertEqual(economy.compute_price(powder), 5)

    def test_jaxon_c_shelf_has_flash_powder(self):
        """Flash-Powder Vial is a documented 20 sp C-Rank Jaxon item."""
        catalog = economy.list_catalog("guild_rpg")
        vial = [i for i in catalog if i["item_id"] == "flash_powder_vial"][0]
        self.assertEqual(vial["rank_label"], "C")
        self.assertEqual(economy.compute_price(vial), 20)

    def test_rank_filter(self):
        d_items = economy.list_catalog("guild_rpg", rank_filter="D")
        self.assertGreaterEqual(len(d_items), 2)
        for item in d_items:
            self.assertTrue(item["rank_label"].startswith("D"))

    def test_catalog_summary_non_empty(self):
        summary = economy.catalog_summary("guild_rpg")
        self.assertIn("Basic Healing Salve", summary)

    def test_catalog_summary_empty_setting(self):
        summary = economy.catalog_summary("empty_realm")
        self.assertIn("No items", summary)

    def test_seed_idempotent(self):
        economy.seed_default_catalog("guild_rpg")
        economy.seed_default_catalog("guild_rpg")
        catalog = economy.list_catalog("guild_rpg")
        ids = [i["item_id"] for i in catalog]
        self.assertEqual(len(ids), len(set(ids)))


class TestBuyItem(EconomyDBTestCase):
    def setUp(self):
        super().setUp()
        economy.seed_default_catalog("guild_rpg")
        economy.grant_silver("guild_rpg", "Buyer", 200)

    def test_buy_consumable_success(self):
        ok, msg = economy.buy_item("guild_rpg", "Buyer", "basic_healing_salve")
        self.assertTrue(ok)
        self.assertEqual(economy.get_wallet("guild_rpg", "Buyer"), 196)
        inv = economy.get_inventory("guild_rpg", "Buyer")
        self.assertEqual(len(inv), 1)

    def test_buy_unknown_item_fails(self):
        ok, msg = economy.buy_item("guild_rpg", "Buyer", "nonexistent")
        self.assertFalse(ok)

    def test_buy_insufficient_funds_fails(self):
        economy.spend_silver("guild_rpg", "Buyer", 195)
        ok, msg = economy.buy_item("guild_rpg", "Buyer", "standard_health_potion")
        self.assertFalse(ok)
        self.assertIn("Insufficient", msg)


class TestInventoryOperations(EconomyDBTestCase):
    def setUp(self):
        super().setUp()
        economy.seed_default_catalog("guild_rpg")

    def test_empty_inventory(self):
        inv = economy.get_inventory("guild_rpg", "Nobody")
        self.assertEqual(len(inv), 0)

    def test_add_item_then_find_in_inventory(self):
        economy.add_to_inventory("guild_rpg", "Hero", "basic_healing_salve", 3)
        inv = economy.get_inventory("guild_rpg", "Hero")
        self.assertEqual(len(inv), 1)
        self.assertEqual(inv[0]["qty"], 3)

    def test_add_same_item_stacks(self):
        economy.add_to_inventory("guild_rpg", "Hero", "basic_healing_salve", 2)
        economy.add_to_inventory("guild_rpg", "Hero", "basic_healing_salve", 1)
        inv = economy.get_inventory("guild_rpg", "Hero")
        self.assertEqual(inv[0]["qty"], 3)

    def test_inventory_summary_shows_items(self):
        economy.add_to_inventory("guild_rpg", "Hero", "energy_draft", 1)
        summary = economy.inventory_summary("guild_rpg", "Hero")
        self.assertIn("Energy Draft", summary)

    def test_inventory_summary_empty(self):
        summary = economy.inventory_summary("guild_rpg", "Nobody")
        self.assertIn("No items", summary)

    def test_add_item_to_inventory_not_in_catalog_still_works(self):
        economy.add_to_inventory("guild_rpg", "Hero", "phantom_mirror", 1)
        inv = economy.get_inventory("guild_rpg", "Hero")
        self.assertEqual(len(inv), 0)


class SceneEffectTestCase(EconomyDBTestCase):
    """Base for scene-effect tests: also points state_manager at the tmp session DB."""

    def setUp(self):
        super().setUp()
        self._sm_patcher = patch.object(state_manager, "DB_PATH", self.tmp_session.name)
        self._sm_patcher.start()
        economy.seed_default_catalog("guild_rpg")

    def tearDown(self):
        self._sm_patcher.stop()
        super().tearDown()


class TestUseItemSceneEffects(SceneEffectTestCase):
    def setUp(self):
        super().setUp()
        economy.add_to_inventory("guild_rpg", "Hero", "beast_repellent_powder", 1)
        economy.add_to_inventory("guild_rpg", "Hero", "flash_powder_vial", 2)

    def test_repel_requires_a_node(self):
        """Scene-effect consumables must be used at a location — not consumed on miss."""
        ok, msg = economy.use_item("guild_rpg", "Hero", "beast_repellent_powder")
        self.assertFalse(ok)
        self.assertIn("location", msg)
        inv = economy.get_inventory("guild_rpg", "Hero")
        powder = [i for i in inv if i["item_id"] == "beast_repellent_powder"][0]
        self.assertEqual(powder["qty"], 1)

    def test_repel_binds_ward_and_consumes(self):
        ok, msg = economy.use_item("guild_rpg", "Hero", "beast_repellent_powder", node_id="node_camp")
        self.assertTrue(ok)
        effects = state_manager.get_scene_effects("chronos_interactive_session", "node_camp")
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["kind"], "repel_animals")
        self.assertEqual(effects[0]["rounds_remaining"], 1)
        inv = economy.get_inventory("guild_rpg", "Hero")
        powder = [i for i in inv if i["item_id"] == "beast_repellent_powder"]
        self.assertFalse(powder)  # consumed down to zero → row deleted

    def test_blind_binds_effect_with_duration(self):
        ok, msg = economy.use_item("guild_rpg", "Hero", "flash_powder_vial", node_id="node_den")
        self.assertTrue(ok)
        effects = state_manager.get_scene_effects("chronos_interactive_session", "node_den")
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["kind"], "blind")
        self.assertEqual(effects[0]["rounds_remaining"], 1)

    def test_reapply_refreshes_instead_of_duplicating(self):
        """Same kind at the same node is an idempotent upsert, not a second row."""
        economy.use_item("guild_rpg", "Hero", "flash_powder_vial", node_id="node_den")
        economy.use_item("guild_rpg", "Hero", "flash_powder_vial", node_id="node_den")
        effects = state_manager.get_scene_effects("chronos_interactive_session", "node_den")
        self.assertEqual(len(effects), 1)

    def test_tick_expires_blind_effect(self):
        economy.use_item("guild_rpg", "Hero", "flash_powder_vial", node_id="node_den")
        expired = state_manager.tick_scene_effects("chronos_interactive_session", "node_den")
        self.assertGreaterEqual(expired, 1)
        effects = state_manager.get_scene_effects("chronos_interactive_session", "node_den")
        self.assertEqual(effects, [])

    def test_get_scene_effects_unscoped_lists_all_nodes(self):
        economy.use_item("guild_rpg", "Hero", "beast_repellent_powder", node_id="node_camp")
        economy.use_item("guild_rpg", "Hero", "flash_powder_vial", node_id="node_den")
        effects = state_manager.get_scene_effects("chronos_interactive_session")
        self.assertEqual(len(effects), 2)


class TestSxm1Economy(EconomyDBTestCase):
    """SxM1 economy is seeded (Gold) alongside Guild RPG on init."""

    def test_sxm1_catalog_has_63_items(self):
        catalog = economy.list_catalog("shota_x_monsters")
        self.assertEqual(len(catalog), 63)

    def test_currency_is_gold(self):
        catalog = economy.list_catalog("shota_x_monsters")
        self.assertTrue(all(i.get("currency") == "gold" for i in catalog))

    def test_confirmed_prices_match_baseline(self):
        catalog = {i["item_id"]: economy.compute_price(i) for i in economy.list_catalog("shota_x_monsters")}
        self.assertEqual(catalog["potion"], 50)
        self.assertEqual(catalog["dodeka_pudding"], 200)
        self.assertEqual(catalog["fairy_revival_potion"], 300)
        self.assertEqual(catalog["smoke_bomb"], 150)

    def test_sellable_and_currency_items_are_priceless(self):
        catalog = economy.list_catalog("shota_x_monsters")
        by_id = {i["item_id"]: i for i in catalog}
        self.assertIsNone(economy.compute_price(by_id["star_medal"]))
        self.assertIsNone(economy.compute_price(by_id["antique_coin"]))
        self.assertIsNone(economy.compute_price(by_id["give_up_challenge"]))

    def test_gold_model_is_internally_consistent(self):
        """50 G/CP base reproduces the 4 confirmed prices exactly."""
        catalog = economy.list_catalog("shota_x_monsters")
        by_id = {i["item_id"]: i for i in catalog}
        self.assertEqual(economy.compute_price(by_id["potion"]), 50 * 1)
        self.assertEqual(economy.compute_price(by_id["dodeka_pudding"]), 50 * 4)
        self.assertEqual(economy.compute_price(by_id["fairy_revival_potion"]), 50 * 3 * 2)
        self.assertEqual(economy.compute_price(by_id["smoke_bomb"]), 50 * 1 * 3)

    def test_sxm1_seed_idempotent(self):
        economy.seed_sxm1_economy()
        economy.seed_sxm1_economy()
        catalog = economy.list_catalog("shota_x_monsters")
        ids = [i["item_id"] for i in catalog]
        self.assertEqual(len(ids), len(set(ids)))

    def test_catalog_summary_shows_gold_unit(self):
        summary = economy.catalog_summary("shota_x_monsters")
        self.assertIn("G", summary)
        self.assertIn("Potion", summary)

    def test_guild_rpg_still_silver_after_sxm1_seed(self):
        """SxM1 seeding must not perturb the Guild RPG silver catalog."""
        catalog = economy.list_catalog("guild_rpg")
        self.assertTrue(all(i.get("currency", "silver") == "silver" for i in catalog))
        self.assertGreaterEqual(len(catalog), 8)


if __name__ == "__main__":
    unittest.main()
