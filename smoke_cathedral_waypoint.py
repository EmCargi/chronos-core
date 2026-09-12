"""Headless smoke test: run Caelen Vhol through the Cathedral Waypoint labyrinth.

Drives the TUI's core play path offline (LLM patched, big-rig independent):
boot state -> load besm_cathedral + cathedral_waypoint -> select Caelen Vhol ->
navigate dock -> customs (Mind gate) -> void breach (vacuum hazard) ->
beacon core (lore) -> skiff skirmish (encounter) -> salvage cache (reward chest)
-> compile the shell frame (Vaelen/Caelen loadout + node) -> dispatch one
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

# 2. Load Cathedral setting + the 6-node waypoint module
setting = get_setting("besm_cathedral")
check("setting resolves", setting is not None,
      f"default_module={setting and setting.get('default_module')}")
story_map, module_name = load_campaign_module("besm_cathedral", "cathedral_waypoint.json")
check("cathedral_waypoint loads", module_name == "Cathedral Waypoint — Orb Radiant (besm_cathedral Starter)" and len(story_map) == 6,
      f"{module_name} | {len(story_map)} nodes")

# 3. Select Caelen Vhol (Xyd Shepherd)
from engine.guild_roster import roster_dict_to_char
import sqlite3
cols = ['setting_id','name','rank_label','race','points_budget','stat_body','stat_mind','stat_soul','acv','dcv','max_hp','max_ep','card_json','source_path','ingested_at','sixth_guard','structural_fault','levers','combat_techniques','skills','defects','shock_value','md_source_path','gender']
row = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_cathedral' AND name='Caelen Vhol'").fetchone()
caelen = roster_dict_to_char(dict(zip(cols, row)))
check("Caelen Vhol selectable", caelen.name == "Caelen Vhol" and caelen.max_hp == 40,
      f"{caelen.name} HP{caelen.max_hp}/EP{caelen.max_ep} ACV{caelen.base_acv}/DCV{caelen.base_dcv} [{caelen.race}]")

# Also verify Vael-Xis (Grey gatekeeper) + Boran-9 (Woolie moral hook)
row2 = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_cathedral' AND name='Vael-Xis'").fetchone()
vaelxis = roster_dict_to_char(dict(zip(cols, row2))) if row2 else None
check("Vael-Xis (Grey) selectable", vaelxis is not None and vaelxis.race == "Grey",
      f"{vaelxis.name if vaelxis else 'missing'} — {vaelxis.race if vaelxis else ''}")
row3 = sqlite3.connect("data/guild_rpg_roster.db").execute(
    "SELECT " + ",".join(cols) + " FROM characters WHERE setting_id='besm_cathedral' AND name='Boran-9'").fetchone()
boran = roster_dict_to_char(dict(zip(cols, row3))) if row3 else None
check("Boran-9 (Woolie) selectable", boran is not None and boran.race == "Woolie",
      f"{boran.name if boran else 'missing'} — Obligated + Shock Collar")

# 4. Navigate dock -> customs
node = story_map["node_01_dock"]
check("dock has north exit", node["exits"].get("north") == "node_02_customs")
customs = story_map["node_02_customs"]
check("customs is a gate", customs["node_type"] == "gate")
check("customs check is Mind (legal)", customs["required_check"]["stat"] == "stat_mind")

# 5. Resolve the customs gate (Mind vs DV12)
rc = customs["required_check"]
res = execute_action_check(caelen.stat_mind, rc["skill"], rc["dv"])
check("customs check resolves", "success" in res and "roll" in res,
      f"stat={rc['stat']} skill={rc['skill']} dv={rc['dv']}")

# 6. Resolve the void breach hazard (Body vs DV15)
void_breach = story_map["node_03_void_breach"]
check("void breach is an encounter", void_breach["node_type"] == "encounter")
rcv = void_breach["required_check"]
resv = execute_action_check(caelen.stat_body, rcv["skill"], rcv["dv"])
check("vacuum check resolves", "success" in resv and "roll" in resv,
      f"stat={rcv['stat']} skill={rcv['skill']} dv={rcv['dv']} fail_damage={rcv['fail_damage']}")

# 7. Beacon core is lore (Cosmic Web hook)
beacon = story_map["node_04_beacon_core"]
check("beacon is lore node", beacon["node_type"] == "lore")
check("beacon leads to skirmish", beacon["exits"].get("north") == "node_05_skiff_skirmish")

# 8. Compile the shell frame with Caelen's loadout + the void breach node
vitals = build_vitals_with_full_loadout("besm_cathedral", caelen, "Orb Radiant Outpost 9")
bridge = lb.LLMBridge()
frame = bridge.compile_system_frame("besm_shell", vitals, void_breach)
check("shell carries Caelen name", "Caelen Vhol" in frame)
check("shell carries Lightning Reflexes", "Lightning Reflexes" in frame)
check("shell carries Steady Hand", "Steady Hand" in frame)
check("shell carries Kinetic Fixation fault", "Kinetic Fixation" in frame)
check("shell carries Core Meltdown guard", "Core Meltdown" in frame)
check("shell carries Void Breach title", "Depressurized Catwalk" in frame)
check("shell carries vitals (HP/EP/ACV/DCV)", all(x in frame for x in ("40", "55", "ACV", "DCV")))
check("shell carries vacuum description", "vacuum" in frame.lower() or "breach" in frame.lower())

# 9. Dispatch one Director turn (patched stream, offline) + apply mechanical payload
def _fake_stream(self, model_name=None, complete_context="", user_input="", ctx=None):
    if ctx is not None:
        ctx["full_raw_text"] = (
            "You seal the breach with a vector burn, the skiff humming. "
            "[MECHANICAL PAYLOAD] {\"hp_loss\": 4, \"ep_loss\": 2}"
        )
    yield "You seal the breach with a vector burn, the skiff humming. "

lb.LLMBridge.dispatch_ollama_turn_stream = _fake_stream

ctx = {}
gen = bridge.dispatch_ollama_turn_stream(ctx=ctx, complete_context=frame, user_input="I vector-burn past the vacuum!"
)
prose = "".join(gen)
check("director streams clean prose", "vector burn" in prose)
check("ctx captures mechanical payload", "[MECHANICAL PAYLOAD]" in ctx.get("full_raw_text", ""))

mech = bridge.inspect_llm_output(ctx["full_raw_text"])[1]
check("mechanical payload parsed", mech.get("hp_loss") == 4 and mech.get("ep_loss") == 2,
      f"hp_loss={mech.get('hp_loss')} ep_loss={mech.get('ep_loss')}")

# 10. Full navigation reachability: all 6 nodes reachable from dock
from engine.verify_dungeon import _reachable_nodes
reachable = _reachable_nodes(story_map, "node_01_dock")
check("all 6 nodes reachable", len(reachable) == 6, sorted(reachable))

# 11. Reward node has the salvage chest (/open target)
salvage = story_map["node_06_salvage_cache"]
check("salvage is reward node", salvage["node_type"] == "reward")
check("salvage has wooden chest", salvage.get("chest", {}).get("tier") == "wooden")

print()
print(f"SMOKE TEST: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)