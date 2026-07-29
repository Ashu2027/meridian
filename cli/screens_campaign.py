"""
cli/screens_campaign.py
Multi-step campaign creation, draft review, and send flow.

KEY DESIGN: The agent (Claude, Antigravity, etc.) generates the message content.
This screen:
 1. Collects campaign metadata from the operator
 2. Shows the list of recipients + their assigned tones
 3. Lets the operator enter (or paste) a draft for each recipient
 4. Validates each draft against the hard rules
 5. Confirms send and dispatches with live progress
"""
from __future__ import annotations

from typing import Optional

import questionary
from rich import box
from rich.panel import Panel
from rich.text import Text

from cli.formatting import (
    console, header_panel, campaigns_table, persons_table,
    draft_preview_panel, make_progress,
    success, error, warn, info, rule,
)
from config import AppConfig
from db.connection import Database
from services.campaign_service import (
    Campaign, CampaignResult, RecipientDraft,
    abort_campaign, build_recipient_list, create_campaign,
    list_campaigns, prepare_recipient_drafts, run_send_phase, submit_draft,
)
from services.message_validator import validate_draft, Draft


# ── Step 1 & 2: Create campaign + pick recipients ──────────────────────────────

def _step_create(db: Database) -> Optional[Campaign]:
    console.clear()
    console.print(header_panel("RUN A CAMPAIGN", "Step 1 — Name & topic"))
    console.print()

    name = questionary.text(
        "Campaign name:",
        validate=lambda v: True if v.strip() else "Name cannot be empty.",
    ).ask()
    if name is None:
        return None

    info("Describe what the message should be about. This is the topic brief.")
    info("Agents (Claude, etc.) will use this to generate the message content.")
    console.print()

    topic = questionary.text(
        "Topic brief (what to communicate):",
        validate=lambda v: True if v.strip() else "Cannot be empty.",
    ).ask()
    if topic is None:
        return None

    # Target filter
    filter_choice = questionary.select(
        "Who should receive this campaign?",
        choices=[
            "All active persons",
            "Filter by category",
        ],
    ).ask()
    if filter_choice is None:
        return None

    target_filter = None
    if filter_choice == "Filter by category":
        from services.person_service import VALID_CATEGORIES
        raw = sorted(VALID_CATEGORIES)
        display = [c.replace("_", " ").title() for c in raw]
        picked = questionary.select("Select category:", choices=display).ask()
        if picked is None:
            return None
        idx = display.index(picked)
        target_filter = {"category": raw[idx]}

    campaign = create_campaign(db, name=name, topic_brief=topic, target_filter=target_filter)
    success(f"Campaign created — ID #{campaign.id}: [bold]{campaign.name}[/]")
    return campaign


# ── Step 3: Show recipient list ────────────────────────────────────────────────

def _step_recipients(db: Database, campaign: Campaign) -> Optional[list[RecipientDraft]]:
    console.clear()
    console.print(header_panel("RUN A CAMPAIGN", "Step 2 — Recipients & tone assignment"))
    console.print()

    recipients = build_recipient_list(db, campaign)
    if not recipients:
        error("No active persons match the target filter. Add persons first.")
        questionary.press_any_key_to_continue().ask()
        return None

    console.print(persons_table(recipients))
    info(f"{len(recipients)} recipient(s) selected.")
    console.print()

    confirmed = questionary.confirm("Proceed with tone assignment and drafting?", default=True).ask()
    if not confirmed:
        abort_campaign(db, campaign.id)
        warn("Campaign aborted.")
        questionary.press_any_key_to_continue().ask()
        return None

    recipient_drafts = prepare_recipient_drafts(db, campaign, recipients)
    return recipient_drafts


# ── Step 4: Draft entry per recipient ─────────────────────────────────────────

def _step_draft_entry(
    db: Database,
    campaign: Campaign,
    recipient_drafts: list[RecipientDraft],
) -> list[RecipientDraft]:
    """
    For each recipient, show their details + tone, then let the operator
    paste in a subject and body (agent-generated externally).
    Validates on entry. Operator can also skip a recipient.
    """
    max_words = int(db.get_config_value("max_words_per_message", "200"))
    total = len(recipient_drafts)

    for i, rd in enumerate(recipient_drafts, start=1):
        while True:
            console.clear()
            console.print(header_panel(
                f"DRAFT {i} of {total}",
                f"{rd.person.full_name}  ·  {rd.person.designation}  ·  tone: {rd.tone.replace('_', ' ')}",
            ))
            console.print()
            info(f"Topic brief: [italic]{campaign.topic_brief}[/]")
            console.print()
            info(f"Recipient:   [bold]{rd.person.full_name}[/] <{rd.person.email}>")
            info(f"Category:    {rd.person.category.replace('_', ' ').title()}")
            info(f"Designation: {rd.person.designation}")
            if rd.person.organization:
                info(f"Organization:{rd.person.organization}")
            console.print()

            action = questionary.select(
                "What would you like to do for this recipient?",
                choices=[
                    "Enter draft (subject + body)",
                    "Skip this person",
                    "Abort campaign",
                ],
            ).ask()

            if action is None or action == "Abort campaign":
                abort_campaign(db, campaign.id)
                warn("Campaign aborted.")
                questionary.press_any_key_to_continue().ask()
                return []

            if action == "Skip this person":
                skip_reason = questionary.text("Skip reason (optional):").ask() or "Operator skipped"
                rd.skipped = True
                rd.skip_reason = skip_reason
                break

            # Enter draft
            subject = questionary.text(
                "Subject line:",
                validate=lambda v: True if v.strip() else "Subject cannot be empty.",
            ).ask()
            if subject is None:
                continue

            console.print()
            info(f"Paste the message body below. Enter a blank line followed by END to finish.")
            console.print("[meridian.muted]─────────────────────────────[/]")

            lines = []
            while True:
                line = input()
                if line.strip() == "END":
                    break
                lines.append(line)
            body = "\n".join(lines)

            # Validate
            result = validate_draft(
                Draft(person_id=rd.person.id, subject=subject, body=body, tone=rd.tone),
                max_words,
            )

            console.clear()
            console.print(draft_preview_panel(
                i, total,
                rd.person.full_name, rd.person.category,
                rd.tone, subject, body, result.word_count,
            ))
            console.print()

            if not result.valid:
                error("Draft has validation issues:")
                for v in result.violations:
                    warn(f"  • {v}")
                console.print()
                retry = questionary.select(
                    "What now?",
                    choices=["Re-enter draft", "Skip this person", "Abort campaign"],
                ).ask()
                if retry == "Re-enter draft":
                    continue
                elif retry == "Skip this person":
                    rd.skipped = True
                    rd.skip_reason = "Validation failed"
                    break
                else:
                    abort_campaign(db, campaign.id)
                    return []

            # Valid — offer approve/edit/skip
            approval = questionary.select(
                "Draft looks good. What now?",
                choices=["Approve", "Re-enter draft", "Skip this person"],
            ).ask()

            if approval == "Approve":
                try:
                    submit_draft(db, rd, subject, body, max_words)
                except ValueError as exc:
                    error(str(exc))
                    continue
                break
            elif approval == "Re-enter draft":
                continue
            else:
                rd.skipped = True
                rd.skip_reason = "Operator chose to skip after review"
                break

    return recipient_drafts


# ── Step 5: Confirm send ───────────────────────────────────────────────────────

def _step_confirm_send(recipient_drafts: list[RecipientDraft]) -> bool:
    approved = sum(1 for rd in recipient_drafts if rd.validated and not rd.skipped)
    skipped  = sum(1 for rd in recipient_drafts if rd.skipped)

    console.clear()
    console.print(header_panel("CONFIRM SEND", "Final review before emails are dispatched"))
    console.print()
    info(f"Approved:  [bold meridian.success]{approved}[/] message(s) ready to send")
    info(f"Skipped:   [bold meridian.warn]{skipped}[/] person(s) will not receive an email")
    console.print()
    warn("This action is irreversible. Each email will be sent immediately.")
    console.print()

    return questionary.confirm(
        f"Send {approved} email(s) now?", default=False
    ).ask() or False


# ── Step 6: Send with live progress ───────────────────────────────────────────

def _step_send(
    db: Database,
    campaign: Campaign,
    recipient_drafts: list[RecipientDraft],
    cfg: AppConfig,
) -> None:
    approved = [rd for rd in recipient_drafts if rd.validated and not rd.skipped]
    total = len(approved)
    rate = int(db.get_config_value("send_rate_per_minute", "20"))

    console.clear()
    console.print(header_panel("SENDING…", f"Campaign: {campaign.name}"))
    console.print()

    sent = failed = 0

    with make_progress("Sending emails") as progress:
        task = progress.add_task("Sending", total=total)

        gen = run_send_phase(
            db, campaign, recipient_drafts,
            api_key=cfg.resend_api_key,
            from_addr=f"{cfg.default_from_name} <{cfg.default_from_email}>",
            rate_per_minute=rate,
        )

        try:
            for result in gen:
                if result.status == "sent":
                    sent += 1
                else:
                    failed += 1
                progress.advance(task)
        except StopIteration as si:
            # generator returned CampaignResult — we don't need it here
            pass

    console.print()
    skipped = sum(1 for rd in recipient_drafts if rd.skipped)

    console.print(Panel(
        f"[meridian.success]Sent:[/]     {sent}\n"
        f"[meridian.error]Failed:[/]   {failed}\n"
        f"[meridian.warn]Skipped:[/]  {skipped}",
        title="[bold meridian.title]CAMPAIGN COMPLETE[/]",
        border_style="meridian.success" if failed == 0 else "meridian.warn",
        box=box.DOUBLE_EDGE,
        padding=(1, 3),
    ))
    questionary.press_any_key_to_continue().ask()


# ── Main campaign flow ─────────────────────────────────────────────────────────

def campaign_menu(db: Database, cfg: AppConfig) -> None:
    while True:
        console.clear()
        console.print(header_panel("CAMPAIGNS"))
        console.print()

        choice = questionary.select(
            "Select an action:",
            choices=[
                "Run a new campaign",
                "View past campaigns",
                "Back to Main Menu",
            ],
        ).ask()

        if choice is None or choice == "Back to Main Menu":
            return
        elif choice == "View past campaigns":
            _view_campaigns(db)
        elif choice == "Run a new campaign":
            _run_new_campaign(db, cfg)


def _view_campaigns(db: Database) -> None:
    console.clear()
    console.print(header_panel("PAST CAMPAIGNS"))
    console.print()
    campaigns = list_campaigns(db)
    if not campaigns:
        warn("No campaigns found.")
    else:
        console.print(campaigns_table(campaigns))
    questionary.press_any_key_to_continue().ask()


def _run_new_campaign(db: Database, cfg: AppConfig) -> None:
    campaign = _step_create(db)
    if not campaign:
        return

    recipient_drafts = _step_recipients(db, campaign)
    if not recipient_drafts:
        return

    recipient_drafts = _step_draft_entry(db, campaign, recipient_drafts)
    if not recipient_drafts:
        return

    if not _step_confirm_send(recipient_drafts):
        abort_campaign(db, campaign.id)
        warn("Send cancelled. Campaign marked as aborted.")
        questionary.press_any_key_to_continue().ask()
        return

    _step_send(db, campaign, recipient_drafts, cfg)
