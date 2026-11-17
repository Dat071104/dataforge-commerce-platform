"""Local-only resource guards before the Week 8 Compose stack starts."""

from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path

STACK_MEMORY_MIB = 5_376
MIN_FREE_MEMORY_MIB = 6_144


def available_memory_mib() -> int:
    """Return host available physical memory, without starting Docker."""
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError("GlobalMemoryStatusEx failed")
        return int(status.ullAvailPhys // (1024 * 1024))

    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values = {}
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            if key in {"MemAvailable", "MemFree"}:
                values[key] = int(value.strip().split()[0])
        available_kib = values.get("MemAvailable", values.get("MemFree"))
        if available_kib is not None:
            return available_kib // 1024
    raise OSError("cannot determine available physical memory on this host")


def docker_memory_mib() -> int:
    """Read the Docker daemon memory limit; this does not start a container."""
    result = subprocess.run(
        ["docker", "info", "--format", "{{.MemTotal}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return int(result.stdout.strip()) // (1024 * 1024)


def assert_stack_memory_budget(
    *, minimum_free_mib: int = MIN_FREE_MEMORY_MIB, stack_mib: int = STACK_MEMORY_MIB
) -> tuple[int, int]:
    available = available_memory_mib()
    docker_available = docker_memory_mib()
    if available < minimum_free_mib:
        raise RuntimeError(
            f"Week 8 requires at least {minimum_free_mib} MiB free RAM; "
            f"the host reports {available} MiB. No containers were started."
        )
    if docker_available < stack_mib:
        raise RuntimeError(
            f"Week 8 Compose memory caps total {stack_mib} MiB, but Docker has "
            f"only {docker_available} MiB. No containers were started."
        )
    return available, docker_available
