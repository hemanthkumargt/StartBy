import base64
import logging
import urllib.parse

from app.gcp import rest

logger = logging.getLogger(__name__)


def access_secret(project: str, name: str, *, version: str = "latest") -> str:
    url = (
        "https://secretmanager.googleapis.com/v1/projects/"
        f"{urllib.parse.quote(project)}/secrets/{urllib.parse.quote(name)}"
        f"/versions/{urllib.parse.quote(version)}:access"
    )
    payload = rest.request_json("GET", url)
    # strip: a secret made with `echo x | gcloud secrets create` carries a
    # trailing newline that would silently break an HMAC compare or a login.
    return base64.b64decode(payload["payload"]["data"]).decode("utf-8").strip()


# Without these the app must not start (a random SECRET_KEY per worker would
# log users out of one worker but not the other; no CRON_SECRET means the cron
# endpoints are unprotected or unusable). Everything else is a feature that
# degrades gracefully when absent.
REQUIRED_SECRETS = frozenset({"SECRET_KEY", "CRON_SECRET"})


def load_into_environ(environ, *, access=access_secret) -> list[str]:
    """Fill environment variables from Secret Manager before Config reads
    them. GCP_SECRETS is a comma-separated list of names; each is both the
    secret id and the variable it populates (SECRET_KEY, SMTP_PASSWORD, ...),
    and a Secret Manager value wins over a value left in .env.

    Required secrets (SECRET_KEY, CRON_SECRET) fail loudly. An optional one
    (SMTP_PASSWORD, GEMINI_API_KEY, GOOGLE_CLIENT_SECRET, ...) that does not
    exist or cannot be read is skipped with a warning: the feature it powers
    stays off, instead of a systemd crash loop for want of an optional key."""
    names = [n.strip() for n in environ.get("GCP_SECRETS", "").split(",") if n.strip()]
    if not names:
        return []
    project = environ.get("GCP_PROJECT", "")
    if not project:
        raise RuntimeError("GCP_SECRETS is set but GCP_PROJECT is not")
    loaded = []
    for name in names:
        try:
            environ[name] = access(project, name)
        except Exception as exc:  # noqa: BLE001 — re-raised or skipped below
            if name in REQUIRED_SECRETS:
                raise RuntimeError(
                    f"could not read required secret {name!r} from Secret Manager: {exc}"
                ) from exc
            logger.warning("optional_secret_skipped name=%s error=%s", name, exc)
            continue
        loaded.append(name)
    return loaded
