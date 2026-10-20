"""Tests for the hook plumbing: the SessionStart envelope, the capped stdin read, the alarm and the quiet streams."""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from test_operations import lazy

hook_io = lazy("jam.harness.hook_io")

CAP = 256 * 1024


class Reads:
    """A binary stream that remembers how much each read asked for."""

    def __init__(self, data):
        self._data, self.sizes = data, []

    def read(self, size=-1):
        self.sizes.append(size)
        return self._data if size < 0 else self._data[:size]


class NothingYet:
    """A non-blocking pipe whose writer has not written yet: a read answers None, not b""."""

    def read(self, size=-1):
        return None


class Failing:
    def __init__(self, error):
        self._error = error

    def read(self, size=-1):
        raise self._error

    def write(self, text):
        raise self._error


class EnvelopeTest(unittest.TestCase):
    def test_it_parses_back_to_exactly_the_nested_session_start_shape(self):
        self.assertEqual(
            json.loads(hook_io.hook_output("hello")),
            {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "hello"}},
        )

    def test_the_context_is_nested_because_a_top_level_key_is_silently_ignored(self):
        parsed = json.loads(hook_io.hook_output("x"))
        self.assertEqual(list(parsed), ["hookSpecificOutput"])
        self.assertNotIn("additionalContext", parsed)

    def test_the_line_has_no_raw_newline_and_survives_awkward_text(self):
        text = 'line one\nline "two"\r\n\t日本語 \\   \ud800'
        line = hook_io.hook_output(text)
        self.assertNotIn("\n", line)
        self.assertNotIn("\r", line)
        self.assertTrue(line.isascii())
        self.assertEqual(json.loads(line)["hookSpecificOutput"]["additionalContext"], text)


class PayloadTest(unittest.TestCase):
    def test_a_json_object_is_returned_as_it_is(self):
        self.assertEqual(hook_io.payload_from(io.BytesIO(b'{"session_id":"a","source":"startup","new":[1]}')), {"session_id": "a", "source": "startup", "new": [1]})

    def test_anything_else_is_an_empty_payload(self):
        for raw in (b"", b"  \n", b"[]", b'"x"', b"1", b"null", b"true", b"{", b'{"a":', b"\xff\xfe", b"\x00", b"{} trailing", b"[" * 100000):
            with self.subTest(raw=raw[:12]):
                self.assertEqual(hook_io.payload_from(io.BytesIO(raw)), {})

    def test_a_payload_at_the_cap_is_read_and_one_byte_more_is_not(self):
        pad = CAP - len(b'{"a":""}')
        self.assertEqual(hook_io.payload_from(io.BytesIO(b'{"a":"' + b"x" * pad + b'"}')), {"a": "x" * pad})
        self.assertEqual(hook_io.payload_from(io.BytesIO(b'{"a":"' + b"x" * (pad + 1) + b'"}')), {})

    def test_it_never_asks_the_stream_for_more_than_the_cap_plus_one_byte(self):
        stream = Reads(b"{}" + b" " * (2 * CAP))
        hook_io.payload_from(stream)
        self.assertEqual(stream.sizes, [CAP + 1])

    def test_the_cap_is_a_parameter(self):
        self.assertEqual(hook_io.payload_from(io.BytesIO(b'{"a":1}'), limit=7), {"a": 1})
        self.assertEqual(hook_io.payload_from(io.BytesIO(b'{"a":1} '), limit=7), {})

    def test_a_read_that_has_nothing_yet_is_an_empty_payload(self):
        self.assertEqual(hook_io.payload_from(NothingYet()), {})

    def test_an_unreadable_stream_is_an_empty_payload(self):
        for error in (OSError("closed"), ValueError("I/O operation on closed file")):
            with self.subTest(error=error):
                self.assertEqual(hook_io.payload_from(Failing(error)), {})


class AlarmTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(signal.signal, signal.SIGALRM, signal.getsignal(signal.SIGALRM))
        self.addCleanup(signal.pthread_sigmask, signal.SIG_SETMASK, signal.pthread_sigmask(signal.SIG_BLOCK, set()))

    def test_it_arms_the_alarm_for_the_given_seconds(self):
        calls = []
        hook_io.arm_alarm(3, alarm=calls.append)
        self.assertEqual(calls, [3])

    def test_it_puts_the_default_disposition_back_so_an_inherited_ignore_cannot_defeat_the_bound(self):
        signal.signal(signal.SIGALRM, signal.SIG_IGN)
        hook_io.arm_alarm(2, alarm=lambda seconds: None)
        self.assertEqual(signal.getsignal(signal.SIGALRM), signal.SIG_DFL)

    def test_it_unblocks_the_signal_so_an_inherited_mask_cannot_hold_the_alarm_back(self):
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
        hook_io.arm_alarm(2, alarm=lambda seconds: None)
        self.assertNotIn(signal.SIGALRM, signal.pthread_sigmask(signal.SIG_BLOCK, set()))

    def test_zero_cancels_without_complaint(self):
        calls = []
        hook_io.arm_alarm(0, alarm=calls.append)
        self.assertEqual(calls, [0])


class StreamTest(unittest.TestCase):
    def test_a_line_is_written_with_one_newline_and_flushed(self):
        stream = io.StringIO()
        hook_io.emitted(stream, "abc")
        self.assertEqual(stream.getvalue(), "abc\n")

    def test_a_vanished_reader_raises_and_leaves_nothing_for_the_exit_time_flush_to_fail_on(self):
        reader, writer = os.pipe()
        os.close(reader)
        stream = os.fdopen(writer, "w")
        self.addCleanup(lambda: None if stream.closed else os.close(writer))
        with self.assertRaises(BrokenPipeError):
            hook_io.emitted(stream, "abc")
        stream.close()  # the interpreter's own exit-time flush; it raises if the text is still buffered for a dead pipe

    def test_any_other_failed_write_also_raises_and_leaves_nothing_for_the_exit_time_flush(self):
        descriptor = os.open(os.devnull, os.O_RDONLY)  # a descriptor nothing can be written to: the flush fails with EBADF
        stream = os.fdopen(descriptor, "w")
        self.addCleanup(lambda: None if stream.closed else os.close(descriptor))
        with self.assertRaises(OSError) as raised:
            hook_io.emitted(stream, "abc")
        self.assertNotIsInstance(raised.exception, BrokenPipeError)
        stream.close()  # the interpreter's own exit-time flush; it raises if the text is still buffered for a descriptor that cannot take it

    def test_only_the_exception_type_is_reported(self):
        stream = io.StringIO()
        hook_io.reported(stream, RuntimeError("secret detail in /some/private/path"))
        self.assertEqual(stream.getvalue(), "RuntimeError\n")

    def test_a_broken_error_stream_is_not_an_error(self):
        hook_io.reported(Failing(OSError("closed")), RuntimeError("x"))
        hook_io.reported(Failing(BrokenPipeError()), RuntimeError("x"))

    def test_an_error_stream_that_does_not_exist_is_not_an_error(self):
        hook_io.reported(None, RuntimeError("x"))  # descriptor 2 was closed before the interpreter started: sys.stderr is None


class BrokenErrorStreamTest(unittest.TestCase):
    def test_a_crash_reported_to_a_vanished_stderr_still_exits_zero(self):
        # The failed write leaves its text buffered; unless the stream is silenced, the exit-time flush fails again and the status becomes 120.
        code = "import sys; sys.path.insert(0, sys.argv[1]); from jam.harness import hook_io; hook_io.reported(sys.stderr, RuntimeError('x'))"
        child = subprocess.Popen([sys.executable, "-I", "-c", code, str(support.SRC)], stderr=subprocess.PIPE)
        child.stderr.close()  # the reader is gone before the child writes anything
        self.assertEqual(child.wait(timeout=30), 0)


if __name__ == "__main__":
    unittest.main()
