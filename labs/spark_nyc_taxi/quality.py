"""Quality policy for the isolated NYC TLC Yellow Taxi Spark lab.

TLC's pickup and drop-off timestamps are local civil times with no UTC offset.
This module therefore interprets them as ``America/New_York`` wall clocks and
rejects endpoints in DST gaps/folds as well as trips whose interval spans a
clock transition. The remaining duration is the elapsed duration implied by
that local wall clock; a true instant cannot be reconstructed from the source
when it omits an offset.

The module deliberately has no row deduplication. TLC records do not provide a
stable trip ID, and even identical source rows can represent distinct trips.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType, LongType, StringType, StructField, StructType

TIME_ZONE = "America/New_York"
_ZONE = ZoneInfo(TIME_ZONE)
_REQUIRED_SOURCE_COLUMNS = (
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime",
    "PULocationID",
    "DOLocationID",
    "trip_distance",
    "fare_amount",
    "total_amount",
)
_RESERVED_PREFIX = "_p73_"
_OPTIONAL_NEGATIVE_COMPONENTS = (
    "extra",
    "mta_tax",
    "tip_amount",
    "tolls_amount",
    "improvement_surcharge",
    "congestion_surcharge",
    "airport_fee",
)
_REJECT_REASONS = (
    "missing_critical",
    "invalid_timestamp_parse",
    "outside_pickup_period",
    "dst_gap_fold_or_crossing",
    "invalid_duration",
    "unknown_zone",
    "nonfinite_distance",
    "nonpositive_distance",
    "distance_out_of_decimal_range",
    "nonfinite_money",
    "money_out_of_decimal_range",
)


class QualityContractError(ValueError):
    """Raised when source or lookup schemas violate the lab contract."""


@dataclass(frozen=True)
class _TransitionWindow:
    kind: Literal["gap", "fold"]
    start_local: datetime
    end_local: datetime


@dataclass(frozen=True)
class QualityFrames:
    """Accepted/rejected trip frames and a small driver-collected quality ledger."""

    accepted: DataFrame
    rejected: DataFrame
    ledger: DataFrame
    input_rows: int
    accepted_rows: int
    rejected_rows: int


def _casefolded_columns(frame: DataFrame) -> dict[str, str]:
    by_folded: dict[str, str] = {}
    for name in frame.columns:
        key = name.casefold()
        if key in by_folded:
            raise QualityContractError(
                f"column names are ambiguous under Spark's case-insensitive resolver: "
                f"{by_folded[key]!r} and {name!r}"
            )
        by_folded[key] = name
    return by_folded


def _get_column(frame: DataFrame, name: str) -> str:
    found = _casefolded_columns(frame).get(name.casefold())
    if found is None:
        raise QualityContractError(f"required column {name!r} is missing")
    return found


def _as_date(value: date | str, *, parameter: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise QualityContractError(f"{parameter} must be an ISO date") from exc


def _local_epoch_micros(column: F.Column) -> F.Column:
    """Encode timestamp fields as a timezone-free civil clock value."""

    days = F.datediff(F.to_date(column), F.lit("1970-01-01")).cast("long")
    micros = F.date_format(column, "SSSSSS").cast("long")
    return (
        days * F.lit(86_400_000_000)
        + F.hour(column).cast("long") * F.lit(3_600_000_000)
        + F.minute(column).cast("long") * F.lit(60_000_000)
        + F.second(column).cast("long") * F.lit(1_000_000)
        + micros
    )


def _naive_epoch_micros(value: datetime) -> int:
    delta = value - datetime(1970, 1, 1)
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


@lru_cache(maxsize=16)
def _dst_windows(first_year: int, last_year: int) -> tuple[_TransitionWindow, ...]:
    """Find New York's local gap/fold intervals using the system IANA tz database."""

    windows: list[_TransitionWindow] = []
    for year in range(first_year, last_year + 1):
        cursor = datetime(year, 1, 1, tzinfo=UTC)
        stop = datetime(year + 1, 1, 1, tzinfo=UTC)
        previous_offset = cursor.astimezone(_ZONE).utcoffset()
        probe = cursor + timedelta(hours=12)
        while probe <= stop:
            current_offset = probe.astimezone(_ZONE).utcoffset()
            if current_offset != previous_offset:
                low = int(cursor.timestamp())
                high = int(probe.timestamp())
                while high - low > 1:
                    middle = (low + high) // 2
                    at_middle = datetime.fromtimestamp(middle, UTC)
                    if at_middle.astimezone(_ZONE).utcoffset() == previous_offset:
                        low = middle
                    else:
                        high = middle
                transition = datetime.fromtimestamp(high, UTC)
                before = (transition - timedelta(seconds=1)).astimezone(_ZONE)
                after = transition.astimezone(_ZONE)
                next_local_after_before = before.replace(tzinfo=None) + timedelta(seconds=1)
                after_local = after.replace(tzinfo=None)
                if after_local > next_local_after_before:
                    windows.append(
                        _TransitionWindow("gap", next_local_after_before, after_local)
                    )
                elif after_local < next_local_after_before:
                    windows.append(
                        _TransitionWindow("fold", after_local, next_local_after_before)
                    )
                previous_offset = current_offset
            cursor = probe
            probe += timedelta(hours=12)
    return tuple(windows)


def validate_zone_lookup(zones_df: DataFrame) -> DataFrame:
    """Validate a complete, unique 1..263 zone dimension and return its safe projection.

    IDs 264 and 265 are TLC's unassigned ``N/A`` records and are excluded. The
    263 real zone IDs must each appear once so a later inner join cannot drop
    known trips or multiply them.
    """

    location_column = _get_column(zones_df, "LocationID")
    borough_column = _get_column(zones_df, "Borough")
    projected = zones_df.select(
        F.col(location_column).cast("int").alias("LocationID"),
        F.trim(F.col(borough_column).cast("string")).alias("Borough"),
    )
    valid = projected.filter(F.col("LocationID").between(1, 263))
    invalid_borough = (
        F.col("Borough").isNull()
        | (F.length(F.trim(F.col("Borough"))) == 0)
        | F.upper(F.trim(F.col("Borough"))).isin("N/A", "NA", "UNKNOWN", "UNASSIGNED")
    )
    summary = projected.agg(
        F.count(F.when(F.col("LocationID").isNotNull(), 1)).alias("nonnull_rows"),
        F.countDistinct("LocationID").alias("distinct_ids"),
        F.count(F.when(F.col("LocationID").isNull(), 1)).alias("null_ids"),
        F.count(F.when(F.col("LocationID").between(1, 263), 1)).alias("valid_rows"),
        F.countDistinct(F.when(F.col("LocationID").between(1, 263), F.col("LocationID"))).alias(
            "valid_distinct_ids"
        ),
        F.min(F.when(F.col("LocationID").between(1, 263), F.col("LocationID"))).alias(
            "min_id"
        ),
        F.max(F.when(F.col("LocationID").between(1, 263), F.col("LocationID"))).alias(
            "max_id"
        ),
        F.sum(
            F.when(F.col("LocationID").between(1, 263) & invalid_borough, 1).otherwise(0)
        ).alias("invalid_borough_rows"),
    ).first()
    if summary["null_ids"]:
        raise QualityContractError("taxi-zone lookup contains a null or unparseable LocationID")
    if summary["nonnull_rows"] != summary["distinct_ids"]:
        raise QualityContractError("taxi-zone lookup contains duplicate LocationID values")
    if summary["invalid_borough_rows"]:
        raise QualityContractError("a numbered taxi zone has a null or unassigned borough")
    if (
        summary["valid_rows"] != 263
        or summary["valid_distinct_ids"] != 263
        or summary["min_id"] != 1
        or summary["max_id"] != 263
    ):
        raise QualityContractError(
            "taxi-zone lookup must contain each assigned LocationID 1..263 exactly once; "
            f"observed rows={summary['valid_rows']}, distinct={summary['valid_distinct_ids']}, "
            f"range={summary['min_id']}..{summary['max_id']}"
        )
    return valid


def _dst_anomaly_condition(
    pickup_local_micros: F.Column,
    dropoff_local_micros: F.Column,
    start_year: int,
    end_year: int,
) -> F.Column:
    anomaly = F.lit(False)
    for window in _dst_windows(start_year, end_year):
        start = F.lit(_naive_epoch_micros(window.start_local))
        end = F.lit(_naive_epoch_micros(window.end_local))
        endpoint_in_window = (
            pickup_local_micros.between(start, end - F.lit(1))
            | dropoff_local_micros.between(start, end - F.lit(1))
        )
        crosses_window = (pickup_local_micros < start) & (dropoff_local_micros >= end)
        anomaly = anomaly | endpoint_in_window | crosses_window
    return anomaly


def _finite(column: F.Column) -> F.Column:
    value = column.cast("double")
    return value.isNotNull() & ~F.isnan(value) & (F.abs(value) < F.lit(float("inf")))


def _additive_negative_flag(raw_df: DataFrame, numeric_aliases: dict[str, str]) -> F.Column:
    columns_by_folded = _casefolded_columns(raw_df)
    conditions: list[F.Column] = [
        F.col(numeric_aliases["fare_amount"]).cast("double") < 0,
        F.col(numeric_aliases["total_amount"]).cast("double") < 0,
    ]
    for name in _OPTIONAL_NEGATIVE_COMPONENTS:
        actual = columns_by_folded.get(name.casefold())
        if actual is not None:
            value = F.col(actual).cast("double")
            conditions.append(value.isNotNull() & (value < 0))
    flag = conditions[0]
    for condition in conditions[1:]:
        flag = flag | condition
    return flag


def apply_quality_policy(
    raw_df: DataFrame,
    zones_df: DataFrame,
    period_start: date | str,
    period_end: date | str,
) -> QualityFrames:
    """Split raw TLC rows by the published Week-6 rejection policy.

    The pickup period is half-open: ``period_start <= pickup_date < period_end``.
    A drop-off after the period boundary remains valid if it is a plausible trip
    from an in-period pickup. Values in fares and surcharge components may be
    negative: those rows are accepted and counted in ``negative_amount_flag``.

    The returned ledger contains only aggregate counters (never trip rows),
    including per-column null counts and both exclusive rejection reasons and
    overlapping anomaly counts. One aggregate row is brought to the driver to
    prove ``accepted + rejected == input`` before returning.
    """

    start_date = _as_date(period_start, parameter="period_start")
    end_date = _as_date(period_end, parameter="period_end")
    if end_date <= start_date:
        raise QualityContractError("period_end must be later than period_start")
    session_time_zone = raw_df.sparkSession.conf.get("spark.sql.session.timeZone")
    if session_time_zone != TIME_ZONE:
        raise QualityContractError(
            "Spark session time zone must be America/New_York for TLC local-wall-clock semantics; "
            f"observed {session_time_zone!r}"
        )

    source_columns = _casefolded_columns(raw_df)
    reserved = [name for name in raw_df.columns if name.casefold().startswith(_RESERVED_PREFIX)]
    if reserved:
        raise QualityContractError(
            f"raw source uses reserved internal columns: {', '.join(reserved)}"
        )
    missing = [name for name in _REQUIRED_SOURCE_COLUMNS if name.casefold() not in source_columns]
    if missing:
        raise QualityContractError(f"raw TLC schema is missing columns: {', '.join(missing)}")
    validate_zone_lookup(zones_df)

    pickup_source = source_columns["tpep_pickup_datetime"]
    dropoff_source = source_columns["tpep_dropoff_datetime"]
    pu_id_source = source_columns["pulocationid"]
    do_id_source = source_columns["dolocationid"]
    distance_source = source_columns["trip_distance"]
    fare_source = source_columns["fare_amount"]
    total_source = source_columns["total_amount"]

    work = (
        raw_df.withColumn("_p73_pickup_ts", F.col(pickup_source).cast("timestamp_ntz"))
        .withColumn("_p73_dropoff_ts", F.col(dropoff_source).cast("timestamp_ntz"))
        .withColumn("_p73_pickup_zone", F.col(pu_id_source).cast("int"))
        .withColumn("_p73_dropoff_zone", F.col(do_id_source).cast("int"))
        .withColumn("_p73_distance_double", F.col(distance_source).cast("double"))
        .withColumn("_p73_fare_double", F.col(fare_source).cast("double"))
        .withColumn("_p73_total_double", F.col(total_source).cast("double"))
    )

    pickup_is_null = F.col(pickup_source).isNull()
    dropoff_is_null = F.col(dropoff_source).isNull()
    missing_critical = (
        pickup_is_null
        | dropoff_is_null
        | F.col(pu_id_source).isNull()
        | F.col(do_id_source).isNull()
        | F.col(distance_source).isNull()
        | F.col(fare_source).isNull()
        | F.col(total_source).isNull()
    )
    invalid_timestamp_parse = (
        (F.col(pickup_source).isNotNull() & F.col("_p73_pickup_ts").isNull())
        | (F.col(dropoff_source).isNotNull() & F.col("_p73_dropoff_ts").isNull())
    )

    pickup_local_micros = _local_epoch_micros(F.col("_p73_pickup_ts"))
    dropoff_local_micros = _local_epoch_micros(F.col("_p73_dropoff_ts"))
    duration_micros = dropoff_local_micros - pickup_local_micros
    outside_period = (
        F.to_date("_p73_pickup_ts") < F.lit(start_date.isoformat()).cast("date")
    ) | (F.to_date("_p73_pickup_ts") >= F.lit(end_date.isoformat()).cast("date"))
    dst_anomaly = _dst_anomaly_condition(
        pickup_local_micros,
        dropoff_local_micros,
        start_date.year - 1,
        end_date.year + 1,
    )
    invalid_duration = (duration_micros <= 0) | (duration_micros > F.lit(86_400_000_000))
    unknown_zone = (
        F.col("_p73_pickup_zone").isNull()
        | F.col("_p73_dropoff_zone").isNull()
        | ~F.col("_p73_pickup_zone").between(1, 263)
        | ~F.col("_p73_dropoff_zone").between(1, 263)
    )
    finite_distance = _finite(F.col("_p73_distance_double"))
    nonfinite_distance = F.col(distance_source).isNotNull() & ~finite_distance
    nonpositive_distance = finite_distance & (F.col("_p73_distance_double") <= 0)
    distance_out_of_decimal_range = finite_distance & (
        F.abs(F.col("_p73_distance_double")) >= F.lit(1.0e15)
    )
    finite_fare = _finite(F.col("_p73_fare_double"))
    finite_total = _finite(F.col("_p73_total_double"))
    nonfinite_money = (
        (F.col(fare_source).isNotNull() & ~finite_fare)
        | (F.col(total_source).isNotNull() & ~finite_total)
    )
    money_out_of_decimal_range = (
        (finite_fare & (F.abs(F.col("_p73_fare_double")) >= F.lit(1.0e16)))
        | (finite_total & (F.abs(F.col("_p73_total_double")) >= F.lit(1.0e16)))
    )

    anomaly_conditions = {
        "missing_critical": missing_critical,
        "invalid_timestamp_parse": invalid_timestamp_parse,
        "outside_pickup_period": outside_period,
        "dst_gap_fold_or_crossing": dst_anomaly,
        "invalid_duration": invalid_duration,
        "unknown_zone": unknown_zone,
        "nonfinite_distance": nonfinite_distance,
        "nonpositive_distance": nonpositive_distance,
        "distance_out_of_decimal_range": distance_out_of_decimal_range,
        "nonfinite_money": nonfinite_money,
        "money_out_of_decimal_range": money_out_of_decimal_range,
    }
    priority = F.lit(None).cast("string")
    for reason in reversed(_REJECT_REASONS):
        priority = F.when(anomaly_conditions[reason], F.lit(reason)).otherwise(priority)
    work = work.withColumn("_p73_reject_reason", priority)

    negative_amount_flag = _additive_negative_flag(
        raw_df,
        {"fare_amount": "_p73_fare_double", "total_amount": "_p73_total_double"},
    )
    accepted = work.filter(F.col("_p73_reject_reason").isNull()).select(
        F.col("_p73_pickup_ts").alias("pickup_ts"),
        F.col("_p73_dropoff_ts").alias("dropoff_ts"),
        F.to_date("_p73_pickup_ts").alias("pickup_date"),
        F.hour("_p73_pickup_ts").cast("int").alias("pickup_hour"),
        F.col("_p73_pickup_zone").alias("pickup_zone"),
        F.col("_p73_dropoff_zone").alias("dropoff_zone"),
        F.round(F.col("_p73_distance_double"), 3)
        .cast(DecimalType(18, 3))
        .alias("trip_distance_miles"),
        F.round(F.col("_p73_fare_double"), 2)
        .cast(DecimalType(18, 2))
        .alias("fare_amount"),
        F.round(F.col("_p73_total_double"), 2)
        .cast(DecimalType(18, 2))
        .alias("total_amount"),
        (duration_micros.cast("double") / F.lit(60_000_000.0)).alias("duration_minutes"),
        negative_amount_flag.alias("negative_amount_flag"),
    )
    rejected = work.filter(F.col("_p73_reject_reason").isNotNull()).select(
        *[F.col(name) for name in raw_df.columns],
        F.col("_p73_reject_reason").alias("reject_reason"),
    )

    count_expressions = [
        F.count(F.lit(1)).alias("input_rows"),
        F.sum(F.when(F.col("_p73_reject_reason").isNull(), 1).otherwise(0)).alias(
            "accepted_rows"
        ),
        F.sum(F.when(F.col("_p73_reject_reason").isNotNull(), 1).otherwise(0)).alias(
            "rejected_rows"
        ),
        F.sum(F.when(negative_amount_flag, 1).otherwise(0)).alias(
            "negative_amount_review_rows"
        ),
    ]
    count_names = ["input_rows", "accepted_rows", "rejected_rows", "negative_amount_review_rows"]
    for reason in _REJECT_REASONS:
        count_expressions.append(
            F.sum(F.when(F.col("_p73_reject_reason") == reason, 1).otherwise(0)).alias(
                f"first_{reason}"
            )
        )
        count_names.append(f"first_{reason}")
        count_expressions.append(
            F.sum(F.when(anomaly_conditions[reason], 1).otherwise(0)).alias(f"overlap_{reason}")
        )
        count_names.append(f"overlap_{reason}")

    for index, source_name in enumerate(raw_df.columns):
        count_expressions.append(
            F.sum(F.when(F.col(source_name).isNull(), 1).otherwise(0)).alias(
                f"null_source_{index:02d}"
            )
        )
        count_names.append(f"null_source_{index:02d}")

    negative_field_sources = [
        source_columns[name.casefold()]
        for name in ("fare_amount", *_OPTIONAL_NEGATIVE_COMPONENTS, "total_amount")
        if name.casefold() in source_columns
    ]
    for index, source_name in enumerate(dict.fromkeys(negative_field_sources)):
        count_expressions.append(
            F.sum(
                F.when(F.col(source_name).cast("double") < 0, 1).otherwise(0)
            ).alias(f"negative_amount_source_{index:02d}")
        )
        count_names.append(f"negative_amount_source_{index:02d}")

    summary = work.agg(*count_expressions).first()
    counts = {name: int(summary[name] or 0) for name in count_names}
    if counts["accepted_rows"] + counts["rejected_rows"] != counts["input_rows"]:
        raise QualityContractError(
            "quality ledger reconciliation failed: accepted + rejected does not equal input"
        )

    ledger_rows: list[tuple[str, str, int]] = [
        ("input_rows", "total", counts["input_rows"]),
        ("accepted_rows", "accepted", counts["accepted_rows"]),
        ("rejected_rows", "rejected", counts["rejected_rows"]),
        (
            "accepted_plus_rejected",
            "reconciliation",
            counts["accepted_rows"] + counts["rejected_rows"],
        ),
        (
            "negative_amount_review_rows",
            "overlapping_review_flag",
            counts["negative_amount_review_rows"],
        ),
    ]
    for reason in _REJECT_REASONS:
        ledger_rows.append(
            (f"first_{reason}", "exclusive_rejection_reason", counts[f"first_{reason}"])
        )
        ledger_rows.append(
            (f"overlap_{reason}", "overlapping_anomaly", counts[f"overlap_{reason}"])
        )
    for index, source_name in enumerate(raw_df.columns):
        ledger_rows.append(
            (
                f"null_source_{source_name}",
                "source_column_null_count",
                counts[f"null_source_{index:02d}"],
            )
        )
    for index, source_name in enumerate(dict.fromkeys(negative_field_sources)):
        ledger_rows.append(
            (
                f"negative_amount_{source_name}",
                "negative_amount_field_count",
                counts[f"negative_amount_source_{index:02d}"],
            )
        )
    ledger_schema = StructType(
        [
            StructField("metric", StringType(), nullable=False),
            StructField("category", StringType(), nullable=False),
            StructField("row_count", LongType(), nullable=False),
        ]
    )
    ledger = raw_df.sparkSession.createDataFrame(ledger_rows, ledger_schema)
    return QualityFrames(
        accepted=accepted,
        rejected=rejected,
        ledger=ledger,
        input_rows=counts["input_rows"],
        accepted_rows=counts["accepted_rows"],
        rejected_rows=counts["rejected_rows"],
    )


def diagnose_duplicate_like_rows(raw_df: DataFrame) -> DataFrame:
    """Return a one-row full-column fingerprint duplicate diagnostic, without dropping rows.

    It performs a shuffle over hashes of the complete source row. The result is
    a diagnostic only: equal full-row hashes are not proof of the same trip.
    No business key is published or used to deduplicate the TLC data.
    """

    columns = [F.col(name) for name in raw_df.columns]
    signature = F.sha2(
        F.to_json(F.struct(*columns), options={"ignoreNullFields": "false"}), 256
    )
    groups = (
        raw_df.select(signature.alias("row_signature"))
        .groupBy("row_signature")
        .count()
        .filter(F.col("count") > 1)
    )
    return groups.agg(
        F.coalesce(F.sum(F.col("count") - 1), F.lit(0)).cast("long").alias(
            "duplicate_like_extra_rows"
        ),
        F.coalesce(F.sum("count"), F.lit(0)).cast("long").alias(
            "duplicate_like_group_members"
        ),
        F.count(F.lit(1)).cast("long").alias("duplicate_like_signature_groups"),
    )
