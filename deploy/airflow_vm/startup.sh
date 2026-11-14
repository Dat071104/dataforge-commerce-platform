#!/usr/bin/env bash
set -Eeuo pipefail

LOG_TAG=dataforge-airflow-startup
exec > >(logger -t "${LOG_TAG}") 2>&1

metadata() {
  curl --fail --silent --show-error \
    -H 'Metadata-Flavor: Google' \
    "http://metadata.google.internal/computeMetadata/v1/$1"
}

readonly IMAGE="$(metadata instance/attributes/dataforge-airflow-image)"
readonly PROJECT_ID="$(metadata project/project-id)"
readonly REGISTRY="us-central1-docker.pkg.dev"
readonly AUTH_DIR="/run/dataforge-airflow-docker-auth"
readonly BUNDLE_CONTAINER="dataforge-airflow-runtime-bundle"
readonly INSTALL_DIR="/opt/dataforge/airflow_vm"

if [[ "$PROJECT_ID" != "dataforge-p7-lab-d0f725" ]]; then
  echo "Startup rejected: unexpected project metadata."
  exit 1
fi
if [[ ! "$IMAGE" =~ ^us-central1-docker\.pkg\.dev/dataforge-p7-lab-d0f725/dataforge-week7/airflow@sha256:[0-9a-f]{64}$ ]]; then
  echo "Startup rejected: Airflow image must be digest-pinned in the approved repository."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install --yes --no-install-recommends docker.io docker-compose python3 curl ca-certificates
systemctl enable --now docker

install -d -m 0700 "$AUTH_DIR"
export DOCKER_CONFIG="$AUTH_DIR"
cleanup_registry_auth() {
  rm -rf -- "$AUTH_DIR"
  unset DOCKER_CONFIG TOKEN TOKEN_JSON
}
trap cleanup_registry_auth EXIT
TOKEN_JSON="$(metadata instance/service-accounts/default/token)"
TOKEN="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' <<<"$TOKEN_JSON")"
unset TOKEN_JSON
printf '%s' "$TOKEN" | docker login \
  --username oauth2accesstoken \
  --password-stdin \
  "https://${REGISTRY}" >/dev/null
unset TOKEN
docker pull "$IMAGE"
docker logout "https://${REGISTRY}" >/dev/null 2>&1 || true
cleanup_registry_auth
trap - EXIT

install -d -m 0755 "$INSTALL_DIR"
docker create --name "$BUNDLE_CONTAINER" --entrypoint /bin/true "$IMAGE" >/dev/null
docker cp "$BUNDLE_CONTAINER:/opt/dataforge/airflow_vm/compose.yaml" "$INSTALL_DIR/compose.yaml"
docker cp "$BUNDLE_CONTAINER:/opt/dataforge/airflow_vm/bootstrap.py" "$INSTALL_DIR/bootstrap.py"
docker cp "$BUNDLE_CONTAINER:/opt/dataforge/airflow_vm/fab_admin_bootstrap.py" "$INSTALL_DIR/fab_admin_bootstrap.py"
docker cp "$BUNDLE_CONTAINER:/opt/dataforge/airflow_vm/secret_command.py" "$INSTALL_DIR/secret_command.py"
docker cp "$BUNDLE_CONTAINER:/opt/dataforge/airflow_vm/dataforge-airflow.service" /etc/systemd/system/dataforge-airflow.service
docker rm "$BUNDLE_CONTAINER" >/dev/null
chmod 0755 "$INSTALL_DIR/bootstrap.py"
chmod 0644 "$INSTALL_DIR/compose.yaml" "$INSTALL_DIR/fab_admin_bootstrap.py" "$INSTALL_DIR/secret_command.py"
chmod 0644 /etc/systemd/system/dataforge-airflow.service

systemctl daemon-reload
systemctl enable --now dataforge-airflow.service

echo "Airflow runtime bootstrap completed; Secret Manager payloads were not written to files."
