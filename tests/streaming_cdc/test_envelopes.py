from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest

from labs.streaming_cdc.envelopes import (
    decode_confluent_avro,
    decode_debezium_envelope,
    to_order_change_row,
    unpack_confluent_frame,
)
from labs.streaming_cdc.operations import OP_DELETE, OP_TOMBSTONE, OP_UPSERT

fastavro = pytest.importorskip(
    "fastavro", reason="Week 8 CI installs the lane's Avro test dependency"
)
parse_schema = fastavro.parse_schema
schemaless_writer = fastavro.schemaless_writer

ORDER = {
    "type": "record",
    "name": "Order",
    "fields": [
        {"name": "order_id", "type": "string"},
        {"name": "customer_id", "type": "string"},
        {
            "name": "order_date",
            "type": {"type": "int", "connect.name": "io.debezium.time.Date"},
        },
        {"name": "province_id", "type": "string"},
        {"name": "status", "type": "string"},
        {
            "name": "order_net_amount",
            "type": {
                "type": "bytes",
                "connect.name": "org.apache.kafka.connect.data.Decimal",
                "connect.parameters": {"scale": "2"},
            },
        },
        {
            "name": "event_time",
            "type": {"type": "string", "connect.name": "io.debezium.time.ZonedTimestamp"},
        },
    ],
}
SCHEMA = parse_schema(
    {
        "type": "record",
        "name": "Envelope",
        "namespace": "dataforge.tests",
        "fields": [
            {"name": "before", "type": ["null", ORDER], "default": None},
            {"name": "after", "type": ["null", "dataforge.tests.Order"], "default": None},
            {
                "name": "source",
                "type": {
                    "type": "record",
                    "name": "Source",
                    "fields": [
                        {"name": "lsn", "type": ["null", "long"], "default": None},
                        {"name": "ts_ms", "type": ["null", "long"], "default": None},
                    ],
                },
            },
            {
                "name": "transaction",
                "type": [
                    "null",
                    {
                        "type": "record",
                        "name": "Transaction",
                        "fields": [{"name": "total_order", "type": ["null", "long"], "default": None}],
                    },
                ],
                "default": None,
            },
            {"name": "op", "type": "string"},
            {"name": "ts_ms", "type": "long"},
        ],
    }
)


def _decimal_bytes(value: str) -> bytes:
    scaled = int(Decimal(value) * 100)
    length = max(1, (scaled.bit_length() + 8) // 8)
    while True:
        try:
            return scaled.to_bytes(length, byteorder="big", signed=True)
        except OverflowError:
            length += 1


def _order(status: str, amount: str = "10.00") -> dict:
    return {
        "order_id": "ord-1",
        "customer_id": "customer-1",
        "order_date": (date(2026, 11, 17) - date(1970, 1, 1)).days,
        "province_id": "province-1",
        "status": status,
        "order_net_amount": _decimal_bytes(amount),
        "event_time": "2026-11-17T10:00:00Z",
    }


def _frame(envelope: dict, schema_id: int = 42) -> bytes:
    payload = BytesIO()
    schemaless_writer(payload, SCHEMA, envelope)
    return b"\x00" + schema_id.to_bytes(4, "big") + payload.getvalue()


def _envelope(op: str, before=None, after=None, *, lsn=101, total_order=1):
    return {
        "before": before,
        "after": after,
        "source": {"lsn": lsn, "ts_ms": 1760000000000},
        "transaction": {"total_order": total_order},
        "op": op,
        "ts_ms": 1760000000100,
    }


@pytest.mark.parametrize(
    ("op", "before", "after", "expected_operation"),
    [
        ("c", None, _order("created"), "upsert"),
        ("r", None, _order("created"), "upsert"),
        ("u", _order("created"), _order("paid", "12.00"), "upsert"),
        ("d", _order("paid", "12.00"), None, "delete"),
    ],
)
def test_avro_frame_decodes_debezium_cudr_envelopes(op, before, after, expected_operation):
    message = _frame(_envelope(op, before, after))
    decoded = decode_confluent_avro(message, schemas_by_id={42: SCHEMA}, key={"order_id": "ord-1"})

    assert decoded.operation == expected_operation
    assert decoded.op_code == op
    assert decoded.key == {"order_id": "ord-1"}
    assert decoded.source_lsn == 101
    assert decoded.transaction_order == 1
    assert decoded.ts_ms == 1760000000100
    assert decoded.source_ts_ms == 1760000000000
    assert decoded.before == before
    assert decoded.after == after


def test_null_value_is_a_tombstone_and_keeps_its_kafka_key():
    decoded = decode_confluent_avro(None, schemas_by_id={}, key={"order_id": "ord-1"})

    assert decoded.operation == "tombstone"
    assert decoded.op_code is None
    assert decoded.key == {"order_id": "ord-1"}
    assert to_order_change_row(decoded)["op"] == OP_TOMBSTONE


def test_confluent_frame_extracts_schema_id_and_payload():
    frame = b"\x00\x00\x00\x00\x2aavro"

    assert unpack_confluent_frame(frame) == (42, b"avro")


@pytest.mark.parametrize("frame", [b"", b"\x00\x00\x00\x00\x2a", b"\x01\x00\x00\x00\x2aavro"])
def test_invalid_confluent_frame_is_rejected(frame):
    with pytest.raises(ValueError):
        unpack_confluent_frame(frame)


def test_unknown_operation_and_invalid_source_lsn_fail_closed():
    with pytest.raises(ValueError, match="unsupported Debezium operation"):
        decode_debezium_envelope({"op": "x"})
    with pytest.raises(ValueError, match="source.lsn"):
        decode_debezium_envelope(
            {"op": "c", "after": _order("created"), "source": {"lsn": "bad"}}
        )


@pytest.mark.parametrize("op", ["t", "m"])
def test_truncate_and_message_operations_fail_closed(op):
    with pytest.raises(ValueError, match="unsupported Debezium operation"):
        decode_debezium_envelope({"op": op})


def test_decoded_operation_uses_the_merge_vocabulary():
    deleted = decode_debezium_envelope(
        _envelope("d", before=_order("paid", "12.00"), after=None),
        key={"order_id": "ord-1"},
    )
    inserted = decode_debezium_envelope(
        _envelope("c", before=None, after=_order("created")),
        key={"order_id": "ord-1"},
    )

    assert to_order_change_row(deleted)["op"] == OP_DELETE
    assert to_order_change_row(inserted)["op"] == OP_UPSERT
