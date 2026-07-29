# Meridian

> Precision outreach for high-value relationships.

Meridian is a fully local, persistent email outreach system for a non-technical operator.  
The **agent** (Claude Code, Antigravity, or any CLI agent) generates message content; Meridian validates it, routes it through your approval, and sends it via Resend.

---

## Architecture at a Glance

```
Agent (generates content)
        ↓
  FastAPI Server  ←─── MCP Server  ←─── Any MCP-compatible agent
        ↓
   Service Layer  (person / tone / campaign / sender)
        ↓
       TiDB  ←──────────────────── CLI (human operator)
        ↓
     Resend API
```

One service layer. Three front-ends:
1. **Human CLI** — `python main.py` — arrow-key menus, rich panels
2. **FastAPI REST API** — `python main.py server` — for agents calling via HTTP
3. **Non-interactive agent CLI** — `python main.py agent <action> --json '...'`
4. **MCP Server** — `python mcp/mcp_server.py` — native MCP tools for Claude Code

---

## Requirements

- Python 3.11+
- TiDB (TiDB Cloud or self-hosted — MySQL wire-compatible)
- A [Resend](https://resend.com) account with a verified sending domain

---

## Installation & Setup

We have provided automated setup scripts for both Windows and Linux/macOS. These scripts will automatically create a Python virtual environment (`.venv`), install all required dependencies, and launch the Setup Wizard.

### Windows
```cmd
install.bat
```

### Linux / macOS
```bash
chmod +x install.sh
./install.sh
```

---

## First Run (Setup Wizard)

If you ran the installation scripts above, the wizard will launch automatically. Otherwise, you can launch it manually:

```bash
python main.py
```

The 5-step wizard will ask for:
1. TiDB host, port, user, password, database, TLS settings
2. Resend API key
3. Default sender identity (from name + from email)
4. FastAPI server host/port + auto-generated Bearer token
5. Review & confirm — applies the database schema automatically

---

## Running

### Human CLI
```bash
python main.py
```

### FastAPI Server (for agents)
```bash
python main.py server
```

The server starts on `http://127.0.0.1:8765` (or your configured port).  
All endpoints require `Authorization: Bearer <your-token>`.

### MCP Server (for Claude Code / Claude Desktop)
```bash
python mcp/mcp_server.py
```

Register in your MCP config pointing at `mcp/mcp_server.py`.

---

## Agent Workflow

The intended workflow for a CLI agent:

```bash
# 1. Create a campaign
python main.py agent campaign-create --json '{"name":"Q3 Update","topic_brief":"Announce Q3 results"}'
# → {"ok":true,"action":"campaign-create","result":{"id":9,"status":"draft"}}

# 2. Get recipients + their assigned tones
python main.py agent campaign-recipients --json '{"campaign_id":9}'
# → list of recipients, each with full_name, designation, category, tone, topic_brief

# 3. Validate a draft before submitting
python main.py agent draft-validate --json '{"person_id":1,"subject":"Q3 Results","body":"...","tone":"professional"}'

# 4. Submit approved drafts for operator review
python main.py agent draft-submit --json '{"campaign_id":9,"person_id":1,"subject":"...","body":"...","tone":"professional"}'

# 5. Operator reviews in CLI, then agent sends (confirm:true required every time)
python main.py agent campaign-send --json '{"campaign_id":9,"confirm":true}'
```

---

## FastAPI Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Public health check |
| POST | `/person/add` | Add a person |
| POST | `/person/search` | Search persons |
| POST | `/person/update` | Update person fields |
| POST | `/person/set_status` | Change person status |
| GET | `/person/{id}` | Get person by ID |
| GET | `/tone` | Get active tone split |
| POST | `/tone/set` | Set new tone split |
| POST | `/campaign/create` | Create a campaign |
| GET | `/campaign/{id}/recipients` | Get recipients + tones |
| POST | `/campaign/draft/validate` | Validate a draft |
| POST | `/campaign/draft/submit` | Submit draft for review |
| POST | `/campaign/send` | Send (requires confirm=true) |
| POST | `/history/query` | Query message history |
| GET | `/catalog/designations` | Standardized designation list |

Interactive docs: `http://127.0.0.1:8765/docs`

---

## Running Tests

```bash
pytest
```

Target: **≥ 90% coverage** (enforced by `pytest.ini`).

---

## Hard Rules (always enforced)

- ≤ 200 words per message (configurable in Settings)
- No emoji — any emoji triggers rejection
- No literal `\n` escape sequences — must be real newlines
- No AI boilerplate (e.g. "I hope this email finds you well") — same rejection as emoji
- `campaign-send` requires `confirm: true` explicitly in every call
- `unsubscribed` / `bounced` persons are never selected into a new campaign

---

## Project Structure

```
meridian/
├── main.py                    # Entry point (CLI / server / agent)
├── config.py                  # AppConfig + load/save
├── requirements.txt
├── pytest.ini
├── db/
│   ├── schema.sql             # Complete DDL
│   └── connection.py          # Pooled TiDB connection
├── services/
│   ├── secrets_manager.py     # Fernet encryption
│   ├── person_service.py      # CRUD + CSV import/export
│   ├── tone_engine.py         # Tone split + assignment
│   ├── message_validator.py   # Word count / emoji / boilerplate rules
│   ├── sender_queue.py        # Rate limiter + Resend + retry
│   └── campaign_service.py    # Campaign orchestration
├── cli/
│   ├── formatting.py          # Rich helpers, color palette
│   ├── menu.py                # Main menu router
│   ├── screens_setup.py       # 5-step setup wizard
│   ├── screens_persons.py     # Person management
│   ├── screens_tone.py        # Tone split config
│   ├── screens_campaign.py    # Campaign creation + review + send
│   ├── screens_history.py     # History / logs
│   └── screens_settings.py    # Settings & secrets
├── api/
│   └── server.py              # FastAPI REST server
├── agent/
│   └── agent_cli.py           # Non-interactive agent interface
├── mcp/
│   └── mcp_server.py          # MCP stdio server
├── tests/
│   ├── conftest.py
│   ├── test_tone_engine.py
│   ├── test_message_validator.py
│   ├── test_person_service.py
│   ├── test_sender_queue.py
│   └── test_api_server.py
├── logs/
│   └── meridian.log           # Rotating operational log
└── data/
    └── imports/               # Drop zone for CSV imports
```
