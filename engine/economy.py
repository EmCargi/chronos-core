import os
import re
import json
import uuid
import logging
import sqlite3
from datetime import datetime

logger = logging.getLogger("ChronosCore.Economy")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ROSTER_PATH = os.path.join(DATA_DIR, "guild_rpg_roster.db")
SESSION_PATH = os.path.join(DATA_DIR, "chronos_session.db")
SESSION_SESSION_ID = "chronos_interactive_session"

# CP-11 Option A: economy writes target the SHARED canonical roster DB by default
# (both TUI and web mutate the same game state). Tests redirect via
# set_active_roster_path() to a throwaway file so the live roster is never touched.
ACTIVE_ROSTER_PATH = ROSTER_PATH

# Quest-economy silver brackets keyed by rank tier.
RANK_BRACKETS = {
    "D": (3, 10),
    "C": (15, 40),
    "B": (50, 200),
    "A": (300, 800),
    "S": (None, None),
    "SS": (None, None),
}

# Idempotent seed catalog: Jaxon the Alchemist's shop (Guild RPG economy
# doc prices) plus Rosivelle's permanent gear as reference permanents.
# NOTE: heal / ep / cure act on vitals; repel_animals / blind bind a scene
# effect to the active node (see use_item). All five kinds are runnable.
SEED_CATALOG = [
    {
        "item_id": "basic_healing_salve",
        "name": "Basic Healing Salve",
        "item_type": "consumable",
        "rank_label": "D",
        "besm_points": 2,
        "item_cp": 1,
        "price_class": "consumable",
        "price_silver": 4,
        "effect_json": {"kind": "heal", "level": 1, "hp": 5},
        "description": "A cheap D-Rank salve. Healing Level 1: restores 5 HP."
    },
    {
        "item_id": "energy_draft",
        "name": "Energy Draft",
        "item_type": "consumable",
        "rank_label": "D",
        "besm_points": 2,
        "item_cp": 1,
        "price_class": "consumable",
        "price_silver": 7,
        "effect_json": {"kind": "ep", "level": 1, "ep": 5},
        "description": "A D-Rank pick-me-up. Restores a small amount of EP."
    },
    {
        "item_id": "beast_repellent_powder",
        "name": "Beast-Repellent Powder",
        "item_type": "consumable",
        "rank_label": "D",
        "besm_points": 2,
        "item_cp": 1,
        "price_class": "consumable",
        "price_silver": 5,
        "effect_json": {"kind": "repel_animals", "level": 1, "area": "campsite"},
        "description": "A D-Rank pungent powder that keeps wild, non-magical animals away from a campsite."
    },
    {
        "item_id": "standard_health_potion",
        "name": "Standard Health Potion",
        "item_type": "consumable",
        "rank_label": "C",
        "besm_points": 6,
        "item_cp": 3,
        "price_class": "consumable",
        "price_silver": 25,
        "effect_json": {"kind": "heal", "level": 3, "hp": 15},
        "description": "A C-Rank tactical potion. Healing Level 3: restores 15 HP."
    },
    {
        "item_id": "standard_antidote",
        "name": "Standard Antidote",
        "item_type": "consumable",
        "rank_label": "C",
        "besm_points": 6,
        "item_cp": 3,
        "price_class": "consumable",
        "price_silver": 30,
        "effect_json": {"kind": "cure", "level": 1, "status": "poison"},
        "description": "A C-Rank antidote for common monster venom."
    },
    {
        "item_id": "flash_powder_vial",
        "name": "Flash-Powder Vial",
        "item_type": "consumable",
        "rank_label": "C",
        "besm_points": 2,
        "item_cp": 1,
        "price_class": "consumable",
        "price_silver": 20,
        "effect_json": {"kind": "blind", "level": 1, "targets": "small_monster_group", "duration_rounds": 1},
        "description": "A C-Rank tactical vial mimicking Weapon (Flare) Level 1: a blinding flash that staggers a small monster group."
    },
    {
        "item_id": "arming_sword",
        "name": "Arming Sword",
        "item_type": "weapon",
        "rank_label": "C",
        "besm_points": 6,
        "item_cp": 3,
        "price_class": "permanent",
        "price_silver": None,
        "effect_json": {},
        "description": "A one-handed longsword (Weapon Level 3)."
    },
    {
        "item_id": "medium_round_shield",
        "name": "Medium Round Shield",
        "item_type": "armor",
        "rank_label": "B",
        "besm_points": 8,
        "item_cp": 4,
        "price_class": "permanent",
        "price_silver": None,
        "effect_json": {"kind": "armor", "armor_rating": 20, "localised": True},
        "description": "A standard metal shield, Localised Armour Rating 20."
    },
    {
        "item_id": "full_plate_armour",
        "name": "Full Plate Armour",
        "item_type": "armor",
        "rank_label": "B",
        "besm_points": 8,
        "item_cp": 4,
        "price_class": "permanent",
        "price_silver": None,
        "effect_json": {"kind": "armor", "armor_rating": 20},
        "description": "Standard full plate, Armour Rating 20."
    },
    {
        "item_id": "high_quality_full_plate",
        "name": "High-Quality Full Plate",
        "item_type": "armor",
        "rank_label": "A",
        "besm_points": 10,
        "item_cp": 5,
        "price_class": "permanent",
        "price_silver": None,
        "effect_json": {"kind": "armor", "armor_rating": 20, "unique": True},
        "description": "Rosivelle's bespoke silver-and-pink plate (+2 Unique). Armour Rating 20."
    },
]

# SxM1 (shota_x_monsters) economy seed: all 63 items with BESM-grounded Gold prices.
from .sxm1_economy_catalog import SEED_CATALOG_SXM1, GOLD_PER_CP
from .models import ChestLootSchema, ChestEffect

def set_active_roster_path(path: str) -> None:
    """Redirect all subsequent economy DB access to `path` (tests / isolated web).

    Reassigns the module-level ACTIVE_ROSTER_PATH global so every function that
    opens the economy DB (get_economy_connection, ...) targets the new file.
    Production default is the SHARED canonical roster DB (CP-11 Option A);
    tests call this with a throwaway path to never touch the live roster.
    """
    global ACTIVE_ROSTER_PATH
    ACTIVE_ROSTER_PATH = path
    logger.info(f"Active economy/roster DB redirected to: {path}")


def get_economy_connection() -> sqlite3.Connection:
    """Safely connects to the canonical roster DB (source of truth for economy)."""
    os.makedirs(os.path.dirname(ACTIVE_ROSTER_PATH), exist_ok=True)
    conn = sqlite3.connect(ACTIVE_ROSTER_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_economy_db() -> None:
    """Creates the economy tables (idempotent) and seeds the default catalog."""
    with get_economy_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS items (
                setting_id     TEXT NOT NULL,
                item_id        TEXT NOT NULL,
                name           TEXT NOT NULL,
                item_type      TEXT NOT NULL,
                rank_label     TEXT NOT NULL,
                besm_points    INTEGER NOT NULL,
                item_cp        INTEGER NOT NULL,
                price_class    TEXT NOT NULL,
                price_silver   INTEGER,
                effect_json    TEXT NOT NULL DEFAULT '{}',
                description    TEXT NOT NULL DEFAULT '',
                currency       TEXT NOT NULL DEFAULT 'silver',
                PRIMARY KEY (setting_id, item_id)
            )
        """)
        # Migration for existing roster DBs that predate the currency column.
        try:
            conn.execute("ALTER TABLE items ADD COLUMN currency TEXT NOT NULL DEFAULT 'silver'")
        except sqlite3.OperationalError:
            pass  # column already present
        # Migration for the generative chest-loot flag (CP: loot_only — hides
        # generated rows from /shop while keeping them in player inventories).
        try:
            conn.execute("ALTER TABLE items ADD COLUMN loot_only INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column already present
        conn.execute("""
            CREATE TABLE IF NOT EXISTS character_wallets (
                setting_id      TEXT NOT NULL,
                character_name  TEXT NOT NULL,
                silver          INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (setting_id, character_name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS character_items (
                setting_id      TEXT NOT NULL,
                character_name  TEXT NOT NULL,
                item_id         TEXT NOT NULL,
                qty             INTEGER NOT NULL DEFAULT 1,
                acquired_at     TEXT NOT NULL,
                PRIMARY KEY (setting_id, character_name, item_id)
            )
        """)
    seed_default_catalog()
    seed_sxm1_economy()
    logger.info("Economy database initialized (items, wallets, inventory).")

def seed_default_catalog(setting_id: str = "guild_rpg", currency: str = "silver",
                         catalog: list | None = None) -> None:
    """Inserts the seed catalog for a setting (idempotent)."""
    if catalog is None:
        catalog = SEED_CATALOG
    with get_economy_connection() as conn:
        for item in catalog:
            conn.execute("""
                INSERT OR IGNORE INTO items (
                    setting_id, item_id, name, item_type, rank_label,
                    besm_points, item_cp, price_class, price_silver,
                    effect_json, description, currency
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                setting_id,
                item["item_id"],
                item["name"],
                item["item_type"],
                item["rank_label"],
                item["besm_points"],
                item["item_cp"],
                item["price_class"],
                item["price_silver"],
                json.dumps(item.get("effect_json", {})),
                item.get("description", ""),
                currency
            ))
    logger.info(f"Seeded item catalog for setting '{setting_id}' (currency={currency}).")

def seed_sxm1_economy() -> None:
    """Seeds the shota_x_monsters economy (BESM-grounded Gold prices)."""
    seed_default_catalog("shota_x_monsters", currency="gold", catalog=SEED_CATALOG_SXM1)

def fibonacci_price(item_cp: int) -> int:
    """Fibonacci silver economy: 1 CP = 100 sp, sequence 100,100,200,300,500...
    Price = sum of the first `item_cp` terms."""
    if item_cp <= 0:
        return 0
    seq = [100, 100]
    while len(seq) < item_cp:
        seq.append(seq[-1] + seq[-2])
    return sum(seq[:item_cp])

def bracket_for_rank(rank_label: str) -> tuple:
    """Returns the (lo, hi) silver bracket for a rank tier, or (None, None)."""
    return RANK_BRACKETS.get(rank_label.upper().split(" ")[0], (None, None))

def compute_price(item: dict) -> int | None:
    """Resolves an item's silver price. Permanents use the Fibonacci curve;
    consumables use their stored quest-bracket price; priceless items return None."""
    if item["price_class"] == "permanent":
        return fibonacci_price(item["item_cp"])
    if item["price_class"] == "priceless":
        return None
    return item.get("price_silver")

def add_item(setting_id: str, item: dict, currency: str = "silver") -> None:
    """Upserts a custom item into a setting's catalog."""
    with get_economy_connection() as conn:
        conn.execute("""
            INSERT INTO items (
                setting_id, item_id, name, item_type, rank_label,
                besm_points, item_cp, price_class, price_silver,
                effect_json, description, currency
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(setting_id, item_id) DO UPDATE SET
                name = excluded.name,
                item_type = excluded.item_type,
                rank_label = excluded.rank_label,
                besm_points = excluded.besm_points,
                item_cp = excluded.item_cp,
                price_class = excluded.price_class,
                price_silver = excluded.price_silver,
                effect_json = excluded.effect_json,
                description = excluded.description,
                currency = excluded.currency
        """, (
            setting_id,
            item["item_id"],
            item.get("name", item["item_id"]),
            item.get("item_type", "misc"),
            item.get("rank_label", "D"),
            item.get("besm_points", 0),
            item.get("item_cp", 0),
            item.get("price_class", "permanent"),
            item.get("price_silver"),
            json.dumps(item.get("effect_json", {})),
            item.get("description", ""),
            currency
        ))
    logger.info(f"Upserted item '{item['item_id']}' for setting '{setting_id}'.")


def _unit(currency: str) -> str:
    """Currency symbol for display: Gold (SxM1) vs Silver (Guild RPG)."""
    return "G" if currency == "gold" else "sp"

def get_item(setting_id: str, item_id: str) -> dict | None:
    """Returns a single catalog item as a dict, or None."""
    with get_economy_connection() as conn:
        row = conn.execute(
            "SELECT * FROM items WHERE setting_id = ? AND item_id = ?", (setting_id, item_id)
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["effect"] = json.loads(item.get("effect_json") or "{}")
        return item

def list_catalog(setting_id: str, rank_filter: str | None = None) -> list:
    """Lists a setting's item catalog, optionally filtered by rank tier.

    Excludes generative `loot_only` rows (CP: loot_only) so /shop stays canonical;
    get_item / get_inventory remain unfiltered so players keep their own loot."""
    with get_economy_connection() as conn:
        base = "SELECT * FROM items WHERE setting_id = ? AND COALESCE(loot_only, 0) = 0"
        if rank_filter:
            rows = conn.execute(
                base + " AND rank_label LIKE ? ORDER BY rank_label, name",
                (setting_id, f"%{rank_filter.upper()}%")
            ).fetchall()
        else:
            rows = conn.execute(
                base + " ORDER BY rank_label, name", (setting_id,)
            ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            item["price_silver"] = compute_price(item)
            result.append(item)
        return result

def catalog_summary(setting_id: str, rank_filter: str | None = None) -> str:
    """Human-readable shop listing for the TUI."""
    items = list_catalog(setting_id, rank_filter)
    if not items:
        return f"No items in the '{setting_id}' catalog."
    lines = []
    for i in items:
        unit = _unit(i.get("currency", "silver"))
        price = f"{i['price_silver']} {unit}" if i["price_silver"] is not None else "priceless"
        lines.append(
            f"  • [bold white]{i['name']}[/bold white] [{i['rank_label']}] "
            f"({i['item_type']}, {i['item_cp']} CP) — {price} [[dim]{i['item_id']}[/dim]]"
        )
    return "\n".join(lines)

def get_wallet(setting_id: str, character_name: str) -> int:
    """Returns the character's silver balance (0 if unregistered)."""
    with get_economy_connection() as conn:
        row = conn.execute(
            "SELECT silver FROM character_wallets WHERE setting_id = ? AND character_name = ?",
            (setting_id, character_name)
        ).fetchone()
        return row["silver"] if row else 0

def grant_silver(setting_id: str, character_name: str, amount: int) -> int:
    """Adds silver to a character's wallet. Returns the new balance."""
    with get_economy_connection() as conn:
        conn.execute("""
            INSERT INTO character_wallets (setting_id, character_name, silver)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_id, character_name) DO UPDATE SET
                silver = silver + excluded.silver
        """, (setting_id, character_name, amount))
        balance = conn.execute(
            "SELECT silver FROM character_wallets WHERE setting_id = ? AND character_name = ?",
            (setting_id, character_name)
        ).fetchone()["silver"]
    logger.info(f"Granted {amount} sp to [{setting_id}] {character_name}. New balance: {balance} sp.")
    return balance

def spend_silver(setting_id: str, character_name: str, amount: int) -> bool:
    """Deducts silver if affordable. Returns True on success."""
    with get_economy_connection() as conn:
        row = conn.execute(
            "SELECT silver FROM character_wallets WHERE setting_id = ? AND character_name = ?",
            (setting_id, character_name)
        ).fetchone()
        balance = row["silver"] if row else 0
        if balance < amount:
            return False
        conn.execute(
            "UPDATE character_wallets SET silver = silver - ? WHERE setting_id = ? AND character_name = ?",
            (amount, setting_id, character_name)
        )
    return True

def add_to_inventory(setting_id: str, character_name: str, item_id: str, qty: int = 1) -> None:
    """Idempotently adds a quantity of an item to a character's inventory."""
    with get_economy_connection() as conn:
        conn.execute("""
            INSERT INTO character_items (setting_id, character_name, item_id, qty, acquired_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(setting_id, character_name, item_id) DO UPDATE SET
                qty = qty + excluded.qty
        """, (setting_id, character_name, item_id, qty, datetime.now().isoformat()))
    logger.info(f"Added {qty}x '{item_id}' to [{setting_id}] {character_name}.")

def buy_item(setting_id: str, character_name: str, item_id: str, qty: int = 1) -> tuple:
    """Attempts to purchase qty of an item. Returns (ok, message)."""
    item = get_item(setting_id, item_id)
    if not item:
        return False, f"Unknown item '{item_id}' in setting '{setting_id}'."
    price = compute_price(item)
    if price is None:
        return False, f"{item['name']} is priceless and cannot be bought."
    total = price * qty
    unit = _unit(item.get("currency", "silver"))
    if not spend_silver(setting_id, character_name, total):
        balance = get_wallet(setting_id, character_name)
        return False, f"Insufficient funds: {total} {unit} needed, wallet has {balance} {unit}."
    add_to_inventory(setting_id, character_name, item_id, qty)
    logger.info(f"[{setting_id}] {character_name} bought {qty}x {item['name']} for {total} {unit}.")
    return True, f"Bought {qty}x {item['name']} for {total} {unit}. Wallet now {get_wallet(setting_id, character_name)} {unit}."

def get_inventory(setting_id: str, character_name: str) -> list:
    """Returns the character's owned items joined with catalog details."""
    with get_economy_connection() as conn:
        rows = conn.execute("""
            SELECT ci.item_id, ci.qty, i.name, i.item_type, i.rank_label,
                   i.price_class, i.price_silver, i.effect_json
            FROM character_items ci
            JOIN items i ON i.setting_id = ci.setting_id AND i.item_id = ci.item_id
            WHERE ci.setting_id = ? AND ci.character_name = ?
            ORDER BY i.rank_label, i.name
        """, (setting_id, character_name)).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            item["price_silver"] = compute_price(item)
            item["effect"] = json.loads(item.get("effect_json") or "{}")
            result.append(item)
        return result

def inventory_summary(setting_id: str, character_name: str) -> str:
    """Human-readable inventory listing for the TUI."""
    items = get_inventory(setting_id, character_name)
    if not items:
        return f"  [italic dim]No items in {character_name}'s inventory.[/italic dim]"
    lines = []
    for i in items:
        lines.append(
            f"  • [bold white]{i['name']}[/bold white] [{i['rank_label']}] "
            f"({i['item_type']}) x{i['qty']} [[dim]{i['item_id']}[/dim]]"
        )
    return "\n".join(lines)

def use_item(setting_id: str, character_name: str, item_id: str,
             node_id: str | None = None) -> tuple:
    """Consumes a consumable item, applying its effect to the character's vitals
    or to the current scene. Returns (ok, message).

    Scene-effect consumables (repel_animals, blind) require a node_id — they
    attach a transient effect to the location whose encounter they alter."""
    item = get_item(setting_id, item_id)
    if not item:
        return False, f"Unknown item '{item_id}' in setting '{setting_id}'."
    if item["item_type"] != "consumable":
        return False, f"{item['name']} is not a consumable and cannot be used."

    effect = item.get("effect") or {}
    kind = effect.get("kind")
    if kind not in ("heal", "ep", "cure", "repel_animals", "blind"):
        return False, f"{item['name']} has no usable effect."

    if kind in ("repel_animals", "blind") and not node_id:
        return False, f"{item['name']} needs an active location to take effect."

    # Check the character actually owns one.
    with get_economy_connection() as conn:
        row = conn.execute(
            "SELECT qty FROM character_items WHERE setting_id = ? AND character_name = ? AND item_id = ?",
            (setting_id, character_name, item_id)
        ).fetchone()
        if not row or row["qty"] < 1:
            return False, f"{character_name} does not own {item['name']}."

    # Apply effect against session vitals.
    delta = 0
    if kind == "heal":
        delta = effect.get("hp", 0)
    elif kind == "ep":
        delta = effect.get("ep", 0)
    elif kind == "cure":
        pass  # status-clearing effects have no numeric vitals change
    elif kind in ("repel_animals", "blind"):
        # Scene effect: bind to the active node so the encounter layer knows.
        from .state_manager import apply_scene_effect
        rounds = effect.get("duration_rounds", 1)
        apply_scene_effect(SESSION_SESSION_ID, node_id, kind,
                           item.get("description", ""), rounds)

    if delta:
        try:
            import sqlite3 as _sq
            with _sq.connect(SESSION_PATH) as sess:
                sess.row_factory = _sq.Row
                vital = sess.execute(
                    "SELECT current_hp, current_ep FROM character_vitals WHERE session_id = ? AND name = ?",
                    (SESSION_SESSION_ID, character_name)
                ).fetchone()
                if vital is not None:
                    new_hp = vital["current_hp"] + (delta if kind == "heal" else 0)
                    new_ep = vital["current_ep"] + (delta if kind == "ep" else 0)
                    sess.execute(
                        "UPDATE character_vitals SET current_hp = ?, current_ep = ? WHERE session_id = ? AND name = ?",
                        (new_hp, new_ep, SESSION_SESSION_ID, character_name)
                    )
        except Exception as e:
            logger.error(f"Failed to apply vitals for '{item_id}': {e}")

    # Decrement quantity.
    with get_economy_connection() as conn:
        conn.execute(
            "UPDATE character_items SET qty = qty - 1 WHERE setting_id = ? AND character_name = ? AND item_id = ?",
            (setting_id, character_name, item_id)
        )
        conn.execute(
            "DELETE FROM character_items WHERE setting_id = ? AND character_name = ? AND item_id = ? AND qty <= 0",
            (setting_id, character_name, item_id)
        )
    logger.info(f"[{setting_id}] {character_name} used {item['name']}.")
    if kind == "repel_animals":
        return True, f"Used {item['name']}. Warded {node_id} — non-magical animals will avoid the area."
    if kind == "blind":
        return True, f"Used {item['name']}. Blinded the target group for {effect.get('duration_rounds', 1)} round(s)."
    return True, f"Used {item['name']}. ({'Restored ' + str(delta) + ' vitals.' if delta else 'Effect applied.'})"

# ── Generative chest loot (The Pydantic Weaver) ────────────────────────────
# The LLM emits ONLY name/item_type/description/item_cp/effect_json inside a
# [LOOT PAYLOAD] block. Python fills the schema gaps, prices with the existing
# curves, and deposits into the canonical items + character_items tables in a
# single transaction (CP-2). Zero LLM math.

CHEST_TIER_CAPS = {"wooden": 3, "gold": 6, "platinum": 10}
CHEST_STRATUM_CP_STEP = 2
GOLD_CATEGORY_MULT = {"consumable": 1, "gear": 2, "valuable": 1}

def loot_cap_for(chest_tier: str, stratum: int = 1) -> int:
    """CP cap for a chest: tier base +2 CP per stratum past 1 (Arbiter ruling #1)."""
    base = CHEST_TIER_CAPS.get(chest_tier, CHEST_TIER_CAPS["wooden"])
    return base + CHEST_STRATUM_CP_STEP * max(0, (stratum or 1) - 1)

def gold_price(item_cp: int, category_mult: float = 1) -> int:
    """SxM1 Gold model (validated peddler baseline): 50 * CP * category_mult."""
    return GOLD_PER_CP * item_cp * category_mult

def currency_for_setting(setting_id: str) -> str:
    """Per-setting currency: shota_x_monsters runs Gold, everything else silver."""
    return "gold" if setting_id == "shota_x_monsters" else "silver"

def rank_label_for_cp(item_cp: int) -> str:
    """CP → quest-rank ladder for generated items (CP-4: distinct from
    besm_catalog.rank_for_cp, which is silver-price-based)."""
    if item_cp <= 2:
        return "D"
    if item_cp <= 4:
        return "C"
    if item_cp <= 7:
        return "B"
    if item_cp <= 12:
        return "A"
    return "S"

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug[:40] or "mystery"

def _runnable_effect(effect) -> bool:
    """Cross-rule: a consumable effect must carry its required sub-fields so the
    item is genuinely actionable (no `{"kind":"heal"}` zero-heal rows)."""
    if not isinstance(effect, ChestEffect):
        return False
    kind = effect.kind
    if kind == "heal":
        return bool(effect.hp)
    if kind == "ep":
        return bool(effect.ep)
    if kind == "cure":
        return bool(effect.status)
    if kind == "repel_animals":
        return bool(effect.area)
    if kind == "blind":
        return bool(effect.targets)
    return False

def parse_chest_loot(raw_text: str, chest_tier: str, stratum: int = 1) -> ChestLootSchema:
    """Regex-extract [LOOT PAYLOAD] → Pydantic validate → cap re-check + cross-rules.

    Raises ValueError on any violation so the caller can fall back to a filler."""
    m = re.search(r"\[LOOT PAYLOAD\](.*?)\[/LOOT PAYLOAD\]", raw_text, re.S | re.I)
    if not m:
        raise ValueError("no [LOOT PAYLOAD] block in response")
    payload = m.group(1).strip().strip("`").strip()
    item = ChestLootSchema.model_validate_json(payload)
    cap = loot_cap_for(chest_tier, stratum)
    if not (1 <= item.item_cp <= cap):
        raise ValueError(f"item_cp {item.item_cp} outside chest cap 1..{cap}")
    if item.item_type == "consumable":
        if not _runnable_effect(item.effect_json):
            raise ValueError("consumable must carry a runnable effect with its sub-fields")
    else:
        if isinstance(item.effect_json, ChestEffect):
            raise ValueError("gear/valuable items cannot carry a consumable effect")
    return item

def deposit_chest_loot(setting_id: str, character_name: str, item: ChestLootSchema,
                       stratum: int = 1) -> str:
    """Fills the schema gaps, prices, and commits the item + inventory deposit
    in ONE transaction (CP-2) so no orphan item row survives a failed deposit."""
    slug = _slugify(item.name)
    item_id = f"chest_{slug}_{uuid.uuid4().hex[:4]}"
    rank = rank_label_for_cp(item.item_cp)
    currency = currency_for_setting(setting_id)

    if item.item_type == "consumable":
        price_class = "consumable"
        if currency == "gold":
            price = gold_price(item.item_cp, GOLD_CATEGORY_MULT["consumable"])
        else:
            lo, hi = bracket_for_rank(rank)
            price = (lo + hi) // 2 if lo is not None else 25
        effect_json = item.effect_json.model_dump() if isinstance(item.effect_json, ChestEffect) else {}
    elif item.item_type == "gear":
        price_class = "permanent"
        price = (gold_price(item.item_cp, GOLD_CATEGORY_MULT["gear"])
                 if currency == "gold" else fibonacci_price(item.item_cp))
        effect_json = {}
    else:
        price_class = "priceless"
        price = None
        effect_json = {}

    with get_economy_connection() as conn:
        conn.execute("""
            INSERT INTO items (
                setting_id, item_id, name, item_type, rank_label,
                besm_points, item_cp, price_class, price_silver,
                effect_json, description, currency, loot_only
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(setting_id, item_id) DO UPDATE SET
                name = excluded.name,
                item_type = excluded.item_type,
                rank_label = excluded.rank_label,
                besm_points = excluded.besm_points,
                item_cp = excluded.item_cp,
                price_class = excluded.price_class,
                price_silver = excluded.price_silver,
                effect_json = excluded.effect_json,
                description = excluded.description,
                currency = excluded.currency,
                loot_only = excluded.loot_only
        """, (
            setting_id, item_id, item.name, item.item_type, rank,
            item.item_cp * 2, item.item_cp, price_class, price,
            json.dumps(effect_json), item.description, currency
        ))
        conn.execute("""
            INSERT INTO character_items (setting_id, character_name, item_id, qty, acquired_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(setting_id, character_name, item_id) DO UPDATE SET
                qty = qty + excluded.qty
        """, (setting_id, character_name, item_id, datetime.now().isoformat()))
    logger.info(f"Chest loot '{item.name}' ({item_id}) deposited to [{setting_id}] {character_name}.")
    return item_id

def generate_chest_loot(setting_id: str, character_name: str, chest_tier: str,
                        stratum: int = 1, raw_text: str = "") -> str:
    """Full pipeline: parse the LLM's [LOOT PAYLOAD] and deposit the item."""
    item = parse_chest_loot(raw_text, chest_tier, stratum)
    return deposit_chest_loot(setting_id, character_name, item, stratum)
