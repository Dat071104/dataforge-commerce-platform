from __future__ import annotations

import pytest

from labs.streaming_cdc.preflight import (
    MIN_FREE_MEMORY_MIB,
    STACK_MEMORY_MIB,
    assert_stack_memory_budget,
)


def test_memory_preflight_allows_the_pinned_stack_with_headroom(monkeypatch):
    monkeypatch.setattr("labs.streaming_cdc.preflight.available_memory_mib", lambda: MIN_FREE_MEMORY_MIB)
    monkeypatch.setattr("labs.streaming_cdc.preflight.docker_memory_mib", lambda: STACK_MEMORY_MIB)

    assert assert_stack_memory_budget() == (MIN_FREE_MEMORY_MIB, STACK_MEMORY_MIB)


def test_memory_preflight_refuses_host_memory_below_the_budget(monkeypatch):
    monkeypatch.setattr("labs.streaming_cdc.preflight.available_memory_mib", lambda: MIN_FREE_MEMORY_MIB - 1)
    monkeypatch.setattr("labs.streaming_cdc.preflight.docker_memory_mib", lambda: STACK_MEMORY_MIB)

    with pytest.raises(RuntimeError, match="No containers were started"):
        assert_stack_memory_budget()


def test_memory_preflight_refuses_a_docker_memory_limit_below_the_stack(monkeypatch):
    monkeypatch.setattr("labs.streaming_cdc.preflight.available_memory_mib", lambda: MIN_FREE_MEMORY_MIB)
    monkeypatch.setattr("labs.streaming_cdc.preflight.docker_memory_mib", lambda: STACK_MEMORY_MIB - 1)

    with pytest.raises(RuntimeError, match="No containers were started"):
        assert_stack_memory_budget()
