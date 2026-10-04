import urllib.parse

from app.gcp import rest


def insert_rows(project: str, dataset: str, table: str, rows: list[dict], *, id_key: str) -> None:
    """Streaming insert. `id_key` names the field used as BigQuery's
    insertId, so a retried call de-duplicates instead of double-counting."""
    url = (
        "https://bigquery.googleapis.com/bigquery/v2/projects/"
        f"{urllib.parse.quote(project)}/datasets/{urllib.parse.quote(dataset)}"
        f"/tables/{urllib.parse.quote(table)}/insertAll"
    )
    body = {
        "skipInvalidRows": False,
        "rows": [{"insertId": str(row[id_key]), "json": row} for row in rows],
    }
    response = rest.request_json("POST", url, body=body)
    # insertAll answers 200 even when individual rows are rejected.
    if response.get("insertErrors"):
        raise rest.GcpError(f"BigQuery rejected rows: {response['insertErrors'][:1]}")
