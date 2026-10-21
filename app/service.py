
from typing import Any

from app.cpq_client import CPQClient
from app.payloads import (
    build_configure_payload,
    build_update_payload,
    build_bulk_add_payload
)
from app.parser import parse_cpq_parts


class CPQService:

    def __init__(self):
        self.client = CPQClient()

    async def configure(
        self,
        bs_id: int,
        document_id: int,
        version_id: str,
        action_id: str,
        instrument_ui: str,
        quantity: int = 1
    ) -> dict[str, Any]:

        payload = build_configure_payload(
            bs_id=bs_id,
            document_id=document_id,
            version_id=version_id,
            action_id=action_id,
            instrument_ui=instrument_ui,
            quantity=quantity
        )

        response = await self.client.configure(payload)

        config_data = response.get("configData", {})
        state = config_data.get("_state", {})

        if state.get("hasError"):
            return {
                "status": "CONFIGURATION_ERROR",
                "messages": state.get("messages", []),
                "ruleMessages": state.get("ruleMessages", {})
            }

        cache_id = response.get("cacheInstanceId")

        if not cache_id:
            return {
                "status": "CONFIGURATION_ERROR",
                "message": "CPQ did not return cacheInstanceId"
            }

        return {
            "status": "CONFIGURED",
            "cacheInstanceId": cache_id,
            "bsId": bs_id,
            "documentId": document_id,
            "instrumentUI": instrument_ui,
            "quantity": quantity,
            "quoteNumber": config_data.get("quoteNumber"),
            "quoteCurrency": config_data.get("quoteCurrency"),
            "region": config_data.get("region")
        }

    async def update(
        self,
        cache_instance_id: str,
        instrument_ui: str,
        quantity: int = 1
    ) -> dict[str, Any]:

        payload = build_update_payload(
            cache_instance_id=cache_instance_id,
            instrument_ui=instrument_ui,
            quantity=quantity
        )

        response = await self.client.update(payload)

        config_data = response.get("configData", {})
        state = config_data.get("_state", {})

        if state.get("hasError"):
            return {
                "status": "UPDATE_ERROR",
                "messages": state.get("messages", []),
                "ruleMessages": state.get("ruleMessages", {})
            }

        parsed = parse_cpq_parts(response)

        return {
            "status": "PARTS_RETRIEVED",
            "instrumentUI": instrument_ui,
            "quantity": quantity,
            **parsed
        }

    async def discover_parts(
        self,
        bs_id: int,
        document_id: int,
        version_id: str,
        action_id: str,
        instrument_ui: str,
        quantity: int = 1
    ) -> dict[str, Any]:

        configuration = await self.configure(
            bs_id=bs_id,
            document_id=document_id,
            version_id=version_id,
            action_id=action_id,
            instrument_ui=instrument_ui,
            quantity=quantity
        )

        if configuration.get("status") != "CONFIGURED":
            return configuration

        parts = await self.update(
            cache_instance_id=configuration["cacheInstanceId"],
            instrument_ui=instrument_ui,
            quantity=quantity
        )

        if parts.get("status") != "PARTS_RETRIEVED":
            return parts

        return {
            "status": "DISCOVERY_COMPLETED",
            "bsId": bs_id,
            "documentId": document_id,
            "quoteNumber": configuration.get("quoteNumber"),
            "quoteCurrency": configuration.get("quoteCurrency"),
            "region": configuration.get("region"),
            "instrumentUI": instrument_ui,
            "quantity": quantity,
            "cacheInstanceId": parts.get(
                "cacheInstanceId",
                configuration["cacheInstanceId"]
            ),
            "totalCategories": parts.get("totalCategories", 0),
            "totalParts": parts.get("totalParts", 0),
            "missingCategoryFields": parts.get(
                "missingCategoryFields", []
            ),
            "configurationState": parts.get(
                "configurationState", {}
            ),
            "categories": parts.get("categories", [])
        }

    async def bulk_add(
        self,
        bs_id: int,
        document_id: int,
        instruments: list[dict[str, Any]],
        confirmed: bool = False
    ) -> dict[str, Any]:

        payload = build_bulk_add_payload(
            bs_id=bs_id,
            document_id=document_id,
            instruments=instruments
        )

        if not confirmed:
            return {
                "status": "CONFIRMATION_REQUIRED",
                "message": (
                    "Please review and confirm the "
                    "instrument configurations before "
                    "adding them to the CPQ transaction."
                ),
                "instrumentCount": len(instruments),
                "payload": payload
            }

        response = await self.client.bulk_add(payload)

        return {
            "status": "BULK_ADD_SUBMITTED",
            "bsId": response.get("bsId"),
            "processId": response.get("processId"),
            "destinationUrl": response.get("destinationUrl"),
            "message": (
                "Bulk-add request submitted to Oracle CPQ. "
                "Verify the resulting transaction lines."
            )
        }
