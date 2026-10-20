"""Tests for the stream helper that the command line and the hook plumbing share."""

from __future__ import annotations

import io
import os
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from test_operations import lazy

streams = lazy("jam.streams")
cli = lazy("jam.cli")
hook_io = lazy("jam.harness.hook_io")


class SilencedTest(unittest.TestCase):
    def test_a_stream_whose_reader_has_gone_is_pointed_away_so_its_buffered_text_can_still_be_flushed(self):
        reader, writer = os.pipe()
        os.close(reader)
        stream = os.fdopen(writer, "w")
        self.addCleanup(lambda: None if stream.closed else os.close(writer))
        stream.write("text that can no longer be delivered")
        with self.assertRaises(BrokenPipeError):
            stream.flush()
        streams.silenced(stream)
        stream.close()  # the exit-time flush of the interpreter; it raises if the stream still points at the dead pipe

    def test_a_stream_with_no_descriptor_is_left_alone(self):
        streams.silenced(io.StringIO())

    def test_a_closed_stream_is_left_alone(self):
        stream = io.StringIO()
        stream.close()
        streams.silenced(stream)


class OneImplementationTest(unittest.TestCase):
    """Two paths that must agree on this are one function, so a fix cannot reach only one of them."""

    def test_the_command_line_and_the_hook_plumbing_use_the_same_function(self):
        self.assertIs(cli.silenced, streams.silenced)
        self.assertIs(hook_io.silenced, streams.silenced)


if __name__ == "__main__":
    unittest.main()
