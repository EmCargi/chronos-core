---
project: digital-dm
date: 2026-09-08
status: active
test_count: 719 total = 719 pass, 1 skip, all runnable (2026-09-08)
git: "local-only, engine code scoped (2026-08-14)"
---
# Chronos Core — Handoff Document

## Current State (2026-09-08)

Chronos Core is a **multi-setting tabletop RPG engine and interactive fiction sandbox** with **two interfaces on one engine**: a terminal Rich TUI and a Streamlit browser dashboard. It pairs a Python-enforced BESM 4e (Tri-Stat System) rules simulation with local-LLM narrative generation via Ollama. V3 shipped on 2026-08-07 with full mechanical enforcement: Combat Techniques, Skills, Defects, and Shock Value are persisted in the roster DB and injected into every LLM shell turn. Multiple settings are registered (Guild RPG, Shota x Monsters 2, My Hero Academia, plus training-yard / Tomoe packages). The thin client runs the TUI *and* the web port; the big rig runs Ollama inference. **719 tests (719 pass, 1 skip) — every engine path regression-checked, including the roster/ingest importer suites + 37 headless web-port smoke tests.** Git was initialized 2026-08-14, **scoped to engine code only** — see Operational Notes for exactly what's excluded and why. As of 2026-08-22 the **Guild RPG cast + regions + organizations are wired into the live roster** via `engine/guild_ingest.py`, `engine/guild_region_ingest.py`, and `engine/guild_org_ingest.py` (deterministic extractors + safe-ingest guard, registry sheets as sole source of truth) — 45 guild_rpg character rows (38 adventurers + 7 bosses) + 16 location rows (4 macro-regions with full Narrative Syntax) + 1 organization row (Aelthar Keldor guild, full NS), see Lineage / What Works.

**Web port shipped 2026-09-07** — `browser_chronos.py` is a Streamlit dashboard mirroring the proven `browser_aeiou.py` shape: sidebar disc/roster selectors (model, setting, active node, home org) + vitals HUD (`st.metric`/`st.progress` for HP/EP/Shock/ACV/DCV) + `st.chat_input` command handler dispatching AI Director turns through the same `LLMBridge` fallback chain. All `engine/` code is reused via `sys.path` bootstrap — zero rules-logic changes. Session state is isolated to `chronos_web_session.db` (CP-2), the full triangulation trail lives in `changelog/proposals/2026-09-07-chronos-core-streamlit-port.md` + `changelog/counterplans/2026-09-07-chronos-core-streamlit-port.md`, and the milestone journal is `dev-journal/2026-09-07-chronos-core-streamlit-port.md`. Launch with the `chronos-ui` zsh alias.

**Command palette wired 2026-09-08** — the browser now mirrors the TUI's dispatch: **26 commands** resolve with zero LLM calls (14 Phase A display + 11 Phase B deterministic math + `/startgreeting`), and `/loot` stays LLM-driven but session-scoped. Phase C economy writes (`/buy`, `/grant`, `/use`, `/provision`) are **deferred** — they'd hit the canonical roster DB via `get_economy_connection()` (CP-2 conflict, see Known Frictions). Triangulated across proposal + counter-plan rounds 1-3 (CP-1..CP-11); journal at `dev-journal/2026-09-08-chronos-core-web-commands.md`.

## Greeting Coverage (2026-08-23)

All **38 linked adventurer rows** have Character-Markdown greetings (First Message + Alternate Greeting N), parsed by `engine/guild_roster.parse_greetings_from_markdown` from the vault `Character Markdowns/`. Greeting blocks may be delimited by bare headers (`First Message`), SillyTavern `|` tables, `GREETINGS:` sections, or **H5 headers** (`##### Alternate Greeting N`); the parser also strips honorific prefixes in `Name:` fields (Professor, Archdruid, …) and accepts `_…_` / `*…*` italic scene prose. New vault markdowns use the H5 convention; `link_greetings_dryrun.py` links rows → markdowns idempotently (it will NOT override an existing `md_source_path`, so force-set via `set_character_md_path` when a card is split/renamed).

**The 7 unlinked rows are INTENTIONAL — do NOT treat them as greeting gaps to fill:**
- `Chieftain Gruk'thar` (A-Elite) — reusable humanoid-threat template (orcs, bandits, etc.); same asset-class as the bosses.
- The 6 bosses: `The Abyssal Behemoth`, `The Undead Guardian`, `Korvath`, `Nythera`, `The Thunderheart Titan`, `Zarkoth` — hostile-only entities; their BESM boss sheets hold action syntax, the markdown vault is reserved for narrative + greetings of actual NPCs.

**Sixth Guard leak auditor (2026-08-23):** `validate_sixth_guard.py` pulls each character's `sixth_guard` from the roster and judges every greeting via Cydonia (big-rig), flagging a greeting ONLY if it asserts immunity / permanent cure / the guard can never trigger. Player softening (meet-hook), planning/embracing the guard, and one-time emergency measures all resolve to HONORS. Re-run with `--only <name>` after any greeting edit. **Audit result 2026-08-23: 45 characters audited (38 with greetings), 0 leaks** — see `sixth_guard_audit_report.md`.

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
| 2026-08-18 | — | `2026-08-18-chronos-core-card-staging-first-ingest.md` | **Cards staged + first ingest: Shota roster 3 → 97.** `stage_cards.py` copies statted cards (94/339; the rest are lore-only SxM2) into `staging/raw/` with the compiled SYSTEM DATA block injected, idempotent + atomic. Live `batch_ingest` sweep: **94/94 processed, 0 failed**, DB checkpoint saved, tier spread T1×25 / T2×27 / T3×19 / T4×13 / T5×10. |
| 2026-08-18 | — | `2026-08-18-chronos-core-roster-ingest-test-suite.md` | **Full coverage closed: 469 tests green.** `test_guild_roster.py` (28: CRUD, settings, power packs, BESM loadout, markdown greetings, threats/locations/tournaments) + `test_batch_ingest.py` (10: METHOD 1 SYSTEM DATA parse, processed-file moves, offline METHOD 3 fallback, invalid-JSON + out-of-bounds failure paths, custom settings, power-pack registration). Both suites redirect roster DB + staging dirs to tmp_path so live `data/` is never touched. |
| 2026-08-18 | — | — | **Git aligned to working tree.** The engine evolution that predated git's scope (BESM mechanics expansion in `models.py` — obstacle/edge dice, resistance; `guild_roster.py` +326; `chronos.py` +343; fallback-chain `THIN_MODEL` in config) plus the 14 legacy mechanics test suites (407 tests, incl. bond progression) were uncommitted. Everything now under git: **18 suites, 470 tests (469 pass, 1 skip)** — the true project state. No proposal; git housekeeping. |
| 2026-08-18 | — | `2026-08-18-chronos-core-bond-progression-backfill.md` | **Bond Progression Framework V2.0 documented** — the framework in `engine/models.py` (4 phases, 7 gains, 4 losses, Shared Triumph / Favoritism Tax / group stats) and its 24-test suite were untracked and untallied until the git alignment. Now: file-map row, What Works bullet, journal entry — the true 470-test state is fully on the record. |
| 2026-08-18 | — | `2026-08-18-chronos-core-diceless-tcr.md` | **Diceless BESM shipped** (`engine/models.py`) — `compute_tcr()` implements Extras Ch.9 Total Combat Roll with per-term rounding, `resolve_diceless_combat()` maps MoS to Table-15 bands, `hedged_check()` gives the auto-7 non-combat path. 32 tests incl. the Kozoh/Azok canonical example (19 vs 17 → Slight Success). |
| 2026-08-18 | — | `2026-08-18-chronos-core-combat-maneuvers.md` | **Combat Maneuvers arsenal shipped** (`engine/models.py`) — tactical stances (one per round: aim/wait escalate minor→major; total defence halts attacks), the full called-shot table, two-weapon attacks, strike-to-wound, touch attacks, the grapple/pin/escape state machine, and multi-target dispersion. 46 tests grounded in the Extras cheat sheet. |
| 2026-08-18 | — | `2026-08-18-chronos-core-status-ailments.md` | **Status Ailments completed** (`engine/models.py`) — poison delivery vectors (injury/contact/ingested/inhaled with AR vs airtight/mask immunity, ingested ×2), continuing-decay ticks, field treatment vs Blight TN, sleep-break vs magic-only paralysis/stone, stun recovery at Body/hour, and the mind-control stack (gradient L1-6, opposed break + Mind Shield, against-nature edges, Exorcism clash). 36 tests.
| 2026-08-18 | — | `2026-08-18-chronos-core-shop-catalog-finalize.md` | **Shop catalog finalized to the AK docs.** Jaxon's full shelf now seeded: added **Beast-Repellent Powder (5 sp, D)** and **Flash-Powder Vial (20 sp, C)** with the doc effects; all six canonical shop prices verified (4 / 7 / 5 / 25 / 30 / 20 sp). 2 regression tests locked the doc prices. Economy 44 → 46, catalog 8 → 10. Priority #8 struck. |
| 2026-08-18 | `changelog/proposals/2026-08-18-chronos-core-besm-item-catalog.md` | `2026-08-18-chronos-core-besm-item-catalog.md` | **BESM source-book items as reusable assets shipped.** `scripts/extract_besm_catalog.py` compiles the read-only ledger (105 weapons / 29 armor / 25 shields / 8 suits / 42 gear / 11 vehicles = **220 rows**) into `engine/besm_catalog.py`'s generated data block (fail-fast subtotal contract + atomic marker-block regeneration). `seed_besm_catalog(setting_id, eras, categories, item_types, price_cap_sp)` provisions any setting idempotently; `rank_for_cp()` derives silver-bracket guild ranks (0→D, >800 sp→S, SS GM-only). Counter-plan rulings all adopted; full suite 586 → 606 (20 new besm tests). | |
| 2026-08-19 | — | `2026-08-19-chronos-core-tui-wiring-complete.md` | **The wiring pass.** `/diceless` (clash + `/diceless hedge` auto-7) and `/maneuver` (stance / two-weapon / strike / touch / called / grapple / grabbed / escape / pin / multi) reach the TUI; a **node-bound `scene_effects` ledger** gives the two last consumables a real effect (repel_animals wards the campsite node, blind staggers the monster group at its node, rounds tick on movement); `use_item()` takes `node_id`. **Latent blocker found:** `engine/__init__.py` never exported the ~40 model functions `chronos.py` imports — the TUI had been broken at import since the BESM expansion; export surface completed. Suite 610 → 616. | |
| 2026-08-19 | — | `2026-08-19-chronos-core-nieven-narrative-syntax.md` | **Nieven's Narrative Syntax tuned in the roster DB.** The stored fields were 5e/D&D-flavored (CR references, Displacer Beast, cantrips, spell-name lists) and his Sixth Guard read as a power-up, not a collapse. Rewritten in the peer pattern: **Institutionalized Symbiont** fault (the sheet's real wound — no self-owned will), **Chimeric Override (Weaponized Messiah)** guard that now costs him (he *enjoys* the Manticore apex he fled → no facade return, penance), and effect-prose levers. Roster DB checkpointed first; verified via accessor + LLM-shell injection. (Content tuning, no code/tests.) | |
| 2026-08-20 | — | `2026-08-20-setting-pack-contract.md` | **The console-and-disc model formalized.** `SETTING_PACK_CONTRACT.md` (repo root) codifies the 5-layer game-disc contract (registration / module / roster / economy / lore vault), the drop-in authoring procedure, and the two shipped discs as reference implementations. README + chronos-core README re-framed around the split. (Docs only — no code/DB/JSON touched.) | |
| 2026-08-20 | — | `2026-08-20-guild-cast-pullover-extractor.md` | **Guild RPG cast pullover extractor + dry run.** `engine/guild_pullover.py` parses both the legacy `### Basic` single files AND the new design-pass `Individual Action Syntax Card` registry sheets into `upsert_character()` payloads — no LLM. Registry sheets' explicit numeric stats (Body/Mind/Soul, ACV/DCV, HP/EP, CP) override the rank-tier ladder used for legacy files; canonical-name map (`Sylvara Duskveil`→`Sylvara`, `Tomoe Shirakane`→`Tomoe`) prevents duplicate rows; fence-tolerant NS parsing. `guild_pullover_dryrun.py` CLI reviews the sweep before any DB write. 17 new tests → 632 pass / 1 skip. Dry run: 31 payloads, 0 unresolved, 9 missing NS. **Roster DB untouched — ingest deferred until the design pass reformats the whole cast to registry format, then wired fresh (safe-ingest guard avoids clobbering the 6 hand-tuned rows).** |
| 2026-08-21 | `changelog/proposals/2026-08-21-chronos-core-sxm1-true-disk.md` | `2026-08-21-chronos-core-sxm1-true-disk-phase2.md` | **SxM1 "true disc" roadmap + Phase 1 Bestiary pullover shipped.** Proposal defines the 5-layer Setting Pack Contract roadmap to make SxM1 a first-class disc (registration ✓ already; module ✓; roster/economy/lore pending). Phase 1 = deterministic, LLM-free `engine/sxm1_pullover.py` + `sxm1_pullover_dryrun.py` mirroring the Guild approach: parses all 103 `sxm1-besm-folder/Bestiary/*.md` stat-block pages into `upsert_character()` payloads, handling both two-column and compact single-row stat layouts, explicit-over-derived stat precedence, verbatim Tamer's Memo in a `chara_card_v2` `card_json` envelope, and tier→rank ladder (Mob/Leader/Boss 25/60/120 CP). Skips the 18 data-sparse SxM2-only pages by design. 10 new tests → 642 total. **Dry run: 85 resolved, 18 skipped, 0 missing memo, 0 DB writes — live roster untouched (safe-ingest guard; the 94 card-derived rows kept separate per user).** |
| 2026-08-21 | `changelog/proposals/2026-08-21-chronos-core-sxm1-true-disk.md` | `2026-08-21-chronos-core-sxm1-true-disk-phase2.md` | **SxM1 Phase 2 — live safe ingest executed (Option B, Safe Add-Only).** `engine/sxm1_ingest.py` wires the Phase 1 parser into `guild_roster.upsert_character` behind a normalized-name safe-ingest guard: default add-only (inserts only Bestiary entries whose normalized name is absent from the roster), `--update-existing` enables Option A (canon upsert of the 76 overlaps), `--dry-run` previews. 3 new regression tests (normalization edges + add-only vs update-existing DB paths). **Live run: 97 → 105 rows (+8 novel: Demon, Digger Ant, Dogu Armor, Ice Swordsman, Odin, Phoenix, Plant Archer, Rafflesia), 0 existing rows mutated, 18 data-sparse skipped, 0 errors.** Backup: `data/guild_rpg_roster.db.bak.sxm1_ingest`. The SxM1 roster now blends the 94 card-derived rows + 3 presets + 8 curated Bestiary monsters as a first-class disc. | |
| 2026-08-22 | — | `2026-08-22-chronos-core-guild-live-ingest.md` | **Guild RPG cast live ingest executed (mirrors SxM1 Phase 2).** `engine/guild_ingest.py` wires `engine/guild_pullover.py` into `guild_roster.upsert_character` behind the same safe-ingest guard (default add-only; `--update-existing` for canon upsert; `--dry-run` preview). The dryrun `--base` now defaults to the `BESM Sheets/adventurers` registry folder (the roster's sole source of truth — legacy `Character Markdowns` retired). Extractor hardened to tolerate `[cite: …]` annotations, the `(EP / Mana)` label variant, and `[cite:]`-annotated lever lines. 5 new tests (`tests/test_guild_ingest.py`) → 651 total (650 pass / 1 skip). **First live run (add-only): 30 new adventurers inserted, 7 hand-tuned rows preserved. A subsequent `--update-existing` run upgraded all 37 sheet characters to the registry-sheet versions (Sylvara 155/250, Nieven 115/200, Eira 80/250, etc.). A later registry sheet for Liora (`liora-head-receptionist.md`) brought her in too, so all 38 guild_rpg rows are now sheet-derived → registry sheets fully canonical.** Pre-write checkpoints in `data/checkpoints/`. Bosses/regions/orgs deliberately out of scope (future entities). |
| 2026-08-22 | — | `2026-08-22-chronos-core-guild-training-grounds-playtest.md` | **Guild RPG training-grounds playtest passed live.** `modules/zarlen_training_grounds_v1.json` (5-room, Guild Training Grounds, Zarlen boss) validated by `verify_dungeon.py`, then played through all 5 nodes in the TUI against big-rig `gemma4-agentic-16k:latest`. Narrative Syntax injection proven live end-to-end: Kari (B-Rank spear-fighter) active POV surfaced her Structural Fault / Sixth Guard in generated prose; Zarlen's NS anchored the climax node. `ACTIVE_MODEL` repointed from the stale `gemma4-v2-Q6_K.gguf:latest` (404 on the rig) to the real `gemma4-agentic-16k:latest` tag. Registry-sheet → roster DB → `besm_shell.md` → Ollama pipeline now confirmed functional, not just unit-tested. |
| 2026-08-23 | f3d3396 | `2026-08-23-chronos-core-guild-org-ingest.md` | **Guild RPG organizations ingested (4th entity type).** New `BESM Sheets/organizations/` folder (source of truth, mirroring adventurers/bosses/regions) seeded with `aelthar-keldor-org-sheet.md` — the guild's "Institutional Narrative Sentence" (Subject + Grand Guard + 3 Levers) in the same NS layout as region sheets. `engine/guild_org_pullover.py` reuses the region NS parser; `engine/guild_org_ingest.py` (+ `guild_org_dryrun.py`) mirror the safe-ingest guard (add-only / `--update-existing` / `--dry-run`, checkpointed). A new `organizations` table (org-type / scale / leader / base / NS parity) was added non-destructively to `guild_roster.py`. **Live ingest: 1 organization (Aelthar Keldor) inserted with full NS, 0 `[cite]` pollution. 4 new tests → 659 total (658 pass / 1 skip).** | |
| 2026-08-23 | 3d528f9 | `2026-08-23-chronos-core-guild-org-shell-wiring.md` | **Guild org Narrative Syntax wired into the live shell (the hub/off-duty location).** The home guild is now a first-class backdrop for the AI Director, not just a roster row. `chronos.py:build_vitals_with_full_loadout` merges the active org's NS (Structural Fault / Grand Guard / 3 Levers + leader/base/type/scale) into the shell vitals; `engine/prompts/besm_shell.md` gained a "Home Guild / Hub" section; a new non-destructive `org_name` column in `campaign_navigation` persists the active guild via `engine/state_manager.py:save_runtime_snapshot`/`load_runtime_navigation`; `/org <name>` + `/orgs` commands switch/list the active guild (mirroring `/char`/`/module`). Default hub = **Aelthar Keldor**. **Smoke-tested: compiled `besm_shell` carries the guild NS (Aelthar Keldor + Grand Guard), no leftover `{org_*}` placeholders.** 1 new test (`test_shell_injects_org_context`) → 660 total (659 pass / 1 skip). | |
| 2026-08-23 | 583a2b3 | `2026-08-23-chronos-guild-hub-greetings.md` | **Hub-anchored greeting starts (domestic greetings open at the guild hall).** With the guild as a hub, character greetings double as campaign/player starting points. `engine/guild_roster.py` gained `classify_greeting()` (domestic vs field vs neutral, keyword-driven) and `format_greeting_list()` now tags each `/greetings` entry `[Hub]` (guild hall/tavern/library) or `[Quest]` (forest/quest/field). `chronos.py:build_greeting_start()` builds the opening node: domestic greetings anchor to `node_id=hub_guildhall`, `title="{org} Guildhall"` (so the hub is the literal starting location), field greetings stay on a generic quest node; `/startgreeting <n>` sets `active_node` to that node and persists it via `save_runtime_snapshot`. **Live-verified on Eira: 10 greetings tag 1/2/5/7/10 as `[Hub]`, 3/4/6/8/9 as `[Quest]`; a domestic greeting renders the AI Director opening at the Aelthar Keldor Guildhall.** 9 new tests (`tests/test_greeting_hub.py`) → 669 total (668 pass / 1 skip). | |
| 2026-08-23 | `changelog/proposals/2026-08-21-chronos-core-sxm1-true-disk.md` | `2026-08-23-chronos-core-sxm1-economy-seed.md` | **SxM1 economy seeded in Gold (Phase 3 of the true-disc roadmap).** `engine/sxm1_economy_catalog.py` carries 63 BESM-grounded items (Gold model `50 × cost × category_mult`, validated vs the 4 confirmed peddler baselines — Potion 50G, Dodeka 200G, Fairy Revival 300G, Smoke Bomb 150G); `economy.py` gained a per-setting `currency` column so Guild RPG stays silver and SxM1 stays Gold; `seed_sxm1_economy()` + per-setting G/sp display; `sxm1_ingest.py` dedup-hardened (Lion Dancer / Lion dancer collision folds into the canonical row, idempotent re-runs). 20 new `test_economy.py` tests → 689 total (688 pass / 1 skip). | |
| 2026-09-07 | `changelog/proposals/2026-09-07-chronos-core-streamlit-port.md` | `2026-09-07-chronos-core-streamlit-port.md` | **Streamlit web port shipped (browser_chronos.py) — the terminal TUI grows a browser dashboard.** Triangulated (proposal → counter-plan CP-1..CP-5 → synthesis). Reuses all `engine/` code via `sys.path` bootstrap; `set_active_db_path()` isolates the web session to `chronos_web_session.db` (CP-2); `load_campaign_module` + `roster_dict_to_char` moved to `engine/guild_roster.py` as the canonical copies (R5 — web port is `rich`-free); pure read-only math only under `@st.cache_data` (CP-1); LLM dispatch never cached + `strip_reasoning_tags()` verified (CP-4); `streamlit-aggraph` dropped for markdown-card nav (CP-5). Bootstrap sentinel (CP-3) survives Streamlit re-exec. 6 new `test_browser_smoke.py` headless AppTest tests → 687 total (687 pass / 1 skip). `chronos-ui` zsh alias added. | |
| 2026-09-08 | `changelog/proposals/2026-09-08-chronos-core-web-commands.md` | `2026-09-08-chronos-core-web-commands.md` | **Command palette wired — the browser grows the TUI's dispatch.** Triangulated across 3 counter-plan rounds (CP-1..CP-11). Phase A: 14 read-only display branches (`/roster` `/lore` `/settings` `/shop` `/wallet` `/inventory` `/loadout` `/greetings` `/engine` `/scv` `/techniques` `/defects` `/effects` `/location` `/threat`) — zero LLM. Phase B: 11 deterministic math branches (`/shock` `/resist` `/fall` `/range` `/size` `/defence` `/sanity` `/recover` `/diceless` `/maneuver` `/attack`) — zero LLM, `try/except` usage guards (CP-5), Rich-tag-only stripper preserves `[Hub]`/`[Quest]`/`[D-Rank]` (CP-9/CP-9H). Phase D: `/startgreeting` — node committed first (CP-4), synthetic node injected into the active disc's map (CP-10/CP-10H); `build_greeting_start` + `build_vitals_with_full_loadout` relocated to canonical engine home (CP-7), thin delegators in `chronos.py`. Phase C: **deferred** — `/buy` `/grant` `/use` `/provision` would write to the canonical roster DB via `get_economy_connection()` (CP-2 conflict, CP-11); `/loot` shipped (session-scoped). `test_browser_smoke.py` 6 → 37 → **719 pass / 1 skip**. | |

## Architecture Overview

```
chronos-core/
    │
    ├── launcher.py ── Unified launcher (4 options: TUI / wizard / ingest / verify)
    │
    ├── chronos.py ── Rich TUI dashboard (command loop + HUD + vitals panel)
    │
    ├── browser_chronos.py ── Streamlit web port (sidebar selectors + vitals HUD + chat input + full command dispatch)
    │       │
    │       ├── engine/state_manager.py ── Runtime session state (vitals, nav, chronology) + set_active_db_path()
    │       ├── engine/guild_roster.py ── Canonical roster DB (settings, characters, power packs) + load_campaign_module/roster_dict_to_char
    │       ├── engine/economy.py ── Items, wallets, inventory, silver price curves
    │       ├── engine/llm_bridge.py ── Ollama dispatch + BESM field formatters + prompt compilation
    │       ├── engine/models.py ── Pydantic v2 CharacterSchema + Tri-Stat derived vitals
    │       ├── engine/batch_ingest.py ── Character card importer (staging/raw/ → processed/failed/)
    │       ├── engine/char_wizard.py ── Interactive character creator with CP-budget checks
    │       └── engine/verify_dungeon.py ── Campaign module structural validator (5-room check)
    │
    ├── config/settings.json ── LLM model, Ollama URL, default rules + setting
    ├── modules/ ── Campaign node maps (8 modules across 3 settings)
    ├── data/
    │   ├── guild_rpg_roster.db ── SOURCE OF TRUTH (settings, characters, items, wallets, inventory)
    │   ├── chronos_session.db ── CLI runtime state only (repopulated from roster on launch)
    │   ├── chronos_web_session.db ── Web port runtime state only (isolated from CLI — CP-2)
    │   └── checkpoints/ ── Pre-migration DB snapshots
    └── staging/ ── Character card import queue (raw/ → processed/ + failed/)
```

**Three databases, one rule:**
- `guild_rpg_roster.db` — the canonical catalog (settings, characters [22 cols with BESM loadout], power packs, items, wallets, inventory). Survives sessions.
- `chronos_session.db` — CLI runtime state only (current vitals, active node, narrative history). Repopulated from the roster on launch.
- `chronos_web_session.db` — web port runtime state only, isolated so the browser dashboard never contends with a running TUI session (CP-2).

## File Map

| File | Purpose | Lines | Tests |
|---|---|---|---|
| `chronos.py` | Main Rich TUI dashboard — command loop, HUD, vitals panel, all `/` commands; `build_greeting_start`/`build_vitals_with_full_loadout` are now thin delegators to the engine canonical copies | ~768 | — |
| `browser_chronos.py` | **Streamlit web port** — sidebar disc/roster selectors (model, setting, node, org) + vitals HUD (`st.metric`/`st.progress`) + `st.chat_input` command handler dispatching AI Director turns via `LLMBridge`; bootstrap sentinel (CP-3); `set_active_db_path(WEB_SESSION_DB_PATH)` isolates the web session (CP-2); pure read-only math under `@st.cache_data` (CP-1); **full command dispatch** — 14 Phase A display + 11 Phase B math + `/startgreeting` + `/loot` (zero-LLM for deterministic, Director for free text/examine/loot); Rich-tag-only stripper (`_rich_to_markdown`, CP-9); `active_char_name` helper (CP-8); `_edge_label`/`_obstacle_label` | ~1,050 | — |
| `tests/test_browser_smoke.py` | Headless web-port tests (37: boot/title/sidebar/vitals/chat/node + Phase A display commands + Phase B math commands + Phase D greeting fallbacks + Rich stripper + greeting-tag survival) via `streamlit.testing.v1.AppTest` — session DB redirected to tmp_path | ~250 | 37 |
| `launcher.py` | Unified launcher (4 options: TUI / wizard / ingest / verify) | ~76 | — |
| ~~`backfill_besm.py`~~ | ~~One-time BESM loadout backfill script~~ | **Archived 2026-08-14** → `dev/archive/chronos-core/backfill_besm.py` |
| **`engine/`** | | | |
| `engine/guild_roster.py` | Canonical roster DB — settings, characters (22 cols), power packs, BESM loadout CRUD | ~693 | — |
| `engine/economy.py` | Item economy — items, wallets, inventory, Fibonacci pricing, rank-bracket consumables, multi-currency seed catalog (silver + Gold) | ~505 | — |
| `engine/besm_catalog.py` | **BESM canon as reusable assets** — generated data block (220 items) + hand-written `rank_for_cp` / `seed_besm_catalog` / `besm_catalog_summary` | ~3,350 | — |
| `tests/test_economy.py` | Economy tests (60: Fibonacci, brackets, wallets, item CRUD, catalog, buy, inventory, SxM1 Gold grounding) | ~430 | 60 |
| `engine/sxm1_economy_catalog.py` | **SxM1 (shota_x_monsters) economy seed** — 63 BESM-grounded items with the validated Gold pricing model (50 × cost × category_mult) | ~230 | — |
| `tests/test_besm_catalog.py` | BESM catalog tests (20: contract, bench parity, rank ladder, idempotent/filtered/non-destructive seeding) | ~230 | 20 |
| `engine/llm_bridge.py` | Ollama dispatch, BESM field formatters (techniques/skills/defects → markdown), prompt compilation, SafeFormatter | ~273 | — |
| `engine/state_manager.py` | Runtime session DB — vitals, navigation, chronology, checkpoint snapshots | ~285 | — |
| `engine/batch_ingest.py` | Character card importer — staging/raw/ → setting detection → roster DB → processed/failed/ | ~308 | — |
| `engine/card_to_besm.py` | **Deterministic SxM card → BESM compiler** — HP table → tier → archetype → stat block → `[SYSTEM DATA: BESM 4E MECHANICS]` block for METHOD 1 | ~350 | — |
| `engine/guild_pullover.py` | **Guild RPG cast pullover extractor** — parses legacy `### Basic` single files AND design-pass `Individual Action Syntax Card` registry sheets into `upsert_character()` payloads (no LLM); explicit table stats override the rank-tier ladder; canonical-name map; fence-tolerant NS parsing | ~410 | — |
| `guild_pullover_dryrun.py` | **Dry-run review CLI** — sweeps the character markdowns through the extractor, prints every payload (table + `--json`), flags missing NS / unresolved files; skips pairs/trio/superseded/empty sources; never touches the roster DB | ~150 | — |
| `engine/sxm1_pullover.py` | **SxM1 Bestiary pullover extractor** — deterministic, LLM-free parse of `shota-monsters-digital-dm/sxm1-besm-folder/Bestiary/*.md` stat-block pages into `upsert_character()` payloads; handles two-column + compact single-row stat layouts, explicit-over-derived precedence, verbatim Tamer's Memo in a `chara_card_v2` card_json envelope, tier→rank ladder (Mob/Leader/Boss 25/60/120 CP); skips data-sparse SxM2-only pages + missing stat blocks + duplicate names | ~216 | — |
| `sxm1_pullover_dryrun.py` | **Dry-run review CLI** — sweeps the Bestiary through the extractor, prints every payload (table + `--json`), logs every skipped page with its exact reason; never touches the roster DB | ~155 | — |
| `engine/sxm1_ingest.py` | **Live safe-ingest** — wires the Phase 1 parser into `guild_roster.upsert_character` behind a normalized-name safe-ingest guard; default Option B add-only (insert only absent normalized names), `--update-existing` = Option A canon upsert, `--dry-run` preview; never writes skipped pages | ~150 | — |
| `tests/test_sxm1_pullover.py` | SxM1 pullover + ingest tests (13: full-page parse, data-sparse skip, missing-stat skip, explicit-over-derived, formula fallback, memo preservation, tier ladder, V2 envelope, duplicate-name skip, compact format, normalization edges, add-only, update-existing) | ~320 | 13 |
| `engine/guild_region_pullover.py` | **Guild RPG region pullover extractor** — deterministic, LLM-free parse of `BESM Sheets/regions/*.md` macro-location sheets into `upsert_location()` payloads; handles the region YAML `SUBJECT`/`THE ANCHOR` NS blocks + both Capital (`**The Strategy:**`) and boss-style (`- Strategy:`) lever formats; `[cite:]` stripped from name + NS | ~210 | — |
| `guild_region_dryrun.py` | **Dry-run review CLI** — sweeps the region sheets through the extractor, prints every payload, flags missing NS / unresolved files, skips the Guild/World/Methods non-region sheets; never touches the roster DB | ~60 | — |
| `engine/guild_region_ingest.py` | **Live safe-ingest** — wires the region parser into `guild_roster.upsert_location` behind a normalized-name safe-ingest guard; default add-only, `--update-existing` = canon upsert, `--dry-run` preview; skips non-region sheets | ~110 | — |
| `tests/test_guild_region_ingest.py` | Region pullover + ingest tests (4: boss-style NS extraction, capital-style NS extraction, add-only leaves seeded, update-existing enriches) | ~150 | 4 |
| `engine/guild_org_pullover.py` | Org/guild LLM-free extractor; reuses the region NS parser (`extract_narrative_syntax`); reads the Basic block (type / scale / leader / base) + the fenced yaml NS card | ~90 | — |
| `engine/guild_org_ingest.py` | Org live safe-ingest (mirrors `guild_region_ingest`); add-only / `--update-existing` Canon Upsert / `--dry-run`; checkpointed; writes `organizations` table | ~110 | — |
| `engine/guild_org_dryrun.py` | Org ingest dry-run preview (no writes) | ~30 | — |
| `tests/test_guild_org_ingest.py` | Org pullover + ingest tests (4: metadata+NS extraction, dark-guild type+inline guard, add-only leaves seeded, update-existing enriches) | ~165 | 4 |
| `stage_cards.py` | **Staging prep** — copies statted cards from corpus into `staging/raw/` with SYSTEM DATA block injected; skips lore-only cards; idempotent atomic writes | ~130 | — |
| `conftest.py` | Pytest root bootstrap — puts `dev/` + `chronos-core/` on sys.path so `core.ollama` imports | ~12 | — |
| `engine/char_wizard.py` | Interactive character creator — CP-budget checks, stat allocation, LLM-assisted | ~192 | — |
| `engine/models.py` | Pydantic v2 CharacterSchema (Tri-Stat + BESM fields + derived vitals) + action/shock/incapacitation/poison checks | ~170 | — |
| `tests/test_models.py` | Model tests (27: schema validation, tri-stat vitals, SV caps, action checks) | ~210 | 27 |
| `tests/test_status_effects.py` | Status tests (27: obstacle dice, shock/knockout, incapacitation, poison resistance) | ~200 | 28 |
| `tests/test_status_ailments.py` | Status ailment tests (36: poison vectors, continuing ticks, decay survival, field treatment, sleep-break vs paralysis/stone, stun recovery, mind-control gradient + break + exorcism) | ~250 | 36 |
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
| `tests/test_stage_cards.py` | Staging prep tests (6: discovery, idempotent injection, statted vs lore-only screening, real-corpus 94 check) | ~80 | 6 |
| `tests/test_bond_progression.py` | Bond Progression Framework V2.0 tests (24: phases, gain/loss tables, Shared Triumph, Favoritism Tax, group stats) | ~155 | 24 |
| `tests/test_bond_progression.py` | Bond Progression Framework V2.0 tests (24: phases, gain/loss tables, Shared Triumph, Favoritism Tax, group stats) | ~155 | 24 |
| `tests/test_diceless.py` | Diceless BESM tests (32: TCR formula + rounding, Table-15 MoS bands, Kozoh/Azok canonical, auto-7 hedging) | ~230 | 32 |
| `tests/test_combat_maneuvers.py` | Combat maneuvers tests (46: tactical stances, two-weapon, strike-to-wound, touch, called shots, grappling, multi-target dispersion) | ~250 | 46 |
| `tests/test_guild_roster.py` | Roster CRUD tests (28: init/settings, character upsert + retrieval, BESM loadout, markdown greetings, power packs, summaries, threats/locations/tournaments) | ~270 | 28 |
| `tests/test_batch_ingest.py` | Importer tests (10: METHOD 1 SYSTEM DATA parse, file moves, offline fallback, failure paths, custom settings, power packs) — roster DB + staging redirected to tmp_path | ~150 | 10 |
| `tests/test_guild_pullover.py` | Pullover extractor tests (17: legacy single + `<Name>` pair split, metadata variants, NS extraction, rank-tier + registry explicit stats, canonical names, registry syntax-card parsing) | ~240 | 17 |
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

**Roster DB tables:** `settings`, `characters` (22 cols: stats + BESM + narrative syntax + card_json), `locations` (10 cols: atlas + `structural_fault` / `sixth_guard` / `levers` NS parity via `upsert_location()`), `power_packs`, `items`, `character_wallets`, `character_items`

**Session DB tables:** `character_vitals`, `campaign_navigation`, `character_inventory`, `scene_effects` (node-bound transient effects — ward/blind, round-budgeted, ticked on movement)

**Active Narrative Syntax** (3 fields per character AND per location, persisted in roster, injected into every LLM turn):
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
| Guild RPG characters | 45 (38 registry-sheet adventurers incl. Liora's `liora-head-receptionist.md` + 7 bosses from `BESM Sheets/bosses`) | `data/guild_rpg_roster.db` |
| Guild RPG locations | 16 (12 seeded atlas rows + 4 macro-regions from `BESM Sheets/regions/` — The Capital City, Inewell, Srurpolis, The Vardun Wood — all 4 carrying full Narrative Syntax) | `data/guild_rpg_roster.db` |
| Shota x Monsters characters | 97 (3 named + 94 ingested monster-boys from the 339-card corpus; **245 lore-only cards wait for SxM2 stats**) | `data/guild_rpg_roster.db` / `persona-etl/output/` |
| Campaign modules | 6 (sandbox, C-rank trial, 5-room dungeon, forest labyrinth, training yard, Tomoe volcano) | `modules/` |
| Item catalog (seeded) | 10 (Jaxon's full shop: salve, draft, beast-repellent, potion, antidote, flash-powder + Rosivelle's permanents) | `data/guild_rpg_roster.db` |
| SxM1 item catalog (seeded) | **63** (all `master_monsters.db` game='sxm1' items: healing/cures/revival/tags/mana-stones/stat-ups/taming/utility/sellable/special) — BESM Item Cost from `Mechanics/08_Item_Conversions.md`, Gold prices via `50 × cost × mult` (validated vs the 4 confirmed peddler baselines) | `data/guild_rpg_roster.db` (setting `shota_x_monsters`, currency=gold) |
| BESM canon catalog (provisionable) | **220** (105 weapons, 29 armor, 25 shields, 8 suits, 42 gear/artifacts, 11 vehicles) — compiled from the source-book ledger | `engine/besm_catalog.py` + `BESM Rules/besm-weapons-armor-gear-reference.md` |
| BESM rules reference files | 15 cheat sheets (~260 KB) + 2 source PDFs (53 MB) | `digital-dm-project/BESM Rules/` (local) |
| Session run records | 2 | `SESSION_RUN_RECORD_*.md` |

## What Works

- **Streamlit web port (2026-09-07)** — `browser_chronos.py` gives Chronos a browser dashboard: sidebar disc/roster selectors (model, setting, active node, home org), vitals HUD (HP/EP/Shock/ACV/DCV via `st.metric`/`st.progress`), and an `st.chat_input` command handler that dispatches AI Director turns through the same `LLMBridge` fallback chain as the TUI. All `engine/` code reused unchanged via `sys.path` bootstrap; the web session DB is isolated to `chronos_web_session.db` via `set_active_db_path()` so the CLI is never disturbed. 6 headless AppTest smoke tests. Launch with the `chronos-ui` zsh alias. (Full triangulation: proposal + counter-plan CP-1..CP-5 + milestone journal, all dated 2026-09-07.)
- **Command palette wired (2026-09-08)** — the browser now mirrors the TUI dispatch: **26 commands** resolve with zero LLM calls. Phase A display (14): `/roster` `/lore` `/settings` `/shop` `/wallet` `/inventory` `/loadout` `/greetings` `/engine` `/scv` `/techniques` `/defects` `/effects` `/location` `/threat`. Phase B deterministic math (11): `/shock` `/resist` `/fall` `/range` `/size` `/defence` `/sanity` `/recover` `/diceless` `/maneuver` `/attack` — arg parsing guarded (`try/except` → usage feed message), Rich markup stripped but semantic `[Hub]`/`[Quest]`/`[D-Rank]` preserved (CP-9). `/startgreeting` commits its node then fires the Director opening (CP-4/CP-10/CP-10H). Only free text, `examine`, and `/loot` reach the LLM. Phase C economy writes deferred (see What Doesn't Work Yet). 37 headless AppTest tests. (Triangulation: proposal + counter-plan rounds 1-3 CP-1..CP-11 + milestone journal, dated 2026-09-08.)
- Multi-setting roster (2 settings, 11 + 30 guild sheet characters = 41; plus 105 SxM1 rows)
- BESM 4e rules enforcement (Combat Techniques, Skills, Defects, Shock Value)
- Active Narrative Syntax injection (Structural Fault, Sixth Guard, Three Levers)
- Tri-Stat derived vitals (HP, EP, ACV, DCV, Shock Value)
- 2d6 action checks with difficulty targets
- Item economy (Fibonacci permanents, rank-bracket consumables, wallets, inventory) — **Jaxon's shop fully seeded 2026-08-18** (Beast-Repellent Powder 5 sp + Flash-Powder Vial 20 sp added; all six doc prices regression-locked, catalog 8 → 10)
- **SxM1 economy seeded 2026-08-23** — `shota_x_monsters` now carries the 63-item Gold catalog (`engine/sxm1_economy_catalog.py`), BESM Item Cost from `Mechanics/08_Item_Conversions.md`, prices validated against the 4 confirmed Watt/Reo peddler baselines (Potion 50G, Dodeka 200G, Fairy Revival 300G, Smoke Bomb 150G) via a `50 × cost × category_mult` Gold model; `economy.py` gained a `currency` column so Guild RPG stays silver and SxM1 stays Gold.
- **BESM canon as reusable assets (2026-08-18)** — `engine/besm_catalog.py` carries the full source-book item canon (**220 items**, compiled deterministically from the read-only ledger by `scripts/extract_besm_catalog.py` with a fail-fast subtotal contract). `seed_besm_catalog(setting_id, eras, categories, item_types, price_cap_sp)` provisions any setting idempotently (INSERT OR IGNORE — never stomps authored rows), and `rank_for_cp()` assigns silver-bracket guild ranks (0→D … >800 sp→S). All prices flow through the existing Fibonacci engine; the live `guild_rpg` shop is never auto-seeded (explicit-only, per 2026-08-18 synthesis).
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
- **Deterministic card → BESM compiler + first ingest (2026-08-18)** — `engine/card_to_besm.py` turns statted cards into METHOD 1 SYSTEM DATA blocks with zero LLM calls; `stage_cards.py` staged the 94 statted cards and a live sweep ingested **94/94 → Shota roster 3 → 97** (T1×25 / T2×27 / T3×19 / T4×13 / T5×10). Verified by 25 contract tests.
- **Full test suite runnable (2026-08-18)** — root venv's corrupted pytest reinstalled + `conftest.py` bootstrap; **469 passed, 1 skipped (470 total)** for the first time (legacy suites previously couldn't import `core.ollama`).
- **Bond Progression Framework V2.0 shipped inside `engine/models.py` (2026-08-18)** — trust scores (0–100) clamp to 4 phases (Surface → Warmth → Confidant → Soulbound); 7 gain triggers (5–10 pts, intimacy once-per-phase) and 4 loss triggers (−15 to −50); Shared Triumph (+10 hero / +5 witnesses) and Favoritism Tax (−10 neglected NPCs). Backfilled from git housekeeping: `tests/test_bond_progression.py` (24) documents it — was untracked and untallied until the alignment pass.
- **Diceless BESM resolution (2026-08-18)** — `compute_tcr()` implements Extras Ch.9's Total Combat Roll (CV + ⌊dmg/10⌋ + ⌊HP/20⌋ + 2×ExtraActions + Mulligans + ⌊EP/10⌋ + edge − ⌊AR/10⌋ − 2×ExtraDefences − obstacle, every term rounded down); `resolve_diceless_combat()` maps MoS to Table-15 outcome bands with HP-loss percentages; `hedged_check()` handles non-combat via the auto-7 baseline (BESM4 p182). Deterministic, zero roll calls.
- **Combat Maneuvers arsenal (2026-08-18)** — tactical stances (aim → ranged minor/major edge by consecutive round; wait-for-opening melee analog; total defence = major defence edge, attacks off), the full called-shot table (disarm melee/ranged with TN 15 Body check, reduce/bypass armour, vital spot ×2, weak points with defender edges), two-weapon attacks (single/minor, two/major, negated by Two Weapons technique), strike-to-wound, touch attacks, the full grapple/pin/escape state machine (free-hand edges, size overload, paralysis, pain-dissociation escape at 5×Body), and multi-target dispersion (N-target obstacle + defender edge curve). All 46 tested, grounded in the Extras cheat sheet.
- **Status Ailments complete (2026-08-18)** — the ledger's four poison vectors enforce AR/Force-Field vs airtight/gas-mask immunity (injury only penetrates if neither layer absorbs the blow; ingested doubles), continuing-decay ticks (20%/round with hourly-major / daily-minor TN 15 survival), field treatment against the Blight TN ladder, sleep-wakes-on-noise-vs-magic-only paralysis/stone, stun recovery at Body/hour, and the full cognitive layer (Mind Control gradient L1-6, opposed break with Mind Shield +2/level, against-nature edges, Exorcism clash with controller-alert on failure). 36 tests.
- **Full TUI wiring (2026-08-19)** — every engine fights on the prompt now. `/diceless <cv> [AR] [extra_def] [edge]` shows the TCR contributor breakdown + Table-15 MoS band and HP losses; `/diceless hedge <target> [stat]` runs the auto-7 non-combat path; `/maneuver` exposes the whole arsenal (tactical stances with consecutive-round edge escalation, two-weapon single/split, strike-to-wound, touch, all called shots with technique reduction, grapple/grabbed/escape/pin, multi-target dispersion). `use_item()` consumes the two last tactical items: Beast-Repellent Powder wards its node and Flash-Powder Vial blinds the group at its node via a new **node-bound `scene_effects` ledger** (session DB — idempotent upsert, `rounds_remaining` budget, ticked on movement, exposed via `/effects`). Also fixed the latent import break: `engine/__init__.py` now exports every model function `chronos.py` needs — the TUI *actually starts* again.
- **Nieven's Narrative Syntax tuned to the peer pattern (2026-08-19)** — the roster DB's three enforced fields for Nieven now match how the rest of the guild is written (and his fan-character sheet): **Structural Fault → The Institutionalized Symbiont** (no self-owned will — a curated weapon, agency outsourced to an owner, passive dormancy when ownerless); **Sixth Guard → The Chimeric Override (the Weaponized Messiah)** (owner endangered → redlines into the Manticore-Lion apex, burning his Grove reserve — and the collapse is that *he enjoys* the weapon he fled, so the facade doesn't return and he sleeps in the dirt); **Levers → Desk Mascot Stasis / Golden Crowd-Fence / Escorted Retreat** in engine-native effect-prose. The old fields were 5e/D&D-flavored (CR 0 cat, Displacer Beast, cantrips, literal spell names) and read as a buff instead of a collapse.
- **Guild RPG cast pullover extractor + dry run (2026-08-20)** — `engine/guild_pullover.py` turns the vault character markdowns into `upsert_character()` payloads with **no LLM**. It parses **both** the legacy `### Basic` single files (narrative syntax from prose + YAML sentence block; stats derived from the rank-tier ladder) and the **design-pass registry sheets** (explicit numeric Body/Mind/Soul/ACV/DCV/HP/EP + CP budget read from the stats table; NS from the `Individual Action Syntax Card`'s SUBJECT/ANCHOR/PREDICATE YAML). Registry table stats **override** the ladder; the `CANONICAL_NAMES` map (`Sylvara Duskveil`→`Sylvara`, `Tomoe Shirakane`→`Tomoe`) prevents duplicate rows; NS parsing is **fence-tolerant** (a missing ```yaml fence never drops the syntax). `guild_pullover_dryrun.py` sweeps the whole cast and prints every payload (table + `--json`), auto-skipping pairs/trio/superseded/empty sources. **17 new tests → 632 total.** Dry run: **31 payloads ready, 0 unresolved, 9 missing NS.** Roster DB intentionally untouched.
- **SxM1 "true disc" roadmap + Phase 1 Bestiary pullover (2026-08-21)** — proposal `changelog/proposals/2026-08-21-chronos-core-sxm1-true-disk.md` defines the 5-layer plan to make SxM1 a first-class disc (registration + module already shipped; roster/economy/lore to follow). Phase 1 shipped `engine/sxm1_pullover.py` + `sxm1_pullover_dryrun.py`: deterministic, LLM-free parse of all 103 `sxm1-besm-folder/Bestiary/*.md` stat-block pages into `upsert_character()` payloads — handles both two-column (`| **Body** | 4 |`) and compact single-row (`| Body 5 | Mind 2 | ... |`) layouts, explicit-stats-over-derived precedence, verbatim Tamer's Memo in a `chara_card_v2` `card_json` envelope, and the tier→rank ladder (Mob/Leader/Boss = 25/60/120 CP). Skips the 18 data-sparse SxM2-only pages by design. **10 new tests → 642 total.** Dry run: **85 resolved, 18 skipped (all data-sparse), 0 missing memo, 0 DB writes** — the live roster (incl. the 94 card-derived monster rows) is untouched, so the SxM1 disc can be reconciled deliberately in Phase 2.
- **SxM1 Phase 2 safe ingest executed (2026-08-21)** — `engine/sxm1_ingest.py` wires the Phase 1 parser into the live roster behind a normalized-name safe-ingest guard (default Option B add-only; `--update-existing` = Option A canon upsert; `--dry-run` preview). **Live run: 97 → 105 rows (+8 novel monsters — Demon, Digger Ant, Dogu Armor, Ice Swordsman, Odin, Phoenix, Plant Archer, Rafflesia), 0 existing rows mutated, 18 data-sparse skipped.** The SxM1 disc roster now blends 94 card-derived + 3 presets + 8 curated Bestiary monsters. 3 new ingest regression tests → 645 total. The 76 overlapping Bestiary pages remain available for a deliberate `--update-existing` upgrade whenever you want the richer canon memos in the roster (non-destructive, re-runnable).
- **Guild RPG cast live ingest executed (2026-08-22)** — `engine/guild_ingest.py` mirrors the SxM1 pattern: deterministic `guild_pullover.py` parse → `guild_roster.upsert_character` behind the normalized-name safe-ingest guard (default add-only; `--update-existing` = canon upsert; `--dry-run` preview; pre-write DB checkpoint). The `guild_pullover_dryrun.py` `--base` now defaults to `BESM Sheets/adventurers` (sole source of truth). **Live run (add-only): 30 new adventurers inserted, 7 hand-tuned rows preserved. A subsequent `--update-existing` run made the registry sheets fully canonical — all 37 sheet characters upgraded to their sheet versions (Sylvara 155/250, Nieven 115/200, Eira 80/250 …). Liora now also has a registry sheet (`liora-head-receptionist.md`), so all 38 rows are sheet-derived. 38 guild_rpg rows total.** 5 new tests (`tests/test_guild_ingest.py`) → 651 total (650 pass / 1 skip). The sheets are now the sole source of truth; re-running `--update-existing` re-syncs any sheet edits.
- **Guild RPG boss cast ingested (2026-08-22)** — extended the pullover extractor to the *boss* sheet schema (which differs from adventurers): `**Character Name:**` / `**Power Bracket:**` / `**Threat Bracket:**` rank labels, `**Body (B)**` stat cells without the ` Stat` suffix, derived-metric bullets where the colon sits *inside* the bold (`**Health Points (HP):** **245**`), the `**Race / Species:**` label, and the `PREDICATE (... Strategic Levers):` block (`- Lever N: <Name> (...):` + `- Strategy:` / `- Action:` bullets). `[cite: …]` markers are now stripped from `race` + all three narrative-syntax fields (previously only the name). A heading-derived name fallback covers sheets that omit `Character Name:` (the Abyssal Behemoth). `guild_ingest.py`'s `dev/` sys.path depth fixed (4 parents from `engine/`; run as `python engine/guild_ingest.py`, not `-m`). **Boss dry run: 7 resolved, 0 unresolved; 1 flagged missing Sixth Guard (the Abyssal Behemoth's sheet genuinely lacks an Anchor — a source gap, not a parser bug). Live ingest (add-only → 7 inserted, then `--update-existing` ×2 to roll the citation-strip fix across all rows): 45 guild_rpg rows total (38 adventurers + 7 bosses), 0 rows with leftover `[cite]` markers. Full suite still 650 pass / 1 skip (no new tests; boss parsing covered by the dry run).**
- **Guild RPG region cast ingested (2026-08-22)** — the roster now carries the four macro-regions (`BESM Sheets/regions/`): The Capital City, Inewell, Srurpolis, The Vardun Wood. `engine/guild_region_pullover.py` parses the region layout (YAML `SUBJECT` + `THE ANCHOR` NS blocks, both lever formats) with no LLM; `engine/guild_region_ingest.py` + `guild_region_dryrun.py` mirror the cast ingest (safe-ingest guard, `--update-existing` canon upsert, `--dry-run` preview). The `locations` table gained `structural_fault` / `sixth_guard` / `levers` columns (parity with characters) via a non-destructive migration folded into `init_roster_db()`, plus `upsert_location()`. **Live run: 3 seeded atlas rows enriched in place + 1 new (Vardun Wood) = 4 regions with full NS, 0 leftover `[cite]`. 4 new tests → 655 total (654 pass / 1 skip).**
- **Guild RPG region cast ingested (2026-08-22)** — extended the roster to macro-locations (the "regions" registry sheets). `engine/guild_region_pullover.py` is a dedicated, LLM-free extractor for the region layout: `**Name:**` + `**Scale & Tier:**` / `**Geopolitical Scale:**` / `**Classification:**` + `**Rank Bracket:**` (the `Rank Bracket` line drives `location_type` → capital/city/region), the YAML `SUBJECT` block (`Structural Fault:` / `The_Grand_Guard:` bullets), and the `THE ANCHOR (The Grand Guard):` bullet block (Failure Trigger + Systemic Collapse) and the `PREDICATE` lever section (both the Capital's `**The Strategy:**` format and the other regions' `- Strategy:` bullets, including `[cite: N]` inside the lever header). `[cite: …]` stripped from `name` + the three NS fields. `engine/guild_region_ingest.py` wires it into a new `upsert_location()` (mirrors `upsert_character`: `(setting_id, name)` key, default add-only, `--update-existing` canon upsert, `--dry-run` preview, pre-write checkpoint); `guild_region_dryrun.py` reviews the sweep. `locations` table gained `structural_fault` / `sixth_guard` / `levers` / `card_json` / `source_path` / `ingested_at` via a non-destructive `ALTER` migration folded into `init_roster_db()`. **Live ingest (`--update-existing`): 3 seeded atlas rows (The Capital City, Inewell, Srurpolis) enriched in place + 1 new (The Vardun Wood) inserted = 4 regions with full NS, 0 rows with leftover `[cite]` markers. 4 new tests (`tests/test_guild_region_ingest.py`) → 655 total (654 pass / 1 skip).**
- **Guild RPG training-grounds playtest passed live (2026-08-22)** — `modules/zarlen_training_grounds_v1.json` (5 rooms, Guild Training Grounds, Zarlen as boss) validated by `verify_dungeon.py` and played through all 5 nodes in the TUI against big-rig `gemma4-agentic-16k:latest`. Narrative Syntax injection confirmed live end-to-end: Kari (B-Rank spear-fighter) as the active POV surfaced her Structural Fault / Sixth Guard in generated prose, and Zarlen's NS anchored the climax node. `ACTIVE_MODEL` repointed to the real rig tag (`gemma4-agentic-16k:latest`), clearing the earlier stale `gemma4-v2-Q6_K.gguf:latest` 404. The registry-sheet → roster → `besm_shell.md` → Ollama pipeline is now proven functional, closing the "live play still the confirmation" gap.
- **Guild RPG organizations ingested (2026-08-22)** — the 4th entity type is now wired. `BESM Sheets/organizations/aelthar-keldor-org-sheet.md` carries the guild's Institutional Narrative Sentence (Subject + Grand Guard + 3 Levers) in the same NS layout as regions; `engine/guild_org_pullover.py` reuses the region NS parser, `engine/guild_org_ingest.py` mirrors the safe-ingest guard into a new `organizations` table (org-type / scale / leader / base + full NS parity) in `guild_roster.py`. **Live ingest: 1 org (Aelthar Keldor) inserted, 0 `[cite]` pollution. 4 new tests → 659 total (658 pass / 1 skip).** All four Guild RPG entity types (adventurers, bosses, regions, organizations) are now in the live roster.

- **Guild org Narrative Syntax wired into the live shell (2026-08-22)** — the home guild is now a hub, not just a roster row. `build_vitals_with_full_loadout` merges the active org's NS into the shell vitals; `besm_shell.md` has a "Home Guild / Hub" section so the AI Director can render off-duty/guild scenes; `/org <name>` + `/orgs` switch/list the active guild (persisted in `campaign_navigation.org_name`, default Aelthar Keldor). `engine/state_manager.py` gained a non-destructive `org_name` migration. Regression: 1 new test (`test_shell_injects_org_context`) → 660 total (659 pass / 1 skip).

- **Hub-anchored greeting starts (2026-08-22)** — character greetings are now real campaign/player starting points, grounded at the hub. `engine/guild_roster.py:classify_greeting()` sorts each greeting domestic/field/neutral (keyword-driven); `format_greeting_list()` tags `/greetings` entries `[Hub]` (guild hall/tavern/library) vs `[Quest]` (forest/quest/field). `chronos.py:build_greeting_start()` builds the opening node: a domestic greeting anchors to `hub_guildhall` / `"{org} Guildhall"` (the hub becomes the literal starting location), a field greeting stays on a generic quest node; `/startgreeting <n>` sets `active_node` there and persists it. **Live-verified on Eira: greetings 1/2/5/7/10 [Hub], 3/4/6/8/9 [Quest]; a domestic greeting opens the AI Director scene at the Aelthar Keldor Guildhall.** 9 new tests (`tests/test_greeting_hub.py`) → 669 total (668 pass / 1 skip).

- **SxM1 Phase 2A canon upsert re-run + Lion Dancer dedup (2026-08-23)** — re-ran `engine/sxm1_ingest.py --update-existing` against the 105-row disc. Found a case-variant duplicate (`Lion Dancer` vs `Lion dancer`); merged the curated data into the canonical `Lion Dancer`, deleted the stray row, and verified no Bestiary data was lost. **Hardened `sxm1_ingest.py`** so a normalized-name collision now folds into the canonical existing row in place (idempotent, no duplicate). Re-run is clean: **105 `shota_x_monsters` rows, 0 normalized collisions.** 13 pullover/ingest tests still green.
- **SxM1 Phase 3 economy grounded + seeded (2026-08-23)** — new `engine/sxm1_economy_catalog.py` carries all **63** `master_monsters.db` (game='sxm1') items with their BESM Item Cost from `Mechanics/08_Item_Conversions.md`. `engine/economy.py` gains a migration-safe `currency` column + `seed_sxm1_economy()` (called from `init_economy_db`), and `catalog_summary`/`buy_item` now print `G` vs `sp` per setting. Gold model `gold = 50 × besm_cost × category_mult` **exactly reproduces the four confirmed Watt/Reo peddler prices** (Potion 50G/10, Dodeka Pudding 200G/10, Fairy Revival 300G/2, Smoke Bomb 150G/1); the other 59 are flagged `[estimated]` and sellable/currency/special items are `priceless`. **20 new tests → 689 total (688 pass / 1 skip).**

## What Doesn't Work Yet

- **Test suite at 687 tests (687 pass, 1 skip, all runnable as of 2026-09-07)** — 27 suites (incl. `test_browser_smoke.py`, 6 headless web-port tests). Both ingest/roster suites isolate the roster DB + staging dirs to tmp_path, so live `data/` is never touched by tests; the web-port smoke tests redirect the session DB to tmp_path too.
- **Guild RPG roster holds 45 characters + 16 locations (2026-08-22)** — the live safe-ingest (`engine/guild_ingest.py`) inserted 30 registry-sheet adventurers, then `--update-existing` runs upgraded the cast to their sheet versions; Liora's later `liora-head-receptionist.md` sheet brought her in too, so all 38 adventurer rows are sheet-derived. The 7 boss sheets (`BESM Sheets/bosses/`) were then ingested the same way, so all 45 rows are now fully sheet-derived from the BESM Sheets (`adventurers/` + `bosses/`) — the sole canonical source. The extractor also now handles the boss `PREDICATE (... Strategic Levers):` lever block and vault sheets that serialize newlines as literal `\n` (the v2 Abyssal Behemoth sheet); the superseded `abyssal-behemoth-boss-sheet.md` is skipped in favor of `*-v2.md`. The four macro-regions (`BESM Sheets/regions/`) are now ingested too via `engine/guild_region_ingest.py`, carrying full Narrative Syntax parity with characters. **Orgs are now ingested as well (see below) — all four Guild RPG entity types (adventurers, bosses, regions, organizations) live in the roster.**
- **Full-project git** — engine code has local-only git (2026-08-14), but confidential character data (`data/`, `staging/`, `modules/`) stays untracked by design. Full-project git deferred to the BESM 4e "universal" rewrite.
- ~~**No Combat Maneuvers runtime**~~ — **Fully wired 2026-08-19** (engine shipped 08-18; `/maneuver` now exposes stances, called shots, two-weapon, strike-to-wound, touch, grappling, pin, multi-target via the TUI).
- **BESM mechanics engine shipped + TUI wired** — 431 tests. Engine math now exposed via `/` commands in the dashboard: `/shock`, `/resist`, `/fall`, `/range`, `/size`, `/defence`, `/scv`, `/sanity`, `/recover`, `/techniques`, `/defects`, `/diceless`, `/maneuver`, `/effects`, `/engine`. Type `/engine` for the full list in-session.
- ~~**No diceless TCR formula**~~ — **Fully wired 2026-08-19** (engine shipped 08-18; `/diceless <cv> [AR] [extra_def] [edge]` + `/diceless hedge` now reach the prompt).
- ~~**Raw tactical consumables unwired**~~ — **Wired 2026-08-19** — `use_item()` now consumes Beast-Repellent Powder (wards the node) and Flash-Powder Vial (blinds the group at the node), both tracked by the `scene_effects` ledger and viewable via `/effects`.
- **Thin client can't run inference** — all LLM-dependent testing requires big rig Ollama
- ~~**Nieven's narrative syntax needs tuning**~~ — **Tuned 2026-08-19** — all three enforced fields rewritten in the peer pattern: **The Institutionalized Symbiont** fault (the sheet's real wound — no self-owned will, passive dormancy when ownerless), **The Chimeric Override (the Weaponized Messiah)** guard that now *costs* him (the collapse is that he enjoys the Manticore apex he fled, so the facade doesn't return), and engine-native effect-prose levers (Desk Mascot Stasis / Golden Crowd-Fence / Escorted Retreat). 5e/CR/D&D-vocabulary bleed purged. Live play still the confirmation.
- ~~**`backfill_besm.py` not archived**~~ — **Archived 2026-08-14** → `dev/archive/chronos-core/backfill_besm.py`

## Known Frictions

| Friction | Impact | Fix Effort |
|---|---|---|
| ~~No automated tests~~ (partial) | ~~BESM functions, economy math had no regression protection~~ | **632 tests across 23 suites** — mechanics, economy, importer, scene effects, and the cast-pullover extractor now covered |
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
| `/use <item_id>` | Consume a consumable (binds repel/blind scene effects to the current node) |
| `/effects` | List active scene effects at the current node (remaining rounds) |
| `/diceless <cv> [AR] [extra_def] [edge]` | Diceless clash vs a challenge — TCR breakdown + Table-15 MoS band; `/diceless hedge <target> [stat]` = auto-7 non-combat |
| `/maneuver <sub>` | Combat maneuver arsenal — `stance`/`two-weapon`/`strike`/`touch`/`called`/`grapple`/`grabbed`/`escape`/`pin`/`multi`; `/maneuver list` for the menu |
| `/provision [info] [filters]` | GM-seed the BESM canon into the active setting's shop. Filters: `eras=archaic,modern`, `categories=melee`, `types=weapon`, `cap=800`; bare token = era filter; `info` = preview only |
| `auto-ingest` | Run staging sweep |

### Register a new setting
1. Add setting entry to `DEFAULT_SETTINGS` in `config/settings.json`
2. Seed roster characters via `upsert_character()`
3. Create a campaign module JSON in `modules/`
4. Provision a shop from the BESM canon (optional, explicit-only):
   `seed_besm_catalog("<setting>", eras=["archaic"], price_cap_sp=800)`
   — or hand-seed with `add_item()` from `engine.economy.py`.

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

1. ~~**Add a pytest suite**~~ → **616 tests across 22 suites.** All engine paths covered: roster CRUD + BESM loadout, batch ingest (METHOD 1/3 + failure paths), card compiler, stage_cards, bond progression, diceless TCR, combat maneuvers, full status ailments, scene-effect consumables, plus the 13 mechanics suites.
2. ~~**Wire Combat Maneuvers**~~ → **Wired 2026-08-19.** `engine/models.py` gains the BESM Extras maneuver calls (`resolve_tactical_stance()` / `two_weapon_attack()` / `strike_to_wound()` / `touch_attack()` / `resolve_called_shot()` / `grapple_attack_edges()` / `grabbed_condition()` / `escape_grapple()` / `pin_condition()` / `multi_target_dispersion()`, 46 tests) and `/maneuver` now exposes all of them in the TUI with technique-aware reduction.
3. ~~**Wire Status Ailments**~~ → **Shipped 2026-08-18.** `engine/models.py` completes the ledger: poison delivery vectors (`resolve_poison_delivery` — injury blocked by AR/Force Field, contact vs airtight, ingested ×2, inhaled vs masks), continuing-decay ticks (`continuing_poison_tick` 20%/round, `decay_survival_check` TN 15 hourly-major/daily-minor), field treatment (`treat_poison` vs Blight TN), interruption rules (`sleep_state_breaks` — sleep wakes on noise/damage, paralysis/stone magic-only), `stun_recovery_per_hour`, and the cognitive layer (`mind_control_gradient`, `mind_control_resistance` with Mind Shield +2/level, `against_nature_break_check`, `exorcism_clash`). 36 tests. Complements the existing shock/incapacitation/blight checks.
4. ~~**Implement diceless TCR formula**~~ → **Wired 2026-08-19.** `engine/models.py` gains `compute_tcr()` (all terms round down; EP/Mulligan declared in advance), `resolve_diceless_combat()` (Table-15 MoS bands), `diceless_battle()` wrapper, and `hedged_check()` (auto-7 non-combat). Verified 32 tests incl. the Kozoh vs Azok canonical (19 vs 17 → Slight Success). `/diceless <cv> [AR] [extra_def] [edge]` + `/diceless hedge <target> [stat]` now run in the TUI.
5. ~~**Move DEFAULT_SETTINGS to config**~~ ✅ Done 2026-08-14 — list now lives in `config/settings.json`, loaded by `engine/config.py`, imported by `engine/guild_roster.py`
6. ~~**Archive `backfill_besm.py`**~~ ✅ Done 2026-08-14 — moved to `dev/archive/chronos-core/backfill_besm.py`
7. ~~**Tune Nieven's narrative syntax**~~ → **Tuned 2026-08-19.** Rewritten in the roster DB: Structural Fault → **The Institutionalized Symbiont** (no self-owned will — passive dormancy when ownerless, fragile, agency outsourced to an owner); Sixth Guard → **The Chimeric Override (the Weaponized Messiah)** (redlines into the Manticore-Lion apex when his owner is threatened; the collapse is that he *enjoys* the weapon he fled — no return to the facade, penance in the dirt); Levers → **Desk Mascot Stasis / Golden Crowd-Fence / Escorted Retreat** in engine-native effect-prose. 5e/CR/D&D vocabulary purged. Live play = final confirmation.
8. ~~**Apply Item CP pricing** to shop catalog refinement~~ → **Done 2026-08-18 + wired 2026-08-19.** Jaxon's shelf matches the AK economy docs item-for-item (catalog 8 → 10, prices regression-locked). Both tactical consumables now **run**: `use_item()` binds Beast-Repellent Powder and Flash-Powder Vial as node-scoped `scene_effects` (round-budgeted, ticked on movement, viewable via `/effects`). Optional future: bump repel's `duration_rounds` to a full night watch in the catalog + refresh the live seed.
9. ~~**Ingest the monster cards (big opportunity)**~~ → **Shipped 2026-08-18.** `stage_cards.py` staged the 94 statted cards; live sweep ingested 94/94. Shota roster **3 → 97**. The 245 lore-only cards will flow in once SxM2 stats are decoded — just re-run `stage_cards.py`.
10. **Promote to big rig** — once stable, Megane handles the copy
11. **Live-play the new commands** — confirm `/maneuver`/`/diceless`/`/effects` narrations read well in a real session (the LLM director carries the prose; the engine holds the numbers)
12. ~~**Full Guild RPG cast pullover — extractor + dry run shipped, ingest pending**~~ → **COMPLETE (2026-08-22).** `engine/guild_pullover.py` + `guild_pullover_dryrun.py` parse the whole cast (registry format, 17 tests); `engine/guild_ingest.py` (5 tests) wires it into the live roster behind the safe-ingest guard. All 38 adventurer rows are now sheet-derived (Liora's `liora-head-receptionist.md` added last); `--update-existing` makes sheets canonical. Bosses/regions/orgs remain future work.
13. **SxM1 "true disc" — Phases 1-3 done, Phases 4-6 pending** — proposal `changelog/proposals/2026-08-21-chronos-core-sxm1-true-disk.md` is the roadmap. **Phase 1 (2026-08-21):** `engine/sxm1_pullover.py` + `sxm1_pullover_dryrun.py` — 85 Bestiary monsters resolved / 18 data-sparse skipped / 0 DB writes. **Phase 2 (2026-08-21):** `engine/sxm1_ingest.py` executed (Option B add-only) — 97 → 105 rows, 0 mutations, 8 novel monsters. **Phase 2A (2026-08-23):** `--update-existing` re-run + Lion Dancer dedup + normalized-collision hardening (idempotent, 0 collisions). **Phase 3 (2026-08-23):** SxM1 economy seeded in Gold — `engine/sxm1_economy_catalog.py` (63 items) + `currency` column in `economy.py`; Gold model validated against the 4 confirmed Watt/Reo peddler prices. **Remaining:** (4) add strata/labyrinth modules from `Mechanics/03_Labyrinths.md`; (5) wire `sxm1-besm-folder/` lore vault into the LLM shell prompt space; (6) add `verify_setting_pack.py` 5-layer validator.
14. **Web port polish — wire the `/command` palette into `browser_chronos.py`** — the V1 command handler dispatches any input to the AI Director; `/shop`, `/buy`, `/inventory`, `/diceless`, `/maneuver`, `/greetings`, `/provision` are engine-ready (all functions imported) but not yet distinct UI paths. Tabs or sidebar sub-panels per command.
15. **Web port polish — `stream: True` + `st.write_stream()`** — deferred per synthesis Q1; big-rig turns block the browser thread ~15-30s behind `st.spinner`. Live token streaming would make long turns feel instant.
16. **Web port polish — directional node navigation (CP-5 design)** — render node exits as `st.pills` / directional buttons mirroring the TUI's cardinal movement, instead of typing node IDs into the selectbox.
17. **Web port polish — restore session on refresh** — the app re-boots from the roster on a fresh browser session; `load_runtime_navigation()` restore from `chronos_web_session.db` would resume the last node/character.
18. **~~Wire the `/command` palette~~ → **COMPLETE (2026-09-08).** 26 commands wired (14 display + 11 math + `/startgreeting`) plus `/loot`; `test_browser_smoke.py` 6 → 37; suite 687 → 719. See What Works / Lineage row 2026-09-08. **Remaining:** the 4 Phase C economy writes (`/buy` `/grant` `/use` `/provision`) are deferred — they route through `get_economy_connection()` which hardcodes the canonical `guild_rpg_roster.db` (CP-2 conflict). Needs Megane's routing ruling: shared canonical economy vs `set_active_economy_db_path()` redirect.
19. **Web port polish — `/setting` `/module` `/char` `/org` as explicit commands** — currently sidebar-only; text equivalents would complete parity (sidebar already covers them natively).

---

*Handoff updated 2026-09-08. Chronos Core v3 — the BESM 4e rules engine, now with **two interfaces on one engine**: the Rich TUI and a Streamlit web port (`browser_chronos.py`, launch with `chronos-ui`). 719 tests, local-only engine-scoped git. The web command palette went from Director-only to **26 wired commands** (14 display + 11 deterministic math + `/startgreeting`) plus session-scoped `/loot` — deterministic commands resolve in microseconds with zero LLM calls, and the Rich-tag stripper preserves semantic `[Hub]`/`[Quest]` markers. The card→BESM compiler + staging bridge took the Shota roster 3 → 97 in one sweep. The LLM narrates; Python enforces. The Sixth Guard is not a suggestion — and now it's also visible and playable in a browser. The one honest gap: Phase C economy writes are deferred until the canonical-DB routing decision lands.*
