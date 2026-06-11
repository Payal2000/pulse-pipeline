# PulsePipe Setup Guide

Complete step-by-step guide to set up PulsePipe from scratch on macOS (Apple Silicon).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Install Google Cloud CLI](#2-install-google-cloud-cli)
3. [Create a GCP Project](#3-create-a-gcp-project)
4. [Enable Billing](#4-enable-billing)
5. [Enable APIs](#5-enable-apis)
6. [Set Up Application Default Credentials](#6-set-up-application-default-credentials)
7. [Create a BigQuery Dataset](#7-create-a-bigquery-dataset)
8. [Enable Vertex AI](#8-enable-vertex-ai)
9. [Set Up Fivetran](#9-set-up-fivetran)
10. [Connect Fivetran to BigQuery](#10-connect-fivetran-to-bigquery)
11. [Create a Google Sheet (Sample Data)](#11-create-a-google-sheet-sample-data)
12. [Install Python and Project Dependencies](#12-install-python-and-project-dependencies)
13. [Configure Environment Variables](#13-configure-environment-variables)
14. [Run the Server](#14-run-the-server)
15. [Use PulsePipe](#15-use-pulsepipe)
16. [Troubleshooting](#16-troubleshooting)

---

## 1. Prerequisites

- macOS (Apple Silicon or Intel)
- Homebrew installed (`/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`)
- Node.js 18+ (`brew install node`)
- A Google account
- A web browser

---

## 2. Install Google Cloud CLI

Download and install the gcloud CLI. **Important:** Install it in your home directory, NOT inside the project folder.

```bash
cd ~
curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-darwin-arm.tar.gz
tar -xf google-cloud-cli-darwin-arm.tar.gz
./google-cloud-sdk/install.sh
```

> For Intel Macs, replace `darwin-arm` with `darwin-x86_64` in the URL.

During installation, you'll be prompted:

- **"Modify profile to update your $PATH and enable shell command completion?"** → Type `Y`
- **"Enter a path to an rc file to update"** → Press Enter to accept the default `[~/.zshrc]`

After installation, restart your shell:

```bash
source ~/.zshrc
```

Verify the installation:

```bash
gcloud --version
```

Expected output:

```
Google Cloud SDK 572.0.0
bq 2.1.32
core 2026.06.05
...
```

---

## 3. Create a GCP Project

### Authenticate with Google

```bash
gcloud init
```

This opens your browser. Sign in with your Google account. When asked to pick a project, select option **8** ("Enter a project ID") or skip for now.

### Create a new project

```bash
gcloud projects create pulse-pipeline-2026 --name="PulsePipe"
```

> If the project ID is taken (globally unique), try a variation like `pulse-pipeline-YOUR_NAME` or `pulse-pipeline-2026-dev`.

Set it as the active project:

```bash
gcloud config set project pulse-pipeline-2026
```

---

## 4. Enable Billing

A billing account is required for BigQuery DML queries and Vertex AI, even within free tier limits. **You will not be charged** for normal hackathon usage.

### Option A: Via browser

1. Go to https://console.cloud.google.com/billing
2. Click **Create Account** (or **Link a billing account**)
3. Enter your country, select "Individual", add a credit card
4. Link the billing account to your project:
   - Go to https://console.cloud.google.com/billing/projects
   - Find `pulse-pipeline-2026`
   - Click **Change billing** → select your billing account

### Option B: Via terminal

List your billing accounts:

```bash
gcloud billing accounts list
```

Copy the `ACCOUNT_ID` from the output, then link it:

```bash
gcloud billing projects link pulse-pipeline-2026 --billing-account=YOUR_BILLING_ACCOUNT_ID
```

Example:

```bash
gcloud billing projects link pulse-pipeline-2026 --billing-account=01011F-268C56-95A15F
```

### Set a budget alert (recommended)

1. Go to **Billing** → **Budgets & alerts** in GCP Console
2. Create a budget for **$1** so you get notified before any real charges

---

## 5. Enable APIs

Enable the required Google Cloud APIs:

```bash
gcloud services enable bigquery.googleapis.com --project=pulse-pipeline-2026
```

---

## 6. Set Up Application Default Credentials

This lets your app authenticate with Google Cloud automatically (no key files needed):

```bash
gcloud auth application-default login
```

This opens a browser to authorize. Accept the permissions.

Set the quota project:

```bash
gcloud auth application-default set-quota-project pulse-pipeline-2026
```

---

## 7. Create a BigQuery Dataset

```bash
bq mk --dataset pulse-pipeline-2026:pulse_pipeline
```

This creates the `pulse_pipeline` dataset where Fivetran will sync data.

---

## 8. Enable Vertex AI

PulsePipe uses Gemini via Vertex AI (avoids free-tier API key credit limits):

```bash
gcloud services enable aiplatform.googleapis.com --project=pulse-pipeline-2026
```

---

## 9. Set Up Fivetran

### Create a Fivetran account

1. Go to https://fivetran.com/signup
2. Sign up with your Google account (14-day free trial, no credit card required)

### Get your API key and secret

1. Log into the Fivetran dashboard
2. Click your **profile icon** (bottom-left corner)
3. Go to **API Key**
4. Copy both the **API Key** and **API Secret** — you'll need these for your `.env` file

---

## 10. Connect Fivetran to BigQuery

### Create a destination in Fivetran

1. In the Fivetran dashboard, go to **Destinations** → **Add Destination**
2. Select **BigQuery**
3. **Destination name**: `pulse_pipeline`
4. **Project ID**: `pulse-pipeline-2026`
5. **Select deployment model**: Choose **SaaS Deployment**
6. **Use own Service Account**: Leave **OFF**

### Grant Fivetran access to BigQuery

Copy the Fivetran service account email shown at the bottom of the destination setup page (looks like `g-xxxxx@fivetran-production.iam.gserviceaccount.com`).

Run this command, replacing the email:

```bash
gcloud projects add-iam-policy-binding pulse-pipeline-2026 \
  --member="serviceAccount:g-YOUR-SERVICE-ACCOUNT@fivetran-production.iam.gserviceaccount.com" \
  --role="roles/bigquery.admin"
```

Example:

```bash
gcloud projects add-iam-policy-binding pulse-pipeline-2026 \
  --member="serviceAccount:g-abound-instantaneously@fivetran-production.iam.gserviceaccount.com" \
  --role="roles/bigquery.admin"
```

### Test the connection

Click **Save & Test** in Fivetran. All tests should pass. If you get a billing error, make sure Step 4 (Enable Billing) is complete.

---

## 11. Create a Google Sheet (Sample Data)

### Create the spreadsheet

1. Go to https://sheets.google.com
2. Create a new spreadsheet
3. Name it: **PulsePipe Demo**

### Add sample data

Enter this data starting from cell A1:

| date | product | quantity | revenue |
|------|---------|----------|---------|
| 2026-06-01 | Widget A | 15 | 299.85 |
| 2026-06-01 | Widget B | 8 | 199.92 |
| 2026-06-02 | Widget A | 22 | 439.78 |
| 2026-06-02 | Widget B | 12 | 299.88 |
| 2026-06-03 | Widget A | 10 | 199.90 |
| 2026-06-03 | Widget B | 18 | 449.82 |
| 2026-06-07 | Widget A | 30 | 599.70 |
| 2026-06-07 | Widget B | 25 | 624.75 |
| 2026-06-08 | Widget A | 28 | 559.72 |
| 2026-06-08 | Widget B | 20 | 499.80 |

> **Important:** Make sure Row 1 has proper headers (`date`, `product`, `quantity`, `revenue`). This ensures clean column names in BigQuery.

### Share the sheet

1. Click **Share**
2. Set to **Anyone with the link** → **Viewer**
3. Copy the sheet URL — you'll need it when talking to the agent

---

## 12. Install Python and Project Dependencies

### Install Python 3.12

```bash
brew install python@3.12
```

### Install uv (Python package manager, needed for Fivetran MCP)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Create a virtual environment and install dependencies

```bash
cd ~/Desktop/pulse-pipeline
python3.12 -m venv venv
source venv/bin/activate
pip install -e .
```

> Always activate the venv before running the server: `source venv/bin/activate`

---

## 13. Configure Environment Variables

### Copy the example file

```bash
cp .env.example .env
```

### Edit `.env` with your values

```env
# Gemini / Google Cloud
GEMINI_MODEL=gemini-2.5-flash
GOOGLE_CLOUD_PROJECT=pulse-pipeline-2026
GOOGLE_API_KEY=your-gemini-api-key
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=true

# Fivetran (from Step 9)
FIVETRAN_API_KEY=your-fivetran-api-key
FIVETRAN_API_SECRET=your-fivetran-api-secret

# BigQuery destination dataset
BIGQUERY_DATASET=pulse_pipeline

# Webhook URL (update after deploying to Cloud Run)
WEBHOOK_URL=https://your-service-url.run.app/api/webhook/fivetran

# Server
PORT=8080
```

### Get a Gemini API key

1. Go to https://aistudio.google.com/apikey
2. Click **Create API Key**
3. Select project **pulse-pipeline-2026**
4. Copy the key and paste it as `GOOGLE_API_KEY` in your `.env`

> With `GOOGLE_GENAI_USE_VERTEXAI=true`, the agent uses Vertex AI (billed through your GCP project) instead of the free-tier Gemini API, which avoids credit exhaustion issues.

---

## 14. Run the Server

```bash
cd ~/Desktop/pulse-pipeline
source venv/bin/activate
python -m pulse_pipeline.server
```

Expected output:

```
INFO:     Started server process [XXXXX]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

Open your browser to **http://localhost:8080**

---

## 15. Use PulsePipe

### Provision a pipeline

Type a message like:

```
Analyze my Google Sheet https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID for weekend vs weekday sales trends
```

The agent will:
1. Identify the Google Sheets connector
2. Create a Fivetran connection
3. Authorize access to your sheet
4. Configure the schema (select relevant tables)
5. Trigger a data sync
6. Wait for data to land in BigQuery
7. Query BigQuery and return the analysis

### Ask follow-up questions

```
What are my top selling products?
Which product has the highest total revenue?
Show me daily revenue trends.
```

---

## 16. Troubleshooting

### `fivetran-mcp-server` not found (npm 404)

The Fivetran MCP server is a Python package, not npm. Make sure `agent.py` uses `uvx`:

```python
fivetran_mcp = MCPToolset(
    connection_params=StdioServerParameters(
        command="uvx",
        args=["--from", "git+https://github.com/fivetran/fivetran-mcp", "fivetran-mcp"],
        ...
    ),
)
```

### `ValueError: No API key was provided`

Add `GOOGLE_API_KEY` to your `.env` file. Get one from https://aistudio.google.com/apikey.

### `429 RESOURCE_EXHAUSTED` (Gemini credits depleted)

Switch to Vertex AI by adding these to your `.env`:

```env
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=true
```

Make sure Vertex AI is enabled:

```bash
gcloud services enable aiplatform.googleapis.com --project=pulse-pipeline-2026
```

### `billingNotEnabled` error in Fivetran connection test

Link a billing account to your GCP project (see Step 4).

### `gcloud` not found after installation

```bash
source ~/.zshrc
```

### Column names garbled in BigQuery

Ensure your Google Sheet has proper headers in Row 1 (`date`, `product`, `quantity`, `revenue`). Fivetran uses the first row as column names.

### `externally-managed-environment` pip error

Use a virtual environment:

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -e .
```

---

## Summary of All Terminal Commands

```bash
# Install gcloud CLI
cd ~
curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-darwin-arm.tar.gz
tar -xf google-cloud-cli-darwin-arm.tar.gz
./google-cloud-sdk/install.sh
source ~/.zshrc

# Create and configure GCP project
gcloud init
gcloud projects create pulse-pipeline-2026 --name="PulsePipe"
gcloud config set project pulse-pipeline-2026

# Enable billing
gcloud billing accounts list
gcloud billing projects link pulse-pipeline-2026 --billing-account=YOUR_BILLING_ACCOUNT_ID

# Enable APIs
gcloud services enable bigquery.googleapis.com --project=pulse-pipeline-2026
gcloud services enable aiplatform.googleapis.com --project=pulse-pipeline-2026

# Set up credentials
gcloud auth application-default login
gcloud auth application-default set-quota-project pulse-pipeline-2026

# Create BigQuery dataset
bq mk --dataset pulse-pipeline-2026:pulse_pipeline

# Grant Fivetran access to BigQuery
gcloud projects add-iam-policy-binding pulse-pipeline-2026 \
  --member="serviceAccount:YOUR_FIVETRAN_SERVICE_ACCOUNT@fivetran-production.iam.gserviceaccount.com" \
  --role="roles/bigquery.admin"

# Install Python and dependencies
brew install python@3.12
cd ~/Desktop/pulse-pipeline
python3.12 -m venv venv
source venv/bin/activate
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env with your values

# Run the server
python -m pulse_pipeline.server
```
