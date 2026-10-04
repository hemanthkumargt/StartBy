import io
import json

import pytest
from freezegun import freeze_time

from app.gcp import rest
from app.services import capture_service, fallback_extractor, gemini_client
from tests.conftest import register

NOW = "2026-10-04T06:00:00"  # Sunday 11:30 in Asia/Kolkata


@pytest.fixture
def capture_client(app):
    app.config["FEATURE_SMART_CAPTURE"] = True
    app.config["FEATURE_ESTIMATES"] = True
    capture_service.rate_limiter.reset()
    client = app.test_client()
    register(client)
    return client


def _gemini_returns(monkeypatch, tasks):
    monkeypatch.setattr(gemini_client, "generate_task_drafts", lambda text, **kw: tasks)


def _gemini_down(monkeypatch):
    def boom(text, **kw):
        raise gemini_client.GeminiUnavailable("quota")

    monkeypatch.setattr(gemini_client, "generate_task_drafts", boom)


def _task_count(client):
    return len(client.get("/api/tasks").get_json())


def _minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


# ---- flag + auth ---------------------------------------------------------


def test_I15_flag_off_capture_routes_do_not_exist(client):
    register(client)
    assert client.post("/api/capture/preview", json={"text": "x"}).status_code == 404
    assert client.post("/api/capture/confirm", json={"tasks": []}).status_code == 404


def test_capture_requires_login(app):
    app.config["FEATURE_SMART_CAPTURE"] = True
    anon = app.test_client()
    assert anon.post("/api/capture/preview", json={"text": "x"}).status_code == 401
    assert anon.post("/api/capture/confirm", json={"tasks": []}).status_code == 401


# ---- preview -------------------------------------------------------------


@freeze_time(NOW)
def test_I14_preview_returns_drafts_and_writes_nothing(capture_client, monkeypatch):
    _gemini_returns(
        monkeypatch,
        [{"title": "Submit lab record", "tag": "study", "due_at": "2026-10-09T17:00:00"}],
    )
    response = capture_client.post("/api/capture/preview", json={"text": "syllabus text"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["source"] == "gemini"
    # 17:00 local (IST) -> 11:30 UTC, the stored/serialised form.
    assert body["tasks"] == [
        {
            "title": "Submit lab record",
            "tag": "study",
            "due_at": "2026-10-09T11:30:00",
            "estimate_hours": None,
            "notes": None,
        }
    ]
    assert _task_count(capture_client) == 0


@freeze_time(NOW)
def test_gemini_unavailable_falls_back_to_regex_extractor(capture_client, monkeypatch):
    _gemini_down(monkeypatch)
    text = "Tasks:\n- Submit DBMS assignment by Friday 5pm\n- Buy groceries\n"
    body = capture_client.post("/api/capture/preview", json={"text": text}).get_json()
    assert body["source"] == "fallback"
    assert body["fallback_reason"] == "ai_unavailable"
    titles = [t["title"] for t in body["tasks"]]
    assert titles == ["Submit DBMS assignment", "Buy groceries"]
    assert body["tasks"][0]["due_at"] == "2026-10-09T11:30:00"
    assert body["tasks"][0]["tag"] == "study"
    assert body["tasks"][1]["due_at"] is None
    assert _task_count(capture_client) == 0


def test_missing_api_key_uses_fallback_without_calling_network(capture_client, monkeypatch):
    def no_network(*a, **kw):  # pragma: no cover - must not run
        raise AssertionError("network call attempted with no API key")

    monkeypatch.setattr(rest, "request_json", no_network)
    body = capture_client.post(
        "/api/capture/preview", json={"text": "Email the professor"}
    ).get_json()
    assert body["source"] == "fallback"
    assert body["tasks"][0]["title"] == "Email the professor"


@freeze_time(NOW)
def test_model_output_is_treated_as_untrusted(capture_client, monkeypatch):
    _gemini_returns(
        monkeypatch,
        [
            {"title": "A" * 500, "tag": "work"},
            {"title": "  Pay\x00 fee\n now ", "tag": "hacker", "due_at": "not-a-date"},
            {"title": 123, "tag": "work"},
            {"title": "", "tag": "work"},
            {"title": "Big", "tag": "study", "estimate_hours": 9999},
            {"title": "Ok est", "tag": "study", "estimate_hours": 2.5, "notes": "n" * 900},
            {"title": "pay fee now", "tag": "personal", "due_at": "also-bad"},  # dup of #2
            {"title": "Flag", "tag": "work", "estimate_hours": True},
        ],
    )
    tasks = capture_client.post("/api/capture/preview", json={"text": "x"}).get_json()["tasks"]
    by_title = {t["title"]: t for t in tasks}
    assert len(tasks) == 5  # 123/""/dup dropped
    assert len(next(iter(by_title))) == 200 and next(iter(by_title)).endswith("…")
    pay = by_title["Pay fee now"]
    assert pay["tag"] == "personal" and pay["due_at"] is None
    assert by_title["Big"]["estimate_hours"] is None
    assert by_title["Ok est"]["estimate_hours"] == 2.5
    assert len(by_title["Ok est"]["notes"]) == 500
    assert by_title["Flag"]["estimate_hours"] is None


def test_estimates_dropped_when_estimates_flag_off(app, capture_client, monkeypatch):
    app.config["FEATURE_ESTIMATES"] = False
    _gemini_returns(monkeypatch, [{"title": "T", "tag": "work", "estimate_hours": 2}])
    task = capture_client.post("/api/capture/preview", json={"text": "x"}).get_json()["tasks"][0]
    assert task["estimate_hours"] is None


def test_preview_caps_number_of_drafts(capture_client, monkeypatch):
    _gemini_returns(monkeypatch, [{"title": f"Task {i}", "tag": "work"} for i in range(60)])
    tasks = capture_client.post("/api/capture/preview", json={"text": "x"}).get_json()["tasks"]
    assert len(tasks) == 25


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"text": ""}, 422),
        ({"text": "   "}, 422),
        ({"text": 5}, 422),
        ({"text": ["a"]}, 422),
        ({}, 422),
        ({"text": "x" * 20_001}, 422),
    ],
)
def test_preview_rejects_bad_text(capture_client, payload, status):
    assert capture_client.post("/api/capture/preview", json=payload).status_code == status


def test_preview_rejects_non_json_body(capture_client):
    response = capture_client.post(
        "/api/capture/preview", data="text=hi", content_type="application/x-www-form-urlencoded"
    )
    assert response.status_code == 422


def test_preview_is_rate_limited_per_user(app, capture_client, monkeypatch):
    _gemini_returns(monkeypatch, [])
    for _ in range(10):
        assert capture_client.post("/api/capture/preview", json={"text": "x"}).status_code == 200
    blocked = capture_client.post("/api/capture/preview", json={"text": "x"})
    assert blocked.status_code == 429
    assert blocked.get_json()["error"]["code"] == "rate_limited"
    other = app.test_client()
    register(other, name="Bo", email="bo@example.com")
    assert other.post("/api/capture/preview", json={"text": "x"}).status_code == 200


# ---- PDF -----------------------------------------------------------------


def _upload(client, data, name="syllabus.pdf"):
    return client.post(
        "/api/capture/preview",
        data={"file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def test_pdf_text_feeds_the_extractor(capture_client, monkeypatch):
    seen = {}

    def fake(text, **kw):
        seen["text"] = text
        return [{"title": "From pdf", "tag": "study"}]

    monkeypatch.setattr(gemini_client, "generate_task_drafts", fake)
    response = _upload(capture_client, _minimal_pdf("Submit report"))
    assert response.status_code == 200
    assert "Submit report" in seen["text"]


def test_non_pdf_upload_rejected(capture_client):
    assert _upload(capture_client, b"MZ not a pdf").status_code == 422


def test_oversize_pdf_rejected(capture_client):
    assert _upload(capture_client, b"%PDF-" + b"0" * (5 * 1024 * 1024 + 10)).status_code == 413


def test_pdf_with_no_text_rejected(capture_client):
    from pypdf import PdfWriter

    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buffer)
    response = _upload(capture_client, buffer.getvalue())
    assert response.status_code == 422
    assert "No selectable text" in response.get_json()["error"]["message"]


def test_corrupt_pdf_rejected_not_500(capture_client):
    assert _upload(capture_client, b"%PDF-1.4\ngarbage garbage").status_code == 422


# ---- confirm -------------------------------------------------------------


def test_confirm_saves_only_the_rows_sent(capture_client):
    response = capture_client.post(
        "/api/capture/confirm",
        json={
            "tasks": [
                {
                    "title": "Keep me",
                    "tag": "work",
                    "due_at": "2026-10-09T11:30:00",
                    "estimate_hours": 2,
                },
            ]
        },
    )
    assert response.status_code == 201
    created = response.get_json()["created"]
    assert [t["title"] for t in created] == ["Keep me"]
    assert created[0]["estimate_hours"] == 2.0
    assert _task_count(capture_client) == 1
    activity = capture_client.get("/api/activity").get_json()
    assert [e["action"] for e in activity] == ["created"]


def test_confirm_is_all_or_nothing_on_a_bad_row(capture_client):
    response = capture_client.post(
        "/api/capture/confirm",
        json={"tasks": [{"title": "Fine", "tag": "work"}, {"title": "Bad", "tag": "nope"}]},
    )
    assert response.status_code == 422
    assert response.get_json()["error"]["message"].startswith("Task 2:")
    assert _task_count(capture_client) == 0


@pytest.mark.parametrize(
    "tasks",
    [None, [], "x", {"title": "a"}, ["str"], [{"title": "t"}] * 26],
)
def test_confirm_rejects_malformed_payloads(capture_client, tasks):
    assert capture_client.post("/api/capture/confirm", json={"tasks": tasks}).status_code == 422
    assert _task_count(capture_client) == 0


def test_confirm_revalidates_client_supplied_values(capture_client):
    bad = {"title": "x" * 201, "tag": "work"}
    assert capture_client.post("/api/capture/confirm", json={"tasks": [bad]}).status_code == 422
    est = {"title": "t", "tag": "work", "estimate_hours": 500}
    assert capture_client.post("/api/capture/confirm", json={"tasks": [est]}).status_code == 422


def test_confirmed_tasks_belong_to_the_caller_only(app, capture_client):
    capture_client.post("/api/capture/confirm", json={"tasks": [{"title": "Mine", "tag": "work"}]})
    other = app.test_client()
    register(other, name="Bo", email="bo@example.com")
    assert other.get("/api/tasks").get_json() == []


# ---- gemini client -------------------------------------------------------


class _Cfg(dict):
    pass


def _cfg(**over):
    base = {
        "GEMINI_BACKEND": "ai_studio",
        "GEMINI_MODEL": "gemini-test",
        "GEMINI_API_KEY": "KEY123",
        "GCP_PROJECT": "",
        "GCP_LOCATION": "us-central1",
    }
    base.update(over)
    return _Cfg(base)


def _ok_payload(tasks):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps({"tasks": tasks})}]}}]}


def test_ai_studio_call_sends_key_in_header_not_url(monkeypatch):
    calls = {}

    def fake(method, url, **kw):
        calls.update(method=method, url=url, **kw)
        return _ok_payload([{"title": "T", "tag": "work"}])

    monkeypatch.setattr(rest, "request_json", fake)
    out = gemini_client.generate_task_drafts("hi", now_local_iso="x", tz_name="UTC", config=_cfg())
    assert out == [{"title": "T", "tag": "work"}]
    assert "KEY123" not in calls["url"]
    assert calls["headers"] == {"x-goog-api-key": "KEY123"}
    assert calls["use_auth"] is False
    assert "<document>\nhi\n</document>" in calls["body"]["contents"][0]["parts"][0]["text"]


def test_vertex_call_uses_service_account_and_regional_host(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        rest, "request_json", lambda m, u, **kw: calls.update(url=u, **kw) or _ok_payload([])
    )
    gemini_client.generate_task_drafts(
        "hi",
        now_local_iso="x",
        tz_name="UTC",
        config=_cfg(GEMINI_BACKEND="vertex", GCP_PROJECT="my-proj", GEMINI_API_KEY=""),
    )
    assert calls["url"].startswith(
        "https://us-central1-aiplatform.googleapis.com/v1/projects/my-proj/"
    )
    assert calls["use_auth"] is True


def test_vertex_without_project_is_unavailable():
    with pytest.raises(gemini_client.GeminiUnavailable):
        gemini_client.generate_task_drafts(
            "hi", now_local_iso="x", tz_name="UTC", config=_cfg(GEMINI_BACKEND="vertex")
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"candidates": []},
        {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]},
        {"candidates": [{"content": {"parts": [{"text": '{"tasks": "no"}'}]}}]},
    ],
)
def test_malformed_gemini_output_raises_unavailable(monkeypatch, payload):
    monkeypatch.setattr(rest, "request_json", lambda *a, **kw: payload)
    with pytest.raises(gemini_client.GeminiUnavailable):
        gemini_client.generate_task_drafts("hi", now_local_iso="x", tz_name="UTC", config=_cfg())


def test_http_error_becomes_unavailable(monkeypatch):
    def boom(*a, **kw):
        raise rest.GcpError("HTTP 429", 429)

    monkeypatch.setattr(rest, "request_json", boom)
    with pytest.raises(gemini_client.GeminiUnavailable):
        gemini_client.generate_task_drafts("hi", now_local_iso="x", tz_name="UTC", config=_cfg())


# ---- fallback extractor --------------------------------------------------


def _extract(text):
    from datetime import datetime

    return fallback_extractor.extract_drafts(
        text, now_local=datetime(2026, 10, 4, 11, 30), tz_name="Asia/Kolkata"
    )


def test_fallback_does_not_invent_dates_from_ordinary_words():
    drafts = _extract("I may call mom\nWait a second for the bus")
    assert [d["due_at"] for d in drafts] == [None, None]


def test_fallback_parses_estimates_and_bullets():
    drafts = _extract("1. Write essay (3 hours)\n* Review notes 30 min")
    assert [(d["title"], d["estimate_hours"]) for d in drafts] == [
        ("Write essay", 3.0),
        ("Review notes", 0.5),
    ]


def test_fallback_end_of_day_when_no_time_given():
    (draft,) = _extract("Submit form tomorrow")
    assert draft["due_at"] == "2026-10-05T23:59:00"
    assert draft["title"] == "Submit form"


def test_fallback_skips_headings_blank_and_tiny_lines():
    assert _extract("Deadlines:\n\n..\nok") == []


def test_fallback_handles_huge_input_quickly():
    drafts = _extract("\n".join(f"Do thing number {i}" for i in range(5000)))
    assert len(drafts) == 25


def test_capture_page_is_404_when_flag_off_and_renders_when_on(app, client):
    register(client)
    assert client.get("/capture").status_code == 404
    app.config["FEATURE_SMART_CAPTURE"] = True
    page = client.get("/capture")
    assert page.status_code == 200
    assert b"Smart Capture" in page.data


def test_capture_nav_link_only_when_flag_on(app, client):
    register(client)
    assert b'href="/capture"' not in client.get("/").data
    app.config["FEATURE_SMART_CAPTURE"] = True
    assert b'href="/capture"' in client.get("/").data


def test_fallback_strips_stacked_connectors_left_by_the_date_phrase():
    (draft,) = _extract("Prepare viva slides 2 hours, due next Tuesday")
    assert draft["title"] == "Prepare viva slides"
    assert draft["estimate_hours"] == 2.0
    assert draft["due_at"] == "2026-10-06T23:59:00"


def _bomb_pdf(repeats: int) -> bytes:
    import zlib

    stream = zlib.compress(b"BT /F1 12 Tf 72 720 Td (x) Tj ET\n" * repeats)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" /Filter /FlateDecode >>\nstream\n"
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    for i, obj in enumerate(objects, start=1):
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    return out + b"trailer\n<< /Size 6 /Root 1 0 R >>\n%%EOF"


def test_decompression_bomb_is_contained_in_the_child_process(capture_client, monkeypatch):
    """A small PDF that inflates to tens of MB must fail fast with a 422 and
    never be parsed in the web worker. (Reviewer repro: ~110 KB -> 2.4 GB.)"""
    import time

    from app.services import pdf_extract

    monkeypatch.setattr(pdf_extract, "CPU_LIMIT_SECONDS", 2)
    bomb = _bomb_pdf(1_500_000)
    assert len(bomb) < 400_000
    started = time.monotonic()
    response = _upload(capture_client, bomb)
    assert response.status_code == 422
    assert response.get_json()["error"]["message"] == "Could not read this PDF"
    assert time.monotonic() - started < 15


def test_long_pdf_text_is_truncated_not_rejected(capture_client, monkeypatch):
    seen = {}

    def fake(text, **kw):
        seen["len"] = len(text)
        return []

    monkeypatch.setattr(gemini_client, "generate_task_drafts", fake)
    long_line = "Submit report " * 40
    pdf = _minimal_pdf(long_line)
    for _ in range(1):
        assert _upload(capture_client, pdf).status_code == 200
    from app.services import pdf_extract

    # The extractor itself never returns more than the capture limit.
    assert len(pdf_extract.extract_text(pdf)) <= 20_000
    assert seen["len"] > 0


def test_rate_limit_applies_before_any_pdf_work(capture_client, monkeypatch):
    calls = []
    from app.services import pdf_extract

    monkeypatch.setattr(
        pdf_extract, "extract_text", lambda data, **kw: calls.append(1) or "Task one"
    )
    _gemini_returns(monkeypatch, [])
    for _ in range(10):
        assert capture_client.post("/api/capture/preview", json={"text": "x"}).status_code == 200
    blocked = _upload(capture_client, _minimal_pdf("x"))
    assert blocked.status_code == 429
    assert calls == []  # no extraction, hence no archive, for a throttled request


def test_flag_off_capture_returns_404_even_when_not_logged_in(app):
    anon = app.test_client()
    assert anon.post("/api/capture/preview", json={"text": "x"}).status_code == 404
    assert anon.post("/api/capture/confirm", json={"tasks": []}).status_code == 404


def test_llm_dates_that_overflow_are_dropped_not_fatal(capture_client, monkeypatch):
    _gemini_returns(
        monkeypatch,
        [
            {"title": "far", "tag": "work", "due_at": "9999-12-31T23:59:59-05:00"},
            {"title": "near", "tag": "work", "due_at": "0001-01-01T00:00:00+05:00"},
            {"title": "ok", "tag": "work", "due_at": "2026-10-09"},
        ],
    )
    response = capture_client.post("/api/capture/preview", json={"text": "x"})
    assert response.status_code == 200
    by_title = {t["title"]: t for t in response.get_json()["tasks"]}
    assert by_title["far"]["due_at"] is None and by_title["near"]["due_at"] is None
    # bare date -> end of that local day (IST 23:59 = 18:29 UTC)
    assert by_title["ok"]["due_at"] == "2026-10-09T18:29:00"


def test_confirm_with_overflowing_due_at_is_a_422_not_a_500(capture_client):
    bad = {"title": "t", "tag": "work", "due_at": "9999-12-31T23:59:59-05:00"}
    assert capture_client.post("/api/capture/confirm", json={"tasks": [bad]}).status_code == 422


def test_fallback_keeps_an_explicit_time_next_to_a_relative_day():
    (draft,) = _extract("Meeting 10am tomorrow")
    assert draft["due_at"] == "2026-10-05T10:00:00"
    (draft,) = _extract("Call mom tomorrow 6:30pm")
    assert draft["due_at"] == "2026-10-05T18:30:00"


def test_fallback_bare_day_of_month_in_the_past_means_next_month():
    (draft,) = _extract("Pay rent on the 1st")
    assert draft["due_at"].startswith("2026-11-01")


# ---- date engine: every case from the human-factors review -----------------


# "now" in _extract is Sunday 2026-10-04 11:30 (Asia/Kolkata).
@pytest.mark.parametrize(
    "text,title,due",
    [
        # a digit in the title must never be read as part of the date
        ("Submit Project 2 by Friday 5pm", "Submit Project 2", "2026-10-09T17:00:00"),
        ("Read chapter 5 by Friday", "Read chapter 5", "2026-10-09T23:59:00"),
        ("Lab 3 due Monday 9am", "Lab 3", "2026-10-05T09:00:00"),
        ("Lab due Monday 9am", "Lab", "2026-10-05T09:00:00"),
        ("Lab due Monday", "Lab", "2026-10-05T23:59:00"),
        # ISO and numeric day-first dates
        ("Exam 2026-10-15 10:00", "Exam", "2026-10-15T10:00:00"),
        ("Quiz 2 on 10/12", "Quiz 2", "2026-12-10T23:59:00"),
        ("Submit report on 10/05", "Submit report", "2027-05-10T23:59:00"),
        ("Hand in by 15/10/2026", "Hand in", "2026-10-15T23:59:00"),
        ("Hand in by 15.10.26", "Hand in", "2026-10-15T23:59:00"),
        # month names; a date only days past stays THIS year (shows as overdue)
        ("Essay due 3 Oct", "Essay", "2026-10-03T23:59:00"),
        ("Pay fee due October 1", "Pay fee", "2026-10-01T23:59:00"),
        ("Viva on 5th Oct at 9am", "Viva", "2026-10-05T09:00:00"),
        ("Report Oct 20, 2026", "Report", "2026-10-20T23:59:00"),
        ("Project 12 January 2027", "Project", "2027-01-12T23:59:00"),
        # relative words, Hinglish, clock times
        ("Meeting 10am tomorrow", "Meeting", "2026-10-05T10:00:00"),
        (
            "DBMS assignment kal tak submit karna hai",
            "DBMS assignment submit karna hai",
            "2026-10-05T23:59:00",
        ),
        ("परसों रिपोर्ट जमा करो", "रिपोर्ट जमा करो", "2026-10-06T23:59:00"),
        ("Call mom at 6pm", "Call mom", "2026-10-04T18:00:00"),
        ("Call mom at 9am", "Call mom", "2026-10-05T09:00:00"),  # 9am already passed today
        ("Finish deck in 3 days", "Finish deck", "2026-10-07T23:59:00"),
        ("Send report EOD", "Send report", "2026-10-04T18:00:00"),
        ("Dinner at noon tomorrow", "Dinner", "2026-10-05T12:00:00"),
    ],
)
def test_date_engine_cases(text, title, due):
    (draft,) = _extract(text)
    assert (draft["title"], draft["due_at"]) == (title, due)


@pytest.mark.parametrize(
    "text",
    [
        "Prepare slides for 2/3 people",  # a fraction, not a date
        "Submit 12/13",  # no month 13
        "Buy 3 pens",  # a bare number
        "Chapter 12",
        "Submit by 31 Feb",  # impossible date
        "Version 2.0 release notes",  # decimal
        "Quiz on 2/30/2026",
    ],
)
def test_ambiguous_or_impossible_dates_are_left_blank(text):
    (draft,) = _extract(text)
    assert draft["due_at"] is None


def test_a_time_zone_word_converts_to_the_users_zone():
    (draft,) = _extract("Call client 5pm EST tomorrow")
    # 17:00 EST (UTC-5) = 22:00 UTC = 03:30 next day IST
    assert draft["due_at"] == "2026-10-06T03:30:00"
    (draft,) = _extract("Standup 10am IST tomorrow")
    assert draft["due_at"] == "2026-10-05T10:00:00"


def test_implausible_years_are_never_produced():
    for text in ("Exam 15/10/2112", "Exam 2099-01-01", "Quiz 1999-05-05"):
        (draft,) = _extract(text)
        assert draft["due_at"] is None, text


def test_the_last_date_mentioned_wins():
    (draft,) = _extract("Moved from 3 Oct to 9 Oct 2026")
    assert draft["due_at"] == "2026-10-09T23:59:00"


# ---- round 2: date-engine regressions found by the second review -------------


@pytest.mark.parametrize(
    "text,due",
    [
        # an explicit date beats the weekday/relative word that describes it
        ("Quiz 2 on Monday 12 Oct, 9:30 AM, Room 3/12", "2026-10-12T09:30:00"),
        ("Thursday, 15 October 2026 viva", "2026-10-15T23:59:00"),
        ("Fri, Oct 16 Seminar", "2026-10-16T23:59:00"),
        ("Assignment 2 – Due: Wed, 14 Oct", "2026-10-14T23:59:00"),
        # EOD is a time-of-day on the chosen date, not a date of its own
        ("Send it by EOD tomorrow", "2026-10-05T18:00:00"),
        ("Send report Fri EOD", "2026-10-09T18:00:00"),
        ("Send report by COB Friday", "2026-10-09T18:00:00"),
        # ordinals only count after a deadline word
        ("Submit by the 12th", "2026-10-12T23:59:00"),
        # chat/email timestamps are when the message was SENT
        ("[04/10/2026, 10:15:32] Prof Rao: Submit the lab record by 9/10", "2026-10-09T23:59:00"),
        ("4/10/26, 10:15 am - Prof: Submit by 9 Oct 5pm", "2026-10-09T17:00:00"),
        # time spellings
        ("Meeting at 5.30pm tomorrow", "2026-10-05T17:30:00"),
        ("Meeting 5:30 p.m. tomorrow", "2026-10-05T17:30:00"),
        ("Meeting 17h30 tomorrow", "2026-10-05T17:30:00"),
        ("Meeting 5pm-6pm tomorrow", "2026-10-05T17:00:00"),
        ("Meeting 5-6pm tomorrow", "2026-10-05T17:00:00"),
        ("Exam 2026-10-14T09:00+05:30", "2026-10-14T09:00:00"),
        ("Exam 2026-10-14T09:00Z", "2026-10-14T14:30:00"),
        # a clock with no date: today if still ahead
        ("Meeting in Room 3/12 at 5pm", "2026-10-04T17:00:00"),
    ],
)
def test_round2_date_cases(text, due):
    (draft,) = _extract(text)
    assert draft["due_at"] == due, draft


@pytest.mark.parametrize(
    "text,title",
    [
        ("Revise 10th class maths", "Revise 10th class maths"),
        ("Prepare for 2nd semester exam", "Prepare for 2nd semester exam"),
        ("Complete 1st year syllabus", "Complete 1st year syllabus"),
        ("Assignment 2 Oct 14", "Assignment 2 Oct 14"),  # 2 Oct? Oct 14? ambiguous: no date
        ("Project 3 Nov 20", "Project 3 Nov 20"),
        ("Watch video 3:45", "Watch video 3:45"),
        ("Read John 3:16", "Read John 3:16"),
        ("Read on page 4.5", "Read on page 4.5"),
        ("कलम खरीदना", "कलम खरीदना"),
        ("कला परियोजना", "कला परियोजना"),
        ("आज़ादी पर निबंध", "आज़ादी पर निबंध"),
        ("Today's lecture notes", "Today's lecture notes"),
        ("Kal ki class ke notes", "Kal ki class ke notes"),
    ],
)
def test_round2_no_false_dates_and_titles_stay_intact(text, title):
    (draft,) = _extract(text)
    assert draft["due_at"] is None, draft
    assert draft["title"] == title


def test_round2_title_after_explicit_date_drops_the_weekday_words():
    (draft,) = _extract("Fri, Oct 16 Seminar")
    assert draft["title"] == "Seminar"
    (draft,) = _extract("Thursday, 15 October 2026 viva")
    assert draft["title"] == "viva"


@pytest.mark.parametrize(
    "line",
    ["by\t" * 6600, "by " * 6600, " " * 19999 + "x", "1/2 " * 4900, "by 1/2 " * 2800],
)
def test_round2_adversarial_input_is_fast(line):
    import time

    started = time.monotonic()
    _extract(line)
    assert time.monotonic() - started < 1.0
