from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.airflow_vm import bootstrap


class BootstrapTests(unittest.TestCase):
    def test_image_requires_exact_project_repository_and_sha256_digest(self) -> None:
        valid = (
            "us-central1-docker.pkg.dev/dataforge-p7-lab-d0f725/"
            "dataforge-week7/airflow@sha256:" + "a" * 64
        )
        bootstrap._validate_image(valid, bootstrap.PROJECT_ID)
        for invalid in (
            valid.replace("@sha256:", ":"),
            valid.replace("dataforge-p7-lab-d0f725", "other-project"),
            valid[:-1] + "Z",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap._validate_image(invalid, bootstrap.PROJECT_ID)

    def test_secret_payload_decodes_without_disclosing_value(self) -> None:
        value = b"f" * 32
        payload = json.dumps(
            {"payload": {"data": base64.b64encode(value).decode("ascii")}}
        ).encode("utf-8")
        self.assertEqual(
            bootstrap._decode_secret_response(payload, "airflow-fernet-key"),
            value.decode("utf-8"),
        )

    def test_invalid_secret_response_is_sanitized(self) -> None:
        with self.assertRaisesRegex(
            bootstrap.BootstrapError,
            "invalid payload for airflow-admin-password",
        ):
            bootstrap._decode_secret_response(b'{"error":"private"}', "airflow-admin-password")

    def test_fernet_and_generated_passwords_are_validated(self) -> None:
        fernet_key = base64.urlsafe_b64encode(b"f" * 32).decode("ascii")
        values = {
            "AIRFLOW_FERNET_KEY": fernet_key,
            "POSTGRES_PASSWORD": "p" * 48,
            "AIRFLOW_ADMIN_PASSWORD": "a" * 48,
        }
        bootstrap._validate_secrets(values)
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap._validate_secrets({**values, "POSTGRES_PASSWORD": "unsafe value"})

    def test_run_mount_detection_requires_tmpfs(self) -> None:
        self.assertTrue(
            bootstrap._is_run_tmpfs("rootfs / rootfs rw 0 0\ntmpfs /run tmpfs rw 0 0")
        )
        self.assertFalse(bootstrap._is_run_tmpfs("rootfs / rootfs rw 0 0\n/dev/sda /run ext4 rw 0 0"))

    def test_secret_files_are_restrictive_and_removed_after_compose_stops(self) -> None:
        values = {
            "AIRFLOW_FERNET_KEY": base64.urlsafe_b64encode(b"f" * 32).decode("ascii"),
            "POSTGRES_PASSWORD": "p" * 48,
            "AIRFLOW_ADMIN_PASSWORD": "a" * 48,
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "secrets"
            bootstrap._write_secret_files(values, directory)
            self.assertEqual(
                {path.name for path in directory.iterdir()},
                {"fernet_key", "metadata_db_password", "admin_password"},
            )
            self.assertEqual((directory / "fernet_key").read_text(), values["AIRFLOW_FERNET_KEY"])
            if os.name == "posix":
                self.assertEqual((directory / "fernet_key").stat().st_mode & 0o777, 0o440)
            bootstrap._remove_secret_files(directory)
            self.assertFalse(directory.exists())

    def test_compose_environment_contains_secret_paths_not_secret_values(self) -> None:
        env = bootstrap._compose_environment(
            bootstrap.PROJECT_ID,
            bootstrap.SERVICE_ACCOUNT,
            "us-central1-docker.pkg.dev/dataforge-p7-lab-d0f725/"
            "dataforge-week7/airflow@sha256:" + "c" * 64,
            "false",
        )
        self.assertNotIn("POSTGRES_PASSWORD", env)
        self.assertNotIn("AIRFLOW_FERNET_KEY", env)
        self.assertNotIn("AIRFLOW_ADMIN_PASSWORD", env)
        self.assertEqual(env["DATAFORGE_SECRET_DIR"], str(bootstrap.SECRET_DIR))

    def test_start_mounts_secrets_from_tmpfs_without_passing_values_to_compose(self) -> None:
        fernet_key = base64.urlsafe_b64encode(b"f" * 32).decode("ascii")
        values = {
            "airflow-fernet-key": fernet_key,
            "airflow-metadata-db-password": "p" * 48,
            "airflow-admin-password": "a" * 48,
        }
        with tempfile.TemporaryDirectory() as temporary:
            secret_dir = Path(temporary) / "airflow-secrets"
            with (
                patch.object(bootstrap, "SECRET_DIR", secret_dir),
                patch.object(
                    bootstrap,
                    "_validate_vm_identity",
                    return_value=(
                        bootstrap.PROJECT_ID,
                        bootstrap.SERVICE_ACCOUNT,
                        "us-central1-docker.pkg.dev/dataforge-p7-lab-d0f725/"
                        "dataforge-week7/airflow@sha256:" + "d" * 64,
                        "false",
                    ),
                ),
                patch.object(bootstrap, "_access_token", return_value="test-token"),
                patch.object(
                    bootstrap,
                    "_secret",
                    side_effect=lambda token, project, secret_id: values[secret_id],
                ),
                patch.object(bootstrap, "_verify_run_tmpfs"),
                patch.object(bootstrap, "_wait_for_postgres"),
            ):
                compose_calls = []

                def fake_compose(args, env, *, persistent=False):
                    compose_calls.append((args, env, persistent))
                    if persistent:
                        raise bootstrap.BootstrapError("runtime exited for smoke test")

                with (
                    patch.object(bootstrap, "_run_compose", side_effect=fake_compose),
                    self.assertRaisesRegex(bootstrap.BootstrapError, "runtime exited for smoke test"),
                ):
                    bootstrap._start()

                self.assertEqual(len(compose_calls), 4)
                for _, environment, _ in compose_calls:
                    serialized_environment = repr(environment)
                    for secret_value in values.values():
                        self.assertNotIn(secret_value, serialized_environment)
                self.assertFalse(secret_dir.exists())

    def test_metadata_identity_defaults_weather_gate_to_off(self) -> None:
        metadata = {
            "project/project-id": bootstrap.PROJECT_ID,
            "instance/service-accounts/default/email": bootstrap.SERVICE_ACCOUNT,
            "instance/attributes/dataforge-airflow-image": (
                "us-central1-docker.pkg.dev/dataforge-p7-lab-d0f725/"
                "dataforge-week7/airflow@sha256:" + "b" * 64
            ),
        }
        with patch.object(bootstrap, "_metadata", side_effect=lambda path, **_: metadata.get(path)):
            self.assertEqual(
                bootstrap._validate_vm_identity(),
                (
                    bootstrap.PROJECT_ID,
                    bootstrap.SERVICE_ACCOUNT,
                    metadata["instance/attributes/dataforge-airflow-image"],
                    "false",
                ),
            )

    def test_attached_identity_rejects_adc_file(self) -> None:
        with patch.dict("os.environ", {"GOOGLE_APPLICATION_CREDENTIALS": "/tmp/adc.json"}):
            with self.assertRaisesRegex(
                bootstrap.BootstrapError,
                "forbids GOOGLE_APPLICATION_CREDENTIALS",
            ):
                bootstrap._validate_vm_identity()


if __name__ == "__main__":
    unittest.main()
