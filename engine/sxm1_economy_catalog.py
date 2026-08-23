"""SxM1 (shota_x_monsters) economy seed catalog.

Grounded in the BESM 4e item math from the SxM1 design docs:
  - Mechanics/06_Equipment.md        (Attributes -> halve -> Item cost scaffold)
  - Mechanics/08_Item_Conversions.md (all 63 items, BESM Item Cost table)
  - Mechanics/04_Economy.md          (Gold currency, carry limits, facilities)

Gold pricing model (validated against the 4 designer-confirmed Watt/Reo
peddler prices -- the game's deliberately HIGH "ripoff" town prices that
nudge players toward exploration):

    gold = GOLD_PER_CP * besm_cost * category_multiplier
    GOLD_PER_CP = 50

    Confirmed checks (your baseline prices):
      Potion            1 * 1 =  50 G   (carry 10)
      Dodeka Pudding    4 * 1 = 200 G   (carry 10)
      Fairy Revival     3 * 2 = 300 G   (carry 2)   <- user "Revival Potion"
      Smoke Bomb        1 * 3 = 150 G   (carry 1)   <- guaranteed-escape premium

Items without a confirmed in-game price are flagged '[estimated]' and should
be replaced as real peddler prices surface. Sellable/currency/special items
are not purchasable (price None) -- they are loot or earned currencies.
"""

GOLD_PER_CP = 50
CONFIRMED_IDS = {"potion", "dodeka_pudding", "fairy_revival_potion", "smoke_bomb"}

# (item_id, name, item_type, besm_cost, category_mult, carry_limit,
#  price_class, besm_build, description)
_RAW = [
    # --- Healing & MP Recovery (10) ---
    ("potion", "Potion", "consumable", 1, 1, 10, "consumable",
     "Healing L1, Ammo (single-use)",
     "Restore a small amount of HP. Carry limit 10. [confirmed]"),
    ("high_potion", "High Potion", "consumable", 2, 1, None, "consumable",
     "Healing L2, Ammo (single-use)",
     "Restore a medium amount of HP. [estimated]"),
    ("full_potion", "Full Potion", "consumable", 3, 1, None, "consumable",
     "Healing L3, Ammo (single-use)",
     "Fully recover all HP. [estimated]"),
    ("mega_potion", "Mega Potion", "consumable", 2, 1, None, "consumable",
     "Healing L2, Ammo (single-use)",
     "Recover HP by 250 points. [estimated]"),
    ("giga_potion", "Giga Potion", "consumable", 4, 1, None, "consumable",
     "Healing L3, Area 1, Ammo (single-use)",
     "Recover huge HP for the whole party. [estimated]"),
    ("elixir", "Elixir", "consumable", 5, 1, None, "consumable",
     "Healing L3 + Energy L3, Ammo (single-use)",
     "Completely recover HP and MP. [estimated]"),
    ("magic_water", "Magic Water", "consumable", 1, 1, None, "consumable",
     "Energy L1, Ammo (single-use)",
     "Recovers a small amount of MP. [estimated]"),
    ("baked_sweet_potato", "Baked Sweet Potato", "consumable", 2, 1, None, "consumable",
     "Healing L2 + Special (Fart Charge), Ammo (single-use)",
     "30% HP + Fart Charge state. [estimated]"),
    ("nautas_lunch_box", "Nauta's Lunch Box", "consumable", 5, 1, None, "consumable",
     "Healing L3 + Energy L2, Area 1, Ammo (single-use)",
     "Energizes the whole party. [estimated]"),
    ("regen_medicine", "Regen Medicine", "consumable", 2, 1, None, "consumable",
     "Regeneration L2, Ammo (single-use)",
     "Allies recover 20% HP/turn in battle. [estimated]"),

    # --- Status Cures (4) ---
    ("antidote", "Antidote", "consumable", 1, 1, None, "consumable",
     "Cure (Poison) L1, Ammo (single-use)",
     "Cures Poison. [estimated]"),
    ("clear_herbs", "Clear Herbs", "consumable", 1, 1, 10, "consumable",
     "Cure (Blind/Silence) L1, Ammo (single-use)",
     "Cures Blind + Silence. Carry limit 10. [estimated]"),
    ("smelling_salts", "Smelling Salts", "consumable", 1, 1, None, "consumable",
     "Cure (Paralysis/Confusion/Sleep) L1, Ammo (single-use)",
     "Cures Paralysis + Confusion + Sleep. [estimated]"),
    ("panacea", "Panacea", "consumable", 2, 1, None, "consumable",
     "Cure (All Status) L2, Ammo (single-use)",
     "Cures all debuffs in battle. [estimated]"),

    # --- Revival (1) ---
    ("fairy_revival_potion", "Fairy Revival Potion", "consumable", 3, 2, 2, "consumable",
     "Healing L3 (Revive), Ammo (single-use)",
     "Revives one ally at full HP, battle only. Carry limit 2. Maps to in-game 'Revival Potion'. [confirmed]"),

    # --- Elemental Tags & Mana Stones (12) ---
    ("fire_tag", "Fire Tag", "consumable", 2, 1, 3, "consumable",
     "Weapon L3, Element (Fire), Ammo (single-use)",
     "Summons Fire magic. Carry limit 3. [estimated]"),
    ("ice_tag", "Ice Tag", "consumable", 2, 1, 3, "consumable",
     "Weapon L3, Element (Ice), Ammo (single-use)",
     "Summons Ice magic. Carry limit 3. [estimated]"),
    ("blizzard_tag", "Blizzard Tag", "consumable", 2, 1, 3, "consumable",
     "Weapon L3, Element (Ice), Area 1, Ammo (single-use)",
     "Summons Blizzard magic. Carry limit 3. [estimated]"),
    ("shock_tag", "Shock Tag", "consumable", 2, 1, 3, "consumable",
     "Weapon L3, Element (Shock), Ammo (single-use)",
     "Summons Shock magic. Carry limit 3. [estimated]"),
    ("wind_tag", "Wind Tag", "consumable", 2, 1, 3, "consumable",
     "Weapon L3, Element (Wind), Ammo (single-use)",
     "Summons Wind magic. Carry limit 3. [estimated]"),
    ("dark_tag", "Dark Tag", "consumable", 2, 1, 3, "consumable",
     "Weapon L3, Element (Dark), Ammo (single-use)",
     "Summons Dark magic. Carry limit 3. [estimated]"),
    ("flash_tag", "Flash Tag", "consumable", 2, 1, 3, "consumable",
     "Weapon L3, Element (Holy), Ammo (single-use)",
     "Summons Holy magic. Carry limit 3. [estimated]"),
    ("inferno_tag", "Inferno Tag", "consumable", 3, 1, 3, "consumable",
     "Weapon L4, Element (Fire), Area 1, Ammo (single-use)",
     "Summons Inferno magic. Carry limit 3. [estimated]"),
    ("mana_stone_blaze", "Mana Stone of Blaze", "consumable", 3, 1, 3, "consumable",
     "Weapon L5, Element (Fire), Area 1, Ammo (single-use)",
     "Unleashes Exhalatio's fury. Carry limit 3. [estimated]"),
    ("mana_stone_frost", "Mana Stone of Frost", "consumable", 3, 1, 3, "consumable",
     "Weapon L5, Element (Ice), Area 1, Ammo (single-use)",
     "Unleashes Congratio's fury. Carry limit 3. [estimated]"),
    ("mana_stone_gale", "Mana Stone of Gale", "consumable", 3, 1, 3, "consumable",
     "Weapon L5, Element (Wind), Area 1, Ammo (single-use)",
     "Unleashes Ventus' fury. Carry limit 3. [estimated]"),
    ("mana_stone_thunder", "Mana Stone of Thunder", "consumable", 3, 1, 3, "consumable",
     "Weapon L5, Element (Shock), Area 1, Ammo (single-use)",
     "Unleashes Æsir-Thor's fury. Carry limit 3. [estimated]"),

    # --- Permanent Stat Items (8, single-use consumables that grant growth) ---
    ("power_up", "Power Up", "consumable", 1, 1, None, "consumable",
     "+3 Attack (Ability), single-use",
     "Permanently +3 Attack Power. [estimated]"),
    ("guard_up", "Guard Up", "consumable", 1, 1, None, "consumable",
     "+3 Defense (Ability), single-use",
     "Permanently +3 Defense. [estimated]"),
    ("magic_up", "Magic Up", "consumable", 1, 1, None, "consumable",
     "+3 Magic Power (Ability), single-use",
     "Permanently +3 Magic Power. [estimated]"),
    ("resist_up", "Resist Up", "consumable", 1, 1, None, "consumable",
     "+3 Magic Defense (Ability), single-use",
     "Permanently +3 Magic Defense. [estimated]"),
    ("speed_up", "Speed Up", "consumable", 1, 1, None, "consumable",
     "+3 Agility (Ability), single-use",
     "Permanently +3 Agility. [estimated]"),
    ("luck_up", "Luck Up", "consumable", 1, 1, None, "consumable",
     "+3 Luck (Ability), single-use",
     "Permanently +3 Luck. [estimated]"),
    ("life_up", "Life Up", "consumable", 1, 1, None, "consumable",
     "+5 HP Max (Ability), single-use",
     "Permanently +50 Max HP. [estimated]"),
    ("mana_up", "Mana Up", "consumable", 1, 1, None, "consumable",
     "+10 EP Max (Ability), single-use",
     "Permanently +10 Max MP. [estimated]"),

    # --- Taming & Bonding (4) ---
    ("dokidoki_pudding", "Dokidoki Pudding", "consumable", 2, 1, None, "consumable",
     "Bond (+1 Tier) L2, Ammo (single-use)",
     "Increases ally-chance after defeat. [estimated]"),
    ("dodeka_pudding", "Dodeka Pudding", "consumable", 4, 1, 10, "consumable",
     "Bond (Guarantee) L4, Ammo (single-use)",
     "Guarantees ally after defeat. Carry limit 10. [confirmed]"),
    ("golden_heart", "Golden Heart", "consumable", 3, 1, None, "consumable",
     "Soul Growth L3, single-use (Bonding)",
     "Crystallized memory; +Growth. [estimated]"),
    ("rainbow_heart", "Rainbow Heart", "consumable", 4, 1, None, "consumable",
     "Soul Growth L4, single-use (Bonding)",
     "Proof of love, strong bond. [estimated]"),

    # --- Utility & Encounters (6) ---
    ("demon_drum", "Demon Drum", "reusable", 2, 1, None, "consumable",
     "Encounter (Taunt/Lure) L2, Equipment",
     "Lures monsters; reusable. [estimated]"),
    ("smoke_ball", "Smoke Ball", "consumable", 1, 2, None, "consumable",
     "Escape (High) L1, Ammo (single-use)",
     "High chance of escape (below guaranteed Smoke Bomb). [estimated]"),
    ("smoke_bomb", "Smoke Bomb", "consumable", 1, 3, 1, "consumable",
     "Escape (Guaranteed) L2, Ammo (single-use)",
     "Guaranteed escape; the only panic-button. Carry limit 1. [confirmed]"),
    ("recall_stone", "Recall Stone", "consumable", 2, 1, None, "consumable",
     "Teleport (City) L2, Ammo (single-use)",
     "Instantly return to city. [estimated]"),
    ("master_repair_agent", "Master Repair Agent", "consumable", 1, 1, None, "consumable",
     "Repair (Clothes) L1, Ammo (single-use)",
     "Repairs damaged clothes. [estimated]"),
    ("star_medal", "Star Medal", "currency", 1, 1, None, "priceless",
     "Currency (Star Medal) L1, Equipment",
     "Trade currency earned by labyrinth dives; not purchasable with gold. [earned]"),

    # --- Sellable / Disposable (16, loot sold for money) ---
    ("antique_coin", "Antique Coin", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("gold_coin", "Gold (Coin)", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("silver_coin", "Silver (Coin)", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("gemstone_blue", "Gemstone (Blue)", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("gemstone_gold", "Gemstone (Gold)", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("gemstone_white", "Gemstone (White)", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("ingot_iron", "Ingot (Iron)", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("ingot_silver", "Ingot (Silver)", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("ingot_gold", "Ingot (Gold)", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("statue_silver", "Statue (Silver)", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("statue_gold", "Statue (Gold)", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("statue_blue_silver", "Statue (Blue Silver)", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("stone_blue_silver", "Stone (Blue Silver)", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("stone_golden", "Stone (Golden)", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("stone_white", "Stone (White)", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),
    ("golden_chalice", "Golden Chalice", "sellable", 1, 1, None, "priceless",
     "Value (Minor) L1",
     "[Disposable] sold for money. [sell-only]"),

    # --- Challenge / Special (2, not purchasable) ---
    ("give_up_challenge", "Give Up (Challenge Item)", "special", 1, 1, None, "priceless",
     "Special (Challenge) L1",
     "Records challenge points. [special]"),
    ("test_hp_half_life", "Test: HP Half Life", "special", 2, 1, None, "priceless",
     "Weapon L4, Ammo (single-use), Test-only",
     "Halves enemy HP. Test-only. [special]"),
]


def _build_catalog() -> list:
    items = []
    for (iid, name, itype, cost, mult, limit, pclass, build, desc) in _RAW:
        if pclass == "priceless":
            gold = None
        else:
            gold = GOLD_PER_CP * cost * mult
        eff = {"besm_build": build, "item_cost": cost}
        if limit is not None:
            eff["carry_limit"] = limit
        items.append({
            "item_id": iid,
            "name": name,
            "item_type": itype,
            "rank_label": "\u2014",
            "besm_points": cost,
            "item_cp": cost,
            "price_class": pclass,
            "price_silver": gold,
            "effect_json": eff,
            "description": desc,
        })
    return items


SEED_CATALOG_SXM1 = _build_catalog()
