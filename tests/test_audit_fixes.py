"""Regression tests for the audit findings fixed on 2026-10-04 (flags-off
equivalence, headers and limits, and the smaller hardening items)."""

import json

from tests.conftest import register

# ---- flags-off equivalence (I15) -------------------------------------------


def test_I15_flag_off_patch_me_ignores_and_hides_assistant_name(client):
    register(client)
    res = client.patch("/api/me", json={"assistant_name": "Jarvis", "dark_mode": True})
    assert res.status_code == 200
    body = res.get_json()
    assert "assistant_name" not in body and body["dark_mode"] is True
    # nothing was stored: turning voice on later shows no leftover custom name
    client.application.config["FEATURE_VOICE"] = True
    assert client.patch("/api/me", json={}).get_json()["assistant_name"] is None


def test_I15_flag_off_auth_responses_have_no_assistant_name(client):
    res = register(client)
    assert "assistant_name" not in res.get_json()
    login = client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": "password123"}
    )
    assert "assistant_name" not in login.get_json()


def test_voice_on_patch_me_still_saves_the_assistant_name(client):
    client.application.config["FEATURE_VOICE"] = True
    register(client)
    res = client.patch("/api/me", json={"assistant_name": "Jarvis"})
    assert res.get_json()["assistant_name"] == "Jarvis"


def _shortcut_urls(client):
    res = client.get("/manifest.webmanifest")
    assert res.status_code == 200 and res.mimetype == "application/manifest+json"
    return [s["url"] for s in json.loads(res.data)["shortcuts"]]


def test_I15_manifest_capture_shortcut_only_when_smart_capture_is_on(client):
    assert _shortcut_urls(client) == ["/tasks?new=1"]
    client.application.config["FEATURE_SMART_CAPTURE"] = True
    assert _shortcut_urls(client) == ["/tasks?new=1", "/capture"]


def test_I15_signed_out_flag_off_pages_are_404_not_a_login_redirect(client):
    for path in ("/insights", "/capture"):
        assert client.get(path).status_code == 404
    register(client)
    for path in ("/insights", "/capture"):
        assert client.get(path).status_code == 404  # same as signed in


def test_flag_on_pages_still_require_login(client):
    client.application.config["FEATURE_INSIGHTS"] = True
    client.application.config["FEATURE_SMART_CAPTURE"] = True
    for path in ("/insights", "/capture"):
        res = client.get(path)
        assert res.status_code == 302 and "/login" in res.location


# ---- headers and limits ----------------------------------------------------


def test_pages_and_api_are_no_store_but_static_and_manifest_are_not(client):
    for path in ("/login", "/api/tasks", "/healthz", "/nope"):
        assert client.get(path).headers["Cache-Control"] == "no-store", path
    for path in ("/static/css/app.css", "/manifest.webmanifest", "/sw.js"):
        res = client.get(path)
        assert res.headers.get("Cache-Control") != "no-store", path


def test_activity_limit_is_clamped(client):
    register(client)
    for i in range(3):
        client.post("/api/tasks", json={"title": f"t{i}"})
    assert len(client.get("/api/activity?limit=2").get_json()) == 2
    assert len(client.get("/api/activity?limit=0").get_json()) == 1
    # SQLite treats LIMIT -1 as "everything": it must be clamped to 1
    assert len(client.get("/api/activity?limit=-1").get_json()) == 1
    assert len(client.get("/api/activity?limit=999999").get_json()) == 3
    assert len(client.get("/api/activity").get_json()) == 3


def test_task_creation_is_rate_limited_per_user(client):
    register(client)
    codes = [client.post("/api/tasks", json={"title": "t"}).status_code for _ in range(122)]
    assert codes[:120] == [201] * 120 and codes[120:] == [429, 429]
    body = client.post("/api/tasks", json={"title": "t"}).get_json()
    assert body["error"]["code"] == "rate_limited"
    # another user is unaffected
    other = client.application.test_client()
    register(other, name="Bo", email="bo@example.com")
    assert other.post("/api/tasks", json={"title": "t"}).status_code == 201


def test_voice_ask_is_rate_limited_per_user(client):
    client.application.config["FEATURE_VOICE"] = True
    register(client)
    codes = [
        client.post("/api/voice/ask", json={"text": "what is next"}).status_code for _ in range(32)
    ]
    assert 429 not in codes[:30] and codes[30:] == [429, 429]
    assert (
        client.post("/api/voice/ask", json={"text": "x"}).get_json()["error"]["code"]
        == "rate_limited"
    )


# ---- the assistant's name is spoken -----------------------------------------


def _voice_user(client, name="Ada Lovelace"):
    client.application.config["FEATURE_VOICE"] = True
    register(client, name=name)


def test_briefing_greeting_introduces_the_assistant_by_name(client):
    _voice_user(client)
    script = client.get("/api/voice/briefing").get_json()["script"]
    assert script.startswith("Good ") and ", Ada. SARA here." in script
    client.patch("/api/me", json={"assistant_name": "Jarvis"})
    assert ", Ada. Jarvis here." in client.get("/api/voice/briefing").get_json()["script"]


def test_a_leading_wake_name_is_stripped_before_classifying(client):
    from app.services import assistant_service

    strip = assistant_service.strip_wake_name
    assert strip("Jarvis, what's due today", "Jarvis") == "what's due today"
    assert strip("jarvis: what's due today", "Jarvis") == "what's due today"
    assert strip("hey Jarvis what is next", "Jarvis") == "what is next"
    assert strip("what would Jarvis do", "Jarvis") == "what would Jarvis do"  # not leading
    assert strip("Jarvisfoo is odd", "Jarvis") == "Jarvisfoo is odd"
    assert strip("Dr. Who, help", "Dr. Who") == "help"  # regex metacharacters in a name

    _voice_user(client)
    client.patch("/api/me", json={"assistant_name": "Jarvis"})
    plain = client.post("/api/voice/ask", json={"text": "what is due today"}).get_json()
    named = client.post("/api/voice/ask", json={"text": "Jarvis, what is due today"}).get_json()
    assert plain["intent"] == named["intent"] == "due"
    # the name itself, alone, is not a question
    assert client.post("/api/voice/ask", json={"text": "Jarvis"}).get_json()["intent"] == "empty"
    # an add command keeps only the task text for capture
    add = client.post("/api/voice/ask", json={"text": "Jarvis, add call mom"}).get_json()
    assert add["action"]["text"] == "add call mom"


def test_ask_loads_the_pending_list_once(client, monkeypatch):
    from app.services import task_service

    _voice_user(client)
    calls = []
    real = task_service.list_tasks

    def counting(*args, **kwargs):
        calls.append(kwargs.get("status"))
        return real(*args, **kwargs)

    monkeypatch.setattr(task_service, "list_tasks", counting)
    client.post("/api/voice/ask", json={"text": "what should I do now"})
    assert calls == ["pending"]


def test_speech_helpers_are_public_and_not_duplicated():
    from app.services import assistant_service, briefing_service, insights_service

    assert callable(briefing_service.say_time) and callable(briefing_service.spoken)
    assert callable(insights_service.is_abandoned) and callable(insights_service.plural)
    for module in (briefing_service, assistant_service, insights_service):
        assert not hasattr(module, "_plural") and not hasattr(module, "_is_abandoned")
    assert not hasattr(briefing_service, "_say_time") and not hasattr(briefing_service, "_spoken")


# ---- Gemini client ----------------------------------------------------------


def _gemini_cfg(**over):
    base = {
        "GEMINI_BACKEND": "ai_studio",
        "GEMINI_MODEL": "gemini-flash-latest",
        "GEMINI_API_KEY": "KEY",
        "GCP_PROJECT": "proj",
        "GCP_LOCATION": "us-central1",
    }
    base.update(over)
    return base


def test_all_text_parts_of_a_response_are_concatenated(monkeypatch):
    from app.gcp import rest
    from app.services import gemini_client

    half = json.dumps({"tasks": [{"title": "A", "tag": "work"}]})
    parts = [{"text": half[:10]}, {"text": "hidden thought", "thought": True}, {"text": half[10:]}]
    monkeypatch.setattr(
        rest, "request_json", lambda *a, **k: {"candidates": [{"content": {"parts": parts}}]}
    )
    out = gemini_client.generate_task_drafts(
        "hi", now_local_iso="x", tz_name="UTC", config=_gemini_cfg()
    )
    assert out == [{"title": "A", "tag": "work"}]
    spoken = [{"text": "submit the "}, {"text": "lab record"}]
    monkeypatch.setattr(
        rest, "request_json", lambda *a, **k: {"candidates": [{"content": {"parts": spoken}}]}
    )
    assert gemini_client.transcribe_audio(b"x", "audio/wav", config=_gemini_cfg()) == (
        "submit the lab record"
    )


def test_gemini_calls_use_a_longer_timeout_but_other_calls_keep_the_default(monkeypatch):
    from app.gcp import rest
    from app.services import gemini_client

    seen = []

    def fake(method, url, **kw):
        seen.append(kw.get("timeout"))
        return {"candidates": [{"content": {"parts": [{"text": '{"tasks": []}'}]}}]}

    monkeypatch.setattr(rest, "request_json", fake)
    gemini_client.generate_task_drafts("hi", now_local_iso="x", tz_name="UTC", config=_gemini_cfg())
    gemini_client.transcribe_audio(b"x", "audio/wav", config=_gemini_cfg())
    assert seen == [30, 30]
    assert rest.TIMEOUT_SECONDS == 10


def test_vertex_pins_a_concrete_model_when_the_latest_alias_or_nothing_is_set():
    from app.services import gemini_client

    vertex = {"GEMINI_BACKEND": "vertex"}
    for model in ("gemini-flash-latest", "", "gemini-pro-latest"):
        url, _, _ = gemini_client._endpoint(_gemini_cfg(GEMINI_MODEL=model, **vertex))
        assert "/models/gemini-2.5-flash:generateContent" in url, model
    url, _, _ = gemini_client._endpoint(_gemini_cfg(GEMINI_MODEL="gemini-2.0-flash", **vertex))
    assert "/models/gemini-2.0-flash:" in url  # an explicit choice is respected
    url, _, _ = gemini_client._endpoint(_gemini_cfg())  # AI Studio keeps the alias
    assert "/models/gemini-flash-latest:" in url


# ---- login demo pill ----------------------------------------------------------


def _login_html(**env):
    import tempfile

    from tests.test_gcp import make_app

    with tempfile.TemporaryDirectory() as tmp:
        return make_app(tmp, **env).test_client().get("/login").get_data(as_text=True)


def test_demo_pill_is_on_by_default_in_development():
    assert 'id="demo-fill-btn"' in _login_html()


def test_demo_pill_is_off_by_default_in_production_and_overridable():
    prod = {"FLASK_ENV": "production", "SECRET_KEY": "k" * 40, "CRON_SECRET": "c" * 40}
    html = _login_html(**prod)
    assert "demo-fill-btn" not in html and "change-me" not in html
    assert 'id="demo-fill-btn"' in _login_html(DEMO_LOGIN_HINT="1", **prod)
    assert "demo-fill-btn" not in _login_html(DEMO_LOGIN_HINT="0")


def test_demo_login_hint_config_defaults():
    from app.config import Config

    assert Config(env={}).DEMO_LOGIN_HINT is True
    assert Config(env={"FLASK_ENV": "production"}).DEMO_LOGIN_HINT is False
    assert Config(env={"FLASK_ENV": "production", "DEMO_LOGIN_HINT": "true"}).DEMO_LOGIN_HINT
