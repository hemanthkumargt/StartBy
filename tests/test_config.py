from app.config import Config


def test_secret_key_has_no_fixed_fallback():
    """Regression guard: a hardcoded default SECRET_KEY would be a known
    value checked into this public repo, letting anyone forge a Flask-Login
    session cookie if .env ever fails to load in production. Two Configs
    built with no SECRET_KEY in the environment must get different random
    keys, not the same hardcoded string."""
    first = Config(env={})
    second = Config(env={})

    assert first.SECRET_KEY != second.SECRET_KEY
    assert first.SECRET_KEY != "dev-secret-key-change-me"
    assert len(first.SECRET_KEY) >= 32


def test_secret_key_respects_env_value():
    config = Config(env={"SECRET_KEY": "explicit-value"})
    assert config.SECRET_KEY == "explicit-value"


def test_production_refuses_placeholder_or_missing_secrets():
    import pytest

    from app.config import Config

    good = {"FLASK_ENV": "production", "SECRET_KEY": "k" * 40, "CRON_SECRET": "c" * 40}
    Config(env=good).validate_for_production()  # fine
    for override in (
        {"SECRET_KEY": ""},
        {"SECRET_KEY": "change-me-to-a-random-value"},
        {"CRON_SECRET": "change-me"},
        {"CRON_SECRET": ""},
        {"CRON_SECRET": "short"},
    ):
        with pytest.raises(RuntimeError, match="Refusing to start"):
            Config(env={**good, **override}).validate_for_production()


def test_development_allows_placeholder_secrets():
    from app.config import Config

    Config(env={"FLASK_ENV": "development", "CRON_SECRET": "change-me"}).validate_for_production()


def test_create_app_raises_in_production_with_placeholders():
    import pytest

    from app import create_app
    from app.config import Config

    with pytest.raises(RuntimeError):
        create_app(Config(env={"FLASK_ENV": "production", "CRON_SECRET": "change-me"}))


def test_location_defaults_match_the_region_provision_sh_creates_resources_in():
    """The Cloud Tasks queue is created in provision.sh's REGION; a different
    app default made every enqueue 404 until CLOUD_TASKS_LOCATION was set."""
    import re
    from pathlib import Path

    script = (Path(__file__).parent.parent / "deploy" / "gcp" / "provision.sh").read_text()
    region = re.search(r'^REGION="\$\{REGION:-([a-z0-9-]+)\}"', script, re.M).group(1)
    config = Config(env={})
    assert config.CLOUD_TASKS_LOCATION == region
    assert config.GCP_LOCATION == region
