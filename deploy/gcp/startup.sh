#!/usr/bin/env bash
# Compute Engine startup script: runs as root on every boot, so it must be
# safe to re-run. Reads its settings from instance metadata (set by
# provision.sh), installs the Ops Agent (Cloud Logging + Monitoring), then
# hands over to deploy/setup.sh for the app itself.
set -euo pipefail
meta() { curl -fs -H 'Metadata-Flavor: Google' \
  "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1" || true; }

REPO_URL="$(meta startby-repo)"
mkdir -p /var/log/startby && chown www-data:www-data /var/log/startby 2>/dev/null || true

# 1 GB of RAM and no swap: a pip install or a memory spike gets the OOM killer.
# A 1 GB swapfile (on the 30 GB boot disk) is cheap insurance; made once.
make_swap() {
  swapon --show | grep -q . && return 0   # some swap already exists
  if [ ! -f /swapfile ]; then
    { fallocate -l 1G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=1024; } &&
      chmod 600 /swapfile && mkswap /swapfile || return 1
  fi
  swapon /swapfile || return 1
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
}
make_swap || echo "WARNING: could not create the swapfile; continuing without swap" >&2

# The Ops Agent is monitoring/logging only: a download or repo hiccup must not
# stop the app from being installed below.
OPS_AGENT_OK=0
if systemctl is-active --quiet google-cloud-ops-agent; then
  OPS_AGENT_OK=1
elif curl -fsSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh \
    && bash add-google-cloud-ops-agent-repo.sh --also-install; then
  OPS_AGENT_OK=1
else
  echo "WARNING: Ops Agent install failed; continuing without it (logs stay in journald)" >&2
fi
if [ "$OPS_AGENT_OK" = 1 ]; then
cat > /etc/google-cloud-ops-agent/config.yaml <<'YAML'
logging:
  receivers:
    startby_app:
      type: files
      include_paths: [/var/log/startby/app.log]
  processors:
    startby_json:
      type: parse_json
      time_key: time
      time_format: "%Y-%m-%dT%H:%M:%S%z"
    startby_severity:
      type: modify_fields
      fields:
        severity:
          move_from: jsonPayload.severity
  service:
    pipelines:
      startby:
        receivers: [startby_app]
        processors: [startby_json, startby_severity]
YAML
systemctl restart google-cloud-ops-agent || true
fi

cat > /etc/logrotate.d/startby <<'ROTATE'
/var/log/startby/app.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    copytruncate
}
ROTATE

# First boot: fetch the code and run the normal installer. Needs a repo the VM
# can clone anonymously over https (a public repo, or swap in a deploy token).
# Guarded on .env (written by setup.sh), not .git: a clone that succeeded but a
# setup that failed (apt lock at first boot, a pip hiccup) is retried next boot.
if [ -n "$REPO_URL" ] && [ ! -f /opt/startby/.env ]; then
  apt-get -o DPkg::Lock::Timeout=300 update
  apt-get -o DPkg::Lock::Timeout=300 install -y git
  [ -d /opt/startby/.git ] || git clone "$REPO_URL" /opt/startby
  STARTBY_REPO_URL="$REPO_URL" USER=root \
    GCP_PROJECT="$(meta startby-project)" DOMAIN="$(meta startby-domain)" \
    bash /opt/startby/deploy/setup.sh
fi
