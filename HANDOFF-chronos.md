---
project: digital-dm
date: 2026-08-16
status: active
test_count: 406 (17 dungeon + 27 models + 44 economy + 27 status + 34 physics + 18 modifiers + 27 size-scale + 28 defence + 27 extended + 34 techniques + 38 sanity + 34 defects + 28 social) + 19 card compiler = 425 pass, 1 skip, all runnable (2026-08-18)
git: "local-only, engine code scoped (2026-08-14)"
---
# Chronos Core — Handoff Document

## Current State (2026-08-15)

Chronos Core is a **multi-setting tabletop RPG engine and interactive fiction sandbox** for the terminal. It pairs a Python-enforced BESM 4e (Tri-Stat System) rules simulation with local-LLM narrative generation via Ollama. V3 shipped on 2026-08-07 with full mechanical enforcement: Combat Techniques, Skills, Defects, and Shock Value are persisted in the roster DB and injected into every LLM shell turn. Two campaign settings are registered (Guild RPG + Shota x Monsters 2) with 11 characters total. The thin client runs the TUI; the big rig runs Ollama inference. No tests, no CI — this is a studio tool. Git was initialized 2026-08-14, **scoped to engine code only** — see Operational Notes for exactly what's excluded and why.

## Lineage

*Chronological trail of the proposals and journal entries that built this project — lets a design model trace "how did we get here" without narration.*

| Date | Proposal | Journal | What Shipped |
|---|---|---|---|
| 2026-08-07 | — | `2026-08-07-digital-dm-v3-besm-enforcement.md` | V3 — full BESM loadout enforced at runtime (Combat Techniques, Skills, Defects, Shock Value), not just design docs (predates proposal template) |
| 2026-08-13 | — | `2026-08-13-archiving-universal-dm-engine.md` | BESM source PDFs relocated to `BESM Rules/`; universal-dm-engine (prompt-engineering predecessor) archived (housekeeping, no proposal) |
| 2026-08-14 | — | `2026-08-14-git-rollout-persona-etl-chronos-core.md` | Git initialized, scoped to engine code only — confidential character data excluded by design (infrastructure work, no proposal) |
| 2026-08-14 | — | `2026-08-14-chronos-core-fallback-chain.md` | **Wired to fallback chain** — `dispatch_ollama_turn()` routes through `dev/core/ollama.py`; big rig first, thin-client (deepseek-r1:7b) fallback. `OLLAMA_URL` removed. |
| 2026-08-15 | `proposal/01_BESM_ENGINE_UPGRADE.md` | `2026-08-15-shota-monsters-pipeline-verification.md`, `2026-08-15-shota-database-extraction.md`, `2026-08-15-master-monster-db-import.md`, `2026-08-15-master-db-text-import.md`, `2026-08-15-master-db-catalog-import.md` | **Pipeline scope verified & corrected.** Two game archives reverse-engineered (SxM2 key `0x2DF7B`, SxM1 key `0x0001034A`), 212 `.rvdata2` files extracted. Weebly scraper built (103 SxM1 monsters, 0 failures). **master_monsters.db** — 13 tables, ~12,300 rows, 337 canonical species across both games + skills/dialogue/items/weapons/armors catalogs + 457 besm/ lore files. 5 import scripts. Ruby 3.2.3 installed for future Marshal decoding. |
| 2026-08-16 | — | `2026-08-16-persona-etl-sxmv2-character-cards.md` | **Bestiary → cards → roster feed, complete.** persona-etl consumed the SxM1 BESM markdown (new `.md` intake + `sxm1-bestiary.md` prompt, big-rig Cydonia-24B) and shipped **339/339 SillyTavern V2 monster-boy cards** (34 batches, 0 failures). These V2 cards are a direct drop-in feed for `batch_ingest` — the Shota setting's roster can balloon from 3 to all 339 species. (Ad-hoc, persona-etl side; no proposal) |
| 2026-08-18 | — | `2026-08-18-chronos-core-card-to-besm-compiler.md` | **Deterministic card → BESM compiler shipped** (`engine/card_to_besm.py`). Reads the card's markdown Combat Profile HP table (row + column layouts) → tier via the 5-Tier Monster Hierarchy ladder → archetype from Combat Role → stat block (Body/Mind/Soul rank pools 10/12/17/23/30, CP budgets 35/57/82/120/200) → emits the exact `[SYSTEM DATA: BESM 4E MECHANICS]` block METHOD 1 parses. No LLM in the loop. Also: root venv's corrupted `pytest` reinstalled + project-root `conftest.py` added — **the full 425-test suite is green for the first time** (legacy tests could never import `core.ollama`). |

## Architecture Overview

```
chronos-core/
    │
    ├── launcher.py ── Unified launcher (4 options: TUI / wizard / ingest / verify)
    │
    ├── chronos.py ── Rich TUI dashboard (command loop + HUD + vitals panel)
    │       │
    │       ├── engine/state_manager.py ── Runtime session state (vitals, nav, chronology)
    │       ├── engine/guild_roster.py ── Canonical roster DB (settings, characters, power packs)
    │       ├── engine/economy.py ── Items, wallets, inventory, silver price curves
    │       ├── engine/llm_bridge.py ── Ollama dispatch + BESM field formatters + prompt compilation
    │       ├── engine/models.py ── Pydantic v2 CharacterSchema + Tri-Stat derived vitals
    │       ├── engine/batch_ingest.py ── Character card importer (staging/raw/ → processed/failed/)
    │       ├── engine/char_wizard.py ── Interactive character creator with CP-budget checks
    │       └── engine/verify_dungeon.py ── Campaign module structural validator (5-room check)
    │
    ├── config/settings.json ── LLM model, Ollama URL, default rules + setting
    ├── modules/ ── Campaign node maps (6 modules across 2 settings)
    ├── data/
    │   ├── guild_rpg_roster.db ── SOURCE OF TRUTH (settings, characters, items, wallets, inventory)
    │   ├── chronos_session.db ── Runtime state only (repopulated from roster on launch)
    │   └── checkpoints/ ── Pre-migration DB snapshots
    └── staging/ ── Character card import queue (raw/ → processed/ + failed/)
```

**Two databases, one rule:**
- `guild_rpg_roster.db` — the canonical catalog (settings, characters [22 cols with BESM loadout], power packs, items, wallets, inventory). Survives sessions.
- `chronos_session.db` — runtime state only (current vitals, active node, narrative history). Repopulated from the roster on launch.

## File Map

| File | Purpose | Lines | Tests |
|---|---|---|---|
| `chronos.py` | Main Rich TUI dashboard — command loop, HUD, vitals panel, all `/` commands | ~768 | — |
| `launcher.py` | Unified launcher (4 options: TUI / wizard / ingest / verify) | ~76 | — |
| ~~`backfill_besm.py`~~ | ~~One-time BESM loadout backfill script~~ | **Archived 2026-08-14** → `dev/archive/chronos-core/backfill_besm.py` |
| **`engine/`** | | | |
| `engine/guild_roster.py` | Canonical roster DB — settings, characters (22 cols), power packs, BESM loadout CRUD | ~693 | — |
| `engine/economy.py` | Item economy — items, wallets, inventory, Fibonacci pricing, rank-bracket consumables, seed catalog | ~461 | — |
| `tests/test_economy.py` | Economy tests (44: Fibonacci, brackets, wallets, item CRUD, catalog, buy, inventory) | ~280 | 44 |
| `engine/llm_bridge.py` | Ollama dispatch, BESM field formatters (techniques/skills/defects → markdown), prompt compilation, SafeFormatter | ~273 | — |
| `engine/state_manager.py` | Runtime session DB — vitals, navigation, chronology, checkpoint snapshots | ~285 | — |
| `engine/batch_ingest.py` | Character card importer — staging/raw/ → setting detection → roster DB → processed/failed/ | ~308 | — |
| `engine/card_to_besm.py` | **Deterministic SxM card → BESM compiler** — HP table → tier → archetype → stat block → `[SYSTEM DATA: BESM 4E MECHANICS]` block for METHOD 1 | ~350 | — |
| `conftest.py` | Pytest root bootstrap — puts `dev/` + `chronos-core/` on sys.path so `core.ollama` imports | ~12 | — |
| `engine/char_wizard.py` | Interactive character creator — CP-budget checks, stat allocation, LLM-assisted | ~192 | — |
| `engine/models.py` | Pydantic v2 CharacterSchema (Tri-Stat + BESM fields + derived vitals) + action/shock/incapacitation/poison checks | ~170 | — |
| `tests/test_models.py` | Model tests (27: schema validation, tri-stat vitals, SV caps, action checks) | ~210 | 27 |
| `tests/test_status_effects.py` | Status tests (27: obstacle dice, shock/knockout, incapacitation, poison resistance) | ~200 | 27 |
| `tests/test_combat_physics.py` | Combat physics tests (34: edge dice, wound penalties, falling damage, range bands) | ~190 | 34 |
| `tests/test_combat_modifiers.py` | Modifier stack tests (18: cancellation, compounding, spillover, combat resolution) | ~140 | 18 |
| `tests/test_size_scale.py` | Size/scale tests (27: grid integrity, strength, AR, ranged mod, knockback, collapse) | ~160 | 27 |
| `tests/test_defence_absorption.py` | Defence absorption tests (28: layers 1-4, force field, armour, absorption, full pipeline) | ~200 | 28 |
| `tests/test_extended_actions.py` | Extended action tests (27: matrix, init, check loop, backlash, opposed contests, detection gradient) | ~190 | 27 |
| `tests/test_combat_techniques.py` | Technique tests (34: has_technique, obstacle reduction, apply_reduction, edge bonus, critical, knockback, rush) | ~200 | 34 |
| `tests/test_sanity_recovery.py` | Sanity/recovery tests (38: SP derivation, trauma checks, spiral, recovery, catastrophic, hemorrhage, natural recovery) | ~240 | 38 |
| `tests/test_defects.py` | Defect tests (34: Fragile, Reduced Damage, Achilles Heel, Bane, Weak Point, Unsettled, phobia, distraction) | ~220 | 34 |
| `tests/test_social_combat.py` | Social combat tests (28: SCV derivation, Social Mastery, Demure, SP, damage table, clash, recovery) | ~200 | 28 |
| `engine/config.py` | Settings loader — reads `config/settings.json` with defaults fallback | ~46 | — |
| `engine/verify_dungeon.py` | Campaign module validator — 5-room structure + obstacle key checks | ~58 | — |
| `tests/test_verify_dungeon.py` | Validator tests (17: valid modules, room detection, required-check, file errors) | ~195 | 17 |
| `tests/test_card_to_besm.py` | Card compiler tests (19: HP row/col tables, tier brackets, archetypes, stat alloc, ACV, SYSTEM DATA contract) | ~200 | 19 |
| `engine/__init__.py` | Package exports | ~30 | — |
| **`engine/prompts/`** | | | |
| `besm_shell.md` | LLM shell prompt (8 sections, 8 directives — includes BESM enforcement) | ~3,587 chars | — |
| `besm_loot.md` | Loot synthesis prompt | ~699 chars | — |
| `besm_module_architect.md` | Module architect prompt (campaign node generation) | ~3,785 chars | — |
| `besm-mapper` | BESM character mapping engine (V2 card → mechanical sheet) | ~53 lines | — |
| **`config/`** | | | |
| `config/settings.json` | Active model, Ollama URL, default rules, default setting | 6 lines | — |
| **`modules/`** | | | |
| `sandbox_75cp.json` | Guild RPG: starter sandbox (75 CP) | — | — |
| `c_rank_trial.json` | Guild RPG: C-Rank trial (75 CP) | — | — |
| `five_room_dungeon_v1.json` | Generic 5-room dungeon template (75 CP) | — | — |
| `forest_labyrinth_v1.json` | Shota x Monsters: Labyrinth I (50 CP) | — | — |
| `guild_training_yard_v1.json` | Guild RPG: training yard | — | — |
| `tomoe_volcano_package_v1.json` | Guild RPG: Tomoe volcano campaign | — | — |

## Schema

```python
class CharacterSchema(BaseModel):
    name: str
    points_budget: int = 75
    stat_body: int          # 1-12 (BESM Tri-Stat)
    stat_mind: int          # 1-12
    stat_soul: int          # 1-12
    current_hp: int | None
    current_ep: int | None

    # BESM rules fields (persisted in roster DB, injected into LLM shell prompt)
    shock_value: int = 0
    combat_techniques: list[dict] = []   # [{name, level, effect}]
    skills: list[dict] = []              # [{name, rank, stat, specialisation}]
    defects: list[dict] = []             # [{name, rank, cp, trigger}]

    @property
    def max_hp(self) -> int:       return (self.stat_body + self.stat_soul) * 5
    @property
    def max_ep(self) -> int:       return (self.stat_mind + self.stat_soul) * 5
    @property
    def base_acv(self) -> int:     return (self.stat_body + self.stat_mind + self.stat_soul) // 3
    @property
    def base_dcv(self) -> int:     return self.base_acv - 2
    @property
    def shock_value_computed(self) -> int:
        base_sv = self.max_hp // 5
        hardboiled = sum(10 * t.get("level", 1) for t in self.combat_techniques
                         if t.get("name", "").lower() == "hardboiled")
        return min(base_sv + hardboiled, self.max_hp // 2)
```

**Roster DB tables:** `settings`, `characters` (22 cols: stats + BESM + narrative syntax + card_json), `power_packs`, `items`, `character_wallets`, `character_items`

**Session DB tables:** `character_vitals`, `campaign_navigation`, `character_inventory`

**Active Narrative Syntax** (3 fields per character, persisted in roster, injected into every LLM turn):
- `structural_fault` — what breaks them (systemic weakness)
- `sixth_guard` — terminal failure point (must collapse, never softened)
- `levers` — three strategic channels (Containment / Velocity / Defection)

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **LLM as narrator, Python as rules authority** | Rules math (checks, damage, pricing) computed locally; LLM only supplies prose. Prevents "the narrator said X but the engine computed Y" desync. |
| **Active Narrative Syntax as enforced contract** | Structural Fault, Sixth Guard, and Levers are persisted fields injected into every shell turn. The LLM MUST enforce the Sixth Guard collapse — not suggested, enforced. |
| **Two-database split** | Roster DB = canonical (survives sessions); Session DB = ephemeral (repopulated on launch). Canonical > runtime. |
| **Setting-agnostic via `setting_id`** | Everything campaign-specific scoped by `setting_id`. New settings register via `register_setting()` — no code changes beyond seeding a roster. |
| **Non-destructive additive migration** | BESM columns added via `ALTER TABLE ADD COLUMN` with safe defaults. Existing data never touched. |
| **Externalized shell prompt** | `engine/prompts/besm_shell.md` — edit the prompt without touching code. SafeFormatter handles missing keys gracefully. |
| **Fibonacci permanent pricing** | 1 CP = 100 sp; sequence `100, 100, 200, 300, 500…`. Matches BESM 4e effects-based model + AK economy docs. |
| **Rank-bracket consumable pricing** | D 3-10 / C 15-40 / B 50-200 / A 300-800 sp. Consumables bypass CP→silver conversion. |
| **Thin client TUI, big rig inference** | Thin client can't run local models (gemma-heretic 7.5B crashes it). Big rig Ollama is the inference node. |
| **Logging to file, not console** | TUI protection — `logging` module writes to `data/chronos_runtime.log`, keeping the Rich console clean. |
| **Checkpoint snapshots** | Pre-migration DB snapshots in `data/checkpoints/` — rollback safety. |

## Compiled Data / Assets

| Source | Count | Location |
|---|---|---|
| Guild RPG characters | 8 (Eira, Rosivelle, Sylvara, Aglae, Tomoe, Liora, Nieven, Zarlen) | `data/guild_rpg_roster.db` |
| Shota x Monsters characters | 3 (Jin, Mayor Ast, Sage Ios) — **card corpus ready to ingest: 339/339 SillyTavern V2 cards** | `data/guild_rpg_roster.db` / `persona-etl/output/` |
| Campaign modules | 6 (sandbox, C-rank trial, 5-room dungeon, forest labyrinth, training yard, Tomoe volcano) | `modules/` |
| Item catalog (seeded) | 8 (healing salves, energy drafts, standard potions, etc.) | `data/guild_rpg_roster.db` |
| BESM rules reference files | 15 cheat sheets (~260 KB) + 2 source PDFs (53 MB) | `digital-dm-project/BESM Rules/` (local) |
| Session run records | 2 | `SESSION_RUN_RECORD_*.md` |

## What Works

- Multi-setting roster (2 settings, 11 characters)
- BESM 4e rules enforcement (Combat Techniques, Skills, Defects, Shock Value)
- Active Narrative Syntax injection (Structural Fault, Sixth Guard, Three Levers)
- Tri-Stat derived vitals (HP, EP, ACV, DCV, Shock Value)
- 2d6 action checks with difficulty targets
- Item economy (Fibonacci permanents, rank-bracket consumables, wallets, inventory)
- Shop commands (`/shop`, `/buy`, `/wallet`, `/inventory`, `/use`)
- Character card auto-ingest (staging/raw/ → setting detection → roster DB)
- Character Creator Wizard (interactive, CP-budget checks)
- Campaign module validator (5-room structure + obstacle keys)
- Rich TUI dashboard with vitals panel and Shock Value bar
- Ollama dispatch via big rig (gemma4-v2-Q6_K.gguf, 11.9B)
- Live LLM narrative generation with mechanical enforcement
- 6 campaign modules across 2 settings
- **Shota×Monsters data layer grown (2026-08-15 → 2026-08-16):** `../shota-monsters-digital-dm/master_monsters.db` (v1.2) is now the canonical source — 339 species, SxM1 text fully imported (memos, 1,234 skills, weapons/armors/items, 2,554 dialogue entries) and indexed in ChromaDB (5,625 vectors, semantic search validated). `besm/` holds 457 extracted source files from the earlier manual pass (overlap with DB rows by design; the DB wins). **SxM2 mechanics are a future expansion, not a blocker** — BESM conversion proceeds on SxM1. Living handoff: `shota-monsters-digital-dm/HANDOFF-shota.md`.
- Checkpoint snapshots (pre-migration DB backup)
- `py_compile` clean on all files
- Live LLM tests: Rosivelle (Phobia: mice), Eira (Compassion Override), Tomoe (Vengeance Singularity), Liora (Perimeter Breach) — all enforced correctly
- **Deterministic card → BESM compiler (2026-08-18)** — `engine/card_to_besm.py` turns the post-08-16 card batch into METHOD 1 SYSTEM DATA blocks with zero LLM calls (HP→tier→archetype→stat block). Verified by 19 contract tests.
- **Full test suite runnable (2026-08-18)** — root venv's corrupted pytest reinstalled + `conftest.py` bootstrap; **425 passed, 1 skipped** for the first time (legacy suites previously couldn't import `core.ollama`).

## What Doesn't Work Yet

- **Test suite at 425 tests (all runnable as of 2026-08-18)** — covering verify_dungeon, models, economy, status effects, combat physics, modifiers, size/scale, defence absorption, extended actions, combat techniques, sanity/recovery, defects, social combat, and the new card compiler. **Still no tests for roster CRUD or batch_ingest** (`test_guild_roster.py`, `test_batch_ingest.py` not yet written).
- **Full-project git** — engine code has local-only git (2026-08-14), but confidential character data (`data/`, `staging/`, `modules/`) stays untracked by design. Full-project git deferred to the BESM 4e "universal" rewrite.
- **No Combat Maneuvers runtime** — `/maneuver` command not wired (designed but not implemented)
- **BESM mechanics engine shipped + TUI wired** — 425 tests. Engine math now exposed via `/` commands in the dashboard: `/shock`, `/resist`, `/fall`, `/range`, `/size`, `/defence`, `/scv`, `/sanity`, `/recover`, `/techniques`, `/defects`, `/engine`. Type `/engine` for the full list in-session.
- **No diceless TCR formula** — alternative resolution mode designed but not implemented
- **Thin client can't run inference** — all LLM-dependent testing requires big rig Ollama
- **Nieven's narrative syntax needs tuning** — flagged for extended live play
- ~~**`backfill_besm.py` not archived**~~ — **Archived 2026-08-14** → `dev/archive/chronos-core/backfill_besm.py`

## Known Frictions

| Friction | Impact | Fix Effort |
|---|---|---|
| ~~No automated tests~~ (partial) | ~~BESM functions, economy math had no regression protection~~ | **425 tests across 14 suites** — roster CRUD and batch_ingest remain untested |
| ~~Big rig was the only inference node~~ | ~~Can't test LLM-dependent features on thin client~~ | **Fixed 2026-08-14** — fallback chain now hops to thin client (deepseek-r1:7b) when big rig is down. Degraded narrator > dead TUI. |
| Nieven's data is confidential | Sourced from guild record AK-S-009, not for external sharing | By design — studio content |
| ~~No reasoning-tag stripping~~ | ~~Reasoning tags could pollute narrative~~ | **Fixed 2026-08-14** — `engine/llm_bridge.py` now calls `strip_reasoning_tags()` (from `dev/core/reasoning.py`) in `dispatch_ollama_turn()` |
| ~~Settings hardcoded in guild_roster.py~~ | ~~DEFAULT_SETTINGS was in code~~ | **Fixed 2026-08-14** — moved to `config/settings.json`; loaded via `engine/config.py` |
| Economy uses `logging` module, not emoji print | Inconsistent with AGENTS.md style (but justified — TUI protection) | By design — logging to file is correct for TUI |
| ~~`backfill_besm.py` cluttered root~~ | ~~One-shot script~~ | **Archived 2026-08-14** → `dev/archive/chronos-core/` |

## How to Extend

### Run the engine
```bash
cd "digital-dm-project/chronos-core"
python3 launcher.py          # launcher menu
# or directly:
venv/bin/python chronos.py   # TUI directly
```

### TUI command palette
| Command | Action |
|---|---|
| `north` `south` `east` `west` | Navigate active node exits |
| `examine` | LLM narrative description of current node |
| `/attack` | Resolve combat/obstacle check |
| `/loot` | LLM-synthesize ephemeral item |
| `/settings` | List registered settings |
| `/setting <id>` | Switch active setting |
| `/module <name>` | Switch campaign module |
| `/char <name>` | Switch active character |
| `/roster` | List setting's roster |
| `/shop [rank]` | List item catalog |
| `/buy <item_id> [qty]` | Purchase from catalog |
| `/wallet [name]` | Show silver balance |
| `/inventory` | Show owned items |
| `/loadout` | Show full BESM build |
| `/use <item_id>` | Consume a consumable |
| `auto-ingest` | Run staging sweep |

### Register a new setting
1. Add setting entry to `DEFAULT_SETTINGS` in `config/settings.json`
2. Seed roster characters via `upsert_character()`
3. Create a campaign module JSON in `modules/`
4. Optionally seed an item catalog in `engine/economy.py`

### Add a new character
1. Create a SillyTavern V2 card `.json` with `[Setting:]`, `[Guild Rank:]`, stats, and Narrative Syntax tags
2. Drop in `staging/raw/`
3. Run `auto-ingest` (launcher option 3)

### Configure the LLM
Edit `config/settings.json`:
```json
{
  "ACTIVE_MODEL": "gemma4-v2-Q6_K.gguf:latest",
  "OLLAMA_URL": "http://100.73.250.56:11434/api/generate",
  "DEFAULT_RULES": "besm_shell",
  "DEFAULT_SETTING": "guild_rpg"
}
```

## Operational Notes

- **Big rig (100.73.250.56)** runs Ollama with `gemma4-v2-Q6_K.gguf:latest` (11.9B Q6_K, 131K context). Never touched by tooling — Megane handles all big-rig operations.
- **Thin client (100.114.138.30)** runs the TUI only — no local inference (gemma-heretic 7.5B crashes it).
- **Git** is local-only, first commit `2d394ed` (2026-08-14) — **scoped to engine code, not the whole project.** Tracked: `chronos.py`, `launcher.py`, `engine/`, `config/settings.json`, this handoff, `chronos-core-README.md`. Excluded via `.gitignore`: `data/` (roster DBs — confidential character data, incl. Nieven's guild record AK-S-009), `staging/` (processed character profiles), `modules/` (scenario packages that reference named characters in narrative text, e.g. Tomoe), `venv/`, plus 4 session/design docs that log real playthrough content or character-specific planning (`SESSION_RUN_RECORD*.md`, `BACKFILL_PLAN_ROSIVELLE_NARRATIVE_SYNTAX.md`, `ITEMS_ECONOMY_PLAN.md`) and `backfill_besm.py` (since archived — character backstory/psychology hardcoded as string literals). Full-project git-init is deferred until the planned BESM 4e "universal" rewrite replaces the guild-rpg/shota-monsters-specific roster.
- **venv** is at `chronos-core/venv/` (project-local, not shared). Python is 3.12.3.
- **Logging** goes to `data/chronos_runtime.log` — not console (TUI protection). This is the one project that uses `logging` module instead of emoji print, by design.
- **Response times**: ~15-30 seconds per LLM turn on gemma4-v2 Q6_K.
- **External dependencies**: BESM 4e rules reference files (15 cheat sheets + 2 source PDFs) live in `digital-dm-project/BESM Rules/`. The original `universal-dm-engine/` (prompt-engineering predecessor to Chronos Core) has been archived to `archive/universal-dm-engine/`. Canonical AK character profiles live in the Obsidian vault.

## Sibling / Parent Project Context

Chronos Core is the engine inside the **digital-dm-project**, which unifies:

| Component | Path | Role |
|---|---|---|
| Chronos Core (engine) | `chronos-core/` | This handoff — the rules sim + TUI |
| Guild RPG campaign vault | `guild-rpg-digital-dm/` | Aelthar Keldor: characters, lorebooks, economy docs, meta |
| Shota x Monsters expansion | `shota-monsters-digital-dm/` | **Now includes:** `master_monsters.db` (v1.2, cross-game), `import_sxm1_text.py` (RVTEXT import + memo PK migration), `build_chromadb.py` (semantic index, 5,625 vectors), `besm_from_db.py` (339 BESM monster files), Weebly JSONs + game data. Living handoff: `HANDOFF-shota.md`. **Canonical-boundary note:** `master_monsters.db` is the canonical data source — the `besm/` files (457 lore/memo extracts) are pre-processed artifacts from an earlier manual pass, and overlap with DB rows by design. Don't reconcile them; the DB wins. |
| Universal DM Engine | `~/dev/universal-dm-engine/` | BESM 4e rulebooks (PDF + text), kernel/shell prompts, item generators |
| Design proposals | `proposal/` | Feature proposals awaiting review |

## Next Session Priorities

1. ~~**Add a pytest suite**~~ → **425 tests across 14 suites.** Remaining coverage gaps: `test_guild_roster.py` (CRUD + BESM loadout) and `test_batch_ingest.py` (card parsing).
2. **Wire Combat Maneuvers** — `/maneuver` command (tactical stances, called shots, grappling, multi-target)
3. **Wire Status Ailments** — poisons, sleep, paralysis, mind control at runtime
4. **Implement diceless TCR formula** — alternative resolution mode (deterministic, no dice)
5. ~~**Move DEFAULT_SETTINGS to config**~~ ✅ Done 2026-08-14 — list now lives in `config/settings.json`, loaded by `engine/config.py`, imported by `engine/guild_roster.py`
6. ~~**Archive `backfill_besm.py`**~~ ✅ Done 2026-08-14 — moved to `dev/archive/chronos-core/backfill_besm.py`
7. **Tune Nieven's narrative syntax** — needs extended live play
8. **Apply Item CP pricing** to shop catalog refinement
9. **Ingest the monster cards (big opportunity)** — persona-etl (08-16) shipped **all 339 SillyTavern V2 monster-boy cards** from the SxM1 bestiary (`persona-etl/output/`, catalog complete). Drop them in `staging/raw/` and run `auto-ingest` to balloon the Shota setting's roster from 3 to all 339 species. **As of 2026-08-18 the deterministic `engine/card_to_besm.py` emits the METHOD 1 SYSTEM DATA block straight from the card's markdown Combat Profile — next step is a staging prep script that copies cards + injects that block before `batch_ingest` runs.**
10. **Promote to big rig** — once stable, Megane handles the copy

---

*Handoff updated 2026-08-18. Chronos Core v3 — the BESM 4e rules engine. 425 tests, local-only engine-scoped git. The Shota×Monsters data layer reached v1.2, and the card→BESM compiler now bridges the 339-card corpus to METHOD 1 deterministically — no LLM guesswork. The LLM narrates; Python enforces. The Sixth Guard is not a suggestion.*
