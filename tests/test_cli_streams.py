"""Tests for how the CLI treats real streams, signals and bytes: pipes, Ctrl-C and stdin."""

from __future__ import annotations

import contextlib
import io
import json
import os
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from jam.errors import HarnessError

from test_cli import SPAWN, cli, run_cli, text_stream, unused_build
from test_operations import identity, operations, raising, runtime_for
from test_service import FakeHarness


PING_LINE = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8") + b"\n"


def quiet_build(*args, **kwargs):
    return runtime_for()


class CountingStream(io.StringIO):
    flushes = 0

    def flush(self):
        self.flushes += 1
        super().flush()


class WriterTest(unittest.TestCase):
    def test_every_line_is_flushed_as_it_is_written(self):
        stream = CountingStream()
        write = cli.writer(stream)
        write("one\n")
        write("two\n")
        self.assertEqual((stream.getvalue(), stream.flushes), ("one\ntwo\n", 2))


class VanishedReaderTest(unittest.TestCase):
    """A pipe whose reader has gone: the exit-time flush of the leftover must not fail a second time."""

    def stream_without_reader(self):
        reader, writer = os.pipe()
        os.close(reader)
        stream = os.fdopen(writer, "w", encoding="utf-8")

        def close():
            with contextlib.suppress(BrokenPipeError):
                stream.close()

        self.addCleanup(close)
        return stream

    def test_the_mcp_server_ends_quietly(self):
        stream, err = self.stream_without_reader(), io.StringIO()
        code = cli.main(["mcp"], env={}, stdin=text_stream(PING_LINE * 3), stdout=stream, stderr=err, build=quiet_build)
        self.assertEqual((code, err.getvalue()), (0, ""))
        stream.flush()  # what the interpreter does at exit

    def test_a_command_result_is_not_an_operation_failure(self):
        stream, err = self.stream_without_reader(), io.StringIO()
        code = cli.main(["list"], env={}, stdin=text_stream(), stdout=stream, stderr=err, build=quiet_build)
        self.assertEqual((code, err.getvalue()), (0, ""))
        stream.flush()


class UsagePrintingTest(unittest.TestCase):
    """--help and a usage error are printed by argparse, outside the operation: a vanished reader is no traceback there either."""

    def stream_without_reader(self):
        return VanishedReaderTest.stream_without_reader(self)

    def test_help_on_a_vanished_stdout_exits_zero_and_leaves_nothing_to_fail_at_exit(self):
        for argv in (["--help"], ["spawn", "--help"], ["list", "-h"]):
            with self.subTest(argv=argv):
                stream, err = self.stream_without_reader(), io.StringIO()
                code = cli.main(argv, env={}, stdin=text_stream(), stdout=stream, stderr=err, build=unused_build)
                self.assertEqual((code, err.getvalue()), (0, ""))
                stream.flush()  # what the interpreter does at exit

    def test_a_usage_error_on_a_vanished_stderr_exits_two_and_prints_nothing(self):
        for argv in (["nonsense"], ["spawn"], ["list", "--bogus"], []):
            with self.subTest(argv=argv):
                stream, out = self.stream_without_reader(), io.StringIO()
                code = cli.main(argv, env={}, stdin=text_stream(), stdout=out, stderr=stream, build=unused_build)
                self.assertEqual((code, out.getvalue()), (2, ""))
                stream.flush()

    def test_a_failure_line_on_a_vanished_stderr_is_still_exit_one(self):
        runtime = runtime_for(FakeHarness(spawn_error=HarnessError("boom")))
        stream, out = self.stream_without_reader(), io.StringIO()
        code = cli.main([*SPAWN, "p"], env={}, stdin=text_stream(), stdout=out, stderr=stream, build=lambda *args, **kwargs: runtime)
        self.assertEqual((code, out.getvalue()), (1, ""))
        stream.flush()


class Unwritable(io.StringIO):
    """A stream whose every write fails the way a closed pipe does."""

    def write(self, text):
        raise BrokenPipeError


class Bare:
    """The least a stream needs: a write that fails like a closed pipe, a flush, and no file descriptor."""

    def write(self, text):
        raise BrokenPipeError

    def flush(self):
        pass


class FailingWriteTest(unittest.TestCase):
    def test_help_whose_write_raises_broken_pipe_exits_zero_without_a_traceback(self):
        for argv in (["--help"], ["spawn", "--help"]):
            with self.subTest(argv=argv):
                err = io.StringIO()
                code = cli.main(argv, env={}, stdin=text_stream(), stdout=Unwritable(), stderr=err, build=unused_build)
                self.assertEqual((code, err.getvalue()), (0, ""))

    def test_a_usage_error_whose_write_raises_broken_pipe_exits_two_without_a_traceback(self):
        for argv in (["nonsense"], ["spawn"]):
            with self.subTest(argv=argv):
                out = io.StringIO()
                code = cli.main(argv, env={}, stdin=text_stream(), stdout=out, stderr=Unwritable(), build=unused_build)
                self.assertEqual((code, out.getvalue()), (2, ""))

    def test_a_stream_with_no_descriptor_to_point_away_is_dropped_the_same_way(self):
        err = io.StringIO()
        self.assertEqual(cli.main(["--help"], env={}, stdin=text_stream(), stdout=Bare(), stderr=err, build=unused_build), 0)
        self.assertEqual(err.getvalue(), "")

    def test_help_and_usage_still_reach_a_reader_that_is_there(self):
        code, out, err = run_cli(["--help"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("usage: jam", out)
        code, out, err = run_cli(["nonsense"])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("jam: usage error:", err)


class Interrupting:
    """A stdin whose first read is the owner pressing Ctrl-C."""

    def __init__(self):
        self.buffer = self

    def __iter__(self):
        return self

    def __next__(self):
        raise KeyboardInterrupt


class InterruptTest(unittest.TestCase):
    def test_an_interrupted_server_ends_quietly_with_the_conventional_code(self):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(["mcp"], env={}, stdin=Interrupting(), stdout=out, stderr=err, build=quiet_build)
        self.assertEqual((code, out.getvalue(), err.getvalue()), (130, "", ""))

    def test_an_interrupted_command_ends_the_same_way(self):
        runtime = operations.Runtime(raising(KeyboardInterrupt()), identity)
        self.assertEqual(run_cli(["list"], runtime), (130, "", ""))


class StdinBytesTest(unittest.TestCase):
    def test_the_server_reads_bytes_and_decodes_them_as_strict_utf8(self):
        data = b'{"jsonrpc":"2.0","id":1,"method":"ping","x":"\xff"}\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
        stdin = io.TextIOWrapper(io.BytesIO(data), encoding="latin-1", newline="")  # a text layer that accepts every byte
        out = io.StringIO()
        code = cli.main(["mcp"], env={}, stdin=stdin, stdout=out, stderr=io.StringIO(), build=quiet_build)
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual([(reply["id"], reply.get("error", {}).get("code")) for reply in replies], [(None, -32700), (2, None)])


if __name__ == "__main__":
    unittest.main()
