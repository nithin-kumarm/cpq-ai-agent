from mcp.server.fastmcp import FastMCP
from app.service import CPQService

mcp = FastMCP("Oracle CPQ Assistant")


@mcp.tool()
async def discover_instrument_parts(
    bs_id: int,
    document_id: int,
    version_id: str,
    action_id: str,
    instrument_ui: str,
    quantity: int = 1,
) -> dict:
    """Read-only discovery: CPQ _configure followed by _update."""
    return await CPQService().discover_parts(
        bs_id=bs_id,
        document_id=document_id,
        version_id=version_id,
        action_id=action_id,
        instrument_ui=instrument_ui,
        quantity=quantity,
    )


@mcp.tool()
async def bulk_add_instruments(
    bs_id: int,
    document_id: int,
    instruments: list[dict],
) -> dict:
    """Write operation: submit instruments directly to CPQ _bulkAddToTxn.

    Does NOT call _configure or _update and does NOT require discovery.
    """
    if not 1 <= len(instruments) <= 20:
        return {"status": "INVALID_INSTRUMENT_COUNT", "message": "Provide 1 to 20 instruments."}
    return await CPQService().bulk_add(
        bs_id=bs_id,
        document_id=document_id,
        instruments=instruments,
        confirmed=True,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
