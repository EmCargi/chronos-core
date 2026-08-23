"""Generate greeting DRAFTS for guild_rpg characters via big-rig Cydonia.

This is the persona-etl Cydonia path (core.ollama -> big-rig Ollama), scoped to
greeting authoring. It does NOT touch the vault Character Markdowns — it writes
review drafts to greeting_drafts/<slug>.md. Once Megane approves a draft, a
separate step appends it to the vault file as the GREETINGS section
(First Message + Alternate Greeting N), matching the Morwen format.

Run with the root venv (needs tenacity):
    /home/megane/dev/venv/bin/python generate_greetings.py
"""
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Path-agnostic bootstrap: dev/ (shared core) + chronos-core/ on sys.path.
BASE_DIR = Path(__file__).resolve().parent
DEV_DIR = str(BASE_DIR.parent.parent)  # /home/megane/dev — shared core lives here
for p in (DEV_DIR, str(BASE_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from core.ollama import default_chain, post_json
from core.reasoning import clean_reasoning_response
from engine import guild_roster as gr

CYDONIA = "hf.co/bartowski/TheDrummer_Cydonia-24B-v4.3-GGUF:Q4_K_M"
FALLBACK = "deepseek-r1:7b"
CHAIN = default_chain(CYDONIA, FALLBACK)
DRAFT_DIR = BASE_DIR / "greeting_drafts"
DRAFT_DIR.mkdir(exist_ok=True)

# Tier-1 targets: name -> (source markdown, focus note, source section marker)
# Soren and Urkakh share the party card; `section` extracts just that
# character's block so Cydonia can't default to the other POV.
TARGETS = {
    "Kari": ("B-Rank/Kari B-Rank.md", None, None),
    "Nico Scruffvale": ("C-Rank/Nico Scruffvale.md", None, None),
    "Soren": ("B-Rank/Soren and Urkakh B-Rank.md", "Soren is one half of the Soren+Urkakh adventurer party. Write greetings from Soren's POV only — he is the human quartermaster, never the orc Urkakh.", "Soren"),
    "Thora": ("C-Rank/Thora C-Rank.md", None, None),
    "Urkakh": ("B-Rank/Soren and Urkakh B-Rank.md", "Urkakh is the orc frontliner of the Soren+Urkakh adventurer party. Write greetings from Urkakh's POV only — he is the orc warrior, never the human Soren.", "Urkakh"),
}


def extract_section(text, marker):
    """Pull the <marker>...</marker> (or to next <tag>/EOF) block from a shared card."""
    if not marker:
        return text
    m = re.search(rf"<{re.escape(marker)}>", text)
    if not m:
        return text
    start = m.end()
    nxt = re.search(r"<[A-Za-z/]", text[start:])
    end = start + nxt.start() if nxt else len(text)
    return text[start:end]
VAULT = "/home/megane/dev/digital-dm-project/guild-rpg-digital-dm/Characters/Official AK Characters/Character Markdowns"

SYSTEM = (
    "You are a character-greeting writer for a BESM 4e tabletop-RPG SillyTavern-style "
    "card. You write the opening 'greeting' messages a character uses when a player first "
    "meets them in the Aelthar Keldor guild world. Write in the character's established voice "
    "and STRICTLY honor their Narrative Syntax — especially any Sixth Guard collapse, which "
    "must read as a real breaking point and is NEVER softened or averted. Use {{char}} for the "
    "character and {{user}} for the player. Output ONLY the greeting section in the exact "
    "markdown format requested, with no preamble, no code fences, and no commentary."
)


def build_user_prompt(name, grounding, focus):
    focus_line = f"\nNOTE: {focus}\n" if focus else ""
    return f"""CHARACTER: {name}
CRITICAL: Write greetings for {name} ONLY. Do not write any other character's greetings.
{focus_line}
--- CHARACTER GROUNDING (profile + Narrative Syntax) ---
{grounding}
--- END GROUNDING ---

TASK: Write 4 greetings for {{char}} in this EXACT format (headers on their own lines):

First Message (N token(s))

<greeting 1: prose with *action/emphasis in italics* and "spoken dialogue in quotes", grounded in the character's world>

Alternate Greeting 1

<greeting 2>

Alternate Greeting 2

<greeting 3>

Alternate Greeting 3

<greeting 4>

REQUIREMENTS:
- Greeting 1 (First Message) and at least one Alternate must be a DOMESTIC scene at the Aelthar Keldor guild hall / tavern / reception (anchors as a [Hub] start).
- At least one Alternate must be a FIELD/QUEST scene (forest, ruins, dungeon) so it tags [Quest].
- Vary mood and situation across the four. Each greeting should be substantial (3-6 sentences of prose plus dialogue).
- Honor the character's Sixth Guard / Structural Fault if present — the collapse is a real breaking point, never softened.
- Use {{char}} / {{user}} tokens. No out-of-character text, no explanations.

OUTPUT FORMAT (strict — four greetings, plain headers, no markdown emphasis, no code fences):
First Message

<3-6 sentences of italic prose scene-setting, then dialogue>

Alternate Greeting 1

<another scene>

Alternate Greeting 2

<another scene, ideally a field/quest scene>

Alternate Greeting 3

<another scene>

Do NOT wrap the output in ``` code fences. Use exactly the header words
"First Message" and "Alternate Greeting N" on their own lines."""


def canonicalize_greetings(raw):
    """Normalize Cydonia's free-form output into the Morwen/SillyTavern
    alternate-export format the parser expects: bare `First Message` +
    `Alternate Greeting N` headers, `{{char}}`/`{{user}}` tokens, renumbered
    sequentially. Tolerates H1/H2 header marks, parenthetical labels like
    `(Hub)`, missing First Message header, and single-brace `{user}`."""
    text = clean_reasoning_response(raw)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # Single-brace -> double-brace tokens so the roster getter can substitute
    text = re.sub(r"(?<!\{)\{user\}(?!\})", "{{user}}", text)
    text = re.sub(r"(?<!\{)\{char\}(?!\})", "{{char}}", text)
    # Strip markdown header hashes from every line
    text = re.sub(r"(?imss)^(#{1,6})\s*", "", text)
    # Normalize greeting header lines regardless of emphasis: **First Message**,
    # *First Message*, **First Message (12 token(s))** -> First Message
    text = re.sub(
        r"(?im)^\s*\*+(first message|alternate greeting\s*\d+)\*+\s*(\([^)]*\))?\s*$",
        r"\1",
        text,
    )
    # Drop (Hub)/(Quest) parentheticals on greeting header lines
    text = re.sub(r"(?im)^\s*(first message|alternate greeting\s*\d+)\s*\([^)]*\)\s*$", r"\1", text)
    # Split on header lines: First Message / Alternate Greeting N
    parts = re.split(r"(?im)^\s*(first message|alternate greeting\s+\d+)\s*$", text)
    greetings = []
    for i in range(1, len(parts), 2):
        body = (parts[i + 1] if i + 1 < len(parts) else "").strip()
        if body:
            greetings.append(body)
    if not greetings:
        return ""
    lines = []
    for idx, body in enumerate(greetings):
        header = "First Message" if idx == 0 else f"Alternate Greeting {idx}"
        lines.append(header)
        lines.append("")
        lines.append(body)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Generate only this one character (e.g. Urkakh)")
    args = ap.parse_args()
    targets = TARGETS
    if args.only:
        targets = {k: v for k, v in TARGETS.items() if k.lower() == args.only.lower()}
        if not targets:
            print(f"Unknown target: {args.only}")
            return
    for name, (rel, focus, section) in targets.items():
        src = os.path.join(VAULT, rel)
        with open(src, "r", encoding="utf-8") as f:
            grounding = f.read()
        if section:
            grounding = extract_section(grounding, section)
        print(f"\n=== Generating greetings for {name} (from {rel}) ===")
        user = build_user_prompt(name, grounding, focus)

        def builder(model):
            return {
                "model": model,
                "prompt": user,
                "system": SYSTEM,
                "stream": False,
                "options": {"temperature": 0.85, "num_predict": 3000},
            }

        # Retry until Cydonia returns a parseable multi-greeting response
        block = ""
        for attempt in range(1, 4):
            raw = post_json("/api/generate", builder, CHAIN, timeout=300)
            block = canonicalize_greetings(raw.get("response", ""))
            n = len(re.findall(r"(?im)^\s*(first message|alternate greeting)", block))
            if n >= 2:
                break
            print(f"  ⚠️ attempt {attempt} yielded {n} greetings; retrying...")

        slug = name.lower().replace(" ", "_")
        draft_path = DRAFT_DIR / f"{slug}_greetings_draft.md"
        header = (
            f"<!-- GREETING DRAFT | model: {CYDONIA} (big-rig) | "
            f"generated: {datetime.now():%Y-%m-%d %H:%M} | STATUS: PENDING REVIEW\n"
            f"     source: {src}\n"
            f"     approve: review below, then ask to append as the GREETINGS section\n"
            f"     (First Message + Alternate Greeting N) to the vault Character Markdown. -->\n\n"
        )
        draft_path.write_text(header + block + "\n", encoding="utf-8")
        # Count greetings for a quick sanity report
        n = len(re.findall(r"(?im)^\s*(first message|alternate greeting)", block))
        print(f"  ✅ draft written: {draft_path}  ({n} greeting headers found)")


if __name__ == "__main__":
    main()
