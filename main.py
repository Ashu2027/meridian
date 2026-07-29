"""
main.py
Entry point for Meridian.
 - `python main.py`                     → Human CLI (setup wizard or main menu)
 - `python main.py agent <action> --json '{...}'` → Non-interactive agent interface
 - `python main.py server`              → Start FastAPI server only
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# ── Logging setup ──────────────────────────────────────────────────────────────
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            LOG_DIR / "meridian.log",
            maxBytes=5 * 1024 * 1024,    # 5 MB
            backupCount=3,
            encoding="utf-8",
        ),
    ],
)

import logging.handlers  # noqa: E402 — imported after basicConfig for handler

logger = logging.getLogger(__name__)

# Ensure data/imports directory exists
Path("data/imports").mkdir(parents=True, exist_ok=True)


def _run_cli() -> None:
    """Boot and run the human CLI."""
    from config import load_config, ConfigMissingError
    from cli.formatting import console, print_logo
    from services.secrets_manager import secrets_exist

    console.clear()
    print_logo()

    if not secrets_exist():
        # First run — launch setup wizard
        from cli.screens_setup import run_setup_wizard
        try:
            cfg = run_setup_wizard()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[meridian.muted]Setup cancelled.[/]")
            sys.exit(0)
    else:
        try:
            cfg = load_config()
        except Exception as exc:
            console.print(f"\n[meridian.error]Failed to load config: {exc}[/]")
            console.print("[meridian.muted]Run with no arguments to re-enter the setup wizard after deleting the secrets file.[/]")
            sys.exit(2)

    from db.connection import Database, wait_for_connection
    db = Database(cfg)
    if not wait_for_connection(db, retries=3, delay=2.0):
        console.print("\n[meridian.error]Cannot connect to TiDB.[/]")
        console.print("[meridian.muted]Check your credentials in Settings & Secrets.[/]")
        sys.exit(2)

    from cli.menu import run_main_menu
    try:
        run_main_menu(db, cfg)
    except (KeyboardInterrupt, EOFError):
        console.print("\n[meridian.muted]Goodbye.[/]")


def _run_server() -> None:
    """Start the FastAPI server."""
    from config import load_config, ConfigMissingError
    try:
        cfg = load_config()
    except ConfigMissingError:
        print("ERROR: Meridian is not configured. Run `python main.py` to complete setup.")
        sys.exit(2)

    import uvicorn
    from api.server import app
    logger.info("Starting Meridian API server on http://%s:%s", cfg.api_host, cfg.api_port)
    uvicorn.run(
        app,
        host=cfg.api_host,
        port=cfg.api_port,
        log_level="info",
    )


def _run_agent(args: list[str]) -> None:
    """
    Non-interactive agent interface.
    Usage: python main.py agent <action> --json '{...}'
    """
    import json as _json

    if len(args) < 2:
        print('{"ok":false,"action":"?","result":null,"error":{"code":"USAGE","message":"Usage: python main.py agent <action> --json \'{"param": "value"}\'"}}')
        sys.exit(1)

    action = args[0]
    params = {}

    if "--json" in args:
        idx = args.index("--json")
        try:
            params = _json.loads(args[idx + 1])
        except (IndexError, _json.JSONDecodeError) as exc:
            print(_json.dumps({
                "ok": False, "action": action, "result": None,
                "error": {"code": "JSON_PARSE_ERROR", "message": str(exc)},
            }))
            sys.exit(1)

    from config import load_config, ConfigMissingError
    from db.connection import Database, wait_for_connection

    try:
        cfg = load_config()
    except ConfigMissingError as exc:
        print(_json.dumps({
            "ok": False, "action": action, "result": None,
            "error": {"code": "NOT_CONFIGURED", "message": str(exc)},
        }))
        sys.exit(2)

    db = Database(cfg)
    if not wait_for_connection(db, retries=3, delay=2.0):
        print(_json.dumps({
            "ok": False, "action": action, "result": None,
            "error": {"code": "DB_UNREACHABLE", "message": "Cannot connect to TiDB."},
        }))
        sys.exit(2)

    from agent.agent_cli import run_agent_command
    run_agent_command(action, params, db, cfg)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] == "agent":
        _run_agent(args[1:])
    elif args and args[0] == "server":
        _run_server()
    else:
        _run_cli()
