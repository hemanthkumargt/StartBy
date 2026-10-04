"""One JSON-over-HTTPS helper for every Google Cloud REST call: timeout,
exactly one retry with backoff on transient failures (network, 429, 5xx),
and a single exception type so callers decide how to degrade."""

import json
import logging
import re
import time
import urllib.error
import urllib.request

from app.gcp import auth

logger = logging.getLogger(__name__)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Google's APIs do not redirect; if one ever does, refuse rather than let
    urllib re-send our Authorization header to wherever it points."""

    def redirect_request(self, *args, **kwargs):
        return None


urllib.request.install_opener(urllib.request.build_opener(_NoRedirect))

TIMEOUT_SECONDS = 10
RETRY_BACKOFF_SECONDS = 1.0
_TRANSIENT_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


_ERROR_CODE_MAX = 64
_ERROR_BODY_MAX = 8192


class GcpError(Exception):
    """`error` is the machine-readable code Google put in the error body
    (OAuth's "invalid_grant", an API's "rateLimitExceeded" / "PERMISSION_DENIED"),
    "" when there was none. It is sanitised and size-capped, never the free-text
    description, so it is safe to log and cannot carry a secret."""

    def __init__(self, message: str, status: int | None = None, error: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.error = _clean_code(error)


def _clean_code(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]", "", str(value))[:_ERROR_CODE_MAX]


def parse_error_code(body: bytes) -> str:
    """Pull the error code out of a Google error response body.

    OAuth endpoints answer {"error": "invalid_grant", ...}; REST APIs answer
    {"error": {"status": "...", "errors": [{"reason": "rateLimitExceeded"}]}}.
    Anything else (HTML, empty, garbage) yields ""."""
    try:
        data = json.loads(body[:_ERROR_BODY_MAX].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return ""
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, str):
        return _clean_code(error)
    if isinstance(error, dict):
        details = error.get("errors")
        if isinstance(details, list) and details and isinstance(details[0], dict):
            reason = details[0].get("reason")
            if reason:
                return _clean_code(reason)
        return _clean_code(error.get("status", ""))
    return ""


def request_json(
    method: str,
    url: str,
    *,
    body: dict | None = None,
    raw_body: bytes | None = None,
    content_type: str = "application/json",
    headers: dict[str, str] | None = None,
    use_auth: bool = True,
    bearer: str | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> dict:
    """Returns the decoded JSON response ({} for an empty body). `bearer`
    is an explicit access token (a user's, for Calendar); otherwise the VM's
    service-account token is used unless use_auth is False."""
    data = raw_body
    if data is None and body is not None:
        data = json.dumps(body).encode()
    last_error: GcpError | None = None
    for attempt in (1, 2):
        try:
            request_headers = {"Content-Type": content_type, **(headers or {})}
            if bearer:
                request_headers["Authorization"] = f"Bearer {bearer}"
            elif use_auth:
                request_headers["Authorization"] = f"Bearer {auth.get_access_token()}"
            request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                text = response.read().decode("utf-8")
            return json.loads(text) if text else {}
        except urllib.error.HTTPError as exc:
            try:
                code = parse_error_code(exc.read(_ERROR_BODY_MAX))
            except Exception:  # noqa: BLE001 — an unreadable body just means no code
                code = ""
            last_error = GcpError(f"{method} {_safe(url)} -> HTTP {exc.code}", exc.code, code)
            if exc.code == 401 and not bearer:
                # Our cached service-account token was rejected (revoked or
                # expired early): drop it so the retry fetches a fresh one.
                auth.reset_cache()
            elif exc.code not in _TRANSIENT_STATUSES:
                break
        except auth.GcpAuthError as exc:
            raise GcpError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — timeouts, DNS, TLS, bad JSON
            last_error = GcpError(f"{method} {_safe(url)} failed: {exc}")
        if attempt == 1:
            time.sleep(RETRY_BACKOFF_SECONDS)
    logger.error("gcp_request_failed error=%s", last_error)
    raise last_error  # type: ignore[misc]


def _safe(url: str) -> str:
    """Log the path, never a query string (API keys can ride in one)."""
    return url.split("?", 1)[0]
