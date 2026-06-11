# PulsePipe

**Self-healing data ops agent** — tell it what data you need in plain English and it provisions, monitors, repairs, and analyzes the entire pipeline autonomously.

Built with **Gemini** + **Google Cloud Agent Builder (ADK)** + **Fivetran MCP** + **BigQuery**.

---

## Architecture

```
User (chat UI)
   │
Gemini agent (Google ADK)
   │
   ├── Fivetran MCP server
   │     creates connectors, runs tests, triggers syncs,
   │     monitors state, fixes schema issues, manages webhooks
   │
   ├── BigQuery tools
   │     queries synced data for analysis
   │
   └── Fivetran webhook → Cloud Run → wakes agent on sync failure
```

### Two Agent Loops

**Loop 1 — Provision** (user-initiated)
1. User describes data needs → agent finds connector types
2. Creates connection (secure Connect Card for user auth)
3. Tests connection, retries on failure
4. Configures schema — syncs only needed tables
5. Registers webhook for self-healing
6. Triggers sync, polls until complete
7. Queries BigQuery and delivers analysis

**Loop 2 — Heal** (event-driven)
1. Sync breaks → Fivetran webhook fires → agent wakes
2. Diagnoses the failure, then climbs the **remediation ladder**:
   - **Autonomous** — transient sync failures, broken tables, unambiguous config errors: fixed and re-synced without human involvement
   - **Judgment calls** — blocked schema changes: the agent reasons about whether the new column/table matters to *your stated goal* and enables it if so
   - **Human-in-the-loop** — credential expiry: agent arrives with a fresh Connect Card link pre-staged, so re-auth takes seconds, not hours
3. Verifies the *pipeline* (setup tests + re-sync) **and the data** (sanity queries in BigQuery)
4. Reports what broke, what it did, and the verified state — live in the chat UI
5. Escalates with a precise diagnosis if it can't fix

> Observability tools tell you your pipeline broke. Fivetran tells you to go
> fix it. PulsePipe closes the loop — it fixes it.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for Fivetran MCP server)
- Google Cloud project with BigQuery enabled
- Fivetran account ([14-day free trial](https://fivetran.com/signup))

### Setup

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/pulse-pipeline.git
cd pulse-pipeline

# Install
pip install -e .

# Configure
cp .env.example .env
# Edit .env with your credentials

# Run
python -m pulse_pipeline.server
```

Open [http://localhost:8080](http://localhost:8080) and start chatting.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `GEMINI_MODEL` | Gemini model ID (default: `gemini-3-flash-preview`) |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| `FIVETRAN_API_KEY` | Fivetran API key |
| `FIVETRAN_API_SECRET` | Fivetran API secret |
| `BIGQUERY_DATASET` | BigQuery dataset (default: `pulse_pipeline`) |
| `WEBHOOK_URL` | Public URL for Fivetran webhooks |
| `PORT` | Server port (default: `8080`) |

---

## Deploy to Cloud Run

### Option 1: Cloud Build

```bash
# Store secrets
gcloud secrets create fivetran-api-key --data-file=- <<< "$FIVETRAN_API_KEY"
gcloud secrets create fivetran-api-secret --data-file=- <<< "$FIVETRAN_API_SECRET"

# Deploy
gcloud builds submit --config deploy/cloudbuild.yaml
```

### Option 2: Direct Deploy

```bash
# Build & push
gcloud builds submit --tag gcr.io/$PROJECT_ID/pulse-pipeline

# Deploy
gcloud run deploy pulse-pipeline \
  --image gcr.io/$PROJECT_ID/pulse-pipeline \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,BIGQUERY_DATASET=pulse_pipeline" \
  --set-secrets "FIVETRAN_API_KEY=fivetran-api-key:latest,FIVETRAN_API_SECRET=fivetran-api-secret:latest"
```

After deploying, update `WEBHOOK_URL` to your Cloud Run service URL + `/api/webhook/fivetran`.

---

## Demo Script

1. **Provision**: Ask _"I want my Google Sheets sales data analyzed for weekend trends"_
2. Watch the agent find the connector, create a Connect Card, configure schema, and trigger sync
3. **Analyze**: Agent queries BigQuery and presents findings
4. **Break it (auth)**: Revoke the Google Sheets OAuth grant → next sync fails →
   webhook fires → agent diagnoses credential expiry → arrives in chat with a
   fresh Connect Card link pre-staged → re-auth in one click → agent re-syncs,
   sanity-checks the data, and reports
5. **Break it (judgment)**: With schema policy set to *block new columns*, add a
   `discount` column to the sheet → agent wakes, reasons that the column is
   relevant to the weekend-trends goal, enables and backfills it, and explains why

> Note: don't demo schema *drift* (e.g. renaming a column) — Fivetran handles
> that natively. PulsePipe's value is what Fivetran does **not** automate.

---

## Tech Stack

- **Agent**: [Google ADK](https://google.github.io/adk-docs/) with Gemini
- **Data Integration**: [Fivetran MCP Server](https://github.com/fivetran/fivetran-mcp-server)
- **Data Warehouse**: Google BigQuery
- **Server**: FastAPI + Uvicorn
- **Hosting**: Google Cloud Run

## License

Apache 2.0 — see [LICENSE](LICENSE).
