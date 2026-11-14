"""Create the initial database-backed Airflow admin without password argv/logging."""

from __future__ import annotations

import os
from pathlib import Path

from airflow.providers.fab.auth_manager.cli_commands.user_command import (
    get_application_builder,
)

ADMIN_USERNAME = "dataforge-admin"
ADMIN_EMAIL = "dataforge-admin@example.com"


def ensure_admin() -> None:
    password_file = Path(
        os.environ.get(
            "DATAFORGE_AIRFLOW_ADMIN_PASSWORD_FILE",
            "/run/secrets/admin_password",
        )
    )
    if password_file != Path("/run/secrets/admin_password"):
        raise RuntimeError("The admin password must use its dedicated tmpfs secret mount")
    try:
        password = password_file.read_text(encoding="utf-8")
    except OSError:
        raise RuntimeError("The Secret Manager admin password mount is unavailable") from None
    if len(password) < 32 or any(ord(character) < 32 for character in password):
        raise RuntimeError("The Secret Manager admin password is missing or invalid")

    with get_application_builder() as appbuilder:
        security_manager = appbuilder.sm
        existing = security_manager.find_user(username=ADMIN_USERNAME)
        if existing is not None:
            roles = {role.name for role in existing.roles}
            if not existing.active or "Admin" not in roles:
                raise RuntimeError("The existing bootstrap account is not an active Admin")
            return

        admin_role = security_manager.find_role("Admin")
        if admin_role is None:
            raise RuntimeError("The FAB Admin role was not initialized")
        user = security_manager.add_user(
            ADMIN_USERNAME,
            "DataForge",
            "Administrator",
            ADMIN_EMAIL,
            admin_role,
            password=password,
        )
        if not user:
            raise RuntimeError("FAB could not create the initial Airflow admin")


if __name__ == "__main__":
    ensure_admin()
