import urllib.parse
from datetime import datetime, timezone

from app.gcp import rest


def write_int_metric(project: str, metric_name: str, value: int, labels: dict[str, str]) -> None:
    """Write one point of a custom gauge metric
    (custom.googleapis.com/startby/<metric_name>) for Cloud Monitoring
    dashboards and alert policies."""
    url = f"https://monitoring.googleapis.com/v3/projects/{urllib.parse.quote(project)}/timeSeries"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "timeSeries": [
            {
                "metric": {
                    "type": f"custom.googleapis.com/startby/{metric_name}",
                    "labels": labels,
                },
                "resource": {"type": "global", "labels": {"project_id": project}},
                "points": [{"interval": {"endTime": now}, "value": {"int64Value": str(value)}}],
            }
        ]
    }
    rest.request_json("POST", url, body=body)
