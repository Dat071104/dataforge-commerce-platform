"""Shared operation vocabulary for the Week 8 CDC pipeline."""

OP_UPSERT = "upsert"
OP_DELETE = "delete"
OP_TOMBSTONE = "tombstone"

DEBEZIUM_OPERATIONS = {
    "c": OP_UPSERT,
    "u": OP_UPSERT,
    "d": OP_DELETE,
    "r": OP_UPSERT,
}
