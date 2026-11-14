#!/usr/bin/env python3
"""Start the Airflow Compose stack without writing Secret Manager values to disk."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ID = "dataforge-p7-lab-d0f725"
REGION = "us-central1"
SERVICE_ACCOUNT = (
    "dataforge-week7-airflow@dataforge-p7-lab-d0f725.iam.gserviceaccount.com"
)
METADATA_ROOT = "http://metadata.google.internal/computeMetadata/v1"
SECRET_IDS = {
    "AIRFLOW_FERNET_KEY": "airflow-fernet-key",
    "POSTGRES_PASSWORD": "airflow-metadata-db-password",
    "AIRFLOW_ADMIN_PASSWORD": "airflow-admin-password",
}
COMPOSE_FILE = Path("/opt/dataforge/airflow_vm/compose.yaml")
SECRET_DIR = Path("/run/dataforge-airflow-secrets")
SECRET_FILE_NAMES = {
    "AIRFLOW_FERNET_KEY": "fernet_key",
    "POSTGRES_PASSWORD": "metadata_db_password",
    "AIRFLOW_ADMIN_PASSWORD": "admin_password",
}


class BootstrapError(RuntimeError):
    """A sanitized startup failure that contains no secret response body."""


def _request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
) -> bytes:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise BootstrapError(f"HTTP request failed with status {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BootstrapError(
            f"request failed ({type(exc).__name__}); response content was suppressed"
        ) from None


def _metadata(path: str, *, optional: bool = False) -> str | None:
    url = f"{METADATA_ROOT}/{path.lstrip('/')}"
    try:
        body = _request(url, headers={"Metadata-Flavor": "Google"})
    except BootstrapError as exc:
        if optional and str(exc) == "HTTP request failed with status 404":
            return None
        raise
    return body.decode("utf-8")


def _validate_image(image: str, project_id: str) -> None:
    expected = (
        rf"^{re.escape(REGION)}-docker\.pkg\.dev/"
        rf"{re.escape(project_id)}/dataforge-week7/airflow@sha256:[0-9a-f]{{64}}$"
    )
    if not re.fullmatch(expected, image):
        raise BootstrapError(
            "Airflow image must be the approved Artifact Registry image pinned by sha256 digest"
        )


def _decode_secret_response(body: bytes, secret_id: str) -> str:
    try:
        payload = json.loads(body)["payload"]["data"]
        value = base64.b64decode(payload, validate=True).decode("utf-8")
    except (KeyError, TypeError, ValueError, UnicodeDecodeError):
        raise BootstrapError(
            f"Secret Manager returned an invalid payload for {secret_id}"
        ) from None
    if not value or any(ord(character) < 32 for character in value):
        raise BootstrapError(f"Secret Manager payload for {secret_id} is invalid")
    return value


def _access_token() -> str:
    raw = _request(
        f"{METADATA_ROOT}/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    try:
        response = json.loads(raw)
        token = response["access_token"]
        if response.get("token_type") != "Bearer" or not isinstance(token, str):
            raise ValueError("invalid token response")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise BootstrapError("Metadata server returned an invalid access token response") from None
    return token


def _secret(token: str, project_id: str, secret_id: str) -> str:
    name = urllib.parse.quote(secret_id, safe="-")
    url = (
        "https://secretmanager.googleapis.com/v1/projects/"
        f"{project_id}/secrets/{name}/versions/latest:access"
    )
    raw = _request(url, headers={"Authorization": f"Bearer {token}"}, timeout=20)
    return _decode_secret_response(raw, secret_id)


def _validate_secrets(secrets: dict[str, str]) -> None:
    try:
        key_bytes = base64.b64decode(
            secrets["AIRFLOW_FERNET_KEY"],
            altchars=b"-_",
            validate=True,
        )
    except (KeyError, ValueError):
        raise BootstrapError("Airflow Fernet key is not a valid URL-safe key") from None
    if len(key_bytes) != 32:
        raise BootstrapError("Airflow Fernet key must decode to 32 bytes")
    for name in ("POSTGRES_PASSWORD", "AIRFLOW_ADMIN_PASSWORD"):
        value = secrets.get(name, "")
        if len(value) < 32 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise BootstrapError(f"{name} must be a strong URL-safe generated value")


def _is_run_tmpfs(mount_table: str) -> bool:
    for line in mount_table.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[1] == "/run" and fields[2] == "tmpfs":
            return True
    return False


def _verify_run_tmpfs() -> None:
    try:
        mount_table = Path("/proc/mounts").read_text(encoding="utf-8")
    except OSError:
        raise BootstrapError("Cannot verify that /run is a memory-backed filesystem") from None
    if not _is_run_tmpfs(mount_table):
        raise BootstrapError("Refusing to stage Secret Manager values outside /run tmpfs")


def _remove_secret_files(directory: Path | None = None) -> None:
    directory = directory or SECRET_DIR
    if directory.is_symlink():
        raise BootstrapError("Refusing to clean a symlink in the Airflow secret directory")
    if not directory.exists():
        return
    if not directory.is_dir():
        raise BootstrapError("Airflow secret path is not a directory")
    allowed_names = set(SECRET_FILE_NAMES.values())
    for path in directory.iterdir():
        if path.name not in allowed_names or path.is_dir():
            raise BootstrapError("Airflow secret directory contains an unexpected entry")
        if not path.is_symlink():
            os.chmod(path, 0o600)
        path.unlink()
    directory.rmdir()


def _write_secret_files(
    secret_values: dict[str, str],
    directory: Path | None = None,
) -> None:
    directory = directory or SECRET_DIR
    _remove_secret_files(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(directory, 0o700)
    for key, filename in SECRET_FILE_NAMES.items():
        value = secret_values[key]
        path = directory / filename
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o440)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(value)
                handle.flush()
            os.chmod(path, 0o440)
        except OSError:
            _remove_secret_files(directory)
            raise BootstrapError("Could not stage Secret Manager values in tmpfs") from None


def _compose_environment(
    project_id: str,
    email: str,
    image: str,
    cloud_enabled: str,
) -> dict[str, str]:
    return {
        "AIRFLOW_IMAGE": image,
        "DATAFORGE_GCP_PROJECT_ID": project_id,
        "DATAFORGE_AIRFLOW_SERVICE_ACCOUNT": email,
        "DATAFORGE_WEATHER_CLOUD_ENABLED": cloud_enabled,
        "DATAFORGE_SECRET_DIR": str(SECRET_DIR),
        "PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
    }


def _compose_command() -> list[str]:
    docker_compose = shutil.which("docker-compose")
    if docker_compose:
        return [docker_compose]
    return ["docker", "compose"]


def _compose_argv(args: list[str]) -> list[str]:
    return [
        *_compose_command(),
        "--file",
        str(COMPOSE_FILE),
        "--project-directory",
        str(COMPOSE_FILE.parent),
        *args,
    ]


def _run_compose(
    args: list[str],
    env: dict[str, str],
    *,
    persistent: bool = False,
) -> None:
    command = _compose_argv(args)
    if persistent:
        result = subprocess.run(command, check=False, env=env)
    else:
        result = subprocess.run(
            command,
            check=False,
            env=env,
            capture_output=True,
            text=True,
        )
    if result.returncode:
        # Compose can include expanded environment in diagnostics; never echo it.
        raise BootstrapError(
            f"Airflow Compose command failed (exit {result.returncode}); captured output suppressed"
        )
    if persistent:
        raise BootstrapError("Airflow Compose runtime exited unexpectedly")


def _wait_for_postgres(env: dict[str, str]) -> None:
    command = [
        *_compose_argv(["exec", "--no-TTY", "postgres", "pg_isready", "-U", "airflow", "-d", "airflow"])
    ]
    for _ in range(60):
        result = subprocess.run(
            command,
            check=False,
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return
        time.sleep(3)
    raise BootstrapError("PostgreSQL did not become ready within the startup bound")


def _validate_vm_identity() -> tuple[str, str, str, str]:
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        raise BootstrapError("attached identity mode forbids GOOGLE_APPLICATION_CREDENTIALS")
    project_id = _metadata("project/project-id")
    email = _metadata("instance/service-accounts/default/email")
    image = _metadata("instance/attributes/dataforge-airflow-image")
    cloud_enabled = _metadata(
        "instance/attributes/dataforge-weather-cloud-enabled",
        optional=True,
    )
    if project_id != PROJECT_ID or email != SERVICE_ACCOUNT:
        raise BootstrapError("VM project or attached service account is outside the approved target")
    if image is None:
        raise BootstrapError("VM metadata does not contain the digest-pinned Airflow image")
    _validate_image(image, project_id)
    if cloud_enabled not in (None, "false", "true"):
        raise BootstrapError("VM weather-cloud gate metadata must be exactly true or false")
    return project_id, email, image, cloud_enabled or "false"


def _start() -> None:
    project_id, email, image, cloud_enabled = _validate_vm_identity()
    token = _access_token()
    secret_values = {
        env_name: _secret(token, project_id, secret_id)
        for env_name, secret_id in SECRET_IDS.items()
    }
    del token
    _validate_secrets(secret_values)
    _verify_run_tmpfs()
    _write_secret_files(secret_values)
    runtime_env = _compose_environment(project_id, email, image, cloud_enabled)
    try:
        _run_compose(
            ["up", "--detach", "--remove-orphans", "--no-build", "postgres"],
            runtime_env,
        )
        _wait_for_postgres(runtime_env)
        _run_compose(["run", "--rm", "--no-deps", "airflow-init"], runtime_env)
        print("Airflow metadata, pool, and FAB admin bootstrap completed.")
        _run_compose(
            [
                "up",
                "--no-deps",
                "--abort-on-container-exit",
                "--no-build",
                "airflow-api-server",
                "airflow-scheduler",
                "airflow-dag-processor",
                "airflow-triggerer",
            ],
            runtime_env,
            persistent=True,
        )
    except BootstrapError:
        try:
            _run_compose(["down", "--remove-orphans"], runtime_env)
        finally:
            _remove_secret_files()
        raise
    del runtime_env
    del secret_values
    print("Airflow Compose runtime exited unexpectedly.")


def _stop() -> None:
    _run_compose(
        ["down", "--remove-orphans"],
        _compose_environment(
            PROJECT_ID,
            SERVICE_ACCOUNT,
            "dataforge-airflow-runtime:unset",
            "false",
        ),
    )
    _remove_secret_files()
    print("Airflow Compose services stopped.")


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "up"
    if action not in ("up", "down"):
        print("Usage: bootstrap.py [up|down]", file=sys.stderr)
        return 2
    try:
        if action == "up":
            _start()
        else:
            _stop()
    except BootstrapError as exc:
        print(f"Airflow bootstrap failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
