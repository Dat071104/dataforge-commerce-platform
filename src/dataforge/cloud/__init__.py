"""Opt-in GCP adapters; importing the local DataForge package needs no GCP SDK."""

from .adapters import (
    CloudAdapterError,
    DataIntegrityError,
    LocationMismatchError,
    ManifestError,
    PermissionDeniedError,
    SnapshotNotFoundError,
    ValidatedSnapshot,
    load_validated_snapshot,
    preflight_snapshot,
    transfer_snapshot,
)

__all__ = [
    "CloudAdapterError",
    "DataIntegrityError",
    "LocationMismatchError",
    "ManifestError",
    "PermissionDeniedError",
    "SnapshotNotFoundError",
    "ValidatedSnapshot",
    "load_validated_snapshot",
    "preflight_snapshot",
    "transfer_snapshot",
]
