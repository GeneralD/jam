"""Tests for how the MCP server reads one JSON-RPC message: version, params, JSON constants and ids.

The wire is untrusted input, so each of these says what is answered, with which
error, and under which id. Helpers come from test_mcp; only functions are
imported, so unittest does not collect those tests a second time.
"""

from __future__ import annotations

import json
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from test_mcp import NEWEST, VERSION, answer, mcp, request, serve_lines, tool_call, tool_result
from test_operations import runtime_for
from test_service import FakeHarness

INVALID_REQUEST, INVALID_PARAMS, METHOD_NOT_FOUND, PARSE_ERROR = -32600, -32602, -32601, -32700


def message(**members):
    """One wire line holding exactly the members given, so any of them can be left out or made odd."""
    return json.dumps(members)


def refuse(constant):
    raise AssertionError(f"a non-JSON constant went onto the wire: {constant}")


def error_of(case, reply):
    """The error member of a reply, or a plain failure when the server answered with a result instead."""
    case.assertIsNotNone(reply, "no reply was sent")
    case.assertIn("error", reply, f"answered instead of rejecting: {reply}")
    return reply["error"]


def wire(line):
    """The reply to a raw line, parsed as strict JSON: NaN, Infinity and -Infinity fail the test."""
    return json.loads(mcp.handle_line(runtime_for(), line.encode("utf-8"), VERSION), parse_constant=refuse)


class VersionTest(unittest.TestCase):
    PING = {"id": 1, "method": "ping"}

    def assert_invalid_request(self, reply, id_=None):
        error = error_of(self, reply)
        self.assertEqual((error["code"], error["message"]), (INVALID_REQUEST, "Invalid Request"))
        self.assertEqual(reply["jsonrpc"], "2.0")
        self.assertNotIn("result", reply)
        self.assertEqual(reply["id"], id_)
        self.assertIs(type(reply["id"]), type(id_))

    def test_a_message_without_jsonrpc_is_an_invalid_request(self):
        self.assert_invalid_request(answer(message(**self.PING)), 1)

    def test_any_other_jsonrpc_value_is_an_invalid_request(self):
        for version in ("1.0", "2", "2.0.0", " 2.0", "", 2.0, 2, None, True, ["2.0"], {"v": "2.0"}):
            with self.subTest(jsonrpc=version):
                self.assert_invalid_request(answer(message(jsonrpc=version, **self.PING)), 1)

    def test_the_version_is_checked_before_the_method_is_looked_up(self):
        for method in ("ping", "initialize", "tools/list", "tools/call", "nonsense"):
            with self.subTest(method=method):
                self.assert_invalid_request(answer(message(jsonrpc="1.0", id=1, method=method)), 1)

    def test_the_id_is_echoed_only_when_it_is_a_valid_request_id(self):
        for id_ in (1, 0, "abc", "", 1.5):
            with self.subTest(id=id_):
                self.assert_invalid_request(answer(message(jsonrpc="1.0", id=id_, method="ping")), id_)
        for id_ in (None, True, False, [1], {"a": 1}):
            with self.subTest(id=id_):
                self.assert_invalid_request(answer(message(jsonrpc="1.0", id=id_, method="ping")))

    def test_a_message_with_no_id_at_all_gets_a_null_id(self):
        self.assert_invalid_request(answer(message(method="ping")))
        self.assert_invalid_request(answer(message(jsonrpc="1.0", method="ping")))

    def test_a_notification_without_the_version_is_not_taken_for_one(self):
        for method in ("notifications/initialized", "notifications/cancelled", "nonsense"):
            with self.subTest(method=method):
                self.assert_invalid_request(answer(message(method=method)))
                self.assertIsNone(answer(message(jsonrpc="2.0", method=method)))

    def test_a_client_response_is_ignored_only_when_it_carries_the_version(self):
        for member in ({"result": {}}, {"error": {"code": -32601, "message": "no"}}):
            with self.subTest(member=member):
                self.assertIsNone(answer(message(jsonrpc="2.0", id=1, **member)))
                self.assert_invalid_request(answer(message(id=1, **member)), 1)
                self.assert_invalid_request(answer(message(jsonrpc="1.0", id="x", **member)), "x")

    def test_the_server_keeps_going_after_a_message_of_the_wrong_version(self):
        lines = [message(**self.PING), message(jsonrpc="2.0", id=2, method="ping")]
        replies = [json.loads(chunk) for chunk in serve_lines(runtime_for(), lines)]
        self.assertEqual([(reply["id"], "error" in reply) for reply in replies], [(1, True), (2, False)])


class ParamsTest(unittest.TestCase):
    TAKE_PARAMS = ("initialize", "tools/list", "ping", "tools/call")
    NOT_OBJECTS = ([], [1], ["name"], "x", "", 5, 0, 1.5, True, False, None)

    def call(self, method, **extra):
        return answer(message(jsonrpc="2.0", id=1, method=method, **extra))

    def test_a_params_that_is_not_an_object_is_invalid_params(self):
        for method in self.TAKE_PARAMS:
            for params in self.NOT_OBJECTS:
                with self.subTest(method=method, params=params):
                    reply = self.call(method, params=params)
                    error = error_of(self, reply)
                    self.assertEqual((error["code"], error["message"], reply["id"]), (INVALID_PARAMS, "Invalid params", 1))

    def test_absent_and_empty_params_are_fine_where_the_method_needs_none(self):
        for method in ("initialize", "tools/list", "ping"):
            for extra in ({}, {"params": {}}):
                with self.subTest(method=method, extra=extra):
                    self.assertNotIn("error", self.call(method, **extra))
        self.assertEqual(self.call("initialize")["result"]["protocolVersion"], NEWEST)

    def test_extra_members_in_the_params_of_a_known_method_are_still_accepted(self):
        for method in ("initialize", "tools/list", "ping"):
            with self.subTest(method=method):
                self.assertNotIn("error", self.call(method, params={"_meta": {"progressToken": 1}, "cursor": "c"}))

    def test_an_unknown_method_is_not_found_whatever_its_params(self):
        for params in (*self.NOT_OBJECTS, {}):
            with self.subTest(params=params):
                self.assertEqual(error_of(self, self.call("nonsense", params=params))["code"], METHOD_NOT_FOUND)

    def test_a_notification_is_never_answered_whatever_its_params(self):
        for method in self.TAKE_PARAMS:
            for params in self.NOT_OBJECTS:
                with self.subTest(method=method, params=params):
                    self.assertIsNone(answer(message(jsonrpc="2.0", method=method, params=params)))


class JsonConstantTest(unittest.TestCase):
    CONSTANTS = ("NaN", "Infinity", "-Infinity")

    def lines(self, constant):
        head = '{"jsonrpc":"2.0",'
        return {
            "member": head + f'"id":1,"method":"ping","x":{constant}}}',
            "array": head + f'"id":1,"method":"ping","x":[{constant}]}}',
            "id": head + f'"id":{constant},"method":"ping"}}',
            "argument": head + f'"id":1,"method":"tools/call","params":{{"name":"list","arguments":{{"cwd":{constant}}}}}}}',
        }

    def test_the_constants_json_does_not_have_are_parse_errors_with_a_null_id(self):
        for constant in self.CONSTANTS:
            for place, line in self.lines(constant).items():
                with self.subTest(constant=constant, place=place):
                    for raw in (line, line.encode("utf-8")):
                        reply = answer(raw)
                        error = error_of(self, reply)
                        self.assertEqual((error["code"], error["message"]), (PARSE_ERROR, "Parse error"))
                        self.assertIsNone(reply["id"])

    def test_the_same_words_as_text_are_ordinary_strings(self):
        text = "NaN Infinity -Infinity"
        self.assertEqual(wire('{"jsonrpc":"2.0","id":1,"method":"ping","x":"NaN"}')["result"], {})
        self.assertEqual(wire('{"jsonrpc":"2.0","id":"Infinity","method":"ping","x":"-Infinity"}')["id"], "Infinity")
        harness = FakeHarness()
        reply = answer(tool_call("spawn", {"cwd": "/work/x", "prompt": text}), runtime_for(harness))
        self.assertFalse(tool_result(reply)[0])
        self.assertEqual(harness.spawn_calls, [("/work/x", text, None, None)])

    def test_the_server_keeps_going_after_a_line_with_a_constant(self):
        lines = [self.lines("NaN")["member"], message(jsonrpc="2.0", id=2, method="ping")]
        replies = [json.loads(chunk) for chunk in serve_lines(runtime_for(), lines)]
        self.assertEqual([(reply["id"], reply.get("error", {}).get("code")) for reply in replies], [(None, PARSE_ERROR), (2, None)])

    def test_a_number_that_overflows_to_infinity_is_never_echoed_as_a_constant(self):
        # `1e999` is a legal JSON number that Python reads as inf, and `parse_constant` never sees it.
        for number in ("1e999", "-1e999"):
            with self.subTest(number=number):
                reply = wire('{"jsonrpc":"2.0","id":' + number + ',"method":"ping"}')
                self.assertEqual(error_of(self, reply)["code"], INVALID_REQUEST)
                self.assertIsNone(reply["id"])


class IdTest(unittest.TestCase):
    def test_a_number_id_with_a_fraction_is_echoed_unchanged(self):
        for text in ("1.5", "-2.25", "0.5", "1.0", "0.0", "1e2", "123456.789"):
            with self.subTest(id=text):
                reply = wire('{"jsonrpc":"2.0","id":' + text + ',"method":"ping"}')
                self.assertEqual(reply.get("result"), {}, reply)
                self.assertEqual(reply["id"], json.loads(text))
                self.assertIs(type(reply["id"]), float)

    def test_the_fraction_survives_the_wire_text(self):
        line = mcp.handle_line(runtime_for(), b'{"jsonrpc":"2.0","id":1.5,"method":"ping"}', VERSION)
        self.assertIn('"id": 1.5', line)

    def test_an_error_reply_echoes_a_fractional_id_too(self):
        for message_ in (request("nonsense", id=1.5), tool_call("nope", id=1.5), request("initialize", [], id=1.5)):
            with self.subTest(method=message_["method"]):
                reply = answer(message_)
                error_of(self, reply)
                self.assertEqual(reply["id"], 1.5)

    def test_null_booleans_and_containers_are_still_invalid_requests(self):
        for text in ("null", "true", "false", "[]", "[1]", "{}", '{"a":1}'):
            with self.subTest(id=text):
                reply = wire('{"jsonrpc":"2.0","id":' + text + ',"method":"ping"}')
                self.assertEqual(error_of(self, reply)["code"], INVALID_REQUEST)
                self.assertIsNone(reply["id"])


class NullUnknownArgumentTest(unittest.TestCase):
    def test_a_null_valued_unknown_argument_is_a_tool_error_and_runs_nothing(self):
        harness = FakeHarness()
        reply = answer(tool_call("list", {"bogus": None}), runtime_for(harness))
        self.assertNotIn("error", reply)
        is_error, text = tool_result(reply)
        self.assertTrue(is_error)
        self.assertIn("unknown argument: bogus", text)
        self.assertEqual(harness.list_calls, [])


if __name__ == "__main__":
    unittest.main()
