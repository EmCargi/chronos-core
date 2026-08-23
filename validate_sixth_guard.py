"""Audit every greeted character's greetings against their enforced Sixth Guard.

The engine's core premise is that a character's Sixth Guard — their terminal
failure point — MUST collapse and can never be softened. Greetings are static
authored prose, so a greeting can *leak* that enforcement: depicting the
character trivially overcoming, narratively resolving, or being immune to the
guard. This auditor pulls each character's `sixth_guard` / `structural_fault`
from the roster and asks the big-rig judge model (Cydonia) to verdict every
greeting as `honors` or `leak`.

Run:  /home/megane/dev/venv/bin/python validate_sixth_guard.py [--only <name>]
Writes a markdown report to sixth_guard_audit_report.md and prints a leak summary.
"""
import argparse
import json
import re
import sys
import os
from pathlib import Path

sys.path.insert(0, "/home/megane/dev")
sys.path.insert(0, "/home/megane/dev/digital-dm-project/chronos-core")

from pydantic import BaseModel, Field, ConfigDict, ValidationError
from core.ollama import default_chain, post_json

from engine import guild_roster as gr

SETTING_ID = "guild_rpg"
CYDONIA = "hf.co/bartowski/TheDrummer_Cydonia-24B-v4.3-GGUF:Q4_K_M"
FALLBACK = "deepseek-r1:7b"
CHAIN = default_chain(CYDONIA, FALLBACK)

SYSTEM = """You are a strict lore-consistency auditor for a tabletop RPG engine.
The engine enforces each character's SIXTH GUARD — a precisely defined terminal
failure point with an explicit TRIGGER (the "exact millisecond" condition that
begins collapse) and a COLLAPSE (what happens). A character's STRUCTURAL FAULT
is contextual weakness and is NOT what you judge.

Greetings are OPENING scenes where the player ("you") has just arrived. Three
design truths MUST inform your verdict:

1. PLAYER SOFTENING IS INTENDED. If the greeting shows the guard's trigger
   onset and the player arriving/helping, the collapse is PENDING/incipient — it
   is the meet-hook, NOT a leak. The guard is not "softened" merely because help
   is at hand.
2. PREPARING / EMBRACING THE GUARD IS VALID. A character who plans for, holds
   the line against, or accepts their guard (contingencies, "until my last
   breath", fallbacks) is HONORS — accepting the guard's reality is the OPPOSITE
   of softening.
3. ONE-TIME EMERGENCY MEASURES ARE VALID. A limited, single-use resource (e.g.
   Arcane Renewal as one emergency use) is a contingency, NOT a cure.

DECIDE HONORS vs LEAK for EACH greeting by this strict rule:

- HONORS: the greeting does not depict the trigger; OR it depicts the trigger
  onset with the collapse PENDING (player arriving, character planning,
  contingency in play, or one-shot emergency measure used); OR it shows the
  collapse actually occurring. A character shown competent, relaxed, in trouble,
  or rescued is HONORS. Absence of a resolved collapse is never a leak.
- LEAK: the greeting ASSERTS the character is IMMUNE to the guard, or that the
  guard CANNOT / WILL NOT ever trigger, or that the collapse is PERMANENTLY and
  unconditionally bypassed/cured. Only an explicit, unconditional denial of the
  guard's reality is a leak. Survival via ordinary competence, a contingency, a
  one-shot, or player help is NEVER a leak.

JUDGE ONLY AGAINST THE SIXTH GUARD. Merely showing the Structural Fault without
depicting the guard's trigger is always HONORS.

Output ONLY JSON, no prose, no markdown fences:
{"Character": "<name>", "Verdicts": [{"Index": <int>, "Verdict": "honors"|"leak", "Reason": "<short; cite trigger depicted + whether collapse is denied vs pending>"}]}
One Verdict per greeting, in order."""


class GreetingVerdict(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    index: int = Field(alias="Index")
    verdict: str = Field(alias="Verdict")
    reason: str = Field(alias="Reason")


class GuardAudit(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    character: str = Field(alias="Character")
    verdicts: list[GreetingVerdict] = Field(alias="Verdicts")


def extract_json(text: str):
    """Pull the first balanced JSON object out of a model response.

    Handles markdown fences and truncated/streamed responses: scans for the
    first '{' and walks to its matching '}' (respecting strings), so a cut-off
    tail doesn't blow up the parse.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    end = -1
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end != -1:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            return None
    return None


def audit_character(name: str) -> dict | None:
    char = gr.get_character(SETTING_ID, name)
    if not char:
        return None
    sixth = (char.get("sixth_guard") or "").strip()
    fault = (char.get("structural_fault") or "").strip()
    levers = (char.get("levers") or "").strip()
    if not sixth and not fault:
        return {"character": name, "skipped": "no sixth_guard/structural_fault set"}
    greetings = gr.get_character_greetings(SETTING_ID, name)
    if not greetings:
        return {"character": name, "skipped": "no greetings"}
    greeting_block = "\n\n".join(
        f"{i + 1}. {g['text']}" for i, g in enumerate(greetings)
    )
    user = (
        f"Character: {name}\n"
        f"Sixth Guard: {sixth}\n"
        f"Structural Fault: {fault}\n"
        f"Levers: {levers}\n\n"
        f"Greetings:\n{greeting_block}\n"
    )

    def builder(model):
        return {
            "model": model,
            "prompt": user,
            "system": SYSTEM,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2, "num_predict": 2500},
        }

    raw = post_json("/api/generate", builder, CHAIN, timeout=300)
    resp = raw.get("response", "")
    data = extract_json(resp)
    if not data:
        return {"character": name, "error": "unparseable judge response", "raw": resp[:300]}
    try:
        audit = GuardAudit.model_validate(data)
    except ValidationError as e:
        return {"character": name, "error": f"schema mismatch: {e}", "raw": resp[:300]}
    return {
        "character": name,
        "verdicts": [
            {"index": v.index, "verdict": v.verdict, "reason": v.reason}
            for v in audit.verdicts
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Audit only this one character")
    ap.add_argument("--report", default="sixth_guard_audit_report.md")
    args = ap.parse_args()

    conn = gr.get_roster_connection()
    rows = conn.execute(
        "SELECT name FROM characters WHERE setting_id = ?", (SETTING_ID,)
    ).fetchall()
    conn.close()
    names = [r["name"] for r in rows]
    if args.only:
        names = [n for n in names if n.lower() == args.only.lower()]
        if not names:
            print(f"Unknown character: {args.only}")
            return

    results = []
    leaks = []

    def write_report():
        lines = [
            "# Sixth Guard Leak Audit",
            "",
            "A greeting LEAKS only if it asserts the character is IMMUNE to their Sixth "
            "Guard, that the guard CANNOT/WILL NOT ever trigger, or that the collapse is "
            "PERMANENTLY and unconditionally bypassed/cured.",
            "",
            "These are NOT leaks (by engine design): the player arriving and softening the "
            "blow (meet-hook); a character planning/preparing for or embracing their guard; "
            "a one-time emergency measure used as a contingency; survival via ordinary "
            "competence or player help.",
            "",
            f"Characters audited: {len(results)}",
            f"Leaks found: {len(leaks)}",
            "",
        ]
        for res in results:
            name = res["character"]
            if res.get("skipped"):
                lines.append(f"## {name} — skipped ({res['skipped']})")
                continue
            if res.get("error"):
                lines.append(f"## {name} — ERROR: {res['error']}")
                continue
            lines.append(f"## {name}")
            for v in res["verdicts"]:
                mark = "LEAK" if v["verdict"].lower() == "leak" else "honors"
                lines.append(f"- **g{v['index']} [{mark}]** — {v['reason']}")
            lines.append("")
        Path(args.report).write_text("\n".join(lines), encoding="utf-8")

    for name in names:
        print(f"  auditing {name} ...", flush=True)
        try:
            res = audit_character(name)
        except Exception as e:  # one bad character must not abort the run
            res = {"character": name, "error": f"exception: {type(e).__name__}: {e}"}
        if not res:
            continue
        results.append(res)
        if res.get("skipped") or res.get("error"):
            print(f"    {res.get('skipped') or res.get('error')}")
            write_report()
            continue
        for v in res["verdicts"]:
            tag = "LEAK " if v["verdict"].lower() == "leak" else "ok   "
            print(f"    [{tag}] g{v['index']}: {v['reason'][:80]}")
            if v["verdict"].lower() == "leak":
                leaks.append((name, v["index"], v["reason"]))
        write_report()

    write_report()

    print(f"\n=== SUMMARY: {len(results)} audited, {len(leaks)} leaks ===")
    for name, idx, reason in leaks:
        print(f"  LEAK {name} g{idx}: {reason}")


if __name__ == "__main__":
    main()
