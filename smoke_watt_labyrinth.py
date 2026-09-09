"""Headless smoke test: run Watt through the First Stratum labyrinth.

Drives the TUI's core play path offline (LLM patched, big-rig independent):
boot state -> load setting+module -> select Watt -> navigate north ->
resolve the encounter check -> compile the shell frame (Watt loadout + node)
-> dispatch one Director turn (patched stream) and apply its mechanical payload.
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

# 2. Load setting + the new labyrinth module
setting = get_setting("shota_x_monsters")
check("setting resolves", setting is not None,
      f"default_module={setting and setting.get('default_module')}")
story_map, module_name = load_campaign_module("shota_x_monsters", "forest_labyrinth_stratum1.json")
check("labyrinth module loads", module_name == "Forest Labyrinth (First Stratum)" and len(story_map) == 6,
      f"{module_name} | {len(story_map)} nodes")

# 3. Select Watt from the roster
from engine.guild_roster import list_characters, roster_dict_to_char
import sqlite3
cols = ['setting_id','name','rank_label','race','points_budget','stat_body','stat_mind','stat_soul','acv','dcv','max_hp','max_ep','card_json','source_path','ingested_at','sixth_guard','structural_fault','levers','combat_techniques','skills','defects','shock_value','md_source_path','gender']
row = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='shota_x_monsters' AND name='Watt'").fetchone()
watt = roster_dict_to_char(dict(zip(cols, row)))
check("Watt selectable", watt.name == "Watt" and watt.max_hp == 60,
      f"{watt.name} HP{watt.max_hp}/EP{watt.max_ep} ACV{watt.base_acv}/DCV{watt.base_dcv}")

# 4. Navigate north from the entrance into the Slime Thicket
node = story_map["node_01_entrance"]
check("entrance has north exit", node["exits"].get("north") == "node_02_thicket")
encounter = story_map["node_02_thicket"]
check("slime thicket is an encounter", encounter["node_type"] == "encounter")

# 5. Resolve the encounter check deterministically (forced-hit path)
rc = encounter["required_check"]
res = execute_action_check(watt.stat_mind, rc["skill"], rc["dv"])
check("encounter check resolves", "success" in res and "roll" in res,
      f"stat={rc['stat']} skill={rc['skill']} dv={rc['dv']} fail_damage={rc['fail_damage']}")

# 6. Compile the shell frame with Watt's full loadout + the node
vitals = build_vitals_with_full_loadout("shota_x_monsters", watt, "Aelthar Keldor")
bridge = lb.LLMBridge()
frame = bridge.compile_system_frame("besm_shell", vitals, encounter)
check("shell carries Watt's name", "Watt" in frame)
check("shell carries Flash Bomb", "Flash Bomb" in frame)
check("shell carries Electromagnetic Cannon", "Electromagnetic Cannon" in frame)
check("shell carries Shock Mastery", "Shock Mastery" in frame)
check("shell carries Reduced Damage defect", "Reduced Damage" in frame)
check("shell carries node title", "Slime Thicket" in frame)
check("shell carries node description", "gelatinous" in frame.lower())
check("shell carries node check", f"{rc['dv']}" in frame)

# 7. Dispatch one Director turn (patched stream, offline) + apply mechanical payload
def _fake_stream(self, model_name=None, complete_context="", user_input="", ctx=None):
    if ctx is not None:
        ctx["full_raw_text"] = (
            "A slime splatters against your boot. " 
            "[MECHANICAL PAYLOAD] {\"hp_loss\": 6}"
        )
    yield "A slime splatters against your boot. "

lb.LLMBridge.dispatch_ollama_turn_stream = _fake_stream

ctx = {}
gen = bridge.dispatch_ollama_turn_stream(ctx=ctx, complete_context=frame, user_input="I blast it with a Flash Bomb!")
prose = "".join(gen)
check("director streams clean prose", "slime splatters" in prose)
check("ctx captures mechanical payload", "[MECHANICAL PAYLOAD]" in ctx.get("full_raw_text", ""))

mech = bridge.inspect_llm_output(ctx["full_raw_text"])[1]
hp_after = watt.current_hp - mech.get("hp_loss", 0)
check("mechanical payload parsed", mech.get("hp_loss") == 6,
      f"hp_loss={mech.get('hp_loss')}")

# 8. Full navigation reachability sanity: all six nodes reachable from entrance
from engine.verify_dungeon import _reachable_nodes
reachable = _reachable_nodes(story_map, "node_01_entrance")
check("all 6 nodes reachable", len(reachable) == 6, sorted(reachable))

print()
print(f"SMOKE TEST: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)