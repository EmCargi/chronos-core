---
project: digital-dm
date: 2026-08-13
status: active
test_count: "0 (compile + live LLM checks only, no formal test suite)"
git: not-enabled
---
# Chronos Core — Handoff Document

## Current State (2026-08-13)

Chronos Core is a **multi-setting tabletop RPG engine and interactive fiction sandbox** for the terminal. It pairs a Python-enforced BESM 4e (Tri-Stat System) rules simulation with local-LLM narrative generation via Ollama. V3 shipped on 2026-08-07 with full mechanical enforcement: Combat Techniques, Skills, Defects, and Shock Value are persisted in the roster DB and injected into every LLM shell turn. Two campaign settings are registered (Guild RPG + Shota x Monsters 2) with 11 characters total. The thin client runs the TUI; the big rig runs Ollama inference. No git, no tests, no CI — this is a studio tool.

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
    │       ├── engine/llm_bridge.py ── Ollama dispatch + BESA field formatters + prompt compilation
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
- `guild_rpg_roster.db` — the canonical catalog (settings, characters [22 cols with BESA loadout], power packs, items, wallets, inventory). Survives sessions.
- `chronos_session.db` — runtime state only (current vitals, active node, narrative history). Repopulated from the roster on launch.

## File Map

| File | Purpose | Lines | Tests |
|---|---|---|---|
| `chronos.py` | Main Rich TUI dashboard — command loop, HUD, vitals panel, all `/` commands | ~768 | — |
| `launcher.py` | Unified launcher (4 options: TUI / wizard / ingest / verify) | ~76 | — |
| `backfill_besa.py` | One-time BESM loadout backfill script (idempotent, all 7 characters) | ~227 | — |
| **`engine/`** | | | |
| `engine/guild_roster.py` | Canonical roster DB — settings, characters (22 cols), power packs, BESA loadout CRUD | ~693 | — |
| `engine/economy.py` | Item economy — items, wallets, inventory, Fibonacci pricing, rank-bracket consumables, seed catalog | ~461 | — |
| `engine/llm_bridge.py` | Ollama dispatch, BESA field formatters (techniques/skills/defects → markdown), prompt compilation, SafeFormatter | ~273 | — |
| `engine/state_manager.py` | Runtime session DB — vitals, navigation, chronology, checkpoint snapshots | ~285 | — |
| `engine/batch_ingest.py` | Character card importer — staging/raw/ → setting detection → roster DB → processed/failed/ | ~308 | — |
| `engine/char_wizard.py` | Interactive character creator — CP-budget checks, stat allocation, LLM-assisted | ~192 | — |
| `engine/models.py` | Pydantic v2 CharacterSchema (Tri-Stat + BESA fields + derived vitals) + `execute_action_check()` | ~67 | — |
| `engine/config.py` | Settings loader — reads `config/settings.json` with defaults fallback | ~46 | — |
| `engine/verify_dungeon.py` | Campaign module validator — 5-room structure + obstacle key checks | ~58 | — |
| `engine/__init__.py` | Package exports | ~30 | — |
| **`engine/prompts/`** | | | |
| `besm_shell.md` | LLM shell prompt (8 sections, 8 directives — includes BESA enforcement) | ~3,587 chars | — |
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

    # BESA rules fields (persisted in roster DB, injected into LLM shell prompt)
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

**Roster DB tables:** `settings`, `characters` (22 cols: stats + BESA + narrative syntax + card_json), `power_packs`, `items`, `character_wallets`, `character_items`

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
| **Non-destructive additive migration** | BESA columns added via `ALTER TABLE ADD COLUMN` with safe defaults. Existing data never touched. |
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
| Shota x Monsters characters | 3 (Jin, Mayor Ast, Sage Ios) | `data/guild_rpg_roster.db` |
| Campaign modules | 6 (sandbox, C-rank trial, 5-room dungeon, forest labyrinth, training yard, Tomoe volcano) | `modules/` |
| Item catalog (seeded) | 8 (healing salves, energy drafts, standard potions, etc.) | `data/guild_rpg_roster.db` |
| BESM rules reference files | 15 cheat sheets (~260 KB) + 2 source PDFs (53 MB) | `Digital DM Project/BESM Rules/` (local) |
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
- Checkpoint snapshots (pre-migration DB backup)
- `py_compile` clean on all files
- Live LLM tests: Rosivelle (Phobia: mice), Eira (Compassion Override), Tomoe (Vengeance Singularity), Liora (Perimeter Breach) — all enforced correctly

## What Doesn't Work Yet

- **No formal test suite** — compile + live LLM checks only. No `pytest`, no CI.
- **No git** — by design (private studio content, confidential character data).
- **No Combat Maneuvers runtime** — `/maneuver` command not wired (designed but not implemented)
- **No Status Ailments runtime** — poisons, sleep, paralysis defined in rules but not enforced at runtime
- **No diceless TCR formula** — alternative resolution mode designed but not implemented
- **Thin client can't run inference** — all LLM-dependent testing requires big rig Ollama
- **Nieven's narrative syntax needs tuning** — flagged for extended live play
- **`backfill_besa.py` not archived** — one-shot script still in root (keep for reproducibility)

## Known Frictions

| Friction | Impact | Fix Effort |
|---|---|---|
| No automated tests | BESA functions, economy math, and ingest logic have no regression protection | Medium — add pytest suite for deterministic subsystems |
| Big rig is the only inference node | Can't test LLM-dependent features on thin client | By design — thin client hardware limit |
| Nieven's data is confidential | Sourced from guild record AK-S-009, not for external sharing | By design — studio content |
| No reasoning-tag stripping | If a reasoning model is used on Ollama, thinking tags could pollute narrative | Low — port `clean_reasoning_response()` if needed |
| Settings hardcoded in `guild_roster.py` | `DEFAULT_SETTINGS` list is in code, not config | Low — move to `config/settings.json` |
| Economy uses `logging` module, not emoji print | Inconsistent with AGENTS.md style (but justified — TUI protection) | By design — logging to file is correct for TUI |
| `backfill_besa.py` still in root | One-shot script cluttering root | Low — move to `scripts/` or archive |

## How to Extend

### Run the engine
```bash
cd "Digital DM Project/chronos-core"
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
| `/loadout` | Show full BESA build |
| `/use <item_id>` | Consume a consumable |
| `auto-ingest` | Run staging sweep |

### Register a new setting
1. Add to `DEFAULT_SETTINGS` in `engine/guild_roster.py`
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
- **Git** is not enabled. By design — confidential character data (Nieven's guild record AK-S-009).
- **venv** is at `chronos-core/venv/` (project-local, not shared). Python is 3.12.3.
- **Logging** goes to `data/chronos_runtime.log` — not console (TUI protection). This is the one project that uses `logging` module instead of emoji print, by design.
- **Response times**: ~15-30 seconds per LLM turn on gemma4-v2 Q6_K.
- **External dependencies**: BESM 4e rules reference files (15 cheat sheets + 2 source PDFs) live in `Digital DM Project/BESM Rules/`. The original `universal-dm-engine/` (prompt-engineering predecessor to Chronos Core) has been archived to `archive/universal-dm-engine/`. Canonical AK character profiles live in the Obsidian vault.

## Sibling / Parent Project Context

Chronos Core is the engine inside the **Digital DM Project**, which unifies:

| Component | Path | Role |
|---|---|---|
| Chronos Core (engine) | `chronos-core/` | This handoff — the rules sim + TUI |
| Guild RPG campaign vault | `guild-rpg-digital-dm/` | Aelthar Keldor: characters, lorebooks, economy docs, meta |
| Shota x Monsters expansion | `shota-monsters-digital-dm/` | BESM 4e expansion: atlas, bestiary, lorebook, ruleset |
| Universal DM Engine | `~/dev/universal-dm-engine/` | BESM 4e rulebooks (PDF + text), kernel/shell prompts, item generators |
| Design proposals | `proposal/` | Feature proposals awaiting review |

## Next Session Priorities

1. **Add a pytest suite** — cover deterministic subsystems (models, economy math, roster CRUD, ingest parsing, dungeon validator). The BESA functions and Fibonacci pricing are pure math — perfect for unit tests.
2. **Wire Combat Maneuvers** — `/maneuver` command (tactical stances, called shots, grappling, multi-target)
3. **Wire Status Ailments** — poisons, sleep, paralysis, mind control at runtime
4. **Implement diceless TCR formula** — alternative resolution mode (deterministic, no dice)
5. **Move `DEFAULT_SETTINGS` to config** — settings list should be in `config/settings.json`, not hardcoded
6. **Archive `backfill_besa.py`** — move to `scripts/` or `archive/` (keep for reproducibility)
7. **Tune Nieven's narrative syntax** — needs extended live play
8. **Apply Item CP pricing** to shop catalog refinement
9. **Promote to big rig** — once stable, Megane handles the copy

---

*Handoff drafted 2026-08-13. Chronos Core v3 — the BESM 4e rules engine. 3,484 lines across 13 Python files, 11 characters, 6 modules, 2 settings. No tests, no git, no CI. The LLM narrates; Python enforces. The Sixth Guard is not a suggestion.*
