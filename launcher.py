#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/ — shared core
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # chronos-core/

from chronos import main as run_game
from engine.char_wizard import run_character_wizard
from engine.batch_ingest import run_auto_ingest
from engine.verify_dungeon import verify_dungeon_structure

def show_menu():
    console = Console()
    while True:
        console.clear()
        menu_text = """
 [bold cyan]1.[/bold cyan] 🎮 [bold white]Launch Chronos Core[/bold white] (Main Game Loop)
 [bold cyan]2.[/bold cyan] 🧙 [bold white]Character Creator Wizard[/bold white] (Interactive sheet builder)
 [bold cyan]3.[/bold cyan] 📥 [bold white]Auto-Ingest Staging Sweep[/bold white] (Import raw character cards)
 [bold cyan]4.[/bold cyan] 🔍 [bold white]Verify Campaign Module[/bold white] (Dungeon structure validation)
 [bold cyan]5.[/bold cyan] ❌ [bold white]Exit[/bold white]
"""
        console.print(Panel(
            menu_text,
            title="[bold gold1]⚡ CHRONOS CORE COMMAND LAUNCHER ⚡[/bold gold1]",
            border_style="cyan",
            padding=(1, 2)
        ))
        
        choice = Prompt.ask("[bold magenta]Select option[/bold magenta]", choices=["1", "2", "3", "4", "5"], default="1")
        
        if choice == "1":
            console.clear()
            try:
                run_game()
            except Exception as e:
                console.print(f"[bold red]Execution error:[/bold red] {e}")
                input("\nPress Enter to return to launcher menu...")
        elif choice == "2":
            console.clear()
            try:
                run_character_wizard()
            except Exception as e:
                console.print(f"[bold red]Execution error:[/bold red] {e}")
            input("\nPress Enter to return to launcher menu...")
        elif choice == "3":
            console.clear()
            console.print("[bold cyan]System:[/bold cyan] Scanning staging/raw/ for JSON characters...")
            try:
                res = run_auto_ingest()
                proc_cnt = len(res["processed"])
                fail_cnt = len(res["failed"])
                console.print(f"[bold green]Auto-Ingest Complete:[/bold green] Ingested {proc_cnt} files, failed {fail_cnt} files.")
            except Exception as e:
                console.print(f"[bold red]Ingestion error:[/bold red] {e}")
            input("\nPress Enter to return to launcher menu...")
        elif choice == "4":
            console.clear()
            module_name = input("Enter path to campaign module JSON (default: modules/five_room_dungeon_v1.json): ").strip()
            if not module_name:
                module_name = "modules/five_room_dungeon_v1.json"
            try:
                verify_dungeon_structure(module_name)
            except Exception as e:
                console.print(f"[bold red]Verification error:[/bold red] {e}")
            input("\nPress Enter to return to launcher menu...")
        elif choice == "5":
            console.print("\n[bold red]Exiting Chronos Core Launcher. Goodbye operative.[/bold red]\n")
            break

if __name__ == "__main__":
    show_menu()
