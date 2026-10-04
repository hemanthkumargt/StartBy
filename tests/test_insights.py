import pytest
from freezegun import freeze_time

from app.services import insights_service
from tests.conftest import register

NOW = "2026-10-04T06:00:00"


@pytest.fixture
def insights_client(app):
    app.config["FEATURE_ESTIMATES"] = True
    app.config["FEATURE_INSIGHTS"] = True
    client = app.test_client()
    register(client)
    return client


def _add(client, title, *, due_in_hours, estimate=2, tag="work"):
    from datetime import datetime, timedelta

    due = (datetime(2026, 10, 4, 6, 0, 0) + timedelta(hours=due_in_hours)).isoformat()
    response = client.post(
        "/api/tasks", json={"title": title, "tag": tag, "due_at": due, "estimate_hours": estimate}
    )
    assert response.status_code == 201
    return response.get_json()


def _insights(client):
    response = client.get("/api/insights")
    assert response.status_code == 200
    return response.get_json()


def _finish(client, task, actual):
    response = client.post(f"/api/tasks/{task['id']}/complete", json={"actual_hours": actual})
    assert response.status_code == 200


# ---- flag ----------------------------------------------------------------


def test_I15_flag_off_insights_routes_do_not_exist(client):
    register(client)
    assert client.get("/api/insights").status_code == 404
    assert client.get("/insights").status_code == 404


def test_insights_requires_login(app):
    app.config["FEATURE_INSIGHTS"] = True
    assert app.test_client().get("/api/insights").status_code == 401


# ---- overload ------------------------------------------------------------


@pytest.mark.parametrize(
    "red,amber,level",
    [
        (0, 0, "none"),
        (1, 0, "none"),
        (1, 2, "none"),
        (1, 3, "warning"),  # 4 at risk
        (0, 4, "warning"),
        (2, 0, "warning"),
        (3, 0, "warning"),
        (4, 0, "critical"),
        (5, 9, "critical"),
    ],
)
def test_overload_level_boundaries(red, amber, level):
    assert insights_service.overload_level(red, amber) == level


@freeze_time(NOW)
def test_overload_empty_workload_is_none(insights_client):
    overload = _insights(insights_client)["overload"]
    assert overload["level"] == "none"
    assert overload["red"] == overload["amber"] == 0
    assert overload["top_tasks"] == []


@freeze_time(NOW)
def test_overload_counts_red_and_amber_and_sums_planned_hours(insights_client):
    for i in range(2):
        _add(insights_client, f"late {i}", due_in_hours=3)  # start_by already passed -> red
    _add(insights_client, "soon", due_in_hours=20)  # start in ~16.5h -> amber
    _add(insights_client, "fine", due_in_hours=60)  # green
    overload = _insights(insights_client)["overload"]
    assert (overload["red"], overload["amber"]) == (2, 1)
    assert overload["level"] == "warning"
    # 2h * 1.5 * 1.15 = 3.45h each, three at-risk tasks
    assert overload["hours_at_risk"] == pytest.approx(10.4, abs=0.05)
    assert "2 tasks past their start time" in overload["message"]
    assert "1 more starting within 24 hours" in overload["message"]


@freeze_time(NOW)
def test_overload_critical_lists_worst_three_first(insights_client):
    for i in range(5):
        _add(insights_client, f"late {i}", due_in_hours=1 + i * 0.5)
    _add(insights_client, "amber one", due_in_hours=20)
    overload = _insights(insights_client)["overload"]
    assert overload["level"] == "critical"
    assert len(overload["top_tasks"]) == 3
    assert all(t["risk"] == "red" for t in overload["top_tasks"])
    assert overload["top_tasks"][0]["title"] == "late 0"  # earliest start_by first


@freeze_time(NOW)
def test_overload_ignores_done_tasks_and_tasks_without_estimates(insights_client):
    done = _add(insights_client, "done late", due_in_hours=1)
    _finish(insights_client, done, 1)
    for i in range(3):
        insights_client.post(
            "/api/tasks", json={"title": f"no est {i}", "due_at": "2026-10-04T07:00:00"}
        )
    assert _insights(insights_client)["overload"]["level"] == "none"


# ---- report card ---------------------------------------------------------


@freeze_time(NOW)
def test_report_card_empty_state(insights_client):
    report = _insights(insights_client)["report_card"]
    assert report["samples"] == 0
    assert report["overall_ratio"] is None
    assert report["by_tag"] == []
    assert report["series"] == []
    assert report["trend"]["direction"] == "insufficient"
    assert "log the actual hours" in report["summary"]


def _complete_series(client, ratios, tag="study"):
    """Complete one 2h-estimate task per ratio, each at a later frozen time
    so completed_at orders them."""
    from datetime import datetime, timedelta

    base = datetime(2026, 10, 4, 6, 0, 0)
    for i, ratio in enumerate(ratios):
        with freeze_time(base + timedelta(hours=i)):
            task = _add(client, f"t{i}", due_in_hours=100, estimate=2, tag=tag)
            _finish(client, task, round(2 * ratio, 2))


def test_report_card_overall_ratio_and_underestimate_summary(insights_client):
    _complete_series(insights_client, [1.5, 1.5, 1.5, 1.5])
    with freeze_time("2026-10-05T00:00:00"):
        report = _insights(insights_client)["report_card"]
    assert report["samples"] == 4
    assert report["overall_ratio"] == pytest.approx(1.5)
    assert "underestimate" in report["summary"]
    (study,) = report["by_tag"]
    assert study["tag"] == "study" and study["samples"] == 4
    assert study["avg_ratio"] == pytest.approx(1.5)
    assert study["multiplier"] is not None
    assert report["trend"]["direction"] == "steady"


def test_report_card_trend_improving(insights_client):
    _complete_series(insights_client, [2.0, 2.0, 1.1, 1.0])
    with freeze_time("2026-10-05T00:00:00"):
        trend = _insights(insights_client)["report_card"]["trend"]
    assert trend["direction"] == "improving"
    assert trend["previous_ratio"] > trend["recent_ratio"]


def test_report_card_trend_worsening(insights_client):
    _complete_series(insights_client, [1.0, 1.0, 2.0, 2.5])
    with freeze_time("2026-10-05T00:00:00"):
        assert _insights(insights_client)["report_card"]["trend"]["direction"] == "worsening"


def test_report_card_needs_minimum_samples_for_a_trend(insights_client):
    _complete_series(insights_client, [1.0, 3.0, 3.0])
    with freeze_time("2026-10-05T00:00:00"):
        report = _insights(insights_client)["report_card"]
    assert report["samples"] == 3
    assert report["trend"]["direction"] == "insufficient"


def test_report_card_overestimating_summary(insights_client):
    _complete_series(insights_client, [0.5, 0.5, 0.5])
    with freeze_time("2026-10-05T00:00:00"):
        assert "overestimate" in _insights(insights_client)["report_card"]["summary"]


def test_report_card_series_is_capped_and_ordered(insights_client):
    _complete_series(insights_client, [1.0] * 15)
    with freeze_time("2026-10-06T00:00:00"):
        series = _insights(insights_client)["report_card"]["series"]
    assert len(series) == 12
    assert series[-1]["title"] == "t14"


def test_I2_deleted_completed_tasks_excluded_from_report(insights_client):
    _complete_series(insights_client, [2.0, 2.0])
    tasks = insights_client.get("/api/tasks?status=done").get_json()
    insights_client.delete(f"/api/tasks/{tasks[0]['id']}")
    with freeze_time("2026-10-05T00:00:00"):
        assert _insights(insights_client)["report_card"]["samples"] == 1


def test_I1_insights_only_cover_the_callers_tasks(app, insights_client):
    _complete_series(insights_client, [2.0, 2.0, 2.0, 2.0])
    other = app.test_client()
    register(other, name="Bo", email="bo@example.com")
    with freeze_time("2026-10-05T00:00:00"):
        data = _insights(other)
    assert data["report_card"]["samples"] == 0
    assert data["overload"]["level"] == "none"


def test_insights_page_renders_when_flag_on(insights_client):
    page = insights_client.get("/insights")
    assert page.status_code == 200
    assert b"Insights" in page.data


def test_insights_without_estimates_says_so_instead_of_claiming_all_is_well(app):
    app.config["FEATURE_INSIGHTS"] = True
    app.config["FEATURE_ESTIMATES"] = False
    client = app.test_client()
    register(client)
    data = client.get("/api/insights").get_json()
    assert "Turn on effort estimates" in data["overload"]["message"]
    assert "Turn on effort estimates" in data["report_card"]["summary"]
    assert data["overload"]["level"] == "none"
