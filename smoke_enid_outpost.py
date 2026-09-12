"""Headless smoke test: run Vaelen Kor through the Tavarre Outpost labyrinth.

Drives the TUI's core play path offline (LLM patched, big-rig independent):
boot state -> load besm_enid + tavarre_outpost -> select Vaelen Kor ->
navigate north -> resolve the Storm Wall hazard -> compile the shell frame
(Vaelen loadout + node) -> dispatch one Director turn (patched stream) and
apply its mechanical payload. Mirrors smoke_watt_labyrinth.py.
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

# 2. Load Enid setting + the Tavarre Outpost labyrinth (5 nodes)
setting = get_setting("besm_enid")
check("setting resolves", setting is not None,
      f"default_module={setting and setting.get('default_module')}")
story_map, module_name = load_campaign_module("besm_enid", "tavarre_outpost.json")
check("tavarre_outpost loads", module_name == "Tavarre Outpost — Heavy Weather (Enid Starter)" and len(story_map) == 5,
      f"{module_name} | {len(story_map)} nodes")

# 3. Select Vaelen Kor from the roster
from engine.guild_roster import roster_dict_to_char
import sqlite3
cols = ['setting_id','name','rank_label','race','points_budget','stat_body','stat_mind','stat_soul','acv','dcv','max_hp','max_ep','card_json','source_path','ingested_at','sixth_guard','structural_fault','levers','combat_techniques','skills','defects','shock_value','md_source_path','gender']
row = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_enid' AND name='Vaelen Kor'").fetchone()
vaelen = roster_dict_to_char(dict(zip(cols, row)))
check("Vaelen Kor selectable", vaelen.name == "Vaelen Kor" and vaelen.max_hp == 50,
      f"{vaelen.name} HP{vaelen.max_hp}/EP{vaelen.max_ep} ACV{vaelen.base_acv}/DCV{vaelen.base_dcv}")

# Also verify the psycho-slave is present (Clover — moral hook)
row2 = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_enid' AND name='Unit 7-Nil \"Clover\"'").fetchone()
clover = roster_dict_to_char(dict(zip(cols, row2))) if row2 else None
check("Clover (psycho-slave) selectable", clover is not None,
      f"{clover.name if clover else 'missing'} — Involuntary Servitude")

# 4. Navigate north from the Outpost into the Storm Wall
node = story_map["node_01_outpost"]
check("outpost has north exit", node["exits"].get("north") == "node_02_storm")
storm = story_map["node_02_storm"]
check("storm wall is an encounter", storm["node_type"] == "encounter")

# 5. Resolve the Storm Wall hazard deterministically
rc = storm["required_check"]
res = execute_action_check(vaelen.stat_mind, rc["skill"], rc["dv"])
check("storm check resolves", "success" in res and "roll" in res,
      f"stat={rc['stat']} skill={rc['skill']} dv={rc['dv']} fail_damage={rc['fail_damage']}")

# 6. Compile the shell frame with Vaelen's full loadout + the node
vitals = build_vitals_with_full_loadout("besm_enid", vaelen, "Tavarre Outpost")
bridge = lb.LLMBridge()
frame = bridge.compile_system_frame("besm_shell", vitals, storm)
check("shell carries Vaelen name", "Vaelen Kor" in frame)
check("shell carries Lightning Reflexes", "Lightning Reflexes" in frame)
check("shell carries Precise Aim", "Precise Aim" in frame)
check("shell carries Psionic Burnout fault", "Psionic Burnout" in frame)
check("shell carries Resonance Feedback guard", "Resonance Feedback" in frame)
check("shell carries Storm Wall title", "Storm Wall" in frame)
check("shell carries node check DV", f"{rc['dv']}" in frame)
check("shell carries hazard description", "wind shear" in frame.lower() or "storm" in frame.lower())

# 7. Dispatch one Director turn (patched stream, offline) + apply mechanical payload
def _fake_stream(self, model_name=None, complete_context="", user_input="", ctx=None):
    if ctx is not None:
        ctx["full_raw_text"] = (
            "You brace against the wind shear, kinesis flaring. "
            "[MECHANICAL PAYLOAD] {\"hp_loss\": 5, \"ep_loss\": 3}"
        )
    yield "You brace against the wind shear, kinesis flaring. "

lb.LLMBridge.dispatch_ollama_turn_stream = _fake_stream

ctx = {}
gen = bridge.dispatch_ollama_turn_stream(ctx=ctx, complete_context=frame, user_input="I channel vector kinesis through the frame!")
prose = "".join(gen)
check("director streams clean prose", "wind shear" in prose)
check("ctx captures mechanical payload", "[MECHANICAL PAYLOAD]" in ctx.get("full_raw_text", ""))

mech = bridge.inspect_llm_output(ctx["full_raw_text"])[1]
check("mechanical payload parsed", mech.get("hp_loss") == 5 and mech.get("ep_loss") == 3,
      f"hp_loss={mech.get('hp_loss')} ep_loss={mech.get('ep_loss')}")

# 8. Full navigation reachability: all 5 nodes reachable from outpost
from engine.verify_dungeon import _reachable_nodes
reachable = _reachable_nodes(story_map, "node_01_outpost")
check("all 5 nodes reachable", len(reachable) == 5, sorted(reachable))

# 9. Lore branch: Bazaroth Shrine is the Cosmic Web hook
shrine = story_map["node_02b_shrine"]
check("shrine is lore node", shrine["node_type"] == "lore")
check("shrine leads to duel", shrine["exits"].get("north") == "node_03_duel")

print()
print(f"SMOKE TEST: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
