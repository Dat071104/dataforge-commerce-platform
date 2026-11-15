from importlib import metadata
from pathlib import Path, PurePosixPath


def _read_required(path: Path, marker: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"required license file is missing: {path.name}")
    contents = path.read_text(encoding="utf-8")
    if marker not in contents:
        raise RuntimeError(f"license file has unexpected contents: {path.name}")


def _distribution_license_file(
    package: str, filename: str, expected_version: str | None = None
) -> Path:
    dist = metadata.distribution(package)
    if expected_version is not None and dist.version != expected_version:
        raise RuntimeError(f"unexpected package version for {package}")

    for item in dist.files or ():
        relative_path = PurePosixPath(str(item))
        if relative_path.name.casefold() != filename.casefold():
            continue
        if not any(part.casefold().endswith(".dist-info") for part in relative_path.parts):
            continue

        path = Path(dist.locate_file(item))
        if path.is_file() and path.stat().st_size > 0:
            return path

    raise RuntimeError(f"{filename} is missing from the {package} distribution")


def main() -> None:
    _read_required(Path("/opt/dataforge/LICENSE"), "MIT License")
    for package in ("apache-airflow", "apache-airflow-core"):
        for filename in ("LICENSE", "NOTICE"):
            _distribution_license_file(package, filename, expected_version="3.4.0")
    google_packages = {
        "google-auth": "2.62.0",
        "google-cloud-bigquery": "3.47.0",
        "google-cloud-storage": "3.17.1",
    }
    for package, version in google_packages.items():
        _distribution_license_file(package, "LICENSE", expected_version=version)

    print("Runtime image license check passed for DataForge, Airflow, and GCP client wheels.")


if __name__ == "__main__":
    main()
