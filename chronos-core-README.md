# ⚡ Chronos Core ⚡ — Version 4

Chronos Core is a **local-first, multi-setting tabletop RPG console** with **two interfaces on one engine**: a terminal Rich TUI and a browser dashboard. It pairs semantic, local-LLM narrative generation (Ollama) with a strict, Python-enforced **Big Eyes, Small Mouth Fourth Edition (Tri-Stat System)** rules simulation — **the LLM narrates; Python holds the numbers.**

> 🕹️ **This is the console.** Settings are **game discs** that plug into it — see
> [`../SETTING_PACK_CONTRACT.md`](../SETTING_PACK_CONTRACT.md) for the five-layer disc contract.
> The engine is setting-agnostic by design; each campaign registers via `config/settings.json`
> (`DEFAULT_SETTINGS`) and ships its own module, roster, economy, and lore vault.

Version 4 is the **demo-ready** console: 11 bootable discs (7 first-party Anime Multiverse
discs + Guild RPG + MHA + Cyberpunk + the SxM testing shelf), **per-disc roster databases**
(every filesystem-homed disc owns its data at the filesystem layer), a 35-command palette in
both interfaces, generative chest loot, and a web port with live token streaming. The SxM
data layer is retained as testing/reference (scope closed 2026-09-13 — the existing game is
canonical).

### 🖥️ Two Interfaces, One Engine

| Interface | Entry point | When to use |
|---|---|---|
| **Terminal TUI** | `launcher.py` or `venv/bin/python chronos.py` | Full command palette, immersive HUD, on the thin client |
| **Browser dashboard** | `chronos-ui` (Streamlit `browser_chronos.py`) | Visual vitals HUD, sidebar disc/roster selectors, live token streaming — openable anywhere on the LAN |

Both interfaces share the same `engine/` code and the same per-disc roster DBs. The web
port adds a separate session DB (`chronos_web_session.db`) so the CLI's session state is
never disturbed.

---

## 🗺️ System Architecture

```text
chronos-core/
├── chronos.py                     # Main Rich TUI dashboard (command loop + HUD)
├── browser_chronos.py             # Streamlit web port (sidebar + vitals HUD + chat + streaming)
├── launcher.py                    # Unified command launcher (TUI / wizard / ingest / verify)
├── engine/
│   ├── __init__.py                # Package exports
│   ├── config.py                  # Settings loader / defaults
│   ├── models.py                  # Pydantic v2 contracts + Tri-Stat + BESM fields
│   ├── state_manager.py           # Runtime session state (vitals, navigation, chronology)
│   ├── guild_roster.py            # Multi-setting roster + BESM loadout + schema migrations
│   ├── economy.py                 # Items, wallets, inventory + silver/gold price curves
│   ├── batch_ingest.py            # Character card importer with setting detection
│   ├── card_to_besm.py            # Deterministic card → BESM compiler (zero LLM)
│   ├── llm_bridge.py              # Ollama dispatch + BESM field formatters + stream holdback
│   ├── disc_registry.py           # Per-disc DB resolver (filename-keyed manifest)
│   ├── verify_dungeon.py          # Module validator (5-room + branching labyrinth)
│   ├── char_wizard.py             # Character Creator Wizard utility
│   └── prompts/
│       ├── besm_shell.md          # LLM shell prompt (8 sections, 8 directives)
│       ├── loot_weaver.md         # Generative chest-loot prompt (Pydantic-enforced)
│       ├── besm_labyrinth_architect.md  # Labyrinth authoring prompt
│       └── besm_loot.md / besm_module_architect.md
├── modules/                       # Campaign node maps (15 modules across the discs)
├── config/settings.json           # LLM model, Ollama URL, DEFAULT_SETTINGS, DISC_DB_DIRS
├── staging/                       # Character card import queue (raw/ → processed/ + failed/)
└── data/
    ├── guild_rpg_roster.db        # SHARED shelf: IP discs without a home repo (cyberpunk, shota)
    ├── chronos_session.db         # CLI runtime session state only
    ├── chronos_web_session.db     # Web port runtime session state (isolated from CLI)
    └── checkpoints/               # Automatic pre-migration DB snapshots
```

**Per-disc roster routing (2026-09-13):** most discs own their roster DB inside their own
folder — `demo-discs/<world>/data/<setting>.db` (tracked) and `guild-rpg-digital-dm/data/`,
`mha-digital-dm/data/` (gitignored, confidential). `engine/disc_registry.py` resolves
setting_id → db path via a lazy filename-keyed manifest; `set_active_setting()` re-points
roster + economy and runs schema migrations only. The shared `guild_rpg_roster.db` above is
now the fallback shelf for discs without a dedicated repo (cyberpunk, shota).

---

## 🎮 The Discs

Eleven discs boot the identical console — different worlds, same engine. The 7 Anime
Multiverse discs (first-party, from BESM 4e Chapter 14) are the demo shipment target.

| Disc | setting_id | Default module | Label | Roster / Data home |
|---|---|---|---|---|
| **Enid: Heavy Weather** | `besm_enid` | `tavarre_outpost.json` | Clearance | 6 chars — own DB (`demo-discs/`) |
| **Ikaris: Swords & Sorcery** | `besm_ikaris` | `shards_tourney.json` | Oath | 6 chars — own DB |
| **Cathedral: Orb Radiant** | `besm_cathedral` | `cathedral_waypoint.json` | Security Clearance | 6 chars — own DB |
| **Aradia: The Living Heaven** | `besm_aradia` | `aerial_path.json` | Chorus | 6 chars — own DB |
| **Bazaroth: The Demon Sun** | `besm_bazaroth` | `pilgrimage_of_bloods.json` | Brand | 6 chars — own DB |
| **Imago: Reality Punk** | `besm_imago` | `ikarion_breach.json` | Credential | 6 chars — own DB |
| **Omphalos: The Council Chamber** | `besm_omphalos` | `council_of_omphalos.json` | Seat | 6 chars — own DB |
| **Guild RPG (Aelthar Keldor)** | `guild_rpg` | `zarlen_training_grounds_v1.json` | Guild Rank | 46 chars + 16 locations + orgs — own DB (`guild-rpg-digital-dm/`) |
| **My Hero Academia** | `my_hero_academia` | `ua_entrance_exam.json` | Hero Rank | 121 chars + 121 Quirk power packs — own DB (`mha-digital-dm/`) |
| **Cyberpunk 2077** | `cyberpunk_2077` | `night_city_heist_v1.json` | Street Cred | 33 chars — shared shelf |
| **Shota x Monsters (testing shelf)** | `shota_x_monsters` | `forest_labyrinth_stratum1.json` | Monster Tier | 109 chars — shared shelf, scope closed |

Plus two registered sub-settings (`guild_training_yard`, `tomoe_volcano_package`) for
Guild RPG's extra modules. New settings register via `register_setting()` — no code
changes beyond seeding a roster.

**Three source archetypes proved:** registry-sheet cast (Guild), one big lorebook (MHA,
188-entry chub.ai JSON → vault + roster), and monster catalog (SxM playground). The engine
and the Setting Pack Contract handle all three.

---

## 🛡️ BESM 4e Rules Enforcement Layer

Every character carries a full mechanical loadout persisted in the roster DB and injected
into the LLM shell prompt on every narrative turn:

| Column | Content | Enforcement |
|---|---|---|
| `combat_techniques` | Martial edges (Hardboiled, Precise Aim, Critical Strike, …) | Applied automatically when relevant — obstacle reduction, damage multipliers, initiative edges |
| `skills` | Training with ranks 1-6 and specialisations | Rank bonus to Stat rolls; Minor Edge on specialisation match |
| `defects` | Mechanical vulnerabilities (Phobia, Lazy, Vulnerability, …) | Triggered immediately on condition — never softened |
| `shock_value` | Modified stun threshold (base HP÷5 + Hardboiled, capped at ½ HP) | Heavy hits force Soul checks or stun |

**The LLM narrates; Python enforces.** The shell prompt injects the active character's full
loadout; the Director holds mechanical constraints — it can *describe* an attack but cannot
*resolve* one. Rules math (checks, damage, pricing) is always local.

---

## 🔥 Active Narrative Syntax

A character's identity is compiled into a **runtime contract** — three fields persisted per
character in the roster DB and injected into every LLM shell turn:

| Field | Meaning |
|---|---|
| `structural_fault` | What breaks them — the systemic weakness their kit can't answer |
| `sixth_guard` | The **terminal failure point**: when its condition is met, the character **must** collapse mechanically and narratively — never softened |
| `levers` | The three value-neutral strategic channels they operate through (Containment / Velocity / Defection) |

**The contract is enforced, not suggested.** The shell prompt instructs the model to weave
the Structural Fault and Levers into narration and collapse the character when the Sixth
Guard fires. Home organizations (e.g. Aelthar Keldor) and macro-regions carry the same
syntax, so the *world* is load-bearing too.

---

## 💰 Item Economy

Items are settings-scoped and priced by a model synthesized from BESM 4e + each disc's
economy docs:

* **Item CP** = half the BESM attribute points (rounded down) — effects-based.
* **Permanent items** price via the **Fibonacci curve** (1 CP = 100 sp; `100, 100, 200, 300, 500 …`).
* **Consumables** price by **quest-rank bracket**: D 3–10 / C 15–40 / B 50–200 / A 300–800 sp · S & SS priceless.
* **Gold discs** (SxM) use `50 × cost × category_mult`; **generative chest loot** (`/open`) prices runtime drops through the same curves with `loot_only` hiding them from `/shop`.
* A 220-item **BESM canon catalog** (`engine/besm_catalog.py`) provisions any disc idempotently via `seed_besm_catalog()`.

---

## 🧙 Character Ingestion & Staging

1. Place a character card `.json` (SillyTavern V2/V3) in `staging/raw/`.
2. Run `auto-ingest` — the parser extracts stats, ranks, combat values, power packs, and the Active Narrative Syntax fields via `[Sixth Guard:]` / `[Structural Fault:]` / `[Levers:]` tags.
3. Cards route to `staging/processed/` on success (and the roster DB is updated), or `staging/failed/` with error logs.

Deterministic compilers do the stat work with **zero LLM**: `card_to_besm.py` (cards) and the
`guild_*`/`sxm1_*` pullovers (registry sheets / bestiary markdown) build roster rows from the
discs' canonical sheets.

---

## 🎮 How to Run

### Browser dashboard (web port)
```bash
chronos-ui                     # zsh alias — launches Streamlit, opens the browser
# or directly:
/home/megane/dev/venv/bin/streamlit run browser_chronos.py
```
The web port boots at `http://localhost:8502` (openable on the LAN). Sidebar picks the
setting / active node / home org / model; the vitals HUD shows HP / EP / Shock / ACV / DCV;
the chat input dispatches AI Director turns through the same Ollama fallback chain as the
TUI, with **live token streaming**. Session state is isolated to `chronos_web_session.db`.

### Terminal TUI
```bash
python3 launcher.py            # launcher menu (TUI / wizard / ingest / verify)
# or directly:
venv/bin/python chronos.py     # Rich TUI with full command palette
```

### Command Palette (35 commands across both interfaces)

| Command | Action |
|---|---|
| `north` `south` `east` `west` | Navigate active node exits (with obstacle checks) |
| `examine` | LLM narrative description of the current node |
| `/attack` | Resolve a combat/obstacle check vs. the active node |
| `/loot` | LLM-synthesize an ephemeral item into the session ledger |
| `/open` | Open a chest-bearing node — generative, Pydantic-validated loot priced + deposited into the canonical economy (`loot_only`, hidden from `/shop`) |
| `/settings` | List all registered settings |
| `/setting <id>` | Switch active setting (re-points to the disc's own DB) |
| `/module <name>` | Switch campaign module within the active setting |
| `/char <name>` | Switch active character within the setting |
| `/org <name>` / `/orgs` | Switch / list the active home organization (guild hub) |
| `/startgreeting <n>` | Begin a session from a character greeting (domestic greetings anchor at the hub) |
| `/roster` | List the setting's roster |
| `/loadout` | Show full BESM build (techniques, skills, defects, shock value) |
| `/shop [rank]` | List the setting's item catalog (optionally filtered) |
| `/buy <item_id> [qty]` | Purchase from the catalog (deducts wallet) |
| `/wallet [name]` | Show a character's silver balance |
| `/grant <silver>` | GM quick-balance command |
| `/inventory` | Show owned items |
| `/use <item_id>` | Consume a consumable (binds repel/blind scene effects to the current node) |
| `/effects` | List active scene effects at the current node |
| `/provision [info] [filters]` | GM-seed the BESM canon into the active setting's shop. Filters: `eras=archaic,modern`, `categories=melee`, `types=weapon`, `cap=800`; bare token = era filter; `info` = preview only |
| `/diceless <cv> [AR] [extra_def] [edge]` | Diceless Total Combat Roll — TCR breakdown + Table-15 MoS band; `/diceless hedge` = auto-7 non-combat |
| `/maneuver <sub>` | Combat maneuver arsenal — `stance`/`two-weapon`/`strike`/`touch`/`called`/`grapple`/`grabbed`/`escape`/`pin`/`multi` |
| `/shock` `/resist` `/fall` `/range` `/size` `/defence` `/sanity` `/recover` `/scv` `/techniques` `/defects` | Deterministic BESM math |
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
  "DEFAULT_SETTING": "guild_rpg",
  "DISC_DB_DIRS": ["../demo-discs", "../guild-rpg-digital-dm", "../mha-digital-dm"]
}
```

`OLLAMA_URL` is not configured directly — the fallback chain routes to the big rig
(`100.73.250.56:11434`) by default and hops to the thin client's local Ollama on
connectivity/server errors. The big rig itself is never touched by tooling.

All rules math (checks, damage, item pricing) is computed locally in Python; the LLM only
supplies prose and loot-flavor, gated through the output validator and Pydantic schema
(`[LOOT PAYLOAD]` for `/open`). The narrative turn receives the active character's **full
BESM loadout**: Active Narrative Syntax, Combat Techniques, Skills, Defects, and Shock Value.

---

## 🧪 Testing

**829 tests, 2 skips** — the engine's rules math, economy, roster/ingest, disc registry,
and the web-port smoke suite are all regression-locked. The per-disc splitter
(`../scripts/split_disc_dbs.py`) exports any disc's rows from the shared DB into its own
database, checkpoint-gated and non-destructive.

---

*Chronos Core v4 — a local, LLM-narrated tabletop RPG console with swappable game discs.
The LLM narrates; Python enforces. Eleven discs boot the identical console.*