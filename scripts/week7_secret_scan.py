"""Scan tracked and nonignored repository files for common credential material.

Ignored local profiles, Terraform state, ADC files, and .env files are excluded
from Git already; they are intentionally not opened by this repository scan.
Findings print only the path and detector name, never the matched value.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_EXTENSIONS = {
    ".cfg",
    ".conf",
    ".csv",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sql",
    ".tf",
    ".txt",
    ".toml",
    ".yml",
    ".yaml",
}
DETECTORS = {
    "private_key": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE
    ),
    "google_oauth_token": re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "oauth_client_secret": re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "oauth_refresh_token": re.compile(
        r"\"refresh_token\"\s*:\s*\"[A-Za-z0-9/_-]{30,}\""
    ),
}


def repository_files(root: Path = ROOT) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    paths = [root / raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw]
    return [
        path
        for path in paths
        if path.suffix.lower() in TEXT_EXTENSIONS and path.is_file()
    ]


def scan_files(paths: list[Path], root: Path = ROOT) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(lines, start=1):
            for name, pattern in DETECTORS.items():
                if pattern.search(line):
                    findings.append(
                        (path.relative_to(root).as_posix(), line_number, name)
                    )
    return findings


def main() -> int:
    files = repository_files()
    findings = scan_files(files)
    if findings:
        for path, line_number, detector in findings:
            print(f"SECRET_SCAN_FINDING path={path} line={line_number} detector={detector}")
        print(f"SECRET_SCAN_STATUS=FAIL findings={len(findings)} files_scanned={len(files)}")
        return 1
    print(f"SECRET_SCAN_STATUS=PASS findings=0 files_scanned={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
