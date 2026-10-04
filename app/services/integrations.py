"""Google Cloud side effects of task events, as one hooks listener.

What happens on a task event, when the matching setting is configured:

* Pub/Sub  — the event is published to PUBSUB_EVENTS_TOPIC (downstream
             consumers, dashboards, a future calendar/notification service).
* BigQuery — the same event is streamed into BQ_DATASET.BQ_EVENTS_TABLE so
             estimation accuracy can be analysed across users.
* Cloud Tasks — a task is scheduled to call back at the moment a pending
             task's start_by arrives, so the start-now email goes out on the
             minute instead of waiting for the next cron sweep.

Everything runs on the gcp dispatcher thread (never in the request), is a
no-op when unconfigured, and a failure is logged and dropped: the cron sweep
remains the safety net for reminders, and events are best-effort telemetry.
Events carry no title or notes, and the user is an HMAC of their id — the
analytics side never sees who or what."""

import hashlib
import hmac
import logging
import uuid
from datetime import timedelta
from typing import Any

from app import timeutil
from app.gcp import bigquery, cloudtasks, dispatcher, monitoring, pubsub, storage
from app.services import backup_service

logger = logging.getLogger(__name__)

# Cloud Tasks refuses a scheduleTime more than 30 days out; a start_by that
# far away is left to the cron sweep (it will be inside the window by then).
_MAX_SCHEDULE_AHEAD = timedelta(days=29)
# Fire a moment after start_by so "now >= start_by" (I12) is certainly true
# when the callback evaluates it, even with small clock differences.
_SCHEDULE_SLACK_SECONDS = 5
_MAX_PENDING_FOR_ARCHIVE = 20


class CloudIntegrations:
    def __init__(self, config: Any) -> None:
        self._project = config["GCP_PROJECT"]
        self._secret_key = str(config["SECRET_KEY"]).encode()
        self._cron_secret = config["CRON_SECRET"]
        self._base_url = config["APP_BASE_URL"]
        self._tasks_location = config["CLOUD_TASKS_LOCATION"]
        self._tasks_queue = config["CLOUD_TASKS_QUEUE"]
        self._topic = config["PUBSUB_EVENTS_TOPIC"]
        self._bq_dataset = config["BQ_DATASET"]
        self._bq_table = config["BQ_EVENTS_TABLE"]
        self._bucket = config["GCS_BUCKET"]
        self._monitoring = config["MONITORING_ENABLED"]

    # -- what is switched on ------------------------------------------------

    @property
    def pubsub_enabled(self) -> bool:
        return bool(self._project and self._topic)

    @property
    def bigquery_enabled(self) -> bool:
        return bool(self._project and self._bq_dataset)

    @property
    def cloudtasks_enabled(self) -> bool:
        return bool(self._project and self._tasks_queue and self._base_url and self._cron_secret)

    @property
    def storage_enabled(self) -> bool:
        return bool(self._bucket)

    @property
    def monitoring_enabled(self) -> bool:
        return bool(self._project and self._monitoring)

    # -- hooks listener ------------------------------------------------------

    def on_task_created(self, task: dict[str, Any], *, user_id: int) -> None:
        self._emit("task.created", task, user_id)
        self._schedule_from_task(task)

    def on_task_updated(
        self, task: dict[str, Any], changed_fields: list[str], *, user_id: int
    ) -> None:
        self._emit("task.updated", task, user_id)
        self._schedule_from_task(task)

    def on_task_completed(self, task: dict[str, Any], *, user_id: int) -> None:
        self._emit("task.completed", task, user_id)

    def on_task_reopened(self, task: dict[str, Any], *, user_id: int) -> None:
        self._emit("task.reopened", task, user_id)
        self._schedule_from_task(task)

    def on_task_deleted(self, task_id: int, *, user_id: int) -> None:
        self._emit("task.deleted", {"id": task_id}, user_id)

    # -- events (Pub/Sub + BigQuery) ----------------------------------------

    def _user_hash(self, user_id: int) -> str:
        return hmac.new(self._secret_key, str(user_id).encode(), hashlib.sha256).hexdigest()[:16]

    def _build_event(self, name: str, task: dict[str, Any], user_id: int) -> dict[str, Any]:
        estimate = task.get("estimate_hours")
        actual = task.get("actual_hours")
        ratio = actual / estimate if estimate and actual else None
        return {
            "event_id": uuid.uuid4().hex,
            "event": name,
            "ts": timeutil.utcnow_iso(),
            "task_id": task["id"],
            "user_hash": self._user_hash(user_id),
            "tag": task.get("tag"),
            "status": task.get("status"),
            "estimate_hours": estimate,
            "actual_hours": actual,
            "ratio": ratio,
            "risk": task.get("risk"),
        }

    def _emit(self, name: str, task: dict[str, Any], user_id: int) -> None:
        if not (self.pubsub_enabled or self.bigquery_enabled):
            return
        event = self._build_event(name, task, user_id)
        if self.pubsub_enabled:
            dispatcher.submit(
                lambda: pubsub.publish(
                    self._project, self._topic, event, attributes={"event": name}
                )
            )
        if self.bigquery_enabled:
            dispatcher.submit(
                lambda: bigquery.insert_rows(
                    self._project, self._bq_dataset, self._bq_table, [event], id_key="event_id"
                )
            )

    # -- Cloud Tasks: exact-time start-now ----------------------------------

    def _schedule_from_task(self, task: dict[str, Any]) -> None:
        if task.get("status") == "pending" and task.get("start_by"):
            self.schedule_start_now(task["id"], task["start_by"])

    def schedule_start_now(self, task_id: int, start_by_iso: str) -> None:
        """Ask Cloud Tasks to call /api/internal/start-now at start_by.
        Triggers are never cancelled: the callback re-checks the task, so a
        stale one (moved deadline, completed, deleted) is a harmless no-op."""
        if not self.cloudtasks_enabled:
            return
        due_at = timeutil.parse_iso(start_by_iso) + timedelta(seconds=_SCHEDULE_SLACK_SECONDS)
        now = timeutil.utcnow()
        if due_at - now > _MAX_SCHEDULE_AHEAD:
            return
        schedule = None if due_at <= now else due_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        dispatcher.submit(
            lambda: cloudtasks.create_http_task(
                self._project,
                self._tasks_location,
                self._tasks_queue,
                url=f"{self._base_url}/api/internal/start-now",
                payload={"task_id": task_id},
                headers={"X-Cron-Secret": self._cron_secret},
                schedule_time_rfc3339=schedule,
            ),
            lane="critical",
        )

    # -- Cloud Storage -------------------------------------------------------

    def archive_pdf(self, user_id: int, data: bytes) -> None:
        """Keep a copy of an uploaded PDF, namespaced by hashed user."""
        # The job closes over up to 5 MB of bytes: skip rather than let a backed-up
        # queue pin hundreds of MB on a 1 GB VM. (Archiving is a convenience.)
        if not self.storage_enabled or dispatcher.pending("bulk") > _MAX_PENDING_FOR_ARCHIVE:
            return
        digest = hashlib.sha256(data).hexdigest()[:12]
        stamp = timeutil.utcnow().strftime("%Y%m%dT%H%M%S")
        name = f"pdfs/{self._user_hash(user_id)}/{stamp}-{digest}.pdf"
        dispatcher.submit(
            lambda: storage.upload_object(self._bucket, name, data, content_type="application/pdf")
        )

    def backup_database(self, db_path: str) -> str:
        """Upload a consistent gzip snapshot; synchronous, because the
        caller (Cloud Scheduler) needs a real success/failure status code.
        Returns the object name. Raises gcp.rest.GcpError on upload failure."""
        stamp = timeutil.utcnow().strftime("%Y%m%dT%H%M%SZ")
        name = f"backups/startby-{stamp}.db.gz"
        storage.upload_object(
            self._bucket,
            name,
            backup_service.snapshot_gzip(db_path),
            content_type="application/gzip",
        )
        return name

    # -- Cloud Monitoring ----------------------------------------------------

    def report_reminder_counts(self, counts: dict[str, int]) -> None:
        if not self.monitoring_enabled:
            return

        def job() -> None:
            for key, value in counts.items():
                monitoring.write_int_metric(self._project, "reminders_sent", value, {"kind": key})

        dispatcher.submit(job)
