# ⚡ Chronos Core ⚡ — Version 3

Chronos Core is a **multi-setting tabletop RPG engine and interactive fiction sandbox** with **two interfaces on one engine**: a terminal Rich TUI and a browser dashboard. It pairs semantic, local-LLM narrative generation with a strict, Python-enforced **Big Eyes, Small Mouth Fourth Edition (Tri-Stat System)** rules simulation — with a **universal campaign catalog, canonical character roster, a setting-agnostic item economy, and a full BESM 4e rules enforcement layer** wired to live Ollama inference.

> 🕹️ **This is the console.** Settings are **game discs** that plug into it — see
> [`../SETTING_PACK_CONTRACT.md`](../SETTING_PACK_CONTRACT.md) for the five-layer disc contract.
> The engine is setting-agnostic by design; each campaign registers via `config/settings.json`
> (`DEFAULT_SETTINGS`) and ships its own module, roster, economy, and lore vault.

Version 3 adds mechanical enforcement to the v2 foundation: the LLM shell prompt injects Combat Techniques, Skills, Defects, and Shock Value for Sixth Guard enforcement across the whole roster. The thin client dispatches narrative turns to the big rig's Ollama server (fallback chain: big rig → thin client), which returns mechanically grounded responses that respect each character's loadout.

### 🖥️ Two Interfaces, One Engine

| Interface | Entry point | When to use |
|---|---|---|
| **Terminal TUI** | `chronos` or `launcher.py` | Full command palette, immersive HUD, on the thin client |
| **Browser dashboard** | `chronos-ui` | Visual vitals HUD, sidebar disc/roster selectors, chat-style command input — openable anywhere on the LAN |

Both interfaces share the same `engine/` code and the same roster DB — the web port adds a separate session DB (`chronos_web_session.db`) so the CLI's session state is never disturbed.

---

## 🗺️ System Architecture

```text
chronos-core/
├── chronos.py                     # Main Rich TUI dashboard (command loop + HUD)
├── browser_chronos.py             # Streamlit web port (sidebar + vitals HUD + chat input)
├── launcher.py                    # Unified command launcher (TUI / wizard / ingest / verify)
├── requirements.txt               # Web port deps (streamlit, plotly, pydantic)
├── (backfill_besm.py archived → dev/archive/chronos-core/)
├── ITEMS_ECONOMY_PLAN.md          # Design doc for the item & silver-economy layer
├── config/
│   └── settings.json              # Global LLM / model / default-setting config
├── modules/
│   ├── sandbox_75cp.json          # Guild RPG: starter sandbox (75 CP)
│   ├── c_rank_trial.json          # Guild RPG: C-Rank trial (75 CP)
│   ├── five_room_dungeon_v1.json  # Generic 5-room dungeon template (75 CP)
│   ├── forest_labyrinth_v1.json   # Shota x Monsters: Labyrinth I (50 CP)
│   ├── guild_training_yard_v1.json  # Guild RPG: training yard
│   ├── zarlen_training_grounds_v1.json  # Guild RPG: training grounds (Zarlen boss)
│   ├── tomoe_volcano_package_v1.json   # Guild RPG: Tomoe volcano campaign
│   └── ua_entrance_exam.json      # My Hero Academia: U.A. Entrance Exam
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
    ├── guild_rpg_roster.db        # SOURCE OF TRUTH: settings, 45 characters, items, economy
    ├── chronos_session.db         # CLI runtime session state only
    ├── chronos_web_session.db     # Web port runtime session state (isolated from CLI)
    └── checkpoints/               # Automatic pre-migration DB snapshots
```

**Three databases, one rule:**
- `guild_rpg_roster.db` — the **canonical catalog** (settings, characters [22 cols with BESM loadout], power packs, items, wallets, inventory). Survives sessions.
- `chronos_session.db` — **CLI runtime state only** (current vitals, active node, narrative history). Repopulated from the roster on launch.
- `chronos_web_session.db` — **web port runtime state only**, kept separate so the browser dashboard never contends with a running TUI session (CP-2).

---

## 🌍 Multi-Setting Architecture (v2)

The core is setting-agnostic. Everything campaign-specific is scoped by a `setting_id`:

| Setting | Description | Default module | Label | Roster |
|---|---|---|---|---|
| `guild_rpg` | Aelthar Keldor: the Guild RPG campaign system | `sandbox_75cp.json` | Guild Rank | 45 rows (38 adventurers + 7 bosses), 16 locations, 1 org |
| `shota_x_monsters` | Shota x Monsters 2 BESM 4e expansion | `forest_labyrinth_v1.json` | Monster Tier | 105 rows (94 card-derived + 3 presets + 8 curated Bestiary) |
| `my_hero_academia` | U.A. High Entrance Exam module | `ua_entrance_exam.json` | Hero Rank | Registered (Disc 3) |

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

**Every roster character** has a complete loadout derived from its canonical profile.
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

### Browser dashboard (web port)
```bash
chronos-ui                     # zsh alias — launches Streamlit, opens the browser
# or directly:
/home/megane/dev/venv/bin/streamlit run browser_chronos.py
```
The web port boots at `http://localhost:8502` (openable on the LAN). Sidebar picks
the setting / active node / home org / model; the vitals HUD shows HP / EP / Shock /
ACV / DCV; the chat input dispatches AI Director turns through the same Ollama
fallback chain as the TUI. Session state is isolated to `chronos_web_session.db`.

### Terminal TUI
```bash
python3 launcher.py            # launcher menu (TUI / wizard / ingest / verify)
# or directly:
venv/bin/python chronos.py     # Rich TUI with full command palette
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
| `/provision [info] [filters]` | GM-seed the BESM canon into the active setting's shop. Filters: `eras=archaic,modern`, `categories=melee`, `types=weapon`, `cap=800`; bare token = era filter; `info` = preview only |
| `auto-ingest` | Run the staging sweep |

### Launcher Utilities
1. **Launch Chronos Core** — full TUI HUD.
2. **Character Creator Wizard** — interactive sheet builder with CP-budget checks.
3. **Auto-Ingest Staging Sweep** — process `staging/raw/`.
4. **Verify Campaign Module** — validate module JSON structure.

---

## 🤖 LLM Backend

Chronos Core dispatches narrative turns to an **Ollama** instance via the canonical
fallback chain (`dev/core/ollama.py`) — **big rig first, thin client last resort**.
Configure in `config/settings.json`:

```json
{
  "ACTIVE_MODEL": "hf.co/bartowski/TheDrummer_Cydonia-24B-v4.3-GGUF:Q4_K_M",
  "THIN_MODEL": "deepseek-r1:7b",
  "DEFAULT_RULES": "besm_shell",
  "DEFAULT_SETTING": "guild_rpg"
}
```

`OLLAMA_URL` is not configured directly — the fallback chain routes to the big rig
(`100.73.250.56:11434`) by default and hops to the thin client's local Ollama on
connectivity/server errors. The big rig itself is never touched by tooling.

All rules math (checks, damage, item pricing) is computed locally in Python; the LLM only supplies prose and loot-flavor, gated through the output validator.

The narrative turn receives the active character's **full BESM loadout**:
- **Active Narrative Syntax** (Structural Fault, Sixth Guard, Three Levers)
- **Combat Techniques** (Hardboiled, Precise Aim, Critical Strike, etc.)
- **Skills** (ranks 1-6 with specialisations)
- **Defects** (Phobia, Lazy, Vulnerability, etc.)
- **Shock Value** (modified stun threshold)

The shell prompt instructs the model to enforce all mechanical constraints — including the un-softened Sixth Guard collapse, automatic Technique application, and immediate Defect triggers.
