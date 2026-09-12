"""Headless smoke test: run The Master Harper through the Council of Omphalos.

Drives the TUI's core play path offline (LLM patched, big-rig independent):
boot state -> load besm_omphalos + council_of_omphalos -> select The Master
Harper -> navigate threshold -> doors (Soul gate) -> council (Mind encounter) ->
empty throne (lore) -> rogue seat (Body encounter) -> weaver relic (reward
chest) -> compile the shell frame (Harper loadout + node) -> dispatch one
Director turn (patched stream) and apply its mechanical payload.
"""
import sys

sys.path.insert(0, "/home/megane/dev")
sys.path.insert(0, ".")

from engine.guild_roster import (
    init_roster_db, load_campaign_module, get_setting,
    build_vitals_with_full_loadout,
)
from engine.economy import init_economy_db
from engine.state_manager import init_db
from engine.models import execute_action_check
from engine import llm_bridge as lb

PASS = []


def check(label, cond, detail=""):
    PASS.append(cond)
    print(f"{'✅' if cond else '❌'} {label}" + (f" — {detail}" if detail else ""))


# 1. Boot engine state
init_db()
init_roster_db()
init_economy_db()

# 2. Load Omphalos setting + the 6-node council module
setting = get_setting("besm_omphalos")
check("setting resolves", setting is not None,
      f"default_module={setting and setting.get('default_module')}")
story_map, module_name = load_campaign_module("besm_omphalos", "council_of_omphalos.json")
check("council_of_omphalos loads", module_name == "The Council of Omphalos (besm_omphalos Starter)" and len(story_map) == 6,
      f"{module_name} | {len(story_map)} nodes")

# 3. Select The Master Harper (Ikaris gatekeeper)
from engine.guild_roster import roster_dict_to_char
import sqlite3
cols = ['setting_id','name','rank_label','race','points_budget','stat_body','stat_mind','stat_soul','acv','dcv','max_hp','max_ep','card_json','source_path','ingested_at','sixth_guard','structural_fault','levers','combat_techniques','skills','defects','shock_value','md_source_path','gender']
row = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_omphalos' AND name='The Master Harper'").fetchone()
harper = roster_dict_to_char(dict(zip(cols, row)))
check("Master Harper selectable", harper.name == "The Master Harper" and harper.max_hp == 45,
      f"{harper.name} HP{harper.max_hp}/EP{harper.max_ep} ACV{harper.base_acv}/DCV{harper.base_dcv} [{harper.race}]")

# Also verify the rogue envoy + Lyra Vance (pressured vote)
row2 = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_omphalos' AND name='The Infernal King''s Envoy'").fetchone()
envoy = roster_dict_to_char(dict(zip(cols, row2))) if row2 else None
check("Envoy (Bazaroth rogue seat) selectable", envoy is not None and envoy.race == "Hellspawn",
      f"{envoy.name if envoy else 'missing'} — {envoy.race if envoy else ''}")
row3 = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_omphalos' AND name='Lyra Vance'").fetchone()
lyra = roster_dict_to_char(dict(zip(cols, row3))) if row3 else None
check("Lyra Vance (Enid pressured vote) selectable", lyra is not None and lyra.race == "Homo Psyche",
      f"{lyra.name if lyra else 'missing'} — {lyra.race if lyra else ''}")

# 4. Navigate threshold -> doors
node = story_map["node_01_threshold"]
check("threshold has north exit", node["exits"].get("north") == "node_02_doors")
doors = story_map["node_02_doors"]
check("doors is a gate", doors["node_type"] == "gate")
check("doors check is Soul", doors["required_check"]["stat"] == "stat_soul")

# 5. Resolve the doors gate (Soul vs DV12)
rc = doors["required_check"]
res = execute_action_check(harper.stat_soul, rc["skill"], rc["dv"])
check("doors check resolves", "success" in res and "roll" in res,
      f"stat={rc['stat']} skill={rc['skill']} dv={rc['dv']}")

# 6. Resolve the council deadlock (Mind vs DV13)
council = story_map["node_03_council"]
check("council is an encounter", council["node_type"] == "encounter")
rcc = council["required_check"]
resc = execute_action_check(harper.stat_mind, rcc["skill"], rcc["dv"])
check("council check resolves", "success" in resc and "roll" in resc,
      f"stat={rcc['stat']} skill={rcc['skill']} dv={rcc['dv']} fail_damage={rcc['fail_damage']}")

# 7. Empty throne is lore (the missing seat)
throne = story_map["node_04_empty_throne"]
check("empty throne is lore node", throne["node_type"] == "lore")
check("empty throne leads to rogue seat", throne["exits"].get("north") == "node_05_rogue_seat")

# 8. Compile the shell frame with the Harper's loadout + the rogue seat node
rogue = story_map["node_05_rogue_seat"]
vitals = build_vitals_with_full_loadout("besm_omphalos", harper, "The Chamber of Omphalos")
bridge = lb.LLMBridge()
frame = bridge.compile_system_frame("besm_shell", vitals, rogue)
check("shell carries Harper name", "The Master Harper" in frame)
check("shell carries Judge Opponent", "Judge Opponent" in frame)
check("shell carries Steady Hand", "Steady Hand" in frame)
check("shell carries Steward's Patience fault", "Steward's Patience" in frame)
check("shell carries Concordat Break guard", "Concordat Break" in frame)
check("shell carries rogue seat title", "The Rogue Seat" in frame)
check("shell carries vitals (HP/EP/ACV/DCV)", all(x in frame for x in ("45", "ACV", "DCV")))
check("shell carries rogue description", "rogue" in frame.lower() or "Bazaroth" in frame)

# 9. Dispatch one Director turn (patched stream, offline) + apply mechanical payload
def _fake_stream(self, model_name=None, complete_context="", user_input="", ctx=None):
    if ctx is not None:
        ctx["full_raw_text"] = (
            "A harp chord stills the chamber, and the rogue seat's enforcers waver. "
            "[MECHANICAL PAYLOAD] {\"hp_loss\": 5, \"ep_loss\": 4}"
        )
    yield "A harp chord stills the chamber, and the rogue seat's enforcers waver. "

lb.LLMBridge.dispatch_ollama_turn_stream = _fake_stream

ctx = {}
gen = bridge.dispatch_ollama_turn_stream(ctx=ctx, complete_context=frame, user_input="I strike the Chord of Order to hold the rogue seat!")
prose = "".join(gen)
check("director streams clean prose", "harp chord" in prose or "chamber" in prose)
check("ctx captures mechanical payload", "[MECHANICAL PAYLOAD]" in ctx.get("full_raw_text", ""))

mech = bridge.inspect_llm_output(ctx["full_raw_text"])[1]
check("mechanical payload parsed", mech.get("hp_loss") == 5 and mech.get("ep_loss") == 4,
      f"hp_loss={mech.get('hp_loss')} ep_loss={mech.get('ep_loss')}")

# 10. Full navigation reachability: all 6 nodes reachable from threshold
from engine.verify_dungeon import _reachable_nodes
reachable = _reachable_nodes(story_map, "node_01_threshold")
check("all 6 nodes reachable", len(reachable) == 6, sorted(reachable))

# 11. Reward node has the Weaver relic chest (/open target)
relic = story_map["node_06_weaver_relic"]
check("relic is reward node", relic["node_type"] == "reward")
check("relic has wooden chest", relic.get("chest", {}).get("tier") == "wooden")

print()
print(f"SMOKE TEST: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)