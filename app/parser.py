
from typing import Any


CATEGORY_NAMES = {
    1: "Install Kit",
    2: "Power Cords",
    3: "Site Prep",
    4: "Training",
    5: "Software",
    6: "SW Install Kit",
    7: "Objective",
    8: "Light Cube",
    9: "Vessel Holder",
    10: "Vessel Adapter",
    11: "Plate",
    12: "Consumable",
    13: "Plate Kit",
    14: "Tray Kit",
    15: "Additional Items",
    16: "Service",
    17: "Miscellaneous Items",
    18: "Service Contracts",
    19: "Reagents",
    20: "Starter Pack",
    21: "CustomCat_5"
}


def parse_price(value: str) -> float | None:
    try:
        return float(value.strip())
    except (ValueError, AttributeError, TypeError):
        return None


def parse_category_data(raw_data: str) -> list[dict]:
    parts = []

    if not isinstance(raw_data, str) or not raw_data.strip():
        return parts

    for raw_record in raw_data.split("$#$"):
        record = raw_record.strip().lstrip("#")

        if not record:
            continue

        fields = record.split("&&")

        if len(fields) < 3:
            continue

        part_number = fields[0].strip()

        if not part_number:
            continue

        parts.append({
            "partNumber": part_number,
            "description": fields[1].strip(),
            "price": parse_price(fields[2]),
            "rawFields": fields
        })

    return parts


def parse_cpq_parts(
    cpq_response: dict[str, Any]
) -> dict[str, Any]:

    config_data = cpq_response.get("configData", {})

    if not isinstance(config_data, dict):
        raise ValueError("Invalid configData in CPQ response")

    categories = []
    total_parts = 0
    missing_fields = []

    for category_number in range(1, 22):

        field_name = f"category{category_number}_data"

        if field_name not in config_data:
            missing_fields.append(field_name)
            continue

        raw_data = config_data[field_name]
        parts = parse_category_data(raw_data)

        categories.append({
            "categoryNumber": category_number,
            "categoryName": CATEGORY_NAMES.get(
                category_number,
                f"Category {category_number}"
            ),
            "fieldName": field_name,
            "rawData": raw_data,
            "parts": parts,
            "count": len(parts)
        })

        total_parts += len(parts)

    state = config_data.get("_state", {})

    return {
        "cacheInstanceId": cpq_response.get("cacheInstanceId"),
        "totalCategories": len(categories),
        "totalParts": total_parts,
        "missingCategoryFields": missing_fields,
        "configurationState": {
            "hasError": state.get("hasError", False),
            "hasWarning": state.get("hasWarning", False),
            "messages": state.get("messages", [])
        },
        "categories": categories
    }
