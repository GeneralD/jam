"""A stdio MCP server over the operations table: newline-delimited JSON-RPC.

One message per line, no Content-Length header. The server keeps no lifecycle
state and answers any request at any time. Startup, initialize, tools/list and
unknown methods do no I/O, because the platform may start the server twice per
session start. Execution is serial; the client is the trusted parent process.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable
from typing import Any, Final, Optional, Union

from . import operations

PROTOCOL_VERSIONS: Final = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME: Final = "jam"
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603


class Rejected(Exception):
    """A protocol-level failure, answered as a JSON-RPC error. Failures inside a tool are results instead."""

    def __init__(self, code: int, message: str, request_id: object = None):
        super().__init__(message)
        self.code, self.message, self.request_id = code, message, request_id


def decoded(raw: Union[bytes, str]) -> str:
    try:
        return raw if isinstance(raw, str) else raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Rejected(PARSE_ERROR, "Parse error") from None


def refused_constant(name: str) -> object:
    """What `json.loads` calls for NaN, Infinity and -Infinity, which strict JSON does not have."""
    raise ValueError(name)


def parsed(text: str) -> object:
    try:
        return json.loads(text, parse_constant=refused_constant)
    except (ValueError, RecursionError):
        raise Rejected(PARSE_ERROR, "Parse error") from None


def valid_id(value: object) -> bool:
    """A request id is a string or a number: not null, not a boolean, not a container, and not a number JSON cannot write."""
    if isinstance(value, bool):
        return False
    if isinstance(value, float):
        return math.isfinite(value)  # `1e999` is legal JSON that reads as inf, and inf has no JSON form to echo
    return isinstance(value, (str, int))


def envelope(raw: Union[bytes, str]) -> Optional[tuple[Union[str, int, float], str, object]]:
    """(id, method, params) of a request, or None for what is never answered.

    The message must be an object whose `jsonrpc` is exactly "2.0"; that is
    checked before anything else is read from it. Then never answered: blank
    lines, client responses (a `result` or `error`, no `method`), and
    notifications (no `id` member), whatever their method. An absent `params`
    comes back as `{}`; a present one comes back as it is, so null stays wrong.
    """
    text = decoded(raw)
    if not text.strip():
        return None
    message = parsed(text)
    if not isinstance(message, dict):
        raise Rejected(INVALID_REQUEST, "Invalid Request")
    if message.get("jsonrpc") != "2.0":
        # The client may be waiting on its id, so a readable one is echoed.
        raise Rejected(INVALID_REQUEST, "Invalid Request", message["id"] if valid_id(message.get("id")) else None)
    if "method" not in message:
        if "result" in message or "error" in message:
            return None
        raise Rejected(INVALID_REQUEST, "Invalid Request")
    if not isinstance(message["method"], str):
        raise Rejected(INVALID_REQUEST, "Invalid Request")
    if "id" not in message:
        return None
    request_id = message["id"]
    if not valid_id(request_id):
        raise Rejected(INVALID_REQUEST, "Invalid Request")
    return request_id, message["method"], message.get("params", {})


def initialized(params: dict[str, Any], version: str) -> dict[str, Any]:
    """Echo the client's protocol version when it is a supported one, else offer the newest."""
    requested = params.get("protocolVersion")
    return {
        "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": version},
    }


def tool(op: operations.Operation) -> dict[str, Any]:
    return {"name": op.name, "description": op.description, "inputSchema": operations.input_schema(op)}


def tool_result(runtime: operations.Runtime, params: dict[str, Any]) -> dict[str, Any]:
    """Run one tool. An error inside a known tool is a result with isError, never a protocol error."""
    if not isinstance(params.get("name"), str):
        raise Rejected(INVALID_PARAMS, "Invalid params")
    op = operations.lookup(params["name"])
    arguments = params.get("arguments", {})
    if op is None or not isinstance(arguments, dict):
        raise Rejected(INVALID_PARAMS, "Invalid params")
    outcome = operations.call(runtime, op, arguments)
    return {"content": [{"type": "text", "text": outcome.text}], "isError": not outcome.ok}


# The methods served, each as (runtime, params, version) -> result. Every one takes an object for params, or none.
HANDLERS: Final = {
    "initialize": lambda runtime, params, version: initialized(params, version),
    "ping": lambda runtime, params, version: {},
    "tools/list": lambda runtime, params, version: {"tools": [tool(op) for op in operations.OPERATIONS]},
    "tools/call": lambda runtime, params, version: tool_result(runtime, params),
}


def result_for(runtime: operations.Runtime, method: str, params: object, version: str) -> dict[str, Any]:
    handler = HANDLERS.get(method)
    if handler is None:
        raise Rejected(METHOD_NOT_FOUND, "Method not found")
    if not isinstance(params, dict):
        raise Rejected(INVALID_PARAMS, "Invalid params")
    return handler(runtime, params, version)


def reply(request_id: object, **body: object) -> str:
    """One wire line. ASCII-only, so it is locale-proof and can never hold a raw newline."""
    return json.dumps({"jsonrpc": "2.0", "id": request_id, **body})


def handle_line(runtime: operations.Runtime, raw: Union[bytes, str], version: str) -> Optional[str]:
    """The reply line for one input line, or None when none is due."""
    try:
        request = envelope(raw)
    except Rejected as bad:
        return reply(bad.request_id, error={"code": bad.code, "message": bad.message})
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
