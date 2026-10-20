"""A stdio MCP server over the operations table: newline-delimited JSON-RPC.

One message per line, no Content-Length header. The server keeps no lifecycle
state and answers any request at any time. Startup, initialize, tools/list and
unknown methods do no I/O, because the platform may start the server twice per
session start. Execution is serial; the client is the trusted parent process.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any, Final, Optional, Union

from . import operations

PROTOCOL_VERSIONS: Final = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME: Final = "jam"
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603


class Rejected(Exception):
    """A protocol-level failure, answered as a JSON-RPC error. Failures inside a tool are results instead."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def decoded(raw: Union[bytes, str]) -> str:
    try:
        return raw if isinstance(raw, str) else raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Rejected(PARSE_ERROR, "Parse error") from None


def parsed(text: str) -> object:
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        raise Rejected(PARSE_ERROR, "Parse error") from None


def envelope(raw: Union[bytes, str]) -> Optional[tuple[Union[str, int], str, object]]:
    """(id, method, params) of a request, or None for what is never answered.

    Never answered: blank lines, client responses, and notifications (no `id`
    member), whatever their method.
    """
    text = decoded(raw)
    if not text.strip():
        return None
    message = parsed(text)
    if not isinstance(message, dict):
        raise Rejected(INVALID_REQUEST, "Invalid Request")
    if "method" not in message:
        if "result" in message or "error" in message:
            return None
        raise Rejected(INVALID_REQUEST, "Invalid Request")
    if not isinstance(message["method"], str):
        raise Rejected(INVALID_REQUEST, "Invalid Request")
    if "id" not in message:
        return None
    request_id = message["id"]
    if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
        raise Rejected(INVALID_REQUEST, "Invalid Request")
    return request_id, message["method"], message.get("params")


def initialized(params: object, version: str) -> dict[str, Any]:
    """Echo the client's protocol version when it is a supported one, else offer the newest."""
    requested = params.get("protocolVersion") if isinstance(params, dict) else None
    return {
        "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": version},
    }


def tool(op: operations.Operation) -> dict[str, Any]:
    return {"name": op.name, "description": op.description, "inputSchema": operations.input_schema(op)}


def tool_result(runtime: operations.Runtime, params: object) -> dict[str, Any]:
    """Run one tool. An error inside a known tool is a result with isError, never a protocol error."""
    if not isinstance(params, dict) or not isinstance(params.get("name"), str):
        raise Rejected(INVALID_PARAMS, "Invalid params")
    op = operations.lookup(params["name"])
    arguments = params.get("arguments", {})
    if op is None or not isinstance(arguments, dict):
        raise Rejected(INVALID_PARAMS, "Invalid params")
    outcome = operations.call(runtime, op, arguments)
    return {"content": [{"type": "text", "text": outcome.text}], "isError": not outcome.ok}


def result_for(runtime: operations.Runtime, method: str, params: object, version: str) -> dict[str, Any]:
    if method == "initialize":
        return initialized(params, version)
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [tool(op) for op in operations.OPERATIONS]}
    if method == "tools/call":
        return tool_result(runtime, params)
    raise Rejected(METHOD_NOT_FOUND, "Method not found")


def reply(request_id: object, **body: object) -> str:
    """One wire line. ASCII-only, so it is locale-proof and can never hold a raw newline."""
    return json.dumps({"jsonrpc": "2.0", "id": request_id, **body})


def handle_line(runtime: operations.Runtime, raw: Union[bytes, str], version: str) -> Optional[str]:
    """The reply line for one input line, or None when none is due."""
    try:
        request = envelope(raw)
    except Rejected as bad:
        return reply(None, error={"code": bad.code, "message": bad.message})
    if request is None:
        return None
    request_id, method, params = request
    try:
        return reply(request_id, result=result_for(runtime, method, params, version))
    except Rejected as bad:
        return reply(request_id, error={"code": bad.code, "message": bad.message})
    except Exception:  # noqa: BLE001
        # A fault in the dispatcher itself. The detail could hold a path, so none is sent.
        return reply(request_id, error={"code": INTERNAL_ERROR, "message": "Internal error"})


def serve(runtime: operations.Runtime, lines: Iterable[Union[bytes, str]], write: Callable[[str], object], version: str) -> None:
    """Answer each line in turn until the input ends or the client stops reading."""
    for raw in lines:
        line = handle_line(runtime, raw, version)
        if line is None:
            continue
        try:
            write(line + "\n")
        except BrokenPipeError:
            return
