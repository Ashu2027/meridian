"""
agent/agent_cli.py
Non-interactive agent subcommand layer (Section 17).
Usage:  python main.py agent <action> --json '{...}'

Every command:
 - Takes --json with a structured payload
 - Prints a single JSON object to stdout
 - Exits 0 (success), 1 (validation failure), 2 (infra failure)

This is the subprocess-friendly interface for shell scripts and non-MCP tooling.
For MCP-native agents, the FastAPI server or mcp_server.py is preferred.
"""
from __future__ import annotations

import json
import sys
from typing import Any


def _ok(action: str, result: Any) -> None:
    print(json.dumps({"ok": True, "action": action, "result": result, "error": None}))
    sys.exit(0)


def _err(action: str, code: str, message: str, exit_code: int = 1) -> None:
    print(json.dumps({
        "ok": False, "action": action, "result": None,
        "error": {"code": code, "message": message}
    }))
    sys.exit(exit_code)


def run_agent_command(action: str, params: dict, db, cfg) -> None:
    """
    Route *action* to the appropriate service layer call.
    All responses go to stdout as JSON; process exits immediately after.
    """
    from services import person_service, tone_engine, campaign_service
    from services.message_validator import Draft, validate_draft

    # ── person-add ─────────────────────────────────────────────────────────────
    if action == "person-add":
        try:
            person = person_service.add_person(db, person_service.PersonInput(
                full_name=params.get("full_name", ""),
                email=params.get("email", ""),
                designation=params.get("designation", ""),
                category=params.get("category", "other"),
                organization=params.get("organization"),
                country=params.get("country"),
                preferred_tone=params.get("preferred_tone", "auto"),
                notes=params.get("notes"),
            ))
            _ok(action, {"id": person.id, "full_name": person.full_name, "email": person.email})
        except ValueError as exc:
            _err(action, "PERSON_ADD_INVALID", str(exc), 1)

    # ── person-search ──────────────────────────────────────────────────────────
    elif action == "person-search":
        persons = person_service.search_persons(
            db,
            category=params.get("category"),
            status=params.get("status"),
            query=params.get("query"),
        )
        _ok(action, [
            {"id": p.id, "full_name": p.full_name, "email": p.email,
             "designation": p.designation, "category": p.category,
             "preferred_tone": p.preferred_tone, "status": p.status}
            for p in persons
        ])

    # ── person-update ──────────────────────────────────────────────────────────
    elif action == "person-update":
        try:
            p = person_service.update_person(db, params["person_id"], params.get("changes", {}))
            _ok(action, {"id": p.id, "full_name": p.full_name, "email": p.email})
        except (ValueError, KeyError) as exc:
            _err(action, "PERSON_UPDATE_INVALID", str(exc), 1)

    # ── person-set-status ──────────────────────────────────────────────────────
    elif action == "person-set-status":
        try:
            person_service.set_status(db, params["person_id"], params["new_status"])
            _ok(action, {"person_id": params["person_id"], "status": params["new_status"]})
        except (ValueError, KeyError) as exc:
            _err(action, "STATUS_INVALID", str(exc), 1)

    # ── person-import-csv ──────────────────────────────────────────────────────
    elif action == "person-import-csv":
        try:
            result = person_service.import_csv(db, params["file_path"])
            _ok(action, {"created": result.created, "skipped": result.skipped, "errors": result.errors})
        except (ValueError, KeyError) as exc:
            _err(action, "IMPORT_FAILED", str(exc), 1)

    # ── person-export-csv ──────────────────────────────────────────────────────
    elif action == "person-export-csv":
        try:
            count = person_service.export_csv(
                db, params["file_path"],
                category=params.get("category"),
                status=params.get("status"),
            )
            _ok(action, {"exported": count, "file": params["file_path"]})
        except (ValueError, KeyError) as exc:
            _err(action, "EXPORT_FAILED", str(exc), 1)

    # ── tone-get ───────────────────────────────────────────────────────────────
    elif action == "tone-get":
        split = tone_engine.get_active_split(db)
        _ok(action, {
            "id": split.id,
            "professional_percent": split.professional,
            "semi_casual_percent": split.semi_casual,
            "casual_percent": split.casual,
            "is_active": split.is_active,
            "note": split.note,
        })

    # ── tone-set ───────────────────────────────────────────────────────────────
    elif action == "tone-set":
        try:
            saved = tone_engine.save_split(
                db,
                params["professional"],
                params["semi_casual"],
                params["casual"],
                params.get("note"),
            )
            _ok(action, {
                "id": saved.id,
                "professional_percent": saved.professional,
                "semi_casual_percent": saved.semi_casual,
                "casual_percent": saved.casual,
                "is_active": True,
            })
        except (ValueError, KeyError) as exc:
            _err(action, "TONE_SPLIT_INVALID", str(exc), 1)

    # ── campaign-create ────────────────────────────────────────────────────────
    elif action == "campaign-create":
        try:
            camp = campaign_service.create_campaign(
                db,
                name=params["name"],
                topic_brief=params["topic_brief"],
                target_filter=params.get("target_filter"),
            )
            _ok(action, {"id": camp.id, "name": camp.name, "status": camp.status})
        except (ValueError, KeyError) as exc:
            _err(action, "CAMPAIGN_CREATE_INVALID", str(exc), 1)

    # ── campaign-recipients ────────────────────────────────────────────────────
    elif action == "campaign-recipients":
        try:
            camp = campaign_service.get_campaign(db, params["campaign_id"])
            if not camp:
                _err(action, "CAMPAIGN_NOT_FOUND", f"Campaign #{params['campaign_id']} not found.", 1)
            recipients = campaign_service.build_recipient_list(db, camp)
            rds = campaign_service.prepare_recipient_drafts(db, camp, recipients)
            _ok(action, [
                {"person_id": rd.person.id, "full_name": rd.person.full_name,
                 "email": rd.person.email, "designation": rd.person.designation,
                 "category": rd.person.category, "tone": rd.tone,
                 "topic_brief": camp.topic_brief}
                for rd in rds
            ])
        except KeyError as exc:
            _err(action, "MISSING_PARAM", str(exc), 1)

    # ── draft-validate ─────────────────────────────────────────────────────────
    elif action == "draft-validate":
        max_words = int(db.get_config_value("max_words_per_message", "200"))
        result = validate_draft(
            Draft(
                person_id=params.get("person_id", 0),
                subject=params.get("subject", ""),
                body=params.get("body", ""),
                tone=params.get("tone", "professional"),
            ),
            max_words,
        )
        _ok(action, {"valid": result.valid, "word_count": result.word_count, "violations": result.violations})

    # ── campaign-send ──────────────────────────────────────────────────────────
    elif action == "campaign-send":
        # Guardrail: explicit confirm required every time
        if not params.get("confirm", False):
            _err(action, "CONFIRM_REQUIRED",
                 "campaign-send requires 'confirm': true explicitly. No implicit state.", 1)

        try:
            camp = campaign_service.get_campaign(db, params["campaign_id"])
            if not camp:
                _err(action, "CAMPAIGN_NOT_FOUND", f"Campaign #{params['campaign_id']} not found.", 1)

            pending_logs = db.fetch_all(
                "SELECT * FROM message_log WHERE campaign_id = %s AND status = 'pending'",
                (params["campaign_id"],),
            )
            if not pending_logs:
                _err(action, "NO_PENDING_DRAFTS", "No pending drafts found.", 1)

            # ── Duplicate-send guard ───────────────────────────────────────────
            # 1. Find person_ids already successfully sent in this campaign
            already_sent_rows = db.fetch_all(
                "SELECT DISTINCT person_id FROM message_log "
                "WHERE campaign_id = %s AND status = 'sent'",
                (params["campaign_id"],),
            )
            already_sent_ids = {row["person_id"] for row in already_sent_rows}

            # 2. Deduplicate pending_logs by person_id (keep only first occurrence)
            #    and skip any person already sent to in this campaign
            seen_person_ids: set = set()
            safe_pending = []
            skipped_duplicates = 0
            for log in pending_logs:
                pid = log["person_id"]
                if pid in already_sent_ids:
                    skipped_duplicates += 1
                    continue  # already sent in this campaign — never send twice
                if pid in seen_person_ids:
                    skipped_duplicates += 1
                    continue  # duplicate entry in pending — only send once
                seen_person_ids.add(pid)
                safe_pending.append(log)

            if not safe_pending:
                _err(action, "NO_PENDING_DRAFTS",
                     f"All {skipped_duplicates} pending draft(s) were duplicates or already sent.", 1)
            # ──────────────────────────────────────────────────────────────────

            from services.sender_queue import ApprovedDraft, dispatch
            approved = [
                ApprovedDraft(
                    person_id=log["person_id"], campaign_id=log["campaign_id"],
                    recipient_email=log["recipient_email"], recipient_name=log["recipient_name"],
                    designation_snapshot=log["designation_snapshot"], subject=log["subject"],
                    body=log["message_body"], word_count=log["word_count"], tone_used=log["tone_used"],
                )
                for log in safe_pending
            ]
            db.execute(
                "DELETE FROM message_log WHERE campaign_id = %s AND status = 'pending'",
                (params["campaign_id"],),
            )
            rate = int(db.get_config_value("send_rate_per_minute", "20"))
            from_addr = f"{cfg.default_from_name} <{cfg.default_from_email}>"
            sent = failed = 0
            for result in dispatch(db, approved, cfg.resend_api_key, from_addr, rate):
                if result.status == "sent":
                    sent += 1
                else:
                    failed += 1

            _ok(action, {
                "campaign_id": params["campaign_id"],
                "sent": sent,
                "failed": failed,
                "skipped_duplicates": skipped_duplicates,
            })
        except KeyError as exc:
            _err(action, "MISSING_PARAM", str(exc), 1)

    # ── history-query ──────────────────────────────────────────────────────────
    elif action == "history-query":
        if "person_id" in params:
            logs = campaign_service.history_for_person(db, params["person_id"])
        elif "campaign_id" in params:
            logs = campaign_service.history_for_campaign(db, params["campaign_id"])
        elif "date_start" in params and "date_end" in params:
            logs = campaign_service.history_by_date_range(db, params["date_start"], params["date_end"])
        else:
            _err(action, "MISSING_FILTER", "Provide person_id, campaign_id, or date_start+date_end.", 1)
        # Convert datetime objects to strings for JSON serialisation
        serialised = [{k: str(v) if hasattr(v, "isoformat") else v for k, v in row.items()} for row in logs]
        _ok(action, serialised)

    else:
        _err(action, "UNKNOWN_ACTION", f"Unknown action: {action!r}", 1)
