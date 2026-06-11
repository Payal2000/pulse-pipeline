# PulsePipe

**Plain English to data insights** — describe what you want to know and PulsePipe
builds the entire pipeline, syncs the data, delivers the analysis, and autonomously
repairs failures. No dashboards, no SQL, no config.

> Observability tools tell you your pipeline broke. Fivetran tells you to go fix it.
> PulsePipe is the only thing in the loop that actually fixes it — and you provisioned
> the whole pipeline by just asking for it.

Built with **Gemini** + **Google ADK** + **Fivetran MCP** + **BigQuery**.

---

## The Problem (quantified)

| Stat | Figure | Source |
|------|--------|--------|
| Pipeline failures at large enterprises | ~4.7/month, ~13 hrs to resolve each | Fivetran 2026 Benchmark |
| Engineering capacity lost to maintenance toil | 53% | Fivetran 2026; dbt 2024 |
| Time just to *detect* a failure | 68% take 4+ hours | Monte Carlo/Wakefield 2023 |
| Business stakeholders find issues before data teams | 74% | Monte Carlo 2022 |
| Pipeline failures slowing AI initiatives | 97% of data leaders | Fivetran 2026 |

## What Exists vs. What We Do

| | Monte Carlo | Fivetran native | **PulsePipe** |
|---|---|---|---|
| Detect failures | Yes | Yes | Yes |
| Diagnose root cause | Yes (AI) | Partial | Yes (Gemini) |
| **Fix the problem** | No (read-only by design) | No (tells human to fix) | **Yes** |
| Provision from natural language | No | No | **Yes** |
| Analyze the data end-to-end | No | No | **Yes** |

---

## Architecture

```
User (chat UI)
   |
Gemini agent (Google ADK)
   |
   |-- Fivetran MCP server (100+ tools, ALLOW_WRITES=true)
   |     creates connectors, tests, syncs, repairs, webhooks
   |
   |-- BigQuery tools
   |     queries + verifies synced data
   |
   +-- Fivetran webhook --> Cloud Run --> wakes agent on failure
```

### Two Agent Loops

**Loop 1 — Provision** (user-initiated, conversational)
1. User describes data needs in one sentence
2. Agent finds connector types, creates a secure Connect Card
3. Tests the connection, configures schema (syncs only needed tables)
4. Registers a webhook for autonomous repair
5. Triggers sync, polls until complete
6. Queries BigQuery, delivers the analysis

**Loop 2 — Repair** (event-driven, graduated remediation ladder)

| Tier | What | Agent does | Human? |
|------|------|-----------|--------|
| **1 — Autonomous** | Sync failures, transient errors | Diagnose + re-sync | No |
| **2 — Judgment** | Blocked schema policy, config errors | Reason about user's goal, fix + re-sync | No |
| **3 — Escalation** | Credential expiry, unresolvable | Pre-stage the fix (Connect Card), notify user | Yes |

After every repair: **verify** (sanity-query BigQuery) + **record** (incident audit log).

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for Fivetran MCP server)
- Google Cloud project with BigQuery enabled
- Fivetran account ([14-day free trial](https://fivetran.com/signup))

### Setup

```bash
git clone https://github.com/YOUR_USERNAME/pulse-pipeline.git
cd pulse-pipeline

pip install -e .

cp .env.example .env
# Edit .env with your credentials

python -m pulse_pipeline.server
```

Open [http://localhost:8080](http://localhost:8080) and start chatting.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `GEMINI_MODEL` | Gemini model ID (default: `gemini-2.5-flash`) |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| `FIVETRAN_API_KEY` | Fivetran API key |
| `FIVETRAN_API_SECRET` | Fivetran API secret |
| `BIGQUERY_DATASET` | BigQuery dataset (default: `pulse_pipeline`) |
| `WEBHOOK_URL` | Public URL for Fivetran webhooks |
| `PORT` | Server port (default: `8080`) |

---

## Deploy to Cloud Run

```bash
# Store secrets
gcloud secrets create fivetran-api-key --data-file=- <<< "$FIVETRAN_API_KEY"
gcloud secrets create fivetran-api-secret --data-file=- <<< "$FIVETRAN_API_SECRET"

# Build & deploy
gcloud builds submit --config deploy/cloudbuild.yaml
```

After deploying, set `WEBHOOK_URL` to `https://<your-service>.run.app/api/webhook/fivetran`.

---

## Demo Script (~3 minutes)

### Act 1 — Provision (plain English to live pipeline)
1. Type: *"I want my Google Sheets sales data analyzed for weekend trends"*
2. Watch: agent finds connector type, creates Connect Card, user authorizes
3. Watch: agent configures schema (syncs only needed tables), triggers sync
4. Watch: sync completes, agent queries BigQuery, presents analysis

### Act 2 — Repair (the differentiator)

**Scene A — Credential revocation** (Tier 3: escalation with fix pre-staged)
1. Revoke the Google Sheets OAuth token in Google Account settings
2. The next sync fails → webhook fires → agent wakes up
3. Watch: agent diagnoses "OAuth token revoked," generates a new Connect Card link
4. User clicks the link, re-authorizes → agent re-syncs automatically
5. *Key stat:* time-to-resolution collapsed from ~13 hours to ~60 seconds

**Scene B — Blocked schema policy** (Tier 2: goal-aware judgment)
1. Add a new `discount` column to the source Google Sheet
2. Fivetran's schema policy blocks the change → webhook fires
3. Watch: agent reasons — *"A discount column appeared. Since you're analyzing
   sales trends, this is relevant — enabling it and backfilling"*
4. Agent modifies schema config, re-syncs, verifies in BigQuery
5. *The wow:* this is a goal-aware judgment call that no rules engine can make

### Act 3 — Audit
- Show the incident log in the sidebar: what broke, what was tried, time-to-recovery
- Show the post-heal verification: row counts, null rates, data freshness

---

## Tech Stack

- **Agent**: [Google ADK](https://google.github.io/adk-docs/) with Gemini
- **Data Integration**: [Fivetran MCP Server](https://github.com/fivetran/fivetran-mcp-server)
- **Data Warehouse**: Google BigQuery
- **Server**: FastAPI + Uvicorn
- **Hosting**: Google Cloud Run

## License

Apache 2.0 — see [LICENSE](LICENSE).
