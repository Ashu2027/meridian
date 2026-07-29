"""
cli/screens_settings.py
Settings & Secrets management screen.
"""
from __future__ import annotations

import questionary
from rich import box
from rich.panel import Panel

from cli.formatting import console, header_panel, success, error, warn, info
from config import AppConfig, save_config
from db.connection import Database


def screen_settings(db: Database, cfg: AppConfig) -> None:
    while True:
        console.clear()
        console.print(header_panel(
            "SETTINGS & SECRETS",
            f"Connected: {cfg.tidb_user}@{cfg.tidb_host}:{cfg.tidb_port}/{cfg.tidb_database}"
        ))
        console.print()

        choice = questionary.select(
            "Select setting to change:",
            choices=[
                "Update TiDB Credentials",
                "Update Resend API Key",
                "Change Default Sender Identity",
                "Change Max Words per Message",
                "Change Emoji Policy",
                "Change Send Rate Limit",
                "Update API Server Settings",
                "Test All Connections",
                "Back to Main Menu",
            ],
        ).ask()

        if choice is None or choice == "Back to Main Menu":
            return
        elif choice == "Update TiDB Credentials":
            _update_tidb(db, cfg)
        elif choice == "Update Resend API Key":
            _update_resend(cfg)
        elif choice == "Change Default Sender Identity":
            _update_sender(cfg)
        elif choice == "Change Max Words per Message":
            _update_max_words(db)
        elif choice == "Change Emoji Policy":
            _update_emoji_policy(db)
        elif choice == "Change Send Rate Limit":
            _update_rate(db)
        elif choice == "Update API Server Settings":
            _update_api(cfg)
        elif choice == "Test All Connections":
            _test_connections(db, cfg)


def _update_tidb(db: Database, cfg: AppConfig) -> None:
    console.print()
    info(f"Current: {cfg.tidb_user}@{cfg.tidb_host}:{cfg.tidb_port}/{cfg.tidb_database}")

    cfg.tidb_host = questionary.text("New host:", default=cfg.tidb_host).ask() or cfg.tidb_host
    cfg.tidb_port = int(questionary.text("New port:", default=str(cfg.tidb_port)).ask() or cfg.tidb_port)
    cfg.tidb_user = questionary.text("New user:", default=cfg.tidb_user).ask() or cfg.tidb_user
    new_pass = questionary.password("New password (leave blank to keep current):").ask()
    if new_pass:
        cfg.tidb_password = new_pass

    save_config(cfg)
    success("TiDB credentials updated.")
    questionary.press_any_key_to_continue().ask()


def _update_resend(cfg: AppConfig) -> None:
    console.print()
    masked = cfg.resend_api_key[:8] + "…" if cfg.resend_api_key else "(not set)"
    info(f"Current Resend key: {masked}")
    new_key = questionary.password(
        "New Resend API key (re_...):",
        validate=lambda v: True if v.strip().startswith("re_") else "Key must start with 're_'.",
    ).ask()
    if new_key:
        cfg.resend_api_key = new_key
        save_config(cfg)
        success("Resend API key updated.")
    questionary.press_any_key_to_continue().ask()


def _update_sender(cfg: AppConfig) -> None:
    console.print()
    info(f"Current sender: {cfg.default_from_name} <{cfg.default_from_email}>")
    new_name = questionary.text("From name:", default=cfg.default_from_name).ask() or cfg.default_from_name
    new_email = questionary.text(
        "From email:",
        default=cfg.default_from_email,
        validate=lambda v: True if "@" in v else "Must be a valid email.",
    ).ask()
    if new_name:
        cfg.default_from_name = new_name
    if new_email:
        cfg.default_from_email = new_email
    save_config(cfg)
    success(f"Sender updated to: {cfg.default_from_name} <{cfg.default_from_email}>")
    questionary.press_any_key_to_continue().ask()


def _update_max_words(db: Database) -> None:
    console.print()
    current = db.get_config_value("max_words_per_message", "200")
    info(f"Current max words: {current}")
    new_val = questionary.text(
        "New limit:",
        default=current,
        validate=lambda v: True if v.strip().isdigit() else "Must be a number.",
    ).ask()
    if new_val:
        db.set_config_value("max_words_per_message", new_val.strip())
        success(f"Max words per message set to {new_val}.")
    questionary.press_any_key_to_continue().ask()


def _update_emoji_policy(db: Database) -> None:
    console.print()
    current = db.get_config_value("allow_emoji", "false")
    info(f"Current emoji policy: {'ALLOWED' if current == 'true' else 'BLOCKED'}")
    choice = questionary.select(
        "New emoji policy:", choices=["Block emoji (false)", "Allow emoji (true)"]
    ).ask()
    if choice:
        new_val = "true" if "true" in choice else "false"
        db.set_config_value("allow_emoji", new_val)
        success(f"Emoji policy updated to: {new_val}")
    questionary.press_any_key_to_continue().ask()


def _update_rate(db: Database) -> None:
    console.print()
    current = db.get_config_value("send_rate_per_minute", "20")
    info(f"Current send rate: {current} emails/minute")
    new_val = questionary.text(
        "New rate (emails per minute):",
        default=current,
        validate=lambda v: True if v.strip().isdigit() else "Must be a number.",
    ).ask()
    if new_val:
        db.set_config_value("send_rate_per_minute", new_val.strip())
        success(f"Send rate updated to {new_val}/min.")
    questionary.press_any_key_to_continue().ask()


def _update_api(cfg: AppConfig) -> None:
    console.print()
    info(f"Current API: http://{cfg.api_host}:{cfg.api_port}")
    cfg.api_host = questionary.text("API host:", default=cfg.api_host).ask() or cfg.api_host
    cfg.api_port = int(questionary.text("API port:", default=str(cfg.api_port)).ask() or cfg.api_port)
    new_token = questionary.password("New API token (leave blank to keep current):").ask()
    if new_token:
        cfg.api_secret_token = new_token
    save_config(cfg)
    success("API settings updated.")
    questionary.press_any_key_to_continue().ask()


def _test_connections(db: Database, cfg: AppConfig) -> None:
    console.print()
    info("Testing TiDB…")
    if db.ping():
        success("TiDB connection OK")
    else:
        error("TiDB connection FAILED")

    info("Testing Resend API key format…")
    if cfg.resend_api_key.startswith("re_"):
        success("Resend API key format OK (re_…)")
    else:
        warn("Resend API key does not start with 're_' — may be invalid")

    info(f"API server configured at http://{cfg.api_host}:{cfg.api_port}")
    success("All checks complete.")
    questionary.press_any_key_to_continue().ask()
