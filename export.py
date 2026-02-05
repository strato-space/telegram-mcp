"""Export helpers for the Telegram MCP (read-only) server."""

from __future__ import annotations

from pathlib import Path
from typing import List, Union

from mcp.types import CallToolResult, ResourceLink, ToolAnnotations

# Import the main module so globals (client, mcp) are initialised once.
import main as telegram_main

mcp = telegram_main.mcp
list_messages = getattr(telegram_main, "list_messages", None)


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True, readOnlyHint=True))
async def export_messages(
    chat_ids: List[Union[int, str]],
    limit: int = 10000,
    search_query: str = None,
    from_date: str = None,
    to_date: str = None,
) -> CallToolResult:
    """Export chat messages to ./output/{chat_ids}-telegram.md."""
    if not chat_ids:
        output_text = "No chat_ids provided."
    else:
        blocks = []
        for chat_id in chat_ids:
            if not list_messages:
                blocks.append(f"## chat_id: {chat_id}\n\nlist_messages is not available.")
                continue
            output_text = await list_messages(
                chat_id=chat_id,
                limit=limit,
                search_query=search_query,
                from_date=from_date,
                to_date=to_date,
            )
            blocks.append(f"## chat_id: {chat_id}\n\n{output_text}")
        output_text = "\n\n---\n\n".join(blocks)

    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    chat_ids_slug = "_".join(str(cid) for cid in chat_ids) if chat_ids else "none"
    if len(chat_ids_slug) > 100:
        chat_ids_slug = f"{chat_ids_slug[:100]}_etc"
    out_path = out_dir / f"{chat_ids_slug}-telegram.md"
    out_path.write_text(output_text, encoding="utf-8")
    uri = out_path.resolve().as_uri()

    return CallToolResult(
        content=[
            ResourceLink(
                type="resource_link",
                uri=uri,
                name=out_path.name,
                mimeType="text/markdown",
            )
        ],
        structuredContent={"path": str(out_path)},
    )
