"""OAuth2 access tokens for Google Cloud REST calls.

On the Compute Engine VM the token comes from the metadata server (the VM's
service account — no key file to leak). For local development set
GCP_ACCESS_TOKEN (e.g. from `gcloud auth print-access-token`)."""

import json
import os
import threading
import time
import urllib.request

_METADATA_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
)
_REFRESH_MARGIN_SECONDS = 60

_lock = threading.Lock()
_cached: dict[str, object] = {"token": None, "expires_at": 0.0}


class GcpAuthError(Exception):
    pass


def get_access_token(*, timeout: float = 2.0) -> str:
    override = os.environ.get("GCP_ACCESS_TOKEN", "")
    if override:
        return override
    with _lock:
        still_valid_until = float(_cached["expires_at"]) - _REFRESH_MARGIN_SECONDS
        if _cached["token"] and time.time() < still_valid_until:
            return str(_cached["token"])
        request = urllib.request.Request(_METADATA_URL, headers={"Metadata-Flavor": "Google"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
            token = payload["access_token"]
            expires_in = float(payload.get("expires_in", 300))
        except Exception as exc:  # noqa: BLE001 — any failure means "no credentials here"
            raise GcpAuthError(f"no Google Cloud credentials available: {exc}") from exc
        _cached["token"] = token
        _cached["expires_at"] = time.time() + expires_in
        return token


def reset_cache() -> None:
    with _lock:
        _cached["token"] = None
        _cached["expires_at"] = 0.0
