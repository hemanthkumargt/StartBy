"""Voice notes: the dictaphone. A note is a saved transcript; it never creates a task."""

import pytest

from app.services import voice_note_service
from tests.conftest import login, register


@pytest.fixture
def vclient(app):
    app.config["FEATURE_VOICE"] = True
    client = app.test_client()
    register(client, name="Ada")
    return client


def post(client, text):
    return client.post("/api/voice/notes", json={"transcript": text})


# ---- flag + auth -----------------------------------------------------------


def test_I15_flag_off_the_notes_routes_do_not_exist(client):
    assert client.get("/api/voice/notes").status_code == 404  # even signed out
    register(client)
    assert client.get("/api/voice/notes").status_code == 404
    assert post(client, "hello").status_code == 404


def test_notes_require_login(app):
    app.config["FEATURE_VOICE"] = True
    c = app.test_client()
    assert c.get("/api/voice/notes").status_code == 401
    assert c.post("/api/voice/notes", json={"transcript": "x"}).status_code == 401


# ---- create / read ---------------------------------------------------------


def test_create_list_get_roundtrip(vclient):
    res = post(vclient, "Call the bank on Monday. Also buy milk and eggs.")
    assert res.status_code == 201
    note = res.get_json()
    assert note["title"] == "Call the bank on Monday"
    assert note["transcript"].startswith("Call the bank")

    listing = vclient.get("/api/voice/notes").get_json()["notes"]
    assert [n["id"] for n in listing] == [note["id"]]
    assert "transcript" not in listing[0] and listing[0]["preview"]

    full = vclient.get(f"/api/voice/notes/{note['id']}").get_json()
    assert full["transcript"] == note["transcript"]


def test_saving_a_note_never_creates_a_task(vclient):
    post(vclient, "Submit the report by Friday 5pm, two hours.")
    assert vclient.get("/api/tasks").get_json() == []


def test_newest_first(vclient):
    first = post(vclient, "first note").get_json()["id"]
    second = post(vclient, "second note").get_json()["id"]
    ids = [n["id"] for n in vclient.get("/api/voice/notes").get_json()["notes"]]
    assert ids == [second, first]


@pytest.mark.parametrize("bad", ["", "   ", "\n\n\t", None, 123, ["a"], {"a": 1}])
def test_empty_or_non_string_is_rejected(vclient, bad):
    assert post(vclient, bad).status_code == 422


def test_non_json_body_is_rejected(vclient):
    assert (
        vclient.post("/api/voice/notes", data="nope", content_type="text/plain").status_code == 422
    )


def test_too_long_is_rejected(vclient):
    assert post(vclient, "a" * (voice_note_service.NOTE_MAX_CHARS + 1)).status_code == 422
    assert post(vclient, "a" * voice_note_service.NOTE_MAX_CHARS).status_code == 201


def test_per_user_cap(vclient, monkeypatch):
    monkeypatch.setattr(voice_note_service, "MAX_NOTES_PER_USER", 2)
    assert post(vclient, "one").status_code == 201
    assert post(vclient, "two").status_code == 201
    assert post(vclient, "three").status_code == 409


def test_control_characters_are_dropped_and_paragraphs_kept(vclient):
    note = post(vclient, "line one\x00\x07\r\nline   two\n\n\n\nline three").get_json()
    assert note["transcript"] == "line one\nline two\n\nline three"


def test_unicode_survives(vclient):
    note = post(vclient, "நாளை காலை 9 மணிக்கு கூட்டம். 👨‍👩‍👧 family dinner").get_json()
    assert "👨‍👩‍👧" in note["transcript"] and "கூட்டம்" in note["transcript"]


def test_html_is_stored_as_text_not_interpreted(vclient):
    note = post(vclient, "<script>alert(1)</script> remind me").get_json()
    assert note["transcript"].startswith("<script>")  # rendered with textContent on the page


def test_long_first_sentence_title_is_shortened_on_a_word(vclient):
    title = voice_note_service.make_title("word " * 60)
    assert len(title) <= voice_note_service.TITLE_MAX_CHARS + 1 and title.endswith("…")
    assert voice_note_service.make_title("!!!") == "Voice note"


# ---- isolation (I1) --------------------------------------------------------


def test_other_users_notes_are_404_everywhere(app, vclient):
    mine = post(vclient, "my private thought").get_json()["id"]
    other = app.test_client()
    register(other, name="Bob", email="bob@example.com")
    assert other.get(f"/api/voice/notes/{mine}").status_code == 404
    assert other.delete(f"/api/voice/notes/{mine}").status_code == 404
    assert other.get("/api/voice/notes").get_json()["notes"] == []
    assert vclient.get(f"/api/voice/notes/{mine}").status_code == 200  # untouched


def test_delete_then_gone(vclient):
    nid = post(vclient, "temporary").get_json()["id"]
    assert vclient.delete(f"/api/voice/notes/{nid}").status_code == 204
    assert vclient.get(f"/api/voice/notes/{nid}").status_code == 404
    assert vclient.delete(f"/api/voice/notes/{nid}").status_code == 404


def test_notes_survive_logout_and_login(app, vclient):
    post(vclient, "keep me")
    vclient.post("/api/auth/logout")
    login(vclient)
    assert len(vclient.get("/api/voice/notes").get_json()["notes"]) == 1


# ---- the page ----------------------------------------------------------------


def test_page_is_404_when_the_flag_is_off_even_signed_out(client):
    assert client.get("/voice").status_code == 404
    register(client)
    assert client.get("/voice").status_code == 404
    assert b"fab-mic" not in client.get("/").data


def test_page_and_floating_mic_when_on(vclient):
    page = vclient.get("/voice")
    assert page.status_code == 200 and b"Voice Notes" in page.data
    assert b"fab-mic" in vclient.get("/tasks").data  # the shortcut is on every other page
    assert b"fab-mic" not in page.data  # but not on the page that has the big mic


def test_page_requires_login_when_on(app):
    app.config["FEATURE_VOICE"] = True
    assert app.test_client().get("/voice").status_code in (302, 401)
