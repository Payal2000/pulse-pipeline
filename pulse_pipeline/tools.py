"""Custom tools that extend the Fivetran MCP capabilities."""

from __future__ import annotations

import json
import logging

from google.cloud import bigquery

from .config import settings

logger = logging.getLogger(__name__)


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
        "rows": rows[:200],  # cap to avoid token explosion
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
