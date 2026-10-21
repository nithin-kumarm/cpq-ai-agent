"""Independent CPQ parts discovery and bulk add via OpenAI -> MCP.

Local single-process POC. Protect /chat with authentication and persistent
idempotency/session storage before exposing this to multiple users.
"""
import asyncio
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI

from app.mcp_client import CPQMCPClient
from app.payloads import build_bulk_add_payload, build_instrument_package_payload

load_dotenv()
MAX_INSTRUMENTS = 20


SYSTEM_PROMPT = """
You are an Oracle CPQ AI Assistant.

You support TWO COMPLETELY INDEPENDENT operations.

OPERATION 1: PARTS DISCOVERY

Use discover_instrument_parts only when the user asks to:
- Discover available parts
- Show available products
- List configuration options

Required information:
- bs_id
- document_id
- version_id
- action_id
- instrument_ui

Workflow:
1. Call Oracle CPQ _configure.
2. Obtain cacheInstanceId.
3. Call Oracle CPQ _update.
4. Display category1_data through category21_data.

Never execute bulk add during discovery.


OPERATION 2: BULK ADD INSTRUMENTS

Use bulk_add_instruments when the user explicitly asks to:
- Add instruments
- Insert instruments
- Submit instruments to a quote

Required information:
- bs_id
- document_id
- instruments array

Each instrument must contain:
- instrumentUI
- selected_parts

IMPORTANT:
- Bulk add does NOT require version_id.
- Bulk add does NOT require action_id.
- Bulk add does NOT require cacheInstanceId.
- Bulk add does NOT require previous parts discovery.
- Never ask for version_id or action_id during bulk add.
- Never call _configure or _update before bulk add.

BULK ADD RULES:

1. Support between 1 and 20 instruments.
2. Different instruments may use different instrumentUI values.
3. Preserve instrument order.
4. Preserve selected part order.
5. Join selected parts using '$'.
6. Generate one instrumentPackagePayload per instrument.
7. Submit all instruments in ONE _bulkAddToTxn call.
8. Do not invent part numbers or transaction identifiers.
9. Only execute bulk add when explicitly requested.
10. Never claim success unless CPQ confirms submission.

If the user provides bsId, documentId, instrumentUI
and selected parts, call bulk_add_instruments immediately.

Do not request additional configuration identifiers.
"""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "discover_instrument_parts",
            "description": "Read-only discovery of available CPQ parts for one instrument. Does not add to quote.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bs_id": {"type": "integer"},
                    "document_id": {"type": "integer"},
                    "version_id": {"type": "string"},
                    "action_id": {"type": "string"},
                    "instrument_ui": {"type": "string"},
                    "quantity": {"type": "integer"},
                },
                "required": ["bs_id", "document_id", "version_id", "action_id", "instrument_ui"],
            },
        },
    },
    
{
    "type": "function",
    "function": {
        "name": "bulk_add_instruments",
        "description": (
            "Directly add 1 to 20 instruments to an Oracle CPQ "
            "transaction using _bulkAddToTxn. "
            "Does not require discovery, versionId, or actionId."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "bs_id": {
                    "type": "integer"
                },
                "document_id": {
                    "type": "integer"
                },
                "instruments": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                        "properties": {
                            "instrumentUI": {
                                "type": "string"
                            },
                            "selected_parts": {
                                "type": "array",
                                "items": {
                                    "type": "string"
                                },
                                "minItems": 1
                            }
                        },
                        "required": [
                            "instrumentUI",
                            "selected_parts"
                        ]
                    }
                }
            },
            "required": [
                "bs_id",
                "document_id",
                "instruments"
            ]
        }
    }
}

]


@dataclass
class CPQSession:
    bs_id: int | None = None
    document_id: int | None = None
    version_id: str | None = None
    action_id: str | None = None
    # Discovery is for user display only, NEVER a precondition for bulk add.
    discoveries: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Per-payload attempt log: block identical repeats and ambiguous retries.
    submissions: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


SESSIONS: dict[str, CPQSession] = {}


class CPQAgent:
    def __init__(self):
        self.openai = AsyncOpenAI()
        self.mcp = CPQMCPClient()
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    @staticmethod
    def get_session(session_id: str) -> CPQSession:
        return SESSIONS.setdefault(session_id, CPQSession())

    @staticmethod
    def _mentioned(message: str, value: str) -> bool:
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(value) + r"(?![A-Za-z0-9_])"
        return bool(re.search(pattern, message, flags=re.IGNORECASE))

    @staticmethod
    def _explicit_add(message: str) -> bool:
        return bool(re.search(r"\b(add|insert|submit|place)\b", message, re.IGNORECASE))

    @staticmethod
    def _set_context(session: CPQSession, args: dict) -> dict | None:
        try:
            bs = int(args.get("bs_id", session.bs_id))
            doc = int(args.get("document_id", session.document_id))
        except (ValueError, TypeError):
            return {"status": "MISSING_INFORMATION", "missingFields": ["bs_id", "document_id"]}
        if session.bs_id is not None and (bs, doc) != (session.bs_id, session.document_id):
            return {"status": "NEW_SESSION_REQUIRED", "message": "Use a new session for a different quote."}
        session.bs_id, session.document_id = bs, doc
        if args.get("version_id") is not None:
            session.version_id = str(args["version_id"])
        if args.get("action_id") is not None:
            session.action_id = str(args["action_id"])
        return None

    async def execute_tool(self, name: str, args: dict, session: CPQSession, user_message: str) -> dict:
        if name not in {"discover_instrument_parts", "bulk_add_instruments"}:
            return {"status": "UNKNOWN_TOOL", "message": f"Unsupported tool: {name}"}

        problem = self._set_context(session, args)
        if problem:
            return problem

        if name == "discover_instrument_parts":
            ui = str(args.get("instrument_ui", "")).strip()
            if not ui:
                return {"status": "MISSING_INFORMATION", "missingFields": ["instrument_ui"]}
            version = args.get("version_id", session.version_id)
            action = args.get("action_id", session.action_id)
            if not version or not action:
                return {"status": "MISSING_INFORMATION", "missingFields": ["version_id", "action_id"]}
            quantity = int(args.get("quantity") or 1)
            if quantity < 1:
                return {"status": "INVALID_QUANTITY"}
            result = await self.mcp.call_tool(
                tool_name="discover_instrument_parts",
                arguments={
                    "bs_id": session.bs_id,
                    "document_id": session.document_id,
                    "version_id": str(version),
                    "action_id": str(action),
                    "instrument_ui": ui,
                    "quantity": quantity,
                },
            )
            if result.get("status") != "DISCOVERY_COMPLETED":
                return result
            # Trim raw CPQ strings before passing to OpenAI, but preserve all parts.
            categories = []
            for cat in result.get("categories", []):
                parts = [
                    {"partNumber": p.get("partNumber"), "description": p.get("description"), "price": p.get("price")}
                    for p in cat.get("parts", []) if p.get("partNumber")
                ]
                if parts:
                    categories.append({"categoryName": cat.get("categoryName"), "parts": parts})
            session.discoveries[ui] = {"categories": categories, "quantity": quantity}
            return {"status": "DISCOVERY_COMPLETED", "instrumentUI": ui, "categories": categories}

        # BULK ADD: deliberately does NOT inspect session.discoveries.
        if not self._explicit_add(user_message):
            return {"status": "ADD_INTENT_REQUIRED", "message": "User must explicitly ask to add instruments."}
        requested = args.get("instruments")
        if not isinstance(requested, list) or not 1 <= len(requested) <= MAX_INSTRUMENTS:
            return {"status": "INVALID_INSTRUMENT_COUNT", "message": "Provide 1 to 20 instruments."}
        instruments = []
        for index, item in enumerate(requested, start=1):
            if not isinstance(item, dict):
                return {"status": "INVALID_SELECTION", "instrumentIndex": index}
            ui = item.get("instrumentUI")
            parts = item.get("selected_parts")
            if not isinstance(ui, str) or not ui.strip() or not self._mentioned(user_message, ui):
                return {"status": "INSTRUMENT_MISMATCH", "instrumentIndex": index}
            if not isinstance(parts, list) or not parts or any(
                not isinstance(p, str) or not p.strip() or not self._mentioned(user_message, p)
                for p in parts
            ):
                return {"status": "SELECTION_MISMATCH", "instrumentIndex": index}
            try:
                package = build_instrument_package_payload(parts)
            except ValueError as error:
                return {"status": "INVALID_SELECTION", "instrumentIndex": index, "message": str(error)}
            instruments.append({"instrumentUI": ui.strip(), "instrumentPackagePayload": package})

        payload = build_bulk_add_payload(session.bs_id, session.document_id, instruments)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if key in session.submissions:
            previous = session.submissions[key]
            return {
                "status": "DUPLICATE_OR_PREVIOUS_ATTEMPT",
                "message": "This exact payload was already attempted in this session. Check CPQ before retrying.",
                "previousStatus": previous["status"],
            }

        # Record before network call: a timeout may occur after CPQ has accepted the request.
        session.submissions[key] = {"status": "SUBMISSION_STATUS_UNKNOWN"}
        try:
            result = await self.mcp.call_tool(
                tool_name="bulk_add_instruments",
                arguments={"bs_id": session.bs_id, "document_id": session.document_id, "instruments": instruments},
            )
        except Exception as error:
            return {
                "status": "SUBMISSION_STATUS_UNKNOWN",
                "message": "Could not confirm CPQ result. Inspect the quote before retrying.",
                "errorType": type(error).__name__,
            }
        status = result.get("status", "SUBMISSION_STATUS_UNKNOWN")
        session.submissions[key]["status"] = status
        return {
            "status": status,
            "instrumentCount": len(instruments),
            "instruments": instruments,
            "bulkAddResult": result,
        }

    async def chat(self, message: str, session_id: str | None = None) -> dict:
        session_id = session_id or str(uuid.uuid4())
        session = self.get_session(session_id)
        async with session.lock:
            context = {
                "bsId": session.bs_id,
                "documentId": session.document_id,
                "versionId": session.version_id,
                "actionId": session.action_id,
                "previouslyDiscoveredModels": list(session.discoveries),
                "note": "Discovery is optional and NEVER required for bulk add.",
            }
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": "CURRENT SESSION: " + json.dumps(context)},
                *session.history[-10:],
                {"role": "user", "content": message},
            ]
            response = await self.openai.chat.completions.create(
                model=self.model, messages=messages, tools=TOOLS,
                tool_choice="auto", parallel_tool_calls=False,
            )
            assistant = response.choices[0].message
            if not assistant.tool_calls:
                answer = assistant.content or ""
                session.history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": answer}])
                return {"status": "RESPONSE", "sessionId": session_id, "message": answer}
            if len(assistant.tool_calls) != 1:
                return {"status": "MULTIPLE_TOOL_CALLS", "sessionId": session_id, "message": "Use one operation per request."}
            call = assistant.tool_calls[0]
            try:
                args = json.loads(call.function.arguments)
                result = await self.execute_tool(call.function.name, args, session, message)
            except (ValueError, TypeError, KeyError) as error:
                result = {"status": "INVALID_TOOL_ARGUMENTS", "message": str(error)}
            messages.append(assistant.model_dump(exclude_none=True))
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})
            # The tool result is authoritative; do not let model rewrite status.
            try:
                final = await self.openai.chat.completions.create(
                    model=self.model, messages=messages, tools=TOOLS, tool_choice="none"
                )
                answer = final.choices[0].message.content or ""
            except Exception:
                answer = "Operation result: " + result.get("status", "UNKNOWN")
            session.history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": answer}])
            return {"status": result.get("status", "UNKNOWN"), "sessionId": session_id, "message": answer, "toolResults": [result]}
