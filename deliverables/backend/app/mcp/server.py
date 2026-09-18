"""
MCP server (WBS 10.12): the platform's read-only tool surface for the Workflow
Manager and sibling agents (the ROI Agent's cross-check, the finance forecast
process), over stdio.

Every tool here is the same function the assistant uses (app/services/
assistant.py, class Tools) -- one tool surface, exposed twice. Nothing writes:
there is no tool that enters a confidence, moves a record or resolves a
proposal, and adding one would be a design change, not a feature.

The caller identity is a service account: OPPTRACK_MCP_USER / _ROLE / _REGIONS
select the scope, defaulting to finance over every region (read-only by the
roles matrix). Run: `python -m app.mcp.server`.

Dependencies: the `mcp` package (FastMCP). Without it, `build_server()` raises
a clear ImportError; the tool list itself needs nothing.
"""

import json
import os
from typing import Any

from app.db.session import SessionLocal
from app.security.roles import Actor
from app.services.assistant import TOOL_SCHEMAS, Tools

READ_ONLY_TOOLS = tuple(t["name"] for t in TOOL_SCHEMAS)


def _actor() -> Actor:
    regions = os.environ.get("OPPTRACK_MCP_REGIONS", "*")
    return Actor(
        user_id=os.environ.get("OPPTRACK_MCP_USER", "mcp-service"),
        role=os.environ.get("OPPTRACK_MCP_ROLE", "finance"),
        regions=() if regions.strip() == "*" else tuple(r.strip() for r in regions.split(",") if r.strip()),
    )


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict:
    """Runs one read-only tool with its own session. Used by the MCP server
    and directly testable without one."""
    if name not in READ_ONLY_TOOLS:
        return {"error": f"unknown tool {name!r}; tools are {list(READ_ONLY_TOOLS)}"}
    db = SessionLocal()
    try:
        tools = Tools(db, _actor())
        return getattr(tools, name)(**(arguments or {}))
    finally:
        db.close()


def tool_definitions() -> list[dict]:
    return [{"name": t["name"], "description": t["description"],
             "input_schema": t.get("input_schema", {"type": "object", "properties": {}})} for t in TOOL_SCHEMAS]


def build_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover
        raise ImportError("pip install mcp -- the MCP server needs the mcp package") from exc

    server = FastMCP("opptrack", instructions=(
        "Opportunity Tracking Agent, read-only. Every figure comes from the deterministic calc engine; "
        "every proposal and decision from the append-only audit tables. Nothing here writes."
    ))

    for definition in tool_definitions():
        name = definition["name"]

        def make(tool_name: str):
            def handler(arguments: str = "{}") -> str:
                """Arguments as a JSON object string matching the tool's input schema."""
                try:
                    parsed = json.loads(arguments or "{}")
                except json.JSONDecodeError as exc:
                    return json.dumps({"error": f"arguments must be a JSON object: {exc}"})
                return json.dumps(call_tool(tool_name, parsed), default=str)
            handler.__name__ = tool_name
            handler.__doc__ = definition["description"] + " Input: " + json.dumps(definition["input_schema"])
            return handler

        server.tool(name=name, description=definition["description"])(make(name))
    return server


if __name__ == "__main__":  # pragma: no cover
    build_server().run(transport="stdio")
