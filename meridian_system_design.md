# Meridian — Complete System Design

**Interface:** CLI only, no browser/web UI, menu-driven for a non-developer end user
**Backend:** Persistent local server process (not a one-shot script)
**Database:** TiDB (MySQL wire-protocol compatible), sole system of record
**Email delivery:** Resend API
**Message authoring:** AI-generated, rule-constrained (no emoji, ≤200 words, real line breaks)
**Platforms:** Linux and Windows

---

## Table of Contents

1. Goals & Non-Goals
2. High-Level Architecture
3. Full Project / File Layout
4. Data Model (complete DDL, every column explained)
5. CLI Layout — every screen, menu, and prompt
6. Module-by-Module Method Design (signatures + pseudocode)
7. Core Algorithms (tone assignment, word/emoji validation, rate limiting, retries)
8. Sequence Flows (setup, add person, run campaign, failure/retry)
9. State Machines (person, campaign, message)
10. Secrets & Encryption Design
11. Error Handling Matrix
12. Logging & Observability
13. Security & Compliance
14. Deployment (Linux + Windows)
15. Testing Strategy
16. Future Extensions
17. Agent-Operable Interface (Claude Code / CLI Coding Agents)
18. MCP Server Integration
19. Standardized Designation Catalog (Broad, Pre-Drafted List)

---

## 1. Goals & Non-Goals

**Goals**
- One local, persistent application that a non-technical operator drives entirely through menus and prompts — never a raw command with flags to memorize.
- TiDB as the single source of truth for contacts, tone configuration, campaigns, and the full send history.
- AI-drafted, per-recipient personalized messages that obey hard rules: no emoji, ≤200 words, real line breaks, and a tone assigned per a configurable professional/semi-casual/casual split that always totals 100%.
- Full auditability: for any person, at any time, the operator can answer "what did we send them, when, with what subject, in what tone, and did it succeed."
- Runs unattended as a local background service on both Linux and Windows.

**Non-Goals**
- No web UI, no REST API exposed to a browser, no public-facing dashboard.
- No list acquisition/scraping — the system manages and sends to a list the operator already has the right to contact.
- No built-in CRM features beyond what's needed for outreach (no deal pipelines, no calendar, no task management).

---

## 2. High-Level Architecture

```
                          ┌────────────────────────────────────────┐
                          │              OPERATOR                  │
                          │        (types into terminal)           │
                          └───────────────────┬──────────────────--┘
                                              │
                                   interacts via keyboard
                                              │
                          ┌───────────────────▼──────────────────┐
                          │            CLI SHELL LAYER            │
                          │  main.py → cli/menu.py (menu router)  │
                          │  rich (rendering) + questionary       │
                          │  (arrow-key select prompts)           │
                          └───────────────────┬────────────────--─┘
                                              │ function calls (in-process,
                                              │ NOT HTTP — same process)
                          ┌───────────────────▼──────────────────--─┐
                          │          LOCAL SERVER / SERVICE LAYER    │
                          │                                          │
                          │  ┌────────────┐  ┌────────────────────┐ │
                          │  │ PersonSvc  │  │ ToneEngine          │ │
                          │  └────────────┘  └────────────────────┘ │
                          │  ┌────────────┐  ┌────────────────────┐ │
                          │  │ CampaignSvc│  │ MessageGenerator    │ │
                          │  └────────────┘  └────────────────────┘ │
                          │  ┌────────────┐  ┌────────────────────┐ │
                          │  │ SenderQueue│  │ SecretsManager      │ │
                          │  └────────────┘  └────────────────────┘ │
                          └──────┬──────────────────┬───────────---┘
                                 │                   │
                     TiDB wire protocol       HTTPS (outbound only)
                                 │                   │
                    ┌────────────▼──────────┐  ┌─────▼──────────┐  ┌──────────────────┐
                    │        TiDB            │  │  Resend API    │  │   AI Provider     │
                    │ persons / tone_settings │  │  (send email)  │  │ (draft messages)  │
                    │ campaigns / message_log │  └────────────────┘  └───────────────────┘
                    │ system_config           │
                    └─────────────────────────┘
```

**Key architectural point:** the "server" and the "CLI" are the same process. There is no socket between them — the CLI shell imports and calls the service layer directly. This is what makes it a *local server-based system* (a real persistent application with a service layer, connection pooling, a queue, and a defined data layer) while still presenting *zero* interface other than the terminal menu. The word "server" here refers to the architecture (long-lived process, connection pooling, queued dispatch, background-capable), not to an HTTP server.

---

## 3. Full Project / File Layout

```
meridian/
│
├── main.py                      # Entry point. Boots config, DB pool, then hands off to cli/menu.py
├── config.py                    # AppConfig dataclass + loader/saver for the encrypted local secrets file
├── requirements.txt
├── README.md
│
├── db/
│   ├── schema.sql                # Full DDL — see Section 4
│   ├── connection.py             # Database class: pooled TiDB connection, execute/fetch helpers
│   └── migrations/                # Numbered .sql files for future schema changes (001_, 002_, ...)
│
├── services/
│   ├── person_service.py         # CRUD + CSV import/export for persons
│   ├── tone_engine.py            # Tone split validation + weighted random assignment
│   ├── message_generator.py      # AI prompt construction, word/emoji validation, regeneration loop
│   ├── campaign_service.py       # Orchestrates a full campaign run end to end
│   ├── sender_queue.py           # Rate limiter, Resend API client, retry/backoff logic
│   └── secrets_manager.py        # Fernet encrypt/decrypt of the local secrets file
│
├── cli/
│   ├── menu.py                   # Top-level menu router / main loop
│   ├── screens_setup.py          # First-run setup wizard screens
│   ├── screens_persons.py        # Person management screens
│   ├── screens_tone.py           # Tone configuration screen
│   ├── screens_campaign.py       # Campaign creation / review / send screens
│   ├── screens_history.py        # Log / history browsing screens
│   └── formatting.py             # Shared rich table/panel builders, colors, prompts
│
├── agent/
│   └── agent_cli.py               # Non-interactive `agent <action> --json` command layer (Section 17)
│
├── mcp/
│   └── mcp_server.py               # MCP server exposing the service layer as tools + resources (Section 18)
│
├── logs/
│   └── meridian.log              # Rotating local operational log (separate from TiDB audit log)
│
└── data/
    └── imports/                   # Drop zone for CSV files the operator wants to import
```

---

## 4. Data Model (Complete DDL)

*(This is the authoritative schema — every column has a stated purpose, no filler fields.)*

```sql
CREATE DATABASE IF NOT EXISTS meridian
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE meridian;

-- ============================================================
-- persons — the contact database
-- ============================================================
CREATE TABLE persons (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    full_name           VARCHAR(150)    NOT NULL,
    email               VARCHAR(255)    NOT NULL,
    designation         VARCHAR(150)    NOT NULL,   -- free-text custom title
    category            ENUM(
                            'billionaire','millionaire','tech_founder','politician',
                            'content_creator','journalist','human_rights','government_org',
                            'government_official','diplomat','media_personality',
                            'united_organization','high_value_person','other'
                        ) NOT NULL DEFAULT 'other',
    organization        VARCHAR(200)    NULL,
    country             VARCHAR(100)    NULL,
    preferred_tone      ENUM('professional','semi_casual','casual','auto') NOT NULL DEFAULT 'auto',
    notes               TEXT            NULL,
    status              ENUM('active','unsubscribed','bounced','archived') NOT NULL DEFAULT 'active',
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_persons_email (email),
    KEY idx_persons_category (category),
    KEY idx_persons_status (status)
) ENGINE=InnoDB;

-- ============================================================
-- tone_settings — the professionality mix (must sum to 100)
-- ============================================================
CREATE TABLE tone_settings (
    id                      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    professional_percent    TINYINT UNSIGNED NOT NULL DEFAULT 60,
    semi_casual_percent     TINYINT UNSIGNED NOT NULL DEFAULT 30,
    casual_percent          TINYINT UNSIGNED NOT NULL DEFAULT 10,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by_note         VARCHAR(255) NULL,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ============================================================
-- campaigns — one batch/run of sends
-- ============================================================
CREATE TABLE campaigns (
    id                          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name                        VARCHAR(200) NOT NULL,
    topic_brief                 TEXT NOT NULL,
    target_filter                VARCHAR(255) NULL,
    tone_professional_percent    TINYINT UNSIGNED NOT NULL,   -- snapshot at run time
    tone_semi_casual_percent     TINYINT UNSIGNED NOT NULL,
    tone_casual_percent          TINYINT UNSIGNED NOT NULL,
    total_recipients              INT UNSIGNED NOT NULL DEFAULT 0,
    total_sent                    INT UNSIGNED NOT NULL DEFAULT 0,
    total_failed                   INT UNSIGNED NOT NULL DEFAULT 0,
    status                          ENUM('draft','in_progress','completed','aborted') NOT NULL DEFAULT 'draft',
    created_at                       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at                      TIMESTAMP NULL
) ENGINE=InnoDB;

-- ============================================================
-- message_log — full send-level audit trail
-- ============================================================
CREATE TABLE message_log (
    id                      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    campaign_id             BIGINT UNSIGNED NULL,
    person_id                BIGINT UNSIGNED NOT NULL,
    recipient_email           VARCHAR(255) NOT NULL,
    recipient_name             VARCHAR(150) NOT NULL,
    designation_snapshot        VARCHAR(150) NOT NULL,
    subject                       VARCHAR(255) NOT NULL,
    message_body                  TEXT NOT NULL,          -- real line breaks, never literal \n
    word_count                     SMALLINT UNSIGNED NOT NULL,
    tone_used                       ENUM('professional','semi_casual','casual') NOT NULL,
    resend_message_id                VARCHAR(100) NULL,
    status                             ENUM('pending','sent','failed','skipped') NOT NULL DEFAULT 'pending',
    error_message                      TEXT NULL,
    sent_at                             TIMESTAMP NULL,
    created_at                           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_msglog_person FOREIGN KEY (person_id) REFERENCES persons(id),
    CONSTRAINT fk_msglog_campaign FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
    KEY idx_msglog_person (person_id),
    KEY idx_msglog_campaign (campaign_id),
    KEY idx_msglog_sent_at (sent_at)
) ENGINE=InnoDB;

-- ============================================================
-- system_config — non-secret operational settings only
-- ============================================================
CREATE TABLE system_config (
    config_key      VARCHAR(100) PRIMARY KEY,
    config_value    VARCHAR(500) NOT NULL,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

INSERT INTO tone_settings (professional_percent, semi_casual_percent, casual_percent, updated_by_note)
VALUES (60, 30, 10, 'default seed row');

INSERT INTO system_config (config_key, config_value) VALUES
    ('max_words_per_message', '200'),
    ('allow_emoji', 'false'),
    ('default_from_name', 'Meridian Desk'),
    ('send_rate_per_minute', '20');
```

---

## 5. CLI Layout — Every Screen

All screens are rendered with `rich` panels/tables; all selections use `questionary`'s arrow-key menus so the operator never types a raw command. Below is the literal on-screen layout for each.

### 5.1 First-Run Setup Wizard

```
┌──────────────────────────────────────────────────────────────┐
│              MERIDIAN — FIRST-TIME SETUP                │
├──────────────────────────────────────────────────────────────┤
│  Step 1 of 5 — TiDB Connection                                 │
│                                                                  │
│  Host:            [__________________]                         │
│  Port:             [4000]                                        │
│  User:              [__________________]                         │
│  Password:           [**********************]                     │
│  Database name:       [meridian]                             │
│  Use TLS? (Y/n):        [Y]                                          │
│                                                                       │
│  > Test Connection        > Continue        > Cancel                  │
└──────────────────────────────────────────────────────────────────────┘

  Step 2 of 5 — Resend API Key
  Step 3 of 5 — AI Provider API Key
  Step 4 of 5 — Default Sender Identity (from name / from email)
  Step 5 of 5 — Review & Confirm
      [Creates schema in TiDB, encrypts and saves secrets file, shows success panel]
```

### 5.2 Main Menu

```
┌──────────────────────────────────────────────────────────────┐
│                     MERIDIAN — MAIN MENU                │
│                  Connected to TiDB: meridian ●            │
├──────────────────────────────────────────────────────────────┤
│   ›  1. Manage Persons                                           │
│      2. Configure Tone Split                                       │
│      3. Run a Campaign                                               │
│      4. View History / Logs                                            │
│      5. Settings & Secrets                                               │
│      6. Exit                                                               │
└──────────────────────────────────────────────────────────────────────────┘
   Use ↑ ↓ to move, Enter to select
```

### 5.3 Manage Persons Submenu

```
┌───────────────────────────────────┐
│         MANAGE PERSONS              │
├───────────────────────────────────┤
│   › 1. Add a Person                  │
│     2. Search / View Persons           │
│     3. Edit a Person                     │
│     4. Import from CSV                     │
│     5. Export to CSV                         │
│     6. Change Status (unsubscribe/etc.)        │
│     7. Back to Main Menu                         │
└─────────────────────────────────────────────────┘
```

**Add a Person — field-by-field prompt sequence:**
```
Full name:            > ___________________
Email:                 > ___________________
Designation:             > ___________________  (free text, e.g. "Managing Editor")
Category:                  > [select from list — arrow keys]
Organization (optional):     > ___________________
Country (optional):            > ___________________
Preferred tone override:         > auto / professional / semi_casual / casual
Notes (optional):                  > ___________________

  ✓ Person saved — ID #482, Jane Whitmore <jane@example.org>
```

**Search / View Persons — table layout:**
```
┌────┬────────────────────┬────────────────────────┬───────────────────┬─────────┬──────────┐
│ ID │ Name                │ Email                    │ Designation          │ Category │ Status    │
├────┼────────────────────┼────────────────────────┼───────────────────┼─────────┼──────────┤
│ 482│ Jane Whitmore        │ jane@example.org           │ Managing Editor        │ journalist│ active     │
│ 483│ Rajiv Menon           │ rajiv@example.com            │ Founder & CEO             │ tech_founder│ active   │
└────┴────────────────────┴────────────────────────┴───────────────────┴─────────┴──────────┘
   [Filter by category]  [Filter by status]  [Search by name/email]  [Back]
```

### 5.4 Tone Configuration Screen

```
┌──────────────────────────────────────────────────────────────┐
│                  CONFIGURE TONE SPLIT                            │
├──────────────────────────────────────────────────────────────┤
│  Professional     [ 60 ]%   ██████████████████░░░░░░░░░░░░░░░░  │
│  Semi-casual       [ 30 ]%   █████████░░░░░░░░░░░░░░░░░░░░░░░░░   │
│  Casual              [ 10 ]%   ███░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   │
│                                                                       │
│  Running total: 100%   ✓ valid                                        │
│                                                                          │
│  Note for this change (optional): ____________________________          │
│                                                                            │
│   > Save        > Reset to Default (60/30/10)        > Cancel              │
└──────────────────────────────────────────────────────────────────────────┘
```
If the operator edits a value and the running total ≠ 100, the "Save" option is disabled and the total is shown in red with the exact amount needed to fix it (e.g. "Total: 97% — add 3% somewhere").

### 5.5 Run a Campaign — Multi-Step Flow

```
Step 1 — Name this campaign:          > "Q3 Update — Journalists"
Step 2 — Select recipients:            > By category / By status / Manually pick / All active
Step 3 — Topic brief (what should the message be about?):
                                         > (free text box, multi-line)
Step 4 — Generating drafts...           [progress bar, one tick per recipient]
Step 5 — Review drafts:
```
```
┌──────────────────────────────────────────────────────────────┐
│  DRAFT 3 of 128 — Jane Whitmore (journalist) — tone: professional│
├──────────────────────────────────────────────────────────────┤
│  Subject: Update on our Q3 findings relevant to your coverage     │
│                                                                       │
│  Dear Ms. Whitmore,                                                    │
│                                                                          │
│  [message body, real line breaks, 178 words]                             │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────┤
│   > Approve      > Regenerate      > Skip this person      > Edit manually  │
└──────────────────────────────────────────────────────────────────────────────┘
```
```
Step 6 — Confirm send:                  "128 approved, 3 skipped. Send now? (y/n)"
Step 7 — Sending...                     [progress bar with live sent/failed counters]
Step 8 — Summary:
```
```
┌──────────────────────────────────────────────────────────────┐
│                  CAMPAIGN COMPLETE                                │
├──────────────────────────────────────────────────────────────┤
│   Sent:      126                                                     │
│   Failed:      2   (view details)                                        │
│   Skipped:       3                                                          │
│   Duration:        6m 24s                                                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 5.6 View History / Logs Screen

```
┌──────────────────────────────────────────────────────────────┐
│                     HISTORY / LOGS                                │
├──────────────────────────────────────────────────────────────┤
│   › 1. Search by person (see everything ever sent to them)          │
│      2. Browse by campaign                                            │
│      3. Browse by date range                                            │
│      4. View failed sends only                                            │
│      5. Back to Main Menu                                                   │
└──────────────────────────────────────────────────────────────────────────────┘
```
**Per-person history detail view:**
```
History for Jane Whitmore <jane@example.org>
┌────────────┬─────────────────┬────────────────────────────┬──────────┬────────┐
│ Date         │ Campaign          │ Subject                        │ Tone       │ Status   │
├────────────┼─────────────────┼────────────────────────────┼──────────┼────────┤
│ 2026-07-12    │ Q3 Update           │ Update on our Q3 findings...      │ professional│ sent     │
│ 2026-05-03      │ Launch Announce       │ A quick note on our new release      │ professional│ sent     │
└────────────┴─────────────────┴────────────────────────────┴──────────┴────────┘
```

### 5.7 Settings & Secrets Screen

```
┌──────────────────────────────────────────────────────────────┐
│                  SETTINGS & SECRETS                               │
├──────────────────────────────────────────────────────────────┤
│   › 1. Update TiDB Credentials                                       │
│      2. Update Resend API Key                                          │
│      3. Update AI Provider API Key                                       │
│      4. Change Default Sender Identity                                     │
│      5. Change Max Words / Emoji Policy                                      │
│      6. Change Send Rate Limit                                                 │
│      7. Test All Connections                                                     │
│      8. Back to Main Menu                                                          │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Module-by-Module Method Design

### 6.1 `config.py`

```
class AppConfig:
    tidb_host: str
    tidb_port: int
    tidb_user: str
    tidb_password: str
    tidb_database: str
    tidb_use_tls: bool
    resend_api_key: str
    ai_api_key: str
    default_from_name: str
    default_from_email: str

load_config() -> AppConfig
    - reads and decrypts the local secrets file via secrets_manager.decrypt()
    - raises ConfigMissingError if no secrets file exists yet (triggers setup wizard)

save_config(cfg: AppConfig) -> None
    - serializes to JSON, encrypts via secrets_manager.encrypt(), writes to disk
    - sets file permissions to owner-read/write only (chmod 600 on Linux;
      icacls restriction on Windows)
```

### 6.2 `db/connection.py` — `Database` class

```
Database.connect() -> None
    - builds a mysql.connector pooling.MySQLConnectionPool sized 5
    - raises DatabaseError with a human-readable message on failure

Database.ping() -> bool
Database.execute(query, params) -> last_insert_id
Database.executemany(query, seq_params) -> affected_row_count
Database.fetch_all(query, params) -> list[dict]
Database.fetch_one(query, params) -> dict | None
Database.run_script(sql_text) -> None       # splits on ';' and runs each statement

wait_for_connection(db, retries=3, delay=2.0) -> bool
    - used at startup so one dropped packet doesn't crash the whole app
```

### 6.3 `services/person_service.py`

```
add_person(data: PersonInput) -> Person
    - validates email format and uniqueness before INSERT
    - returns the created row including its new id

get_person(person_id) -> Person | None
search_persons(filters: {category?, status?, query?}) -> list[Person]
update_person(person_id, changes: dict) -> Person
set_status(person_id, new_status) -> None
    - writes an audit note if status becomes 'unsubscribed' or 'bounced',
      so the reason is traceable

import_csv(file_path) -> ImportResult(created, skipped, errors)
    - required columns: full_name, email, designation, category
    - optional columns: organization, country, preferred_tone, notes
    - row-level validation; a bad row is skipped and reported, not fatal
    - duplicate emails are skipped, not overwritten (explicit "Edit" needed to change)

export_csv(filters, destination_path) -> int   # returns row count written
```

### 6.4 `services/tone_engine.py`

```
get_active_split() -> ToneSplit(professional, semi_casual, casual)

validate_split(professional, semi_casual, casual) -> (bool, str)
    - returns (False, "Total is 97%, add 3%") if sum != 100
    - returns (False, "Each value must be 0-100") for out-of-range input
    - returns (True, "") when valid

save_split(professional, semi_casual, casual, note) -> None
    - sets is_active = FALSE on the previous row, inserts a new active row
    - never UPDATEs the old row in place — every change is a new
      historical record, so campaign snapshots stay meaningful

assign_tone(person: Person, split: ToneSplit, rng: Random) -> Tone
    - if person.preferred_tone != 'auto': return person.preferred_tone
    - otherwise weighted-random pick using split percentages (see Section 7.1)
```

### 6.5 `services/message_generator.py`

```
build_system_prompt(tone: Tone) -> str
    - returns the fixed rule block (no emoji, ≤200 words, real line breaks,
      natural human-sounding language per Section 7.2a) plus a tone-specific
      voice paragraph (see Section 7.2)

generate_draft(person: Person, topic_brief: str, tone: Tone) -> Draft(subject, body, word_count)
    - calls the AI provider with system prompt + a user turn containing
      recipient name, designation, organization, category, and the topic brief
    - runs validate_draft() on the result
    - if invalid, re-prompts with a corrective instruction, up to 3 attempts
    - raises GenerationFailedError after 3 failed attempts (never sends
      an unvalidated draft)

validate_draft(draft: Draft) -> (bool, list[str])
    - checks word_count <= system_config.max_words_per_message
    - checks for any character in a maintained emoji Unicode-range set
    - checks the body contains real newline characters where the model
      might otherwise emit the literal two-character sequence "\n"
    - checks the body against a maintained list of AI-sounding boilerplate
      phrases (Section 7.2a) — a match is treated as a validation failure,
      same as an emoji or an over-limit word count
    - returns the list of violations found, if any
```

### 6.6 `services/campaign_service.py`

```
create_campaign(name, topic_brief, target_filter) -> Campaign
    - snapshots the current active tone split onto the campaign row

build_recipient_list(campaign, filter) -> list[Person]

run_drafting_phase(campaign, recipients) -> list[Draft]
    - for each recipient: assign_tone() then message_generator.generate_draft()
    - yields progress events for the CLI progress bar

run_review_phase(drafts) -> list[ApprovedDraft]
    - interactive; CLI presents each draft per Section 5.5

run_send_phase(campaign, approved_drafts) -> CampaignResult
    - hands off to sender_queue.dispatch(), updates campaign counters as
      results stream back, marks campaign status 'completed' or 'aborted'
```

### 6.7 `services/sender_queue.py`

```
class RateLimiter:
    - token-bucket implementation, refills at system_config.send_rate_per_minute

dispatch(approved_drafts: list[ApprovedDraft]) -> Iterator[SendResult]
    - for each draft: acquire a rate-limit token, call Resend, log outcome
    - on transient failure: retry with exponential backoff (see Section 7.3)
    - on permanent failure: mark person bounced, log and move on
    - writes a message_log row for every single attempt, success or failure,
      before proceeding to the next recipient (crash-safe audit trail)

send_via_resend(from_addr, to_addr, subject, body) -> ResendResponse
    - POSTs to Resend's send endpoint with the API key from AppConfig
    - body is sent so that real line breaks render as real breaks,
      never as a visible "\n" in the recipient's inbox
```

### 6.8 `services/secrets_manager.py`

```
generate_local_key() -> bytes
    - creates a Fernet key on first run, stored separately from the
      encrypted secrets file itself (see Section 10)

encrypt(data: dict) -> bytes
decrypt(blob: bytes) -> dict
```

---

## 7. Core Algorithms

### 7.1 Weighted Tone Assignment

```
function assign_tone(split, rng):
    roll = rng.uniform(0, 100)
    if roll < split.professional_percent:
        return PROFESSIONAL
    elif roll < split.professional_percent + split.semi_casual_percent:
        return SEMI_CASUAL
    else:
        return CASUAL
```
Applied once per recipient at drafting time (not re-rolled on regenerate, so "Regenerate" in the review screen keeps the same tone and only asks the AI for a different draft in that tone).

### 7.2 Tone Voice Definitions (fixed prompt fragments)

- **Professional:** formal register, no idioms or contractions, addresses the recipient by title and surname, suited to diplomats, officials, and institutional recipients.
- **Semi-casual:** warm but polished, first name where appropriate, plain sentences, suited to founders and media personalities.
- **Casual:** conversational and direct, still respectful, no slang, suited to content creators.

### 7.2a Natural, Human-Sounding Language — A Hard Rule Across All Three Tones

This applies on top of every tone above and is enforced in `build_system_prompt()` as a non-negotiable instruction block, not a style suggestion:

> Write this the way an actual person would write a real, individual email — not the way an AI assistant or a mail-merge tool would. Do not use stock opening lines such as "I hope this email finds you well" or "I wanted to reach out." Do not use generic closings such as "Please do not hesitate to contact me" unless the register truly calls for it. Do not write in a way that reveals a template with a name dropped in — let the recipient's actual role and context shape how the sentence is built, not just which name appears in it. Vary sentence length. Avoid corporate boilerplate and filler phrases. This should read like it was written once, for this one person, by someone who thought about what they wanted to say to them specifically.

**Enforcement:** `validate_draft()` (Section 6.5) checks the generated text against a maintained list of known AI-sounding boilerplate phrases (the ones above, plus others like "in today's fast-paced world," "I trust this message finds you well," "as a valued member of," "leverage synergies") in addition to its emoji and word-count checks. A match triggers the same corrective re-prompt-and-regenerate loop already defined for those checks — never a silent pass-through.

### 7.3 Retry / Backoff for Sends

```
function send_with_retry(draft, max_attempts=3):
    for attempt in 1..max_attempts:
        result = send_via_resend(draft)
        if result.success:
            return result
        if result.error_type == PERMANENT:      # invalid address, hard bounce
            return result                          # do not retry
        wait(base_delay * 2^(attempt-1))            # exponential backoff
    return result   # final failed result after exhausting attempts
```

### 7.4 Word Count Enforcement

```
function enforce_word_limit(text, limit=200):
    words = split_on_whitespace(text)
    if len(words) <= limit:
        return text
    return None   # signals message_generator to re-prompt for a shorter draft,
                    # never silently truncates mid-sentence
```

---

## 8. Sequence Flows

### 8.1 First-Run Setup
```
Operator → CLI: launches app, no secrets file found
CLI → Operator: setup wizard, Step 1-5
CLI → TiDB: test connection
CLI → TiDB: run_script(schema.sql)
CLI → secrets_manager: encrypt(config) → write to disk
CLI → Operator: "Setup complete, returning to Main Menu"
```

### 8.2 Add a Person
```
Operator → CLI: Main Menu → Manage Persons → Add a Person
CLI → Operator: field prompts
CLI → person_service.add_person(data)
person_service → TiDB: INSERT INTO persons ...
TiDB → person_service: new id
CLI → Operator: confirmation panel with new ID
```

### 8.3 Run a Full Campaign
```
Operator → CLI: Main Menu → Run a Campaign
CLI → Operator: name, recipient filter, topic brief
CLI → campaign_service.create_campaign()
campaign_service → TiDB: INSERT INTO campaigns (tone snapshot included)
CLI → campaign_service.build_recipient_list()
campaign_service → TiDB: SELECT ... FROM persons WHERE ...
loop per recipient:
    campaign_service → tone_engine.assign_tone()
    campaign_service → message_generator.generate_draft()
    message_generator → AI provider: HTTPS request
    AI provider → message_generator: draft text
    message_generator → message_generator: validate_draft()
CLI → Operator: review screen per draft (approve/regenerate/skip/edit)
Operator → CLI: confirm send
CLI → campaign_service.run_send_phase()
loop per approved draft:
    campaign_service → sender_queue.dispatch()
    sender_queue → Resend API: HTTPS POST
    Resend API → sender_queue: message id or error
    sender_queue → TiDB: INSERT INTO message_log (every attempt)
CLI → TiDB: UPDATE campaigns SET status='completed', totals...
CLI → Operator: summary panel
```

### 8.4 Failure & Retry Path
```
sender_queue → Resend API: send attempt 1 → timeout
sender_queue → sender_queue: classify as TRANSIENT
sender_queue → sender_queue: wait(backoff), attempt 2 → 500 error
sender_queue → sender_queue: classify as TRANSIENT, wait, attempt 3 → success
sender_queue → TiDB: INSERT INTO message_log (status='sent', resend_message_id=...)
```
```
sender_queue → Resend API: send attempt 1 → 422 invalid address
sender_queue → sender_queue: classify as PERMANENT, no retry
sender_queue → TiDB: INSERT INTO message_log (status='failed', error_message=...)
sender_queue → person_service.set_status(person_id, 'bounced')
```

---

## 9. State Machines

### 9.1 `persons.status`
```
active ──(unsubscribe request)──> unsubscribed
active ──(hard bounce)──> bounced
active ──(operator archives)──> archived
unsubscribed/bounced/archived ──(operator reactivates)──> active
```
Only `active` persons are eligible to be selected into a new campaign's recipient list.

### 9.2 `campaigns.status`
```
draft ──(recipients + drafts confirmed)──> in_progress
in_progress ──(all sends attempted)──> completed
in_progress ──(operator cancels mid-run)──> aborted
```

### 9.3 `message_log.status`
```
pending ──(dispatch succeeds)──> sent
pending ──(dispatch fails, exhausts retries)──> failed
pending ──(operator skips at review)──> skipped
```

---

## 10. Secrets & Encryption Design

- A local Fernet symmetric key is generated on first run and stored in a file separate from the encrypted secrets blob (so neither file alone is useful to an attacker who only gets one of them).
- Secrets file location:
  - Linux: `~/.config/meridian/secrets.enc` and `~/.config/meridian/key.bin`
  - Windows: `%APPDATA%\meridian\secrets.enc` and `key.bin`
- File permissions locked to the owning user only (`chmod 600` equivalent on both OSes).
- The CLI's "Settings & Secrets" menu is the only way to view (masked) or change any credential — there is no plain-text config file to hand-edit.
- TiDB connections default to TLS; the setup wizard only allows disabling TLS with an explicit confirmation warning, for local/self-hosted test clusters.

---

## 11. Error Handling Matrix

| Failure | Where Caught | System Response |
|---|---|---|
| TiDB unreachable at startup | `wait_for_connection()` | Retries 3x with delay, then shows a clear CLI error and returns to a "fix connection" screen instead of crashing |
| Invalid TiDB credentials | `Database.connect()` | Human-readable error surfaced in Settings screen, does not proceed to Main Menu |
| Resend API key invalid/expired | `send_via_resend()` first call | Aborts the send phase immediately, no partial silent failures, tells operator to fix the key in Settings |
| AI provider timeout | `message_generator.generate_draft()` | Retries the single draft up to 3x; if still failing, marks that recipient "skipped — generation failed" and continues the batch |
| Draft exceeds word limit after 3 regenerations | `generate_draft()` | Raises `GenerationFailedError`, recipient is flagged for manual edit at review, never auto-sent |
| Draft contains emoji after generation | `validate_draft()` | Automatic re-prompt with corrective instruction; never surfaced to Resend uncorrected |
| Resend hard bounce / invalid address | `sender_queue.dispatch()` | No retry; person marked `bounced`; logged with `error_message` |
| Resend transient 5xx/timeout | `sender_queue.dispatch()` | Exponential backoff retry up to 3 attempts before marking `failed` |
| CSV import row missing required field | `person_service.import_csv()` | Row skipped, reported by row number in the import summary, rest of file still processed |
| Duplicate email on import or add | `person_service` | Rejected with a clear message; existing record is never silently overwritten |
| Tone split doesn't total 100% | `tone_engine.validate_split()` | Save button disabled in CLI, exact shortfall/excess shown |
| Mid-campaign crash/power loss | `sender_queue.dispatch()` write-before-advance | Every attempt is logged to TiDB before moving to the next recipient, so on restart the operator can see exactly which recipients were and weren't reached, and re-run only the remainder |

---

## 12. Logging & Observability

Two separate logs, serving different purposes:

1. **`message_log` (TiDB)** — the business audit trail: what was sent, to whom, when, in what tone, with what result. Queried through the History/Logs CLI screens.
2. **`logs/meridian.log` (local file, rotating)** — operational/technical log: connection events, retries, stack traces, timing. Not shown to the operator by default; used for troubleshooting. Rotates at a fixed size to avoid unbounded growth, keeps a small number of backups.

---

## 13. Security & Compliance

- Least-privilege TiDB user: grants limited to `SELECT, INSERT, UPDATE` on the `meridian` schema only — no `DROP`/`ALTER` in normal operation (schema changes go through the migrations folder, run explicitly).
- All outbound calls (TiDB, Resend, AI provider) are HTTPS/TLS; no outbound call is ever made in plaintext.
- Full send history is retained indefinitely by default so the operator can always answer "did we already contact this person, and what did we say" before a follow-up.
- Because the recipient list includes journalists, officials, diplomats, and other high-scrutiny public figures, the design assumes the operator already has a legitimate, consensual basis for contacting each person; the system manages and sends to a list the operator supplies, and does not perform any collection or scraping of contact data itself.
- Unsubscribe/bounce status is authoritative and checked before every campaign's recipient list is built — no send ever bypasses `persons.status`.

---

## 14. Deployment

### 14.1 Linux
- Run interactively: `python3 main.py` from the project directory (after `pip install -r requirements.txt`).
- For persistence, register as a `systemd --user` service so it survives terminal closure; the CLI remains the control surface via `systemctl --user status/start/stop` for the process lifecycle only — all actual operation still happens inside the CLI menus once attached.

### 14.2 Windows
- Run interactively via `python main.py` in a terminal (PowerShell or Command Prompt).
- For persistence, register as a Scheduled Task set to run at logon, or run inside Windows Terminal in the background; same principle — process lifecycle is OS-managed, all operation is through the CLI menus.

### 14.3 Common
- No Docker requirement; pure Python + pip dependencies, since the target is a local machine, not a cloud deployment.
- TiDB itself can be TiDB Cloud (managed, TLS by default) or a self-hosted cluster reachable from the local machine — the setup wizard's connection fields work identically either way.

---

## 15. Testing Strategy

- **Unit tests** for `tone_engine.validate_split()` and `assign_tone()` (distribution correctness across large sample sizes), `message_generator.validate_draft()` (emoji detection, word count edge cases), and `sender_queue`'s retry/backoff logic (mocked Resend responses for transient vs. permanent failures).
- **Integration tests** against a disposable TiDB schema (create, run a full mock campaign end-to-end, tear down) to verify the full sequence in Section 8.3 without hitting the real Resend or AI APIs (both mocked).
- **CSV import tests** covering malformed rows, duplicate emails, and missing required columns.

---

## 16. Future Extensions (not built now, designed for)

- Per-category tone overrides in addition to per-person overrides.
- Scheduled/recurring campaigns (e.g. a segment contacted on a cadence) versus today's fully operator-triggered model.
- A mandatory dry-run threshold (e.g. auto-require full review above N recipients) instead of a flat optional dry-run toggle.
- Webhook ingestion from Resend for delivery/bounce/open events to automatically update `persons.status` and `message_log.status` beyond what the synchronous send response reports.

---

## 17. Agent-Operable Interface (Claude Code / CLI Coding Agents)

The human-facing menus in Section 5 (`rich` + `questionary`) are built for a person pressing arrow keys in a live terminal. An automated agent — Claude Code, Antigravity, or any other CLI coding agent — cannot reliably drive that layer: it has no stable way to "see" a highlighted menu item or send an arrow-key keystroke and know which option it landed on. For an agent to operate this system in a standardized, repeatable way, the design needs a **second, parallel interface** that sits beside the human CLI, not inside it.

### 17.1 Principle: One Service Layer, Two Front Ends

Section 6's service layer (`person_service`, `tone_engine`, `campaign_service`, `sender_queue`, `secrets_manager`) is already agent-friendly by construction: every function is a plain, typed, deterministic call with a defined return value — no hidden state, no screen-reading required. The human CLI (Section 5) is one front end onto that layer. The **Agent Interface** described below is a second front end onto the exact same layer, so nothing about the core system needs to change — this is an additive layer.

```
                    ┌───────────────────────┐
                    │   SERVICE LAYER        │   (Section 6 — unchanged)
                    │ person / tone / campaign│
                    │ sender / secrets         │
                    └──────┬────────────┬─────┘
                           │            │
              ┌────────────▼──┐   ┌─────▼─────────────┐
              │ Human CLI Menu │   │  Agent Interface    │
              │ (rich/questionary)│  (non-interactive,     │
              │  Section 5      │   │  structured JSON)      │
              └────────────────┘   └────────────────────────┘
                     ↑                        ↑
                  operator                 Claude Code /
                (arrow keys)              Antigravity / any
                                          CLI coding agent
```

### 17.2 Non-Interactive Command Contract

The Agent Interface is exposed as a **non-interactive subcommand mode** on the same `main.py` entry point, distinguished by an `agent` prefix, so it never collides with the human's normal launch (`python main.py` with no arguments still opens the human menu). Every agent subcommand:

- Takes a single `--json` argument containing a structured request payload (no multi-step prompts, no arrow keys).
- Prints a single structured JSON object to stdout and exits — nothing interactive, nothing that blocks waiting for keystrokes.
- Uses process exit codes consistently: `0` for success, `1` for a validation failure, `2` for a connection/infrastructure failure — so an agent can branch on exit code without parsing text.

```
python main.py agent person-add     --json '{...}'
python main.py agent person-search   --json '{...}'
python main.py agent tone-get         --json '{}'
python main.py agent tone-set          --json '{...}'
python main.py agent campaign-create    --json '{...}'
python main.py agent campaign-draft      --json '{...}'
python main.py agent campaign-send        --json '{...}'
python main.py agent history-query          --json '{...}'
```

### 17.3 Standardized Request/Response Schema

Every agent command follows the same envelope, so an agent only has to learn the shape once:

```
Request:
{
  "action": "tone-set",
  "params": { "professional": 60, "semi_casual": 30, "casual": 10, "note": "H2 adjustment" }
}

Response (success):
{
  "ok": true,
  "action": "tone-set",
  "result": { "id": 14, "professional_percent": 60, "semi_casual_percent": 30, "casual_percent": 10, "is_active": true },
  "error": null
}

Response (failure):
{
  "ok": false,
  "action": "tone-set",
  "result": null,
  "error": { "code": "TONE_SPLIT_INVALID", "message": "Total is 97%, add 3%" }
}
```

This is the same envelope for every action — `person-add`, `campaign-send`, everything — so a coding agent writing a script against this system only has to parse one response shape.

### 17.4 Example: Agent Sets a New Tone Split

```
$ python main.py agent tone-set --json '{"professional":50,"semi_casual":35,"casual":15,"note":"lighter tone for August"}'

{"ok": true, "action": "tone-set", "result": {"id": 15, "professional_percent": 50, "semi_casual_percent": 35, "casual_percent": 15, "is_active": true}, "error": null}
```
Internally this calls exactly the same `tone_engine.validate_split()` → `tone_engine.save_split()` path as the human "Configure Tone Split" screen — same validation, same TiDB row, same history-preserving insert described in Section 6.4. The agent gets a guarantee: **anything it can do through this interface obeys the same rules the human CLI enforces** — the 100%-total rule, the emoji/word-count rules, the duplicate-email rule, all of it, because both front ends call the identical service functions.

### 17.5 Example: Agent Adds a Person and Runs a Campaign

```
$ python main.py agent person-add --json '{"full_name":"Jane Whitmore","email":"jane@example.org","designation":"Managing Editor","category":"journalist"}'
{"ok": true, "action": "person-add", "result": {"id": 482, ...}, "error": null}

$ python main.py agent campaign-create --json '{"name":"Q3 Update","topic_brief":"...", "target_filter":{"category":"journalist"}}'
{"ok": true, "action": "campaign-create", "result": {"id": 9, "status": "draft"}, "error": null}

$ python main.py agent campaign-draft --json '{"campaign_id":9}'
{"ok": true, "action": "campaign-draft", "result": {"drafts_generated": 128, "drafts_flagged_for_review": 3}, "error": null}

$ python main.py agent campaign-send --json '{"campaign_id":9, "confirm":true}'
{"ok": true, "action": "campaign-send", "result": {"sent": 126, "failed": 2, "skipped": 3}, "error": null}
```

### 17.6 Guardrails Specific to Agent Use

Because an agent can issue commands far faster and more repetitively than a human operator, three protections apply only to the Agent Interface, on top of everything in Section 11:

1. **`campaign-send` requires an explicit `"confirm": true`** in the payload every single time — there is no "remember my last answer" state, so an agent can never trigger a real send as a side effect of a exploratory or mistaken call.
2. **Idempotency keys** — `campaign-create` and `person-add` accept an optional `"idempotency_key"`; replaying the same key returns the original result instead of creating a duplicate, protecting against an agent retrying a call after a timeout without knowing whether the first attempt succeeded.
3. **Rate ceiling independent of `send_rate_per_minute`** — the Agent Interface enforces its own hard ceiling on `campaign-send` calls per hour, separate from the email-sending rate limiter in Section 7.3, so a misbehaving or looping agent script cannot spin up an unbounded number of campaigns even if each individual campaign is small.

### 17.7 What This Enables

With Section 17 in place, a CLI coding agent (Claude Code, Antigravity, or similar) can be pointed at this repository and, using nothing but the documented `agent <action> --json '{...}'` contract:

- Read and write the tone split (`tone-get` / `tone-set`), always validated against the 100% rule.
- Create, search, update, and import/export persons (`person-add`, `person-search`, `person-update`, `person-import-csv`, `person-export-csv`).
- Create a campaign, generate drafts, and — only with explicit confirmation — send it (`campaign-create`, `campaign-draft`, `campaign-send`).
- Query the full audit trail (`history-query`) to answer "what have we sent this person" before taking any further action.

None of this requires the agent to parse `rich` tables or simulate keystrokes — it is a first-class, documented, structured interface that happens to share the exact same underlying rules, validation, and TiDB tables as the human menu.

---

## 18. MCP Server Integration

MCP (Model Context Protocol) is the current standard for connecting an AI agent — Claude, Claude Code, or any other MCP-compatible client — directly to a system's real capabilities, instead of the agent shelling out to CLI subprocesses and parsing text. Section 17's non-interactive `agent` contract is still valuable (for shell scripts, cron-style automation, and non-MCP tooling), but for Claude Code and similar agents, an **MCP server is the correct native front end**: same service layer, same validation, same TiDB tables — just exposed as first-class MCP tools instead of subprocess calls.

### 18.1 Where It Sits

```
                    ┌───────────────────────┐
                    │   SERVICE LAYER        │   (Section 6 — unchanged)
                    │ person / tone / campaign│
                    │ sender / secrets         │
                    └──┬──────────┬─────────┬──┘
                       │          │         │
              ┌────────▼──┐ ┌─────▼──────┐ ┌▼────────────────┐
              │ Human CLI  │ │ Agent CLI   │ │  MCP Server       │
              │ (Section 5)│ │ (Section 17)│ │  mcp_server.py      │
              └────────────┘ └─────────────┘ └──┬─────────────────┘
                                                  │ MCP protocol (stdio)
                                                  ▼
                                     Claude Code / Claude Desktop /
                                     any MCP-compatible agent
```

### 18.2 New Project File

```
mcp/
└── mcp_server.py    # MCP server exposing the service layer as tools + resources
```

`mcp_server.py` is built on the standard MCP Python SDK, registered as a **stdio server** (the default and simplest transport for a local tool like this — no network port, no auth layer needed beyond what the OS process boundary already gives you). It is added to Claude Code's MCP configuration by pointing at this script, exactly like any other local MCP server.

### 18.3 Tool Definitions

Each MCP tool is a thin wrapper around one service-layer function, with a declared JSON Schema for its inputs — this is the same contract as Section 17's envelope, just exposed as native MCP tools instead of a `--json` CLI flag:

| MCP Tool Name | Wraps | Input Schema (key fields) |
|---|---|---|
| `person_add` | `person_service.add_person()` | full_name, email, designation, category, organization?, country?, preferred_tone?, notes? |
| `person_search` | `person_service.search_persons()` | category?, status?, query? |
| `person_update` | `person_service.update_person()` | person_id, changes |
| `person_set_status` | `person_service.set_status()` | person_id, new_status |
| `person_import_csv` | `person_service.import_csv()` | file_path |
| `tone_get` | `tone_engine.get_active_split()` | (none) |
| `tone_set` | `tone_engine.validate_split()` + `save_split()` | professional, semi_casual, casual, note? |
| `campaign_create` | `campaign_service.create_campaign()` | name, topic_brief, target_filter |
| `campaign_draft` | `campaign_service.run_drafting_phase()` | campaign_id |
| `campaign_send` | `campaign_service.run_send_phase()` | campaign_id, confirm (must be `true`) |
| `history_query` | queries against `message_log` | person_id? / campaign_id? / date_range? |

### 18.4 Resources (Read-Only Context for the Agent)

Alongside tools, the MCP server exposes a small set of **resources** so an agent can pull context into its own reasoning without an explicit tool call each time:

- `meridian://tone-settings/active` — current tone split, always fresh.
- `meridian://designation-catalog` — the full standardized designation list from Section 19, so an agent adding a new person can pick a standardized designation instead of inventing free text.
- `meridian://persons/recent` — the most recently added/updated persons, for quick context.

### 18.5 Same Guardrails, Native Enforcement

Everything in Section 17.6 carries over unchanged, enforced at the tool level:
- `campaign_send` requires `confirm: true` in every call — no session memory of a prior confirmation.
- `person_add` and `campaign_create` accept an optional `idempotency_key`.
- A per-hour ceiling on `campaign_send` invocations applies regardless of how many separate agent sessions are calling it.

### 18.6 Configuring Claude Code / an MCP Client

The operator (not the agent) runs the one-time step of registering the server, using whatever MCP-server registration mechanism the client provides (e.g. Claude Code's MCP config file), pointing it at `mcp_server.py` and the same local secrets file described in Section 10 — the MCP server reuses `config.py` and `db/connection.py` exactly as the human CLI does, so there are no separate credentials to manage for agent access.

---

## 19. Standardized Designation Catalog (Broad, Pre-Drafted List)

To keep `persons.designation` consistent instead of drifting into inconsistent free text ("CEO" vs. "Chief Executive Officer" vs. "Founder/CEO"), the system ships a **pre-drafted, standardized catalog** of designations grouped by category. Both the human CLI's "Add a Person" screen and the MCP `person_add` tool present this catalog as the first choice, with free text only as a fallback for a genuinely uncommon title.

### 19.1 New Table: `designation_catalog`

```sql
CREATE TABLE designation_catalog (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    category        ENUM(
                        'billionaire','millionaire','tech_founder','politician',
                        'content_creator','journalist','human_rights','government_org',
                        'government_official','diplomat','media_personality',
                        'united_organization','high_value_person','other'
                    ) NOT NULL,
    standard_title  VARCHAR(150) NOT NULL,
    UNIQUE KEY uq_catalog_category_title (category, standard_title)
) ENGINE=InnoDB;
```

`persons.designation` remains a free-text `VARCHAR` (people's actual titles are too varied to force into a rigid enum), but the catalog is what both the human CLI and the MCP `person_add` tool suggest first, keeping the data clean without making the field genuinely rigid.

### 19.2 Seed List

**Billionaire / Ultra-High-Net-Worth**
Chairman & Founder · Chairman Emeritus · Executive Chairman · Principal Owner · Family Office Principal · Managing Partner, Family Office · Sovereign Wealth Fund Governor · Private Investment Office Principal · Philanthropic Foundation Chair · Estate & Legacy Trustee

**Millionaire / High-Net-Worth**
Managing Director · Principal, Private Equity · General Partner, Venture Capital · Portfolio Manager · Independent Investor · Angel Investor · Family Business Owner · Managing Partner

**Tech Founder / Executive**
Founder & CEO · Co-Founder & CTO · Founder & President · Chief Executive Officer · Chief Technology Officer · Chief Product Officer · Chief Operating Officer · Chairman & CEO · Serial Entrepreneur · Startup Studio Founder · Venture Partner

**Politician**
President · Vice President · Prime Minister · Deputy Prime Minister · Senator · Member of Parliament · Member of Congress · Governor · Mayor · State/Provincial Minister · Cabinet Minister · Party Leader · Opposition Leader · City Council Member

**Content Creator**
YouTuber / Channel Owner · Independent Podcast Host · Newsletter Publisher · Streaming Creator · Social Media Creator · Digital Publisher · Online Educator · Creator-Economy Founder

**Journalist**
Editor-in-Chief · Managing Editor · Senior Correspondent · Foreign Correspondent · Investigative Reporter · Bureau Chief · News Anchor · Columnist · Contributing Editor · Op-Ed Editor · Photojournalist

**Human Rights**
Human Rights Defender · Executive Director, NGO · Advocacy Director · UN Special Rapporteur · Field Director · Legal Counsel, Human Rights Organization · Campaign Director · Policy Director, Human Rights

**Government Organization**
Agency Director · Director-General · Commissioner · Regulatory Chair · Executive Secretary · Program Director · Bureau Director · Inspector-General

**Government Official**
Cabinet Secretary · Undersecretary · Permanent Secretary · Chief of Staff · Policy Advisor · Director of Communications · Deputy Minister · Attorney General · Central Bank Governor

**Diplomat**
Ambassador · Deputy Chief of Mission · Consul General · Permanent Representative to the UN · Special Envoy · Charg\u00e9 d'Affaires · Foreign Service Officer · Trade Commissioner

**Media Personality**
Television Host · Radio Host · News Presenter · Talk Show Host · Documentary Presenter · Media Commentator · Broadcast Personality

**United Organization (UN and Peer Bodies)**
Secretary-General · Deputy Secretary-General · Under-Secretary-General · Assistant Secretary-General · Special Representative · Resident Coordinator · Program Director, UN Agency · Regional Director

**High-Value Person (General)**
Board Chair · Board Member · Senior Advisor · Distinguished Fellow · Executive Advisor · Strategic Advisor

**Other**
(Free-text entry — used only when none of the above genuinely fits; the CLI and MCP tool both flag "Other" selections for the operator to review periodically, so the catalog can be extended rather than let free text accumulate unchecked.)

### 19.3 Why a Catalog Instead of a Rigid Enum on `persons.designation`

An ENUM on `designation` itself would break the moment a real person's title doesn't match exactly (e.g. "Executive Chairman & Co-Founder"). The catalog instead acts as a **guided default with an escape hatch**: the CLI and MCP tool present it as a selectable list first, and only fall through to free text when the operator explicitly chooses "Other" — giving consistency for the overwhelming majority of entries without ever blocking a real, unusual title from being recorded accurately.

---

This document is the complete blueprint: architecture, every table and column, every CLI screen's exact layout and every agent/MCP command's exact contract, every module's method signatures and pseudocode, the core algorithms (including the hard natural-language rule), full sequence flows, state machines, secrets handling, the error matrix, deployment, testing, and the standardized designation catalog. Tell me which module you want built into real code first, or if you want the whole thing built in one pass.
