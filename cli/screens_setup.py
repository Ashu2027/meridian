"""
cli/screens_setup.py
5-step first-run setup wizard.
Collects TiDB credentials, Resend key, sender identity, then writes the
encrypted secrets file and applies the database schema.
"""
from __future__ import annotations

import secrets
import string

import questionary
from rich.panel import Panel
from rich import box

from cli.formatting import console, header_panel, success, error, warn, info, rule
from config import AppConfig, save_config
from db.connection import Database, wait_for_connection, apply_schema
from services.secrets_manager import generate_local_key, secrets_exist


def _gen_token(n: int = 32) -> str:
    """Generate a URL-safe random token for API auth."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def run_setup_wizard() -> AppConfig:
    """
    Interactive 5-step first-run wizard.
    Returns a fully populated AppConfig after writing secrets to disk.
    """
    console.clear()
    console.print(header_panel(
        "MERIDIAN — FIRST-TIME SETUP",
        "Let's get you connected and ready to send.",
    ))
    console.print()

    cfg = AppConfig()

    # ── Step 1 — TiDB Connection ───────────────────────────────────────────────
    console.print(Panel(
        "[meridian.title]Step 1 of 5[/] — [bold]TiDB Connection[/]",
        border_style="meridian.border", box=box.ROUNDED,
    ))
    console.print()

    cfg.tidb_host = questionary.text(
        "TiDB Host:",
        validate=lambda v: True if v.strip() else "Host cannot be empty.",
    ).ask()
    if cfg.tidb_host is None:
        raise KeyboardInterrupt

    cfg.tidb_port = int(questionary.text(
        "TiDB Port:",
        default="4000",
        validate=lambda v: True if v.strip().isdigit() else "Port must be a number.",
    ).ask() or "4000")

    cfg.tidb_user = questionary.text(
        "Username:",
        validate=lambda v: True if v.strip() else "Username cannot be empty.",
    ).ask()

    cfg.tidb_password = questionary.password(
        "Password:",
    ).ask()

    cfg.tidb_database = questionary.text(
        "Database name:",
        default="meridian",
    ).ask() or "meridian"

    use_tls = questionary.confirm("Use TLS? (recommended for TiDB Cloud)", default=True).ask()
    cfg.tidb_use_tls = use_tls

    if use_tls:
        ca_path = questionary.text(
            "Path to CA certificate (leave blank to use system CA):",
            default="",
        ).ask()
        cfg.tidb_ssl_ca = ca_path.strip() or None

    # Test connection
    info("Testing TiDB connection…")
    db = Database(cfg)
    if not wait_for_connection(db, retries=3, delay=2.0):
        error("Cannot connect to TiDB with those credentials.")
        error("Please check your host, port, and credentials, then restart the setup.")
        raise SystemExit(2)
    success("TiDB connection successful!")
    console.print()

    # ── Step 2 — Resend API Key ────────────────────────────────────────────────
    console.print(Panel(
        "[meridian.title]Step 2 of 5[/] — [bold]Resend API Key[/]",
        border_style="meridian.border", box=box.ROUNDED,
    ))
    console.print()
    info("Get your key from: [link=https://resend.com/api-keys]https://resend.com/api-keys[/link]")

    cfg.resend_api_key = questionary.password(
        "Resend API Key (re_...):",
        validate=lambda v: True if v.strip().startswith("re_") else "Key must start with 're_'.",
    ).ask()
    if cfg.resend_api_key is None:
        raise KeyboardInterrupt
    console.print()

    # ── Step 3 — Sender Identity ───────────────────────────────────────────────
    console.print(Panel(
        "[meridian.title]Step 3 of 5[/] — [bold]Default Sender Identity[/]",
        border_style="meridian.border", box=box.ROUNDED,
    ))
    console.print()
    warn("The 'From' email must be a domain verified in your Resend account.")

    cfg.default_from_name = questionary.text(
        "From name:",
        default="Meridian Desk",
    ).ask() or "Meridian Desk"

    cfg.default_from_email = questionary.text(
        "From email (e.g. outreach@yourdomain.com):",
        validate=lambda v: True if "@" in v.strip() else "Must be a valid email address.",
    ).ask()
    if cfg.default_from_email is None:
        raise KeyboardInterrupt
    console.print()

    # ── Step 4 — API Server Token ──────────────────────────────────────────────
    console.print(Panel(
        "[meridian.title]Step 4 of 5[/] — [bold]FastAPI Server Configuration[/]",
        border_style="meridian.border", box=box.ROUNDED,
    ))
    console.print()
    info("The FastAPI server allows agents (Claude Code, Antigravity, etc.) to call Meridian.")

    cfg.api_host = questionary.text("API server host:", default="127.0.0.1").ask() or "127.0.0.1"
    cfg.api_port = int(questionary.text(
        "API server port:", default="8765",
        validate=lambda v: True if v.strip().isdigit() else "Must be a number.",
    ).ask() or "8765")

    auto_token = _gen_token()
    use_auto = questionary.confirm(
        f"Auto-generate a secure API token? (token will be shown once)", default=True
    ).ask()
    if use_auto:
        cfg.api_secret_token = auto_token
        console.print()
        console.print(Panel(
            f"[bold]Your API Bearer Token (save this now!):[/]\n\n"
            f"[meridian.accent]{auto_token}[/]\n\n"
            "[meridian.muted]This token is required to call the FastAPI server from agents.[/]",
            border_style="meridian.warn",
            box=box.DOUBLE_EDGE,
        ))
        questionary.press_any_key_to_continue("Press any key to continue…").ask()
    else:
        cfg.api_secret_token = questionary.password(
            "Enter your API token:",
            validate=lambda v: True if len(v.strip()) >= 16 else "Token must be at least 16 characters.",
        ).ask()
    console.print()

    # ── Step 5 — Review & Confirm ──────────────────────────────────────────────
    console.print(Panel(
        "[meridian.title]Step 5 of 5[/] — [bold]Review & Confirm[/]",
        border_style="meridian.border", box=box.ROUNDED,
    ))
    console.print()
    info(f"TiDB:    [bold]{cfg.tidb_user}@{cfg.tidb_host}:{cfg.tidb_port}/{cfg.tidb_database}[/]  TLS={'on' if cfg.tidb_use_tls else 'off'}")
    info(f"Resend:  [bold]{cfg.resend_api_key[:8]}…[/]")
    info(f"From:    [bold]{cfg.default_from_name} <{cfg.default_from_email}>[/]")
    info(f"API:     [bold]http://{cfg.api_host}:{cfg.api_port}[/]")
    console.print()

    confirmed = questionary.confirm("Save configuration and apply database schema?", default=True).ask()
    if not confirmed:
        warn("Setup cancelled. No changes were saved.")
        raise SystemExit(0)

    # Save secrets
    generate_local_key()
    save_config(cfg)
    success("Secrets encrypted and saved.")

    # Apply schema
    info("Applying database schema…")
    try:
        apply_schema(db)
        success("Schema applied. Meridian is ready!")
    except Exception as exc:
        error(f"Schema application failed: {exc}")
        raise SystemExit(2)

    console.print()
    questionary.press_any_key_to_continue(
        "[meridian.muted]Press any key to enter the main menu…[/]"
    ).ask()
    return cfg
