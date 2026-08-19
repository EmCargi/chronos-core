"""tests/test_besm_catalog.py — BESM canon catalog as reusable engine assets.

Ground truth is the source-book ledger `besm-weapons-armor-gear-reference.md`
compiled by `scripts/extract_besm_catalog.py` into `engine/besm_catalog.py`:
  * Catalog contract (220 items across 6 categories, unique slugs)
  * Bench parity against the BESM cost tables + Fibonacci price engine
  * Silver-bracket rank ladder (0→D, >800 sp→S, SS never emitted)
  * Idempotent, filter-driven, non-destructive seeding into a setting's items
"""

import os
import re
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))          # chronos-core/

import engine.economy as economy
import engine.besm_catalog as besm_cat

SLUG_RE = re.compile(r"^besm_[a-z0-9_]+$")


class TestCatalogContract(unittest.TestCase):
    def test_total_rows_and_unique_ids(self):
        ids = [r["item_id"] for r in besm_cat.BESM_CATALOG]
        self.assertEqual(len(ids), 220)
        self.assertEqual(len(set(ids)), 220)

    def test_per_item_type_distribution(self):
        counts = {}
        for r in besm_cat.BESM_CATALOG:
            counts[r["item_type"]] = counts.get(r["item_type"], 0) + 1
        self.assertEqual(counts["weapon"], 105)
        self.assertEqual(counts["armor"], 37)   # 29 matrix + 8 suits
        self.assertEqual(counts["shield"], 25)
        self.assertEqual(counts["accessory"], 11)
        self.assertEqual(counts["artifact"], 31)
        self.assertEqual(counts["vehicle"], 11)

    def test_all_slugs_follow_contract(self):
        for r in besm_cat.BESM_CATALOG:
            self.assertTrue(SLUG_RE.match(r["item_id"]), r["item_id"])
            self.assertNotIn("__", r["item_id"])

    def test_all_rows_have_shape(self):
        for r in besm_cat.BESM_CATALOG:
            self.assertIn(r["item_type"], {"weapon", "armor", "shield", "accessory", "artifact", "vehicle"})
            self.assertIn(r["price_class"], {"permanent"})
            self.assertIsNone(r["price_silver"])
            self.assertGreaterEqual(r["item_cp"], 0)
            self.assertTrue(r["name"])

    def test_sources_present_for_every_id(self):
        for r in besm_cat.BESM_CATALOG:
            self.assertIn(r["item_id"], besm_cat.SOURCES)

    def test_bench_parity_with_ledger(self):
        rows = {r["item_id"]: r for r in besm_cat.BESM_CATALOG}
        longsword = rows["besm_archaic_melee_longsword"]
        self.assertEqual((longsword["besm_points"], longsword["item_cp"]), (6, 3))
        self.assertEqual(economy.fibonacci_price(longsword["item_cp"]), 400)
        full_plate = rows["besm_archaic_armor_full_plate"]
        self.assertEqual((full_plate["besm_points"], full_plate["item_cp"]), (8, 4))
        self.assertEqual(economy.fibonacci_price(full_plate["item_cp"]), 700)
        heavy = rows["besm_modern_armor_heavy_body_armour"]
        self.assertEqual((heavy["besm_points"], heavy["item_cp"]), (12, 6))
        self.assertEqual(economy.fibonacci_price(heavy["item_cp"]), 2000)
        buckler = rows["besm_universal_buckler_metal"]
        self.assertEqual((buckler["besm_points"], buckler["item_cp"]), (0, 3))
        self.assertEqual(economy.fibonacci_price(buckler["item_cp"]), 400)

    def test_weapon_effect_metadata(self):
        rows = {r["item_id"]: r for r in besm_cat.BESM_CATALOG}
        sw = rows["besm_modern_ranged_pistol_heavy"]
        self.assertEqual(sw["effect_json"]["kind"], "weapon")
        self.assertEqual(sw["effect_json"]["level"], 7)
        self.assertEqual(sw["effect_json"]["effective_level"], 4)
        self.assertEqual(sw["effect_json"]["enhancements"], ["Range 3"])

    def test_armor_effect_metadata(self):
        rows = {r["item_id"]: r for r in besm_cat.BESM_CATALOG}
        plate = rows["besm_archaic_armor_full_plate"]
        self.assertEqual(plate["effect_json"]["kind"], "armor")
        self.assertEqual(plate["effect_json"]["armor_rating"], 20)


class TestRankForCp(unittest.TestCase):
    def test_zero_cp_is_d(self):
        self.assertEqual(besm_cat.rank_for_cp(0), "D")

    def test_ladder_bench(self):
        self.assertEqual(besm_cat.rank_for_cp(1), "B")    # 100 sp
        self.assertEqual(besm_cat.rank_for_cp(3), "A")    # 400 sp
        self.assertEqual(besm_cat.rank_for_cp(4), "A")    # 700 sp
        self.assertEqual(besm_cat.rank_for_cp(5), "S")    # 1200 sp
        self.assertEqual(besm_cat.rank_for_cp(55), "S")   # mass-driver territory

    def test_never_emits_ss(self):
        for cp in range(0, 60):
            self.assertNotEqual(besm_cat.rank_for_cp(cp), "SS")


class BESMCatalogDBTestCase(unittest.TestCase):
    """tmp DBs, fresh init per test — mirrors test_economy.py."""

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
        economy.init_economy_db()   # also seeds the 10 authored rows

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        os.unlink(self.tmp_roster.name)
        os.unlink(self.tmp_session.name)


class TestSeedBesmCatalog(BESMCatalogDBTestCase):
    def test_matches_helper_counts_and_spreads(self):
        count, spread = besm_cat.besm_catalog_matches(eras=["archaic"])
        self.assertGreater(count, 0)
        self.assertEqual(sum(spread.values()), count)

    def test_matches_helper_respects_cap(self):
        count, spread = besm_cat.besm_catalog_matches(eras=["archaic"], price_cap_sp=800)
        self.assertGreater(count, 0)
        self.assertLess(count, len([r for r in besm_cat.BESM_CATALOG if r["era"] == "archaic"]))

    def test_matches_helper_no_filters_is_full_canon(self):
        count, _ = besm_cat.besm_catalog_matches()
        self.assertEqual(count, 220)

    def test_matches_helper_none_match(self):
        count, spread = besm_cat.besm_catalog_matches(eras=["nope"])
        self.assertEqual(count, 0)
        self.assertEqual(spread, {})

    def test_archaic_seed_populates_and_ranks(self):
        n = besm_cat.seed_besm_catalog("guild_rpg", eras=["archaic"])
        self.assertGreater(n, 0)
        catalog = economy.list_catalog("guild_rpg")
        besm_items = [i for i in catalog if i["item_id"].startswith("besm_")]
        self.assertGreaterEqual(len(besm_items), n)
        for item in besm_items:
            self.assertIn(item["rank_label"], {"D", "C", "B", "A", "S"})

    def test_price_cap_excludes_expensive(self):
        n = besm_cat.seed_besm_catalog("realm_b", eras=["archaic"], price_cap_sp=800)
        catalog = economy.list_catalog("realm_b")
        prices = [i["price_silver"] for i in catalog]
        self.assertTrue(all(p is not None and p <= 800 for p in prices))
        self.assertGreater(n, 0)
        # Some archaic siege weapon is beyond the cap and must be absent.
        self.assertNotIn("besm_archaic_siege_catapult_large", [i["item_id"] for i in catalog])

    def test_idempotent_reruns(self):
        besm_cat.seed_besm_catalog("guild_rpg", eras=["archaic"])
        first = len(economy.list_catalog("guild_rpg"))
        besm_cat.seed_besm_catalog("guild_rpg", eras=["archaic"])
        second = len(economy.list_catalog("guild_rpg"))
        self.assertEqual(first, second)

    def test_existing_authored_rows_untouched(self):
        besm_cat.seed_besm_catalog("guild_rpg", eras=["archaic"])
        catalog = economy.list_catalog("guild_rpg")
        ids = [i["item_id"] for i in catalog]
        sword = [i for i in catalog if i["item_id"] == "arming_sword"][0]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(economy.compute_price(sword), 400)
        self.assertEqual(len(economy.get_inventory("guild_rpg", "Nobody")), 0)

    def test_categories_filter(self):
        n = besm_cat.seed_besm_catalog("realm_b", eras=["archaic"], categories=["melee"])
        catalog = economy.list_catalog("realm_b")
        self.assertTrue(all(i["item_id"].startswith("besm_archaic_melee_") for i in catalog))
        self.assertGreater(n, 0)

    def test_item_types_filter(self):
        besm_cat.seed_besm_catalog("realm_b", item_types=["vehicle"])
        catalog = economy.list_catalog("realm_b")
        self.assertTrue(all(i["item_type"] == "vehicle" for i in catalog))
        self.assertEqual(len(catalog), 11)

    def test_setting_isolation(self):
        besm_cat.seed_besm_catalog("realm_b", eras=["archaic"])
        guild = economy.list_catalog("guild_rpg")
        self.assertFalse(any(i["item_id"].startswith("besm_") for i in guild))
        realm = economy.list_catalog("realm_b")
        self.assertTrue(any(i["item_id"].startswith("besm_") for i in realm))

    def test_persisted_effect_json_carries_provenance(self):
        besm_cat.seed_besm_catalog("guild_rpg", eras=["archaic"])
        item = economy.get_item("guild_rpg", "besm_archaic_melee_longsword")
        self.assertIsNotNone(item)
        effect = item["effect"]
        self.assertEqual(effect.get("era"), "archaic")
        self.assertEqual(effect.get("category"), "melee")
        self.assertEqual(effect.get("kind"), "weapon")

    def test_summary_non_empty(self):
        self.assertIn("220 items", besm_cat.besm_catalog_summary())


if __name__ == "__main__":
    unittest.main()