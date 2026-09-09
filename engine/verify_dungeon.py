import json
import logging
import os
import sys
from collections import deque

LEGACY_ROOMS = ["guardian", "puzzle", "setback", "climax", "reward"]
NODE_TYPES = {
    "entrance", "encounter", "puzzle", "chest", "gate", "shortcut",
    "rest", "symbol_monster", "climax", "reward", "lore",
}
CHECK_NODE_TYPES = {"encounter", "puzzle", "gate", "symbol_monster", "climax"}
NULL_CHECK_NODE_TYPES = {"rest", "reward", "entrance", "lore"}
CHEST_TIERS = {"wooden", "gold", "platinum"}
REQUIRED_CHECK_KEYS = ["stat", "skill", "dv", "fail_damage"]
MIN_LABYRINTH_NODES = 5


def _verify_legacy_5room(nodes: dict) -> bool:
    """Legacy contract (unchanged): all 5 room-keys present AND every non-null
    required_check carries stat/skill/dv/fail_damage. Returns True only if both hold."""
    found_rooms = {r: False for r in LEGACY_ROOMS}
    for node_id in nodes:
        for r in LEGACY_ROOMS:
            if r in node_id.lower():
                found_rooms[r] = True
    if not all(found_rooms.values()):
        return False

    for node_id, node_data in nodes.items():
        req_check = node_data.get("required_check")
        if req_check is not None:
            if not isinstance(req_check, dict):
                return False
            missing_keys = [k for k in REQUIRED_CHECK_KEYS if k not in req_check]
            if missing_keys:
                return False
    return True


def _reachable_nodes(nodes: dict, start: str) -> set:
    """Cycle-safe BFS from start — cyclic labyrinths (shortcut → entrance loops)
    must not crash the validator. Only counts exit targets that exist as keys."""
    seen = {start}
    queue = deque([start])
    while queue:
        node_id = queue.popleft()
        for target in (nodes.get(node_id, {}).get("exits") or {}).values():
            if target not in nodes:  # open exit — handled by L3, not a traversal target
                continue
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def _warn_dv_nonmonotonic(nodes: dict) -> None:
    """L9 advisory: warn when a deeper stratum's highest DV dips below a shallower
    stratum's. Taste, not structure — logs a warning, never fails the module."""
    max_dv_by_stratum = {}
    for node_data in nodes.values():
        req_check = node_data.get("required_check")
        if isinstance(req_check, dict):
            dv = req_check.get("dv")
            if isinstance(dv, (int, float)):
                stratum = node_data.get("stratum")
                if isinstance(stratum, int):
                    max_dv_by_stratum[stratum] = max(
                        max_dv_by_stratum.get(stratum, -1), dv
                    )
    prev = -1
    for stratum in sorted(max_dv_by_stratum):
        if max_dv_by_stratum[stratum] < prev:
            logging.warning(
                f"[Advisory] DV not monotonic across stratum {stratum} "
                "(node difficulty dips vs a shallower stratum) — authoring taste only"
            )
        prev = max_dv_by_stratum[stratum]


def _verify_labyrinth(data: dict, nodes: dict) -> bool:
    """Labyrinth contract (relaxed-union branch, only when legacy fails).
    Returns True for a valid branching labyrinth; hard-fails structural faults,
    warns on authoring taste (L9)."""
    # L1 — minimum 5 nodes, no upper cap (CP-1)
    if len(nodes) < MIN_LABYRINTH_NODES:
        print(f"[Error] Labyrinth needs at least {MIN_LABYRINTH_NODES} nodes; got {len(nodes)}")
        return False

    # L2 — starting_node is explicit and valid (Megane ruling: hard-fail, no fallback)
    start = data.get("starting_node")
    if not start or start not in nodes:
        print(f"[Error] Labyrinth missing valid starting_node (got {start!r})")
        return False

    # L2 — cycle-safe reachability: no orphan nodes
    reachable = _reachable_nodes(nodes, start)
    if len(reachable) != len(nodes):
        orphans = sorted(set(nodes) - reachable)
        print(f"[Error] Labyrinth has orphan nodes unreachable from start: {orphans}")
        return False

    # L3 — no open exits
    for node_id, node_data in nodes.items():
        for direction, target in (node_data.get("exits") or {}).items():
            if target not in nodes:
                print(f"[Error] Node '{node_id}' exit '{direction}' -> unknown '{target}'")
                return False

    for node_id, node_data in nodes.items():
        node_type = node_data.get("node_type")
        # L4 — valid node_type (CP-3: 11-type enum incl. lore)
        if node_type not in NODE_TYPES:
            print(f"[Error] Node '{node_id}' invalid node_type {node_type!r}")
            return False
        # L5 — stratum in 1-5
        stratum = node_data.get("stratum")
        if not isinstance(stratum, int) or not (1 <= stratum <= 5):
            print(f"[Error] Node '{node_id}' stratum must be int 1-5; got {stratum!r}")
            return False
        # L6 — required_check per node_type
        req_check = node_data.get("required_check")
        if node_type in CHECK_NODE_TYPES:
            if not isinstance(req_check, dict):
                print(f"[Error] Node '{node_id}' ({node_type}) needs a required_check dict")
                return False
            missing_keys = [k for k in REQUIRED_CHECK_KEYS if k not in req_check]
            if missing_keys:
                print(f"[Error] Node '{node_id}' required_check missing keys: {missing_keys}")
                return False
        elif node_type in NULL_CHECK_NODE_TYPES and req_check is not None:
            print(f"[Error] Node '{node_id}' ({node_type}) must have required_check null")
            return False
        # L7 — chest tier validity
        chest = node_data.get("chest")
        if chest is not None:
            if not isinstance(chest, dict) or chest.get("tier") not in CHEST_TIERS:
                print(f"[Error] Node '{node_id}' chest tier must be one of {sorted(CHEST_TIERS)}")
                return False
        # L8 — symbol coupling
        if node_data.get("symbol") is True and node_type != "symbol_monster":
            print(f"[Error] Node '{node_id}' has symbol:true but node_type is '{node_type}'")
            return False

    # L9 — advisory DV monotonicity (warns, still passes)
    _warn_dv_nonmonotonic(nodes)
    return True


def verify_dungeon_structure(json_path: str) -> bool:
    """
    Parses campaign JSON, validating it against the relaxed union: a module passes
    if it is EITHER a legacy linear 5-room map (unchanged) OR a valid branching
    labyrinth module (stratum/node_type/chest/symbol contract). Legacy runs first.
    """
    if not os.path.exists(json_path):
        print(f"[Error] File not found: {json_path}")
        return False

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[Error] Failed to parse JSON: {e}")
        return False

    nodes = data.get("nodes", {})

    # Legacy path first — unchanged semantics, so 9 shipped modules + 18 tests pass untouched.
    if _verify_legacy_5room(nodes):
        print(f"[Success] Validation PASSED for: {json_path}")
        return True

    # Labyrinth path only when legacy fails.
    if _verify_labyrinth(data, nodes):
        print(f"[Success] Validation PASSED (labyrinth) for: {json_path}")
        return True

    return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default verification for five_room_dungeon_v1.json
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        default_path = os.path.join(base_dir, "modules", "five_room_dungeon_v1.json")
        verify_dungeon_structure(default_path)
    else:
        verify_dungeon_structure(sys.argv[1])
