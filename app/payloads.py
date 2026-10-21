
from typing import Any


CATEGORY_FIELDS = [
    f"category{i}_data"
    for i in range(1, 21)
]


def build_configure_payload(
    bs_id: int,
    document_id: int,
    version_id: str,
    action_id: str,
    instrument_ui: str,
    quantity: int = 1
) -> dict[str, Any]:

    if not instrument_ui:
        raise ValueError("instrumentUI is required")

    if quantity < 1:
        raise ValueError("Quantity must be at least 1")

    return {
        "cacheInstanceId": "-1",
        "bsId": bs_id,
        "documentId": document_id,
        "fromPunchin": True,
        "modelPunchin": {
            "parameters": {
                "_variable_name_punchin": "true",
                "_has_jet_access": "true",
                "document_id": str(document_id),
                "version_id": str(version_id),
                "_isjet": "true",
                "IsConfigure": "true",
                "action_id": str(action_id)
            }
        },
        "configData": {
            "instrumentUI": str(instrument_ui),
            "InstrumentQty": quantity
        },
        "criteria": {
            "state": True,
            "childDefs": [
                {"name": "_priceInfo"},
                {"name": "_recmdParts"},
                {"name": "_recmdModels"},
                {"name": "_mandatoryParts"},
                {"name": "_mandatoryModels"},
                {"name": "_bom"},
                {"name": "_sysNavigationInfo"}
            ]
        }
    }


def build_update_payload(
    cache_instance_id: str,
    instrument_ui: str,
    quantity: int = 1
) -> dict[str, Any]:

    if not cache_instance_id or cache_instance_id == "-1":
        raise ValueError("Valid cacheInstanceId is required")

    if not instrument_ui:
        raise ValueError("instrumentUI is required")

    if quantity < 1:
        raise ValueError("Quantity must be at least 1")

    return {
        "cacheInstanceId": cache_instance_id,
        "configData": {
            "instrumentUI": str(instrument_ui),
            "InstrumentQty": quantity
        },
        "criteria": {
            "fields": CATEGORY_FIELDS.copy(),
            "state": True
        }
    }

def build_instrument_package_payload(
    selected_parts: list[str]
) -> str:

    if not selected_parts:
        raise ValueError(
            "At least one part must be selected"
        )

    cleaned_parts = []

    for part_number in selected_parts:
        part_number = part_number.strip()

        if not part_number:
            raise ValueError(
                "Part number cannot be empty"
            )

        if "$" in part_number:
            raise ValueError(
                "Part number cannot contain '$'"
            )

        cleaned_parts.append(part_number)

    return "$".join(cleaned_parts)


def build_bulk_add_payload(
    bs_id: int,
    document_id: int,
    instruments: list[dict[str, Any]]
) -> dict[str, Any]:

    if not instruments:
        raise ValueError("At least one instrument is required")

    items = []

    for index, instrument in enumerate(instruments):

        instrument_ui = instrument.get("instrumentUI")
        package_payload = instrument.get(
            "instrumentPackagePayload"
        )

        if not instrument_ui:
            raise ValueError(
                f"Instrument {index + 1}: instrumentUI is required"
            )

        if not package_payload:
            raise ValueError(
                f"Instrument {index + 1}: "
                "instrumentPackagePayload is required"
            )

        items.append({
            "configData": {
                "instrumentUI": str(instrument_ui),
                "bulkAdd": True,
                "instrumentPackagePayload": str(package_payload)
            },
            "productFamily": "sQuotes",
            "productLine": "instruments",
            "model": "instruments"
        })

    return {
        "bsId": bs_id,
        "documentId": document_id,
        "items": items
    }
