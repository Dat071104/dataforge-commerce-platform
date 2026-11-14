from __future__ import annotations

import re
from pathlib import Path

MODEL = Path(__file__).parents[2] / "dashboards" / "P5" / "DataForge" / "DataForge.SemanticModel" / "definition"


def _relationship_blocks() -> list[dict[str, str]]:
    text = (MODEL / "relationships.tmdl").read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^relationship\s+", text)[1:]
    relationships: list[dict[str, str]] = []
    for block in blocks:
        properties: dict[str, str] = {}
        for line in block.splitlines():
            stripped = line.strip()
            if ":" in stripped:
                key, value = stripped.split(":", maxsplit=1)
                properties[key.strip()] = value.strip()
        relationships.append(properties)
    return relationships


def test_tmdl_relationship_and_date_role_findings_are_exact() -> None:
    relationships = _relationship_blocks()
    assert len(relationships) == 15
    assert all("fromColumn" in item and "toColumn" in item for item in relationships)

    # No relationship has explicit cardinality or cross-filter settings in
    # this source pack; do not claim values inferred from Power BI defaults.
    assert not any("fromCardinality" in item or "toCardinality" in item for item in relationships)
    assert not any("crossFilteringBehavior" in item for item in relationships)

    date_relationships = [item for item in relationships if item["toColumn"] == "dim_date.date_key"]
    assert len(date_relationships) == 7
    shipment_ship_date = [
        item for item in date_relationships if item["fromColumn"] == "fct_shipment.ship_date_key"
    ]
    shipment_delivery_date = [
        item for item in date_relationships if item["fromColumn"] == "fct_shipment.delivery_date_key"
    ]
    assert len(shipment_ship_date) == 1 and shipment_ship_date[0].get("isActive") != "false"
    assert len(shipment_delivery_date) == 1 and shipment_delivery_date[0].get("isActive") == "false"

    shipment = (MODEL / "tables" / "fct_shipment.tmdl").read_text(encoding="utf-8")
    assert shipment.count("USERELATIONSHIP('dim_date'[date_key], 'fct_shipment'[delivery_date_key])") == 3


def test_tmdl_has_no_bridge_table_and_records_the_south_rls_role() -> None:
    table_files = list((MODEL / "tables").glob("*.tmdl"))
    assert not any("bridge" in path.stem.lower() for path in table_files)
    relationships = _relationship_blocks()
    assert not any("bridge" in item.get("fromColumn", "").lower() for item in relationships)
    assert not any("bridge" in item.get("toColumn", "").lower() for item in relationships)

    role_path = MODEL / "roles" / "South_Region_Viewer.tmdl"
    role = role_path.read_text(encoding="utf-8")
    model = (MODEL / "model.tmdl").read_text(encoding="utf-8")
    assert "role South_Region_Viewer" in role
    assert model.count("ref role South_Region_Viewer") == 1
    permissions = [line.strip() for line in role.splitlines() if line.strip().startswith("tablePermission ")]
    assert permissions == [
        "tablePermission dim_geography = 'dim_geography'[region] = \"South\"",
        "tablePermission dim_customer = 'dim_customer'[customer_region] = \"South\"",
    ]
