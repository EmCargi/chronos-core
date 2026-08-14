from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import random

class CharacterSchema(BaseModel):
    name: str
    points_budget: int = 75
    stat_body: int = Field(..., ge=1, le=12)
    stat_mind: int = Field(..., ge=1, le=12)
    stat_soul: int = Field(..., ge=1, le=12)
    current_hp: Optional[int] = None
    current_ep: Optional[int] = None

    # BESA rules fields — populated from roster DB at runtime
    shock_value: int = 0
    combat_techniques: List[Dict[str, Any]] = []
    skills: List[Dict[str, Any]] = []
    defects: List[Dict[str, Any]] = []

    @property
    def max_hp(self) -> int:
        return (self.stat_body + self.stat_soul) * 5

    @property
    def max_ep(self) -> int:
        return (self.stat_mind + self.stat_soul) * 5

    @property
    def base_acv(self) -> int:
        return (self.stat_body + self.stat_mind + self.stat_soul) // 3

    @property
    def base_dcv(self) -> int:
        return self.base_acv - 2

    @property
    def shock_value_computed(self) -> int:
        """Recompute from base HP + Hardboiled techniques."""
        base_sv = self.max_hp // 5
        hardboiled = sum(10 * t.get("level", 1) for t in self.combat_techniques
                         if isinstance(t, dict) and t.get("name", "").lower() == "hardboiled")
        return min(base_sv + hardboiled, self.max_hp // 2)

class NodeSchema(BaseModel):
    node_id: str
    title: str
    description: str
    exits: Dict[str, str]
    required_check: Optional[Dict[str, Any]] = None

def execute_action_check(stat_rank: int, skill_rank: int, difficulty_value: int) -> dict:
    """
    Rolls 2d6 cleanly using python's random.randint(1, 6).
    Calculates total: roll_sum + stat_rank + skill_rank.
    Returns a dictionary tracking success status and details.
    """
    die1 = random.randint(1, 6)
    die2 = random.randint(1, 6)
    roll_sum = die1 + die2
    total = roll_sum + stat_rank + skill_rank
    success = total >= difficulty_value
    return {
        "success": success,
        "roll": roll_sum,
        "total": total,
        "target": difficulty_value
    }
