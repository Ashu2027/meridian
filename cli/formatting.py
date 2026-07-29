"""
cli/formatting.py
Shared rich helpers, color palette, and prompt utilities.
All screens import from here to maintain visual consistency.
"""
from __future__ import annotations

from typing import Any, List, Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress,
    SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# ── Color palette ──────────────────────────────────────────────────────────────

THEME = Theme({
    "meridian.title":   "bold #C0CAF5",      # soft lavender
    "meridian.accent":  "#7AA2F7",            # bright blue
    "meridian.success": "#9ECE6A",            # green
    "meridian.warn":    "#E0AF68",            # amber
    "meridian.error":   "#F7768E",            # red
    "meridian.muted":   "#565F89",            # dark comment
    "meridian.border":  "#3B4261",            # panel border
    "meridian.pro":     "#BB9AF7",            # professional tone (purple)
    "meridian.semi":    "#7AA2F7",            # semi-casual (blue)
    "meridian.cas":     "#73DACA",            # casual (teal)
    "status.active":      "bold #9ECE6A",
    "status.unsubscribed":"bold #E0AF68",
    "status.bounced":     "bold #F7768E",
    "status.archived":    "bold #565F89",
})

console = Console(theme=THEME)


# ── Logo / banner ──────────────────────────────────────────────────────────────

LOGO = r"""
  ███╗   ███╗███████╗██████╗ ██╗██████╗ ██╗ █████╗ ███╗   ██╗
  ████╗ ████║██╔════╝██╔══██╗██║██╔══██╗██║██╔══██╗████╗  ██║
  ██╔████╔██║█████╗  ██████╔╝██║██║  ██║██║███████║██╔██╗ ██║
  ██║╚██╔╝██║██╔══╝  ██╔══██╗██║██║  ██║██║██╔══██║██║╚██╗██║
  ██║ ╚═╝ ██║███████╗██║  ██║██║██████╔╝██║██║  ██║██║ ╚████║
  ╚═╝     ╚═╝╚══════╝╚═╝  ╚═╝╚═╝╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝
"""


def print_logo() -> None:
    console.print(Text(LOGO, style="meridian.accent"), justify="center")
    console.print(
        Text("  Precision Outreach for High-Value Relationships", style="meridian.muted"),
        justify="center"
    )
    console.print()


def header_panel(title: str, subtitle: str = "") -> Panel:
    content = Text(title, style="meridian.title", justify="center")
    if subtitle:
        content.append(f"\n{subtitle}", style="meridian.muted")
    return Panel(
        content,
        border_style="meridian.border",
        box=box.DOUBLE_EDGE,
        expand=True,
    )


def success(msg: str) -> None:
    console.print(f"  [meridian.success]✓[/] {msg}")


def warn(msg: str) -> None:
    console.print(f"  [meridian.warn]⚠[/]  {msg}")


def error(msg: str) -> None:
    console.print(f"  [meridian.error]✗[/]  {msg}")


def info(msg: str) -> None:
    console.print(f"  [meridian.accent]›[/]  {msg}")


def rule(title: str = "") -> None:
    console.rule(f"[meridian.muted]{title}[/]" if title else "", style="meridian.border")


# ── Tables ─────────────────────────────────────────────────────────────────────

def persons_table(persons: list) -> Table:
    t = Table(
        box=box.SIMPLE_HEAD,
        border_style="meridian.border",
        show_footer=False,
        header_style="bold meridian.accent",
        expand=True,
    )
    t.add_column("ID",          style="meridian.muted",  width=6,  justify="right")
    t.add_column("Name",        style="meridian.title",  min_width=20)
    t.add_column("Email",       style="meridian.accent", min_width=22)
    t.add_column("Designation", min_width=18)
    t.add_column("Category",    style="meridian.muted",  min_width=15)
    t.add_column("Status",      min_width=12)

    for p in persons:
        status_style = f"status.{p.status}" if hasattr(p, "status") else ""
        t.add_row(
            str(p.id),
            p.full_name,
            p.email,
            p.designation,
            p.category.replace("_", " ").title(),
            Text(p.status.upper(), style=status_style),
        )
    return t


def campaigns_table(campaigns: list) -> Table:
    t = Table(
        box=box.SIMPLE_HEAD,
        border_style="meridian.border",
        header_style="bold meridian.accent",
        expand=True,
    )
    t.add_column("ID",        style="meridian.muted", width=6, justify="right")
    t.add_column("Name",      style="meridian.title", min_width=20)
    t.add_column("Status",    min_width=12)
    t.add_column("Sent",      justify="right", min_width=6)
    t.add_column("Failed",    justify="right", min_width=7)
    t.add_column("Skipped",   justify="right", min_width=8)
    t.add_column("Created",   min_width=16)

    status_styles = {
        "draft": "meridian.muted",
        "in_progress": "meridian.warn",
        "completed": "meridian.success",
        "aborted": "meridian.error",
    }
    for c in campaigns:
        st = c.status
        t.add_row(
            str(c.id),
            c.name,
            Text(st.upper().replace("_", " "), style=status_styles.get(st, "")),
            str(c.total_sent),
            str(c.total_failed),
            str(max(0, c.total_recipients - c.total_sent - c.total_failed)),
            str(c.created_at)[:16] if c.created_at else "",
        )
    return t


def message_log_table(logs: list) -> Table:
    t = Table(
        box=box.SIMPLE_HEAD,
        border_style="meridian.border",
        header_style="bold meridian.accent",
        expand=True,
    )
    t.add_column("Date",     min_width=16)
    t.add_column("Campaign", min_width=18, style="meridian.muted")
    t.add_column("Subject",  min_width=30)
    t.add_column("Tone",     min_width=12)
    t.add_column("Status",   min_width=8)

    for log in logs:
        tone_style = {
            "professional": "meridian.pro",
            "semi_casual": "meridian.semi",
            "casual": "meridian.cas",
        }.get(log.get("tone_used", ""), "")
        status = log.get("status", "")
        status_style = {
            "sent": "meridian.success",
            "failed": "meridian.error",
            "skipped": "meridian.muted",
            "pending": "meridian.warn",
        }.get(status, "")
        t.add_row(
            str(log.get("sent_at", log.get("created_at", "")))[:16],
            str(log.get("campaign_name", "—")),
            str(log.get("subject", "")),
            Text(log.get("tone_used", "—").replace("_", " ").title(), style=tone_style),
            Text(status.upper(), style=status_style),
        )
    return t


def tone_bar(label: str, percent: int, width: int = 32) -> str:
    filled = int(width * percent / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"{label:<14} [{percent:>3}]%   {bar}"


# ── Progress bars ──────────────────────────────────────────────────────────────

def make_progress(description: str = "Working") -> Progress:
    return Progress(
        SpinnerColumn(style="meridian.accent"),
        TextColumn(f"[meridian.muted]{description}[/]"),
        BarColumn(bar_width=40, style="meridian.border", complete_style="meridian.accent"),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


def draft_preview_panel(
    draft_num: int,
    total: int,
    person_name: str,
    category: str,
    tone: str,
    subject: str,
    body: str,
    word_count: int,
) -> Panel:
    tone_styles = {
        "professional": "meridian.pro",
        "semi_casual":  "meridian.semi",
        "casual":       "meridian.cas",
    }
    tone_label = tone.replace("_", " ").title()
    t = Text()
    t.append(f"Subject: ", style="meridian.muted")
    t.append(f"{subject}\n\n", style="meridian.title")
    t.append(body)
    t.append(f"\n\n─── {word_count} words", style="meridian.muted")

    return Panel(
        t,
        title=(
            f"[meridian.muted]DRAFT {draft_num} of {total}[/]  "
            f"[meridian.title]{person_name}[/]  "
            f"[meridian.muted]({category})[/]  "
            f"[{tone_styles.get(tone, '')}]tone: {tone_label}[/]"
        ),
        border_style="meridian.border",
        box=box.ROUNDED,
        expand=True,
        padding=(1, 2),
    )
