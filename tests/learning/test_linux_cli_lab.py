from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "labs" / "learning" / "linux_cli_lab.sh"
README = ROOT / "labs" / "learning" / "README.md"


@pytest.mark.skipif(os.name == "nt", reason="the shell lab is exercised on Linux CI")
def test_linux_cli_lab_uses_common_tools_and_sets_private_permissions(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.fail("Linux CI must provide bash for the CLI mini-lab")

    result = subprocess.run(
        [bash, str(SCRIPT), str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "delivered_total=135.50" in result.stdout
    assert "delivered_rows=2" in result.stdout
    assert "permission_mode=600" in result.stdout
    assert (tmp_path / "delivered.csv").read_text(encoding="utf-8").splitlines() == [
        "order_id,status,amount",
        "O001,Delivered,100.00",
        "O003,Delivered,35.50",
    ]


def test_linux_cli_readme_has_crontab_example_and_exactly_five_ssh_lines() -> None:
    text = README.read_text(encoding="utf-8")
    assert "15 6 * * *" in text
    ssh_section = text.split("## SSH in five lines", maxsplit=1)[1]
    numbered_lines = [line for line in ssh_section.splitlines() if line[:1].isdigit() and ". " in line]
    assert len(numbered_lines) == 5
