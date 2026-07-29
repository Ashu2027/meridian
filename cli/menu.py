"""
cli/menu.py
Top-level main menu router.
"""
from __future__ import annotations

import questionary
from rich import box
from rich.panel import Panel
from rich.text import Text

from cli.formatting import console, header_panel, print_logo, rule, info
from cli.screens_persons import persons_menu
from cli.screens_tone import screen_tone_config, screen_tone_history
from cli.screens_campaign import campaign_menu
from cli.screens_history import history_menu
from cli.screens_settings import screen_settings
from config import AppConfig
from db.connection import Database
from services.tone_engine import get_active_split


def run_main_menu(db: Database, cfg: AppConfig) -> None:
    """
    Persistent main loop. Returns only when the user selects Exit.
    """
    while True:
        console.clear()
        print_logo()

        # Status line
        split = get_active_split(db)
        console.print(Panel(
            Text.assemble(
                ("  Connected to TiDB: ", "meridian.muted"),
                (f"{cfg.tidb_database}", "bold meridian.accent"),
                ("  ●  ", "meridian.success"),
                ("Tone split: ", "meridian.muted"),
                (f"Pro {split.professional}%", "meridian.pro"),
                (" / ", "meridian.muted"),
                (f"Semi {split.semi_casual}%", "meridian.semi"),
                (" / ", "meridian.muted"),
                (f"Cas {split.casual}%", "meridian.cas"),
                ("  ●  ", "meridian.muted"),
                (f"API: http://{cfg.api_host}:{cfg.api_port}", "meridian.muted"),
            ),
            border_style="meridian.border",
            box=box.SIMPLE,
        ))
        console.print()

        choice = questionary.select(
            "Main Menu:",
            choices=[
                "1  Manage Persons",
                "2  Configure Tone Split",
                "3  Tone Split History",
                "4  Run / View Campaigns",
                "5  View History / Logs",
                "6  Settings & Secrets",
                "7  Exit",
            ],
            use_indicator=True,
        ).ask()

        if choice is None or choice.startswith("7"):
            console.print()
            console.print("[meridian.muted]Goodbye.[/]")
            break
        elif choice.startswith("1"):
            persons_menu(db)
        elif choice.startswith("2"):
            screen_tone_config(db)
        elif choice.startswith("3"):
            screen_tone_history(db)
        elif choice.startswith("4"):
            campaign_menu(db, cfg)
        elif choice.startswith("5"):
            history_menu(db)
        elif choice.startswith("6"):
            screen_settings(db, cfg)
