import base64
import json
import urllib.parse

from app.gcp import rest


def publish(
    project: str, topic: str, payload: dict, attributes: dict[str, str] | None = None
) -> None:
    """Publish one JSON message to a Pub/Sub topic."""
    url = (
        "https://pubsub.googleapis.com/v1/projects/"
        f"{urllib.parse.quote(project)}/topics/{urllib.parse.quote(topic)}:publish"
    )
    message = {"data": base64.b64encode(json.dumps(payload).encode()).decode()}
    if attributes:
        message["attributes"] = attributes
    rest.request_json("POST", url, body={"messages": [message]})
