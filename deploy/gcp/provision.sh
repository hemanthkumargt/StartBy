#!/usr/bin/env bash
# Creates every Google Cloud resource StartBy uses, in two idempotent phases
# (re-running skips what exists). Run from Cloud Shell or any machine with
# gcloud logged in as a project Owner:
#
#   PROJECT_ID=my-project DOMAIN=startby.duckdns.org \
#     STARTBY_REPO_URL=https://github.com/you/StartBy.git ./deploy/gcp/provision.sh
#
# Phase 1 (default run): APIs, service account, bucket, Pub/Sub, BigQuery,
#   Cloud Tasks, secrets, static IP, firewall, VM. Then it prints the exact
#   next steps (DNS, certbot, start the service).
# Phase 2 (PHASE=after-https, or automatically when https://$DOMAIN/healthz
#   already answers): the uptime check, the alert policy and the two Cloud
#   Scheduler jobs. These need the live HTTPS site, so they come last:
#
#   PHASE=after-https PROJECT_ID=... DOMAIN=... STARTBY_REPO_URL=... ./deploy/gcp/provision.sh
#
# COST NOTE: the reserved static IP is billed (about $3/month; the new-account
# credit covers it). Delete it with the VM when you are done:
#   gcloud compute addresses delete startby-vm-ip --region us-central1
#
# NOT YET RUN against a real project — treat the first run as a dry run:
# read the output, and expect to adjust a flag or two to your gcloud version.
# Billing must be linked to the project (several APIs below refuse otherwise).
set -euo pipefail

: "${PROJECT_ID:?set PROJECT_ID}"
: "${DOMAIN:?set DOMAIN (the DuckDNS/own domain that will point at the VM)}"
: "${STARTBY_REPO_URL:?set STARTBY_REPO_URL (https git URL the VM can clone anonymously)}"
# e2-micro is only in the Always Free tier in us-west1, us-central1, us-east1.
REGION="${REGION:-us-central1}"
ZONE="${ZONE:-us-central1-a}"
VM_NAME="${VM_NAME:-startby-vm}"
BUCKET="${BUCKET:-${PROJECT_ID}-startby}"
SA_NAME="startby-vm"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
QUEUE="start-now"
TOPIC="startby-events"
DATASET="startby"
TABLE="task_events"
SCHEDULER_TZ="Asia/Kolkata"
HERE="$(cd "$(dirname "$0")" && pwd)"
TOTAL=10

gc() { gcloud --project "$PROJECT_ID" "$@"; }
exists() { "$@" >/dev/null 2>&1; }
# retry N DELAY cmd...: IAM changes (and a just-created service account) take
# a while to propagate, so a fixed sleep is either too short or wasted time.
retry() {
  local tries="$1" delay="$2" n=1
  shift 2
  until "$@"; do
    if [ "$n" -ge "$tries" ]; then
      echo "   gave up after $n attempts: $*" >&2
      return 1
    fi
    echo "   attempt $n/$tries failed, retrying in ${delay}s..." >&2
    n=$((n + 1))
    sleep "$delay"
  done
}

echo "== 1/$TOTAL Enable APIs =="
gc services enable \
  compute.googleapis.com secretmanager.googleapis.com storage.googleapis.com \
  aiplatform.googleapis.com pubsub.googleapis.com cloudtasks.googleapis.com \
  bigquery.googleapis.com calendar-json.googleapis.com cloudscheduler.googleapis.com \
  monitoring.googleapis.com logging.googleapis.com \
  iam.googleapis.com cloudresourcemanager.googleapis.com

echo "== 2/$TOTAL VM service account + IAM roles (no key file: identity comes from metadata) =="
exists gc iam service-accounts describe "$SA" || \
  gc iam service-accounts create "$SA_NAME" --display-name "StartBy VM"
ROLES="roles/secretmanager.secretAccessor roles/pubsub.publisher roles/cloudtasks.enqueuer
       roles/bigquery.dataEditor roles/monitoring.metricWriter roles/logging.logWriter"
# Vertex AI bills per token (CLAUDE.md: free path is the AI Studio key). Only
# grant it when the team has explicitly opted in:  ENABLE_VERTEX=1 ./provision.sh
[ "${ENABLE_VERTEX:-0}" != "1" ] || ROLES="$ROLES roles/aiplatform.user"
for role in $ROLES; do
  # A brand-new service account can take a while to become visible to IAM.
  retry 6 10 gc projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:$SA" --role "$role" --condition=None >/dev/null
done

echo "== 3/$TOTAL Cloud Storage: PDFs + DB backups (private, backups expire after 30 days) =="
exists gc storage buckets describe "gs://$BUCKET" || \
  gc storage buckets create "gs://$BUCKET" --location "$REGION" \
    --uniform-bucket-level-access --public-access-prevention
gc storage buckets update "gs://$BUCKET" --lifecycle-file "$HERE/bucket-lifecycle.json"
retry 6 10 gc storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member "serviceAccount:$SA" --role roles/storage.objectAdmin >/dev/null

echo "== 4/$TOTAL Pub/Sub: task events topic =="
exists gc pubsub topics describe "$TOPIC" || gc pubsub topics create "$TOPIC"

echo "== 5/$TOTAL BigQuery: dataset + events table =="
exists bq --project_id "$PROJECT_ID" show "${DATASET}" || \
  bq --project_id "$PROJECT_ID" mk --location "$REGION" --dataset "${PROJECT_ID}:${DATASET}"
exists bq --project_id "$PROJECT_ID" show "${DATASET}.${TABLE}" || \
  bq --project_id "$PROJECT_ID" mk --table "${PROJECT_ID}:${DATASET}.${TABLE}" \
    "$HERE/task_events_schema.json"
# (roles/bigquery.dataEditor is granted project-wide above; streaming inserts
# need tables.updateData on the table, which that role includes.)

echo "== 6/$TOTAL Cloud Tasks: queue for exact-time start-now reminders =="
exists gc tasks queues describe "$QUEUE" --location "$REGION" || \
  gc tasks queues create "$QUEUE" --location "$REGION" \
    --max-attempts 10 --min-backoff 10s --max-backoff 600s \
    --max-concurrent-dispatches 2

echo "== 7/$TOTAL Secret Manager =="
make_secret() { # name, value
  if exists gc secrets describe "$1"; then
    printf '%s' "$2" | gc secrets versions add "$1" --data-file=- >/dev/null
  else
    printf '%s' "$2" | gc secrets create "$1" --replication-policy automatic --data-file=- >/dev/null
  fi
}
rand() { python3 -c 'import secrets; print(secrets.token_hex(32))'; }
exists gc secrets describe SECRET_KEY || make_secret SECRET_KEY "$(rand)"
exists gc secrets describe CRON_SECRET || make_secret CRON_SECRET "$(rand)"
[ -z "${SMTP_PASSWORD:-}" ] || make_secret SMTP_PASSWORD "$SMTP_PASSWORD"
[ -z "${GEMINI_API_KEY:-}" ] || make_secret GEMINI_API_KEY "$GEMINI_API_KEY"
[ -z "${GOOGLE_CLIENT_SECRET:-}" ] || make_secret GOOGLE_CLIENT_SECRET "$GOOGLE_CLIENT_SECRET"

echo "== 8/$TOTAL Compute Engine: static IP (billed, ~\$3/month), firewall, VM =="
exists gc compute addresses describe "${VM_NAME}-ip" --region "$REGION" || \
  gc compute addresses create "${VM_NAME}-ip" --region "$REGION"
VM_IP="$(gc compute addresses describe "${VM_NAME}-ip" --region "$REGION" --format='value(address)')"
exists gc compute firewall-rules describe startby-web || \
  gc compute firewall-rules create startby-web --allow tcp:80,tcp:443 --target-tags startby-web
exists gc compute instances describe "$VM_NAME" --zone "$ZONE" || \
  gc compute instances create "$VM_NAME" --zone "$ZONE" --machine-type e2-micro \
    --image-family ubuntu-2204-lts --image-project ubuntu-os-cloud \
    --boot-disk-size 30GB --boot-disk-type pd-standard \
    --address "$VM_IP" --tags startby-web --service-account "$SA" --scopes cloud-platform \
    --metadata "startby-project=$PROJECT_ID,startby-domain=$DOMAIN,startby-bucket=$BUCKET,startby-region=$REGION,startby-repo=${STARTBY_REPO_URL}" \
    --metadata-from-file "startup-script=$HERE/startup.sh"


# ---------------------------------------------------------------------------
# PHASE 2 — needs the live HTTPS site (Scheduler would call a dead URL, the
# uptime check would alert immediately). Runs with PHASE=after-https, or when
# https://$DOMAIN/healthz already answers.
# ---------------------------------------------------------------------------
RUN_PHASE2=0
if [ "${PHASE:-}" = "after-https" ]; then
  RUN_PHASE2=1
  curl -fsS --max-time 10 "https://${DOMAIN}/healthz" >/dev/null 2>&1 || \
    echo "   WARNING: https://${DOMAIN}/healthz is not answering yet; the jobs will fail until it does."
elif curl -fsS --max-time 10 "https://${DOMAIN}/healthz" >/dev/null 2>&1; then
  echo "   https://${DOMAIN}/healthz answers: running phase 2."
  RUN_PHASE2=1
fi

if [ "$RUN_PHASE2" != 1 ]; then
  cat <<NEXT

Phase 1 done (infrastructure). Next steps, in order:
  1. DNS: point ${DOMAIN} at ${VM_IP} (DuckDNS).
  2. Wait ~3-5 minutes for the VM's startup script to install the app, then SSH in
     (gcloud compute ssh ${VM_NAME} --zone ${ZONE}) and run certbot:
       sudo certbot --nginx -d ${DOMAIN} --staging    # rehearse first
     then the real certificate (recipe in deploy/README-deploy.md).
     Leave SECURE_COOKIES=0 until the REAL certificate is installed.
  3. On the VM: sudo systemctl start startby && sudo systemctl reload nginx
  4. Back here, run phase 2 (uptime check, alert policy, Scheduler jobs):
       PHASE=after-https PROJECT_ID=${PROJECT_ID} DOMAIN=${DOMAIN} \\
         STARTBY_REPO_URL=${STARTBY_REPO_URL} ./deploy/gcp/provision.sh
  5. Optional: Google Calendar OAuth client (redirect URI https://${DOMAIN}/calendar/callback),
     GOOGLE_CLIENT_ID in the VM's .env, GOOGLE_CLIENT_SECRET in Secret Manager + GCP_SECRETS.
  6. Vertex AI needs no key (GEMINI_BACKEND=vertex uses the VM service account; billed per token).
NEXT
  exit 0
fi

echo "== 9/$TOTAL Cloud Scheduler: reminder sweep (safety net) + nightly backup =="
CRON_SECRET_VALUE="$(gc secrets versions access latest --secret CRON_SECRET)"
upsert_job() { # name schedule path
  if exists gc scheduler jobs describe "$1" --location "$REGION"; then
    # `update` takes --update-headers (it REPLACES the header set); `--headers`
    # is create-only and would be rejected.
    gc scheduler jobs update http "$1" --location "$REGION" --schedule "$2" \
      --time-zone "$SCHEDULER_TZ" --uri "https://${DOMAIN}$3" --http-method POST \
      --update-headers "X-Cron-Secret=${CRON_SECRET_VALUE}" --attempt-deadline 60s
  else
    gc scheduler jobs create http "$1" --location "$REGION" --schedule "$2" \
      --time-zone "$SCHEDULER_TZ" --uri "https://${DOMAIN}$3" --http-method POST \
      --headers "X-Cron-Secret=${CRON_SECRET_VALUE}" --attempt-deadline 60s
  fi
}
upsert_job startby-reminders "*/10 * * * *" /api/cron/reminders
upsert_job startby-backup "30 2 * * *" /api/cron/backup

echo "== 10/$TOTAL Cloud Monitoring: uptime check + alert policy =="
if [ -n "$(gc monitoring uptime list-configs --filter='displayName="StartBy /healthz"' --format='value(name)' 2>/dev/null)" ]; then
  echo "   uptime check already exists"
else
  gc monitoring uptime create "StartBy /healthz" \
    --resource-type=uptime-url \
    --resource-labels="host=${DOMAIN},project_id=${PROJECT_ID}" \
    --protocol=https --path=/healthz --period=5 || \
    echo "   (uptime check not created: create it in Monitoring > Uptime checks for https://${DOMAIN}/healthz)"
fi
if [ -n "$(gc monitoring policies list --filter='displayName="StartBy /healthz is failing"' --format='value(name)' 2>/dev/null)" ]; then
  echo "   alert policy already exists"
else
  # GA command first; older gcloud versions only have it under `alpha`.
  gc monitoring policies create --policy-from-file "$HERE/alert-uptime.json" 2>/dev/null || \
    gc alpha monitoring policies create --policy-from-file "$HERE/alert-uptime.json" || \
    echo "   (alert policy not created: see deploy/gcp/alert-uptime.json, create it in the console)"
fi
echo "   NOTE: the alert policy has no notification channel, so it fires but emails nobody."
echo "   Add your email in Monitoring > Alerting > Edit notification channels."

echo
echo "All done. Remaining: seed demo data and rehearse backup/restore/rollback (README-deploy.md)."
