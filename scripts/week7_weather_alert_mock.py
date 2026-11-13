"""Build an in-memory, non-delivering mock for the Mini-project 3 alert contract."""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass

NORMAL_STATUSES = {"NO_NEW_BATCH", "SOURCE_NOT_READY"}
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


@dataclass(frozen=True)
class MockDelivery:
    """An in-memory event; it has no network or email transport."""

    status: str
    payload: dict[str, str]


def prepare_mock_delivery(
    *,
    run_id: str,
    status: str,
    stage: str,
    error_category: str | None,
) -> MockDelivery | None:
    """Return a redacted mock for terminal failures and ignore normal outcomes."""
    if status in NORMAL_STATUSES:
        return None
    if status != "FAILED":
        raise ValueError("only terminal FAILED or a recognized normal status is supported")
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("run_id must be a bounded safe identifier")
    if not SAFE_TOKEN.fullmatch(stage):
        raise ValueError("stage must be a bounded safe token")
    if not error_category or not SAFE_TOKEN.fullmatch(error_category):
        raise ValueError("error_category must be a bounded safe token")

    return MockDelivery(
        status="MOCK_ONLY",
        payload={
            "event": "DATAFORGE_WEATHER_FAILURE",
            "run_id": run_id,
            "stage": stage,
            "error_category": error_category,
            "external_delivery": "false",
            "destination": "NOT_CONFIGURED",
        },
    )


class MemoryNotificationSink:
    """Test double for exercising alert routing without any external delivery."""

    def __init__(self) -> None:
        self.events: list[dict[str, str]] = []

    def send(self, delivery: MockDelivery) -> None:
        if delivery.status != "MOCK_ONLY":
            raise ValueError("the mock sink accepts only MOCK_ONLY events")
        self.events.append(dict(delivery.payload))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", choices=["FAILED", *sorted(NORMAL_STATUSES)], required=True)
    parser.add_argument("--run-id", default="mock-weather-run-001")
    parser.add_argument("--stage", default="dbt_test")
    parser.add_argument("--error-category", default="quality_gate")
    args = parser.parse_args(argv)

    delivery = prepare_mock_delivery(
        run_id=args.run_id,
        status=args.status,
        stage=args.stage,
        error_category=args.error_category if args.status == "FAILED" else None,
    )
    sink = MemoryNotificationSink()
    if delivery is not None:
        sink.send(delivery)
    print(
        json.dumps(
            {
                "mode": "mock_only",
                "status": args.status,
                "prepared": delivery is not None,
                "external_delivery": False,
                "events": sink.events,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
