"""Tests for how the CLI treats real streams, signals and bytes: pipes, Ctrl-C and stdin."""

from __future__ import annotations

import contextlib
import io
import json
import os
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from test_cli import cli, run_cli, text_stream
from test_operations import identity, operations, raising, runtime_for


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
