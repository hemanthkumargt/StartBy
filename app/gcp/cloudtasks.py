import base64
import json
import urllib.parse

from app.gcp import rest


def create_http_task(
    project: str,
    location: str,
    queue: str,
    *,
    url: str,
    payload: dict,
    headers: dict[str, str],
    schedule_time_rfc3339: str | None = None,
) -> None:
    """Enqueue an HTTP POST to `url`, optionally delayed until a time. Cloud
    Tasks retries it with backoff until the endpoint answers 2xx."""
    endpoint = (
        "https://cloudtasks.googleapis.com/v2/projects/"
        f"{urllib.parse.quote(project)}/locations/{urllib.parse.quote(location)}"
        f"/queues/{urllib.parse.quote(queue)}/tasks"
    )
    task = {
        "httpRequest": {
            "url": url,
            "httpMethod": "POST",
            "headers": {"Content-Type": "application/json", **headers},
            "body": base64.b64encode(json.dumps(payload).encode()).decode(),
        }
    }
    if schedule_time_rfc3339:
        task["scheduleTime"] = schedule_time_rfc3339
    rest.request_json("POST", endpoint, body={"task": task})
