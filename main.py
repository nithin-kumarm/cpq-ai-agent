
import logging

import httpx

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from app.agent import CPQAgent
from app.service import CPQService


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Oracle CPQ AI Agent",
    description=(
        "Discover Oracle CPQ instrument parts and "
        "add selected configurations to transactions."
    ),
    version="1.0.0"
)


class DiscoverRequest(BaseModel):
    bsId: int
    documentId: int
    versionId: str
    actionId: str
    instrumentUI: str = Field(min_length=1)
    quantity: int = Field(default=1, ge=1)


class InstrumentItem(BaseModel):
    instrumentUI: str = Field(min_length=1)
    instrumentPackagePayload: str = Field(min_length=1)


class BulkAddRequest(BaseModel):
    bsId: int
    documentId: int
    instruments: list[InstrumentItem] = Field(min_length=1)


class BulkAddConfirmRequest(BulkAddRequest):
    confirmed: bool = False


def get_service() -> CPQService:
    return CPQService()


def handle_cpq_error(error: Exception):
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code

        logger.error(
            "CPQ returned HTTP %s",
            status
        )

        raise HTTPException(
            status_code=502,
            detail={
                "message": "Oracle CPQ API request failed",
                "cpqStatusCode": status
            }
        ) from error

    if isinstance(error, httpx.RequestError):
        logger.error(
            "CPQ connection error: %s",
            type(error).__name__
        )

        raise HTTPException(
            status_code=502,
            detail="Unable to connect to Oracle CPQ"
        ) from error

    if isinstance(error, ValueError):
        raise HTTPException(
            status_code=400,
            detail=str(error)
        ) from error

    logger.exception("Unexpected CPQ application error")

    raise HTTPException(
        status_code=500,
        detail="Internal application error"
    ) from error


@app.get("/")
async def health_check():
    return {
        "status": "OK",
        "application": "Oracle CPQ AI Agent",
        "version": "1.0.0"
    }


@app.post("/config/discover")
async def discover_parts(body: DiscoverRequest):

    try:
        service = get_service()

        result = await service.discover_parts(
            bs_id=body.bsId,
            document_id=body.documentId,
            version_id=body.versionId,
            action_id=body.actionId,
            instrument_ui=body.instrumentUI,
            quantity=body.quantity
        )

        return result

    except Exception as error:
        handle_cpq_error(error)


@app.post("/config/bulk-add/prepare")
async def prepare_bulk_add(body: BulkAddRequest):

    try:
        service = get_service()

        result = await service.bulk_add(
            bs_id=body.bsId,
            document_id=body.documentId,
            instruments=[
                item.model_dump()
                for item in body.instruments
            ],
            confirmed=False
        )

        return result

    except Exception as error:
        handle_cpq_error(error)


@app.post("/config/bulk-add")
async def bulk_add(body: BulkAddConfirmRequest):

    try:
        service = get_service()

        result = await service.bulk_add(
            bs_id=body.bsId,
            document_id=body.documentId,
            instruments=[
                item.model_dump()
                for item in body.instruments
            ],
            confirmed=body.confirmed
        )

        return result

    except Exception as error:
        handle_cpq_error(error)



class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    sessionId: str | None = None


@app.post("/chat")
async def chat(body: ChatRequest):
    try:
        agent = CPQAgent()

        return await agent.chat(
            message=body.message,
            session_id=body.sessionId
        )

    except Exception as error:
        handle_cpq_error(error)

