import urllib.parse

from app.gcp import rest


def upload_object(bucket: str, name: str, data: bytes, *, content_type: str) -> None:
    """Simple media upload (<= a few MB; larger needs the resumable API,
    which neither a 5 MB PDF nor a small SQLite backup requires)."""
    url = (
        f"https://storage.googleapis.com/upload/storage/v1/b/{urllib.parse.quote(bucket)}/o"
        f"?uploadType=media&name={urllib.parse.quote(name, safe='')}"
    )
    rest.request_json("POST", url, raw_body=data, content_type=content_type)
