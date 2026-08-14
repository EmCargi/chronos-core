import os
import json
import logging
import sqlite3
from datetime import datetime

logger = logging.getLogger("ChronosCore.Economy")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ROSTER_PATH = os.path.join(DATA_DIR, "guild_rpg_roster.db")
SESSION_PATH = os.path.join(DATA_DIR, "chronos_session.db")

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

def get_economy_connection() -> sqlite3.Connection:
    """Safely connects to the canonical roster DB (source of truth for economy)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(ROSTER_PATH)
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
                PRIMARY KEY (setting_id, item_id)
            )
        """)
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
    logger.info("Economy database initialized (items, wallets, inventory).")

def seed_default_catalog(setting_id: str = "guild_rpg") -> None:
    """Inserts the seed catalog for a setting (idempotent)."""
    with get_economy_connection() as conn:
        for item in SEED_CATALOG:
            conn.execute("""
                INSERT OR IGNORE INTO items (
                    setting_id, item_id, name, item_type, rank_label,
                    besm_points, item_cp, price_class, price_silver,
                    effect_json, description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                item.get("description", "")
            ))
    logger.info(f"Seeded default item catalog for setting '{setting_id}'.")

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

def add_item(setting_id: str, item: dict) -> None:
    """Upserts a custom item into a setting's catalog."""
    with get_economy_connection() as conn:
        conn.execute("""
            INSERT INTO items (
                setting_id, item_id, name, item_type, rank_label,
                besm_points, item_cp, price_class, price_silver,
                effect_json, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(setting_id, item_id) DO UPDATE SET
                name = excluded.name,
                item_type = excluded.item_type,
                rank_label = excluded.rank_label,
                besm_points = excluded.besm_points,
                item_cp = excluded.item_cp,
                price_class = excluded.price_class,
                price_silver = excluded.price_silver,
                effect_json = excluded.effect_json,
                description = excluded.description
        """, (
            setting_id,
            item["item_id"],
            item["name"],
            item.get("item_type", "misc"),
            item.get("rank_label", "D"),
            item.get("besm_points", 0),
            item.get("item_cp", 0),
            item.get("price_class", "permanent"),
            item.get("price_silver"),
            json.dumps(item.get("effect_json", {})),
            item.get("description", "")
        ))
    logger.info(f"Upserted item '{item['item_id']}' for setting '{setting_id}'.")

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
    """Lists a setting's item catalog, optionally filtered by rank tier."""
    with get_economy_connection() as conn:
        if rank_filter:
            rows = conn.execute(
                "SELECT * FROM items WHERE setting_id = ? AND rank_label LIKE ? ORDER BY rank_label, name",
                (setting_id, f"%{rank_filter.upper()}%")
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM items WHERE setting_id = ? ORDER BY rank_label, name", (setting_id,)
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
        price = f"{i['price_silver']} sp" if i["price_silver"] is not None else "priceless"
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
    if not spend_silver(setting_id, character_name, total):
        balance = get_wallet(setting_id, character_name)
        return False, f"Insufficient funds: {total} sp needed, wallet has {balance} sp."
    add_to_inventory(setting_id, character_name, item_id, qty)
    logger.info(f"[{setting_id}] {character_name} bought {qty}x {item['name']} for {total} sp.")
    return True, f"Bought {qty}x {item['name']} for {total} sp. Wallet now {get_wallet(setting_id, character_name)} sp."

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

def use_item(setting_id: str, character_name: str, item_id: str) -> tuple:
    """Consumes a consumable item, applying its effect to the character's vitals.
    Returns (ok, message)."""
    item = get_item(setting_id, item_id)
    if not item:
        return False, f"Unknown item '{item_id}' in setting '{setting_id}'."
    if item["item_type"] != "consumable":
        return False, f"{item['name']} is not a consumable and cannot be used."

    effect = item.get("effect") or {}
    kind = effect.get("kind")
    if kind not in ("heal", "ep", "cure"):
        return False, f"{item['name']} has no usable effect."

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

    if delta:
        try:
            import sqlite3 as _sq
            with _sq.connect(SESSION_PATH) as sess:
                sess.row_factory = _sq.Row
                vital = sess.execute(
                    "SELECT current_hp, current_ep FROM character_vitals WHERE session_id = ? AND name = ?",
                    ("chronos_interactive_session", character_name)
                ).fetchone()
                if vital is not None:
                    new_hp = vital["current_hp"] + (delta if kind == "heal" else 0)
                    new_ep = vital["current_ep"] + (delta if kind == "ep" else 0)
                    sess.execute(
                        "UPDATE character_vitals SET current_hp = ?, current_ep = ? WHERE session_id = ? AND name = ?",
                        (new_hp, new_ep, "chronos_interactive_session", character_name)
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
    return True, f"Used {item['name']}. ({'Restored ' + str(delta) + ' vitals.' if delta else 'Effect applied.'})"
