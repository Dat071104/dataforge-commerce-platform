"""No-network smoke test for FAB initialization and hashed admin persistence."""

from __future__ import annotations

import base64
import logging
import os
import runpy
import subprocess
from pathlib import Path
from urllib.parse import quote

from airflow.providers.fab.auth_manager.cli_commands.user_command import (
    get_application_builder,
)
from werkzeug.security import check_password_hash

BOOTSTRAP = runpy.run_path(
    "/opt/dataforge/airflow_vm/fab_admin_bootstrap.py",
    run_name="airflow_vm_fab_bootstrap",
)
SECRET_COMMAND = "/opt/dataforge/airflow_vm/secret_command.py"


def _config_value(section: str, key: str, env: dict[str, str]) -> str:
    result = subprocess.run(
        ["airflow", "config", "get-value", section, key],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode:
        raise RuntimeError(
            f"Airflow config command failed for {section}.{key}; output suppressed"
        )
    return result.stdout.strip()


def main() -> None:
    password = os.environ.get("DATAFORGE_TEST_ADMIN_PASSWORD", "")
    if len(password) < 32:
        raise RuntimeError("Smoke test requires a non-secret placeholder of at least 32 characters")

    password_file = Path("/run/secrets/admin_password")
    password_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fernet_key = base64.urlsafe_b64encode(b"f" * 32).decode("ascii")
    database_password = "ci-placeholder-db-password-0123456789"
    (password_file.parent / "fernet_key").write_text(fernet_key, encoding="utf-8")
    (password_file.parent / "metadata_db_password").write_text(
        database_password,
        encoding="utf-8",
    )
    password_file.write_text("too-short", encoding="utf-8")
    os.chmod(password_file, 0o440)
    os.chmod(password_file.parent / "fernet_key", 0o440)
    os.chmod(password_file.parent / "metadata_db_password", 0o440)
    os.environ["DATAFORGE_AIRFLOW_ADMIN_PASSWORD_FILE"] = str(password_file)
    try:
        BOOTSTRAP["ensure_admin"]()
    except RuntimeError:
        pass
    else:
        raise AssertionError("FAB bootstrap accepted a short admin password")
    finally:
        os.chmod(password_file, 0o600)
        password_file.write_text(password, encoding="utf-8")
        os.chmod(password_file, 0o440)

    command_env = os.environ.copy()
    command_env.pop("AIRFLOW__DATABASE__SQL_ALCHEMY_CONN", None)
    command_env.update(
        {
            "AIRFLOW__CORE__FERNET_KEY_CMD": f"python {SECRET_COMMAND} fernet-key",
            "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN_CMD": (
                f"python {SECRET_COMMAND} database-url"
            ),
            "AIRFLOW__API__SECRET_KEY_CMD": f"python {SECRET_COMMAND} api-secret",
            "AIRFLOW__API_AUTH__JWT_SECRET_CMD": f"python {SECRET_COMMAND} jwt-secret",
        }
    )
    if _config_value("core", "fernet_key", command_env) != fernet_key:
        raise AssertionError("Airflow did not resolve the Fernet key from its tmpfs command")
    database_url = _config_value("database", "sql_alchemy_conn", command_env)
    if not database_url.endswith(f"{quote(database_password, safe='')}@postgres:5432/airflow"):
        raise AssertionError("Airflow did not resolve the metadata DB URL from its tmpfs command")
    api_secret = _config_value("api", "secret_key", command_env)
    jwt_secret = _config_value("api_auth", "jwt_secret", command_env)
    if len(api_secret) != 64 or len(jwt_secret) != 64 or api_secret == jwt_secret:
        raise AssertionError("Airflow did not resolve separate API and JWT command secrets")

    migration = subprocess.run(
        ["airflow", "db", "migrate"],
        check=False,
        capture_output=True,
        text=True,
    )
    if migration.returncode:
        raise RuntimeError(
            f"Airflow metadata migration failed with exit {migration.returncode}; output suppressed"
        )

    logging.disable(logging.CRITICAL)
    BOOTSTRAP["ensure_admin"]()
    with get_application_builder() as appbuilder:
        user = appbuilder.sm.find_user(username=BOOTSTRAP["ADMIN_USERNAME"])
        if user is None or not user.active:
            raise AssertionError("FAB bootstrap did not create an active admin")
        if not any(role.name == "Admin" for role in user.roles):
            raise AssertionError("FAB bootstrap account is missing the Admin role")
        if user.password == password or not check_password_hash(user.password, password):
            raise AssertionError("FAB did not persist a password hash")

    airflow_home_password_file = (
        Path(os.environ["AIRFLOW_HOME"])
        / "simple_auth_manager_passwords.json.generated"
    )
    if airflow_home_password_file.exists():
        raise AssertionError("SimpleAuthManager generated an admin password file")
    for path in password_file.parent.iterdir():
        path.unlink()
    print("fab_admin_created=True password_hash_valid=True plaintext_stored=False simpleauth_file_absent=True")


if __name__ == "__main__":
    main()
