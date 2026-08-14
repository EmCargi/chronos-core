import json
import os
import sys

def verify_dungeon_structure(json_path: str) -> bool:
    """
    Parses campaign JSON, ensuring all 5 required rooms exist as nodes and every obstacle node
    contains necessary mechanical keys: stat, skill, dv, and fail_damage.
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
    
    # 1. Ensure exactly/at least 5 rooms exist
    required_rooms = ["guardian", "puzzle", "setback", "climax", "reward"]
    found_rooms = {r: False for r in required_rooms}
    
    for node_id, node_data in nodes.items():
        for r in required_rooms:
            if r in node_id.lower():
                found_rooms[r] = True
                
    missing_rooms = [r for r, found in found_rooms.items() if not found]
    if missing_rooms:
        print(f"[Error] Missing required room nodes: {missing_rooms}")
        return False
        
    # 2. Verify obstacle nodes contain stat, skill, dv, and fail_damage keys
    for node_id, node_data in nodes.items():
        req_check = node_data.get("required_check")
        if req_check is not None:
            # Must contain stat, skill, dv, fail_damage
            required_keys = ["stat", "skill", "dv", "fail_damage"]
            missing_keys = [k for k in required_keys if k not in req_check]
            if missing_keys:
                print(f"[Error] Node '{node_id}' required_check missing keys: {missing_keys}")
                return False
                
    print(f"[Success] Validation PASSED for: {json_path}")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default verification for five_room_dungeon_v1.json
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        default_path = os.path.join(base_dir, "modules", "five_room_dungeon_v1.json")
        verify_dungeon_structure(default_path)
    else:
        verify_dungeon_structure(sys.argv[1])
