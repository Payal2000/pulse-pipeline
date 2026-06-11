"""Custom tools that extend the Fivetran MCP capabilities."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import bigquery

from .config import settings

logger = logging.getLogger(__name__)

# In-memory incident log (persists for the server's lifetime)
_incident_log: list[dict] = []


def query_destination(sql: str) -> dict:
    """Execute a read-only SQL query against the BigQuery destination warehouse.

    Use this tool after a Fivetran sync completes to analyze the data that was
    loaded.  Always prefer this over asking the user to check BigQuery manually.

    Args:
        sql: A BigQuery-compatible SQL query.  Use the dataset
             configured for Fivetran (available in the connection details).

    Returns:
        A dict with ``columns``, ``rows`` (list of lists), and ``total_rows``.
    """
    client = bigquery.Client(project=settings.gcp_project)
    job = client.query(sql)
    result = job.result()

    columns = [field.name for field in result.schema]
    rows = [list(row.values()) for row in result]

    return {
        "columns": columns,
        "rows": rows[:200],
        "total_rows": result.total_rows,
        "truncated": result.total_rows > 200,
    }


def format_analysis(title: str, summary: str, data_points: list[dict]) -> dict:
    """Format an analysis result for the user with a title, summary, and key data points.

    Use this after running query_destination to present findings clearly.

    Args:
        title: A short title for the analysis (e.g. "Weekend Sales Trends").
        summary: A 2-3 sentence executive summary of the findings.
        data_points: A list of dicts, each with 'label' and 'value' keys,
                     representing the key metrics or findings.

    Returns:
        A formatted analysis dict ready to be displayed to the user.
    """
    return {
        "title": title,
        "summary": summary,
        "data_points": data_points,
        "type": "analysis",
    }


def get_destination_schema(dataset: str | None = None) -> dict:
    """List all tables and their columns in the BigQuery destination dataset.

    Use this to understand what data is available after a Fivetran sync.

    Args:
        dataset: BigQuery dataset ID. Defaults to the configured dataset.

    Returns:
        A dict mapping table names to their column definitions.
    """
    ds = dataset or settings.bigquery_dataset
    client = bigquery.Client(project=settings.gcp_project)

    tables = {}
    for table_ref in client.list_tables(ds):
        table = client.get_table(table_ref)
        tables[table.table_id] = [
            {"name": f.name, "type": f.field_type, "mode": f.mode}
            for f in table.schema
        ]

    return {"dataset": ds, "tables": tables}


def verify_post_heal(connection_id: str, expected_tables: list[str]) -> dict:
    """Run post-repair sanity checks against BigQuery to verify data integrity.

    Call this AFTER every successful repair to confirm the fix actually worked
    at the data level — not just the connection level.  "Fixed AND verified."

    Args:
        connection_id: The Fivetran connection ID that was repaired.
        expected_tables: List of table names to check in BigQuery.

    Returns:
        A verification report with row counts, null rates, and freshness
        for each table.
    """
    ds = settings.bigquery_dataset
    client = bigquery.Client(project=settings.gcp_project)
    report = {"connection_id": connection_id, "tables": {}, "healthy": True}

    for table_name in expected_tables:
        table_id = f"{settings.gcp_project}.{ds}.{table_name}"
        try:
            table = client.get_table(table_id)
            row_count = table.num_rows
            modified = table.modified.isoformat() if table.modified else "unknown"

            # Check null rates on first 3 columns
            if table.schema:
                check_cols = [f.name for f in table.schema[:3]]
                null_sql = ", ".join(
                    f"ROUND(COUNTIF({c} IS NULL) / COUNT(*) * 100, 1) AS {c}_null_pct"
                    for c in check_cols
                )
                sql = f"SELECT {null_sql} FROM `{table_id}`"
                null_result = list(client.query(sql).result())
                null_rates = dict(null_result[0].items()) if null_result else {}
            else:
                null_rates = {}

            table_report = {
                "row_count": row_count,
                "last_modified": modified,
                "null_rates": null_rates,
                "status": "healthy",
            }

            # Flag if table is empty or has >50% nulls in any column
            if row_count == 0:
                table_report["status"] = "warning_empty"
                report["healthy"] = False
            elif any(v > 50 for v in null_rates.values()):
                table_report["status"] = "warning_high_nulls"
                report["healthy"] = False

            report["tables"][table_name] = table_report

        except Exception as e:
            report["tables"][table_name] = {
                "status": "error",
                "error": str(e),
            }
            report["healthy"] = False

    return report


def record_incident(
    connection_id: str,
    failure_type: str,
    remediation_tier: str,
    actions_taken: list[str],
    outcome: str,
    time_to_recovery_seconds: int | None = None,
) -> dict:
    """Record a pipeline incident for the audit trail.

    Call this after every repair attempt (successful or not) to build a
    complete incident history.

    Args:
        connection_id: The Fivetran connection ID.
        failure_type: What failed (e.g. "credential_expiry", "sync_failure",
                      "config_error", "blocked_schema_policy").
        remediation_tier: Which tier was used ("tier_1_autonomous",
                         "tier_2_judgment", "tier_3_escalation").
        actions_taken: List of actions the agent performed.
        outcome: Result ("resolved", "escalated", "partial").
        time_to_recovery_seconds: Seconds from detection to resolution,
                                  if resolved.

    Returns:
        The recorded incident with an ID and timestamp.
    """
    incident = {
        "id": f"INC-{len(_incident_log) + 1:04d}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connection_id": connection_id,
        "failure_type": failure_type,
        "remediation_tier": remediation_tier,
        "actions_taken": actions_taken,
        "outcome": outcome,
        "time_to_recovery_seconds": time_to_recovery_seconds,
    }
    _incident_log.append(incident)
    logger.info("Incident recorded: %s", json.dumps(incident, default=str))
    return incident


def get_incident_log() -> list[dict]:
    """Return the full incident audit log (used by the server, not the agent)."""
    return list(_incident_log)
