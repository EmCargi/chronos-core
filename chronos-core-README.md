# ⚡ Chronos Core ⚡ — Version 3

Chronos Core is a **multi-setting tabletop RPG engine and interactive fiction sandbox** for the terminal. It pairs semantic, local-LLM narrative generation with a strict, Python-enforced **Big Eyes, Small Mouth Fourth Edition (Tri-Stat System)** rules simulation — with a **universal campaign catalog, canonical character roster, a setting-agnostic item economy, and a full BESM 4e rules enforcement layer** wired to live Ollama inference.

Version 3 adds mechanical enforcement to the v2 foundation: the LLM shell prompt injects Combat Techniques, Skills, Defects, and Shock Value for Sixth Guard enforcement across all 7 roster characters. The thin client TUI dispatches narrative turns to the big rig's Ollama server, which returns mechanically grounded responses that respect each character's loadout.

---

## 🗺️ System Architecture

```text
chronos-core/
├── chronos.py                     # Main Rich TUI dashboard (command loop + HUD)
├── launcher.py                    # Unified command launcher (TUI / wizard / ingest / verify)
├── (backfill_besm.py archived → dev/archive/chronos-core/)
├── ITEMS_ECONOMY_PLAN.md          # Design doc for the item & silver-economy layer
├── config/
│   └── settings.json              # Global LLM / model / default-setting config
├── modules/
│   ├── sandbox_75cp.json          # Guild RPG: starter sandbox (75 CP)
│   ├── c_rank_trial.json          # Guild RPG: C-Rank trial (75 CP)
│   ├── five_room_dungeon_v1.json  # Generic 5-room dungeon template (75 CP)
│   └── forest_labyrinth_v1.json   # Shota x Monsters: Labyrinth I (50 CP)
├── staging/
│   ├── raw/                       # Incoming character card .json queue
│   ├── processed/                 # Successfully ingested character cards
│   └── failed/                    # Failed ingestions with error logs
├── engine/
│   ├── __init__.py                # Package exports
│   ├── config.py                  # Settings loader / defaults
│   ├── models.py                  # Pydantic v2 contracts + Tri-Stat + BESM fields
│   ├── state_manager.py           # Runtime session state (vitals, navigation, chronology)
│   ├── guild_roster.py            # Multi-setting roster + BESM loadout functions
│   ├── economy.py                 # Items, wallets, inventory + silver price curves
│   ├── batch_ingest.py            # Character card importer with setting detection
│   ├── llm_bridge.py              # Ollama dispatch + BESM field formatters
│   ├── char_wizard.py             # Character Creator Wizard utility
│   ├── verify_dungeon.py          # Campaign module structural validator
│   └── prompts/
│       ├── besm_shell.md          # LLM shell prompt (8 sections, 8 directives)
│       └── besm_loot.md           # Loot synthesis prompt
└── data/
    ├── guild_rpg_roster.db        # SOURCE OF TRUTH: 22 cols, 7 characters + economy
    ├── chronos_session.db         # Runtime session state only
    └── checkpoints/               # Automatic pre-migration DB snapshots
```

**Two databases, one rule:**
- `guild_rpg_roster.db` — the **canonical catalog** (settings, characters [22 cols with BESM loadout], power packs, items, wallets, inventory). Survives sessions.
- `chronos_session.db` — **runtime state only** (current vitals, active node, narrative history). Repopulated from the roster on launch.

---

## 🌍 Multi-Setting Architecture (v2)

The core is setting-agnostic. Everything campaign-specific is scoped by a `setting_id`:

| Setting | Description | Default module | Label | Roster |
|---|---|---|---|---|
| `guild_rpg` | Aelthar Keldor: the Guild RPG campaign system | `sandbox_75cp.json` | Guild Rank | 7 adventurers (Eira, Rosivelle, Sylvara, Aglae, Tomoe, Liora, Nieven) |
| `shota_x_monsters` | Shota x Monsters 2 BESM 4e expansion | `forest_labyrinth_v1.json` | Monster Tier | 3 presets (Jin, Mayor Ast, Sage Ios) |

New settings register via `register_setting()` — no code changes required beyond seeding a roster.

**Character ingest** routes cards automatically: `[Setting: <id>]` is authoritative, `[Guild Rank:]` implies `guild_rpg`, `[Tier:]` implies `shota_x_monsters`, and a configured `DEFAULT_SETTING` catches everything else.

---

## 🔥 Active Narrative Syntax

A character's identity is compiled into a **runtime contract** — three fields persisted per
character in the roster DB and injected into every LLM shell turn:

| Field | Meaning |
|---|---|
| `structural_fault` | What breaks them — the systemic weakness their kit can't answer |
| `sixth_guard` | The **terminal failure point**: when its condition is met, the character **must** collapse mechanically and narratively — the breakdown is never softened |
| `levers` | The three value-neutral strategic channels they operate through (Containment / Velocity / Defection) |

**The contract is enforced, not suggested.** The shell prompt (Directive 4) instructs the
model to weave the Structural Fault and Levers into narration, and to collapse the character
when the Sixth Guard's condition fires — no ACV/DCV rationalization, no softened escape.

**Three guard classes** emerge across the roster, each watching a different axis:
- **Resource** — Eira (EP 0 + ally in danger → Compassion Override)
- **Spatial** — Seris (threat closing past her footwork), Miri (overextension past the line)
- **Environmental** — Rosivelle (non-standard hazard bypassing textbook geometry)

This turns party composition into *load-bearing structure*: each member's guard is disarmed
by a specific teammate's discipline, so teamwork is a mechanical necessity, not a preference.

---

## 🛡️ BESM 4e Rules Enforcement Layer

Every character now carries a full mechanical loadout persisted in the roster DB and
injected into the LLM shell prompt on every `/examine` and `/loot` turn:

| Column | Content | Enforcement |
|---|---|---|
| `combat_techniques` | Martial edges (Hardboiled, Precise Aim, Critical Strike, etc.) | Applied automatically when relevant — obstacle reduction, damage multipliers, initiative edges |
| `skills` | Training with ranks 1-6 and specialisations | Rank bonus to Stat rolls; Minor Edge on specialisation match |
| `defects` | Mechanical vulnerabilities (Phobia, Lazy, Vulnerability, etc.) | Triggered immediately on condition — never softened or narrated around |
| `shock_value` | Modified stun threshold (base HP÷5 + Hardboiled, capped at ½ HP) | Heavy hits force Soul checks or stun |

**All 7 roster characters** have complete loadouts derived from their canonical profiles.
The LLM enforces these in real time: Rosivelle freezes vs. mice (Phobia), Tomoe's rage
vs. Zarkhoth (Vengeance Singularity), Liora's collapse in darkness (Perimeter Breach).

---

## ⚡ Tri-Stat & CP Rules Economy

Chronos Core enforces the **BESM 4e** physics:

* **Stats**: Body, Mind, Soul — rank `1` to `12`.
* **Cost**: 2 CP per stat rank.
* **Power levels**: Human 25–49 CP / Heroic 50–74 / Paragon 75–99 / etc.
* **Derived vitals**:
  * **HP** = (Body + Soul) × 5
  * **EP** = (Mind + Soul) × 5
  * **Shock Value** = Max HP ÷ 5
  * **ACV** = (Body + Mind + Soul) ÷ 3
  * **DCV** = ACV − 2
* **Checks**: `2d6 + Stat Rank + Skill Rank ≥ DV`
  * Difficulty targets: Simple 6 / Easy 9 / Average 12 / Difficult 15 / Challenging 18 / Unlikely 21 / Improbable 24
  * **Hedging** = take 7

---

## 💰 Item Economy (v2)

Items are settings-scoped and priced by a model synthesized from BESM 4e + the Aelthar Keldor economy:

* **Item CP** = half the BESM attribute points (rounded down) — effects-based.
* **Permanent items** price via the **Fibonacci silver curve** (1 CP = 100 sp; `100, 100, 200, 300, 500 …`):
  * 3 CP → 400 sp · 4 CP → 700 sp · 5 CP → 1,200 sp
* **Consumables** price by **quest-rank bracket**: D 3–10 / C 15–40 / B 50–200 / A 300–800 sp · S & SS priceless.
* **Healing** scales `Lvl × 5 HP` (Standard Health Potion = Lvl 3 → 15 HP @ 25 sp).
* Seeded **Guild RPG shop** (Jaxon the Alchemist + Rosivelle's reference permanents); each setting gets its own catalog.

---

## 🧙 Character Ingestion & Staging

1. Place a character card `.json` (SillyTavern V2/V3 format) in `staging/raw/`.
2. Run `auto-ingest` — the parser extracts stats, ranks, combat values, power packs, and the Active Narrative Syntax fields via `[Sixth Guard:]` / `[Structural Fault:]` / `[Levers:]` tags.
3. Cards route to `staging/processed/` on success (and the roster DB is updated), or `staging/failed/` with error logs.

Canonical AK profiles live as structured markdown in the Aethor Kaeldor character vault, each embedding a `JSON Payload` that maps directly to roster rows.

---

## 🎮 How to Run

```bash
python3 launcher.py
```

Or launch the TUI directly (Python 3.10+; install deps with the bundled venv):

```bash
venv/bin/python chronos.py
```

### Command Palette

| Command | Action |
|---|---|
| `north` `south` `east` `west` | Navigate active node exits (with obstacle checks) |
| `examine` | LLM narrative description of the current node |
| `/attack` | Resolve a combat/obstacle check vs. the active node |
| `/loot` | LLM-synthesize an ephemeral item into the session ledger |
| `/settings` | List all registered settings |
| `/setting <id>` | Switch active setting |
| `/module <name>` | Switch campaign module within the active setting |
| `/char <name>` | Switch active character within the setting |
| `/roster` | List the setting's roster |
| `/shop [rank]` | List the setting's item catalog (optionally filtered) |
| `/buy <item_id> [qty]` | Purchase from the catalog (deducts wallet) |
| `/wallet [name]` | Show a character's silver balance |
| `/grant <silver>` | GM quick-balance command |
| `/inventory` | Show owned items |
| `/loadout` | Show full BESM build (techniques, skills, defects, shock value) |
| `/use <item_id>` | Consume a consumable (e.g. heal 15 HP) |
| `auto-ingest` | Run the staging sweep |

### Launcher Utilities
1. **Launch Chronos Core** — full TUI HUD.
2. **Character Creator Wizard** — interactive sheet builder with CP-budget checks.
3. **Auto-Ingest Staging Sweep** — process `staging/raw/`.
4. **Verify Campaign Module** — validate module JSON structure.

---

## 🤖 LLM Backend

Chronos Core dispatches narrative turns to an **Ollama** instance (local or big rig). Configure in `config/settings.json`:

```json
{
  "ACTIVE_MODEL": "gemma4-v2-Q6_K.gguf:latest",
  "OLLAMA_URL": "http://100.73.250.56:11434/api/generate",
  "DEFAULT_RULES": "besm_shell",
  "DEFAULT_SETTING": "guild_rpg"
}
```

All rules math (checks, damage, item pricing) is computed locally in Python; the LLM only supplies prose and loot-flavor, gated through the output validator.

The narrative turn receives the active character's **full BESM loadout**:
- **Active Narrative Syntax** (Structural Fault, Sixth Guard, Three Levers)
- **Combat Techniques** (Hardboiled, Precise Aim, Critical Strike, etc.)
- **Skills** (ranks 1-6 with specialisations)
- **Defects** (Phobia, Lazy, Vulnerability, etc.)
- **Shock Value** (modified stun threshold)

The shell prompt instructs the model to enforce all mechanical constraints — including the un-softened Sixth Guard collapse, automatic Technique application, and immediate Defect triggers.
