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
