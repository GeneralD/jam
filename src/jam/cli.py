"""The command line: an argparse parser generated from the operations table.

stdout carries exactly one JSON line per command, byte-identical to the MCP tool
result for the same arguments. A failure is one `jam: ...` line on stderr and
exit 1; a usage error is exit 2; an interrupt ends the command quietly with 130.
A reader that has gone away is never an error of the operation, nor of --help or
a usage error: whatever was being printed is dropped, with no traceback and the
same exit code. `main` takes its environment, streams and runtime builder as
arguments, so tests never touch the real ones.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import textwrap
from collections.abc import Mapping
from functools import reduce
from typing import IO, Any, Callable, Final, Optional

from . import compose, mcp, operations
from .streams import silenced

PROG: Final = "jam"
INTERRUPTED: Final = 130  # the shell's status for a command ended by SIGINT
EPILOGS: Final = {
    "spawn": (
        "The brief goes after `--`, so it may start with a dash.\nFor a long or multi-line brief:\n\n"
        '  <jam> spawn --cwd /abs/dir -- "$(cat <<\'BRIEF\'\n'
        "  ...the complete brief...\n"
        "  BRIEF\n"
        '  )"'
    ),
}


class Parser(argparse.ArgumentParser):
    """An argparse parser whose usage errors read `jam: usage error: ...` and exit 2."""

    def error(self, message: str) -> Any:
        self.print_usage(sys.stderr)
        self.exit(2, f"{PROG}: usage error: {message}\n")


class Subcommand(Parser):
    """A command's own parser. It rejects what it does not know itself, so the usage line shown is its own.

    argparse would hand the extras back to the root parser, which would then print the root usage.
    """

    def parse_known_args(self, args: Any = None, namespace: Any = None) -> Any:
        parsed, extras = super().parse_known_args(args, namespace)
        if extras:
            self.error(f"unrecognized arguments: {' '.join(extras)}")
        return parsed, extras


def flag_of(param: operations.Param) -> str:
    return "--" + param.name.replace("_", "-")


# The operations text spells arguments the MCP way, include_exited; on this command line they are flags.
FLAG_SPELLINGS: Final = {param.name: flag_of(param) for op in operations.OPERATIONS for param in op.params if "_" in param.name and not param.positional}


def spelled_as_flags(text: str) -> str:
    return reduce(lambda spelled, name: spelled.replace(name, FLAG_SPELLINGS[name]), FLAG_SPELLINGS, text)


def add_param(parser: argparse.ArgumentParser, param: operations.Param) -> None:
    if param.positional:
        parser.add_argument(param.name, metavar=param.name.upper(), help=param.description)
    elif param.kind == "boolean":
        parser.add_argument(flag_of(param), dest=param.name, action="store_true", default=None, help=param.description)
    else:
        metavar = "ABSOLUTE_DIR" if param.absolute else param.name.upper()
        parser.add_argument(flag_of(param), dest=param.name, metavar=metavar, required=param.required, help=param.description)


def add_command(commands: Any, op: operations.Operation) -> None:
    parser = commands.add_parser(
        op.name,
        help=op.summary,
        description=textwrap.fill(spelled_as_flags(op.description), 79),
        epilog=EPILOGS.get(op.name),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    for param in op.params:
        add_param(parser, param)


def build_parser() -> argparse.ArgumentParser:
    # Python 3.14 adds colour to help and usage; a model reading Bash output wants plain text.
    plain = {"color": False} if sys.version_info >= (3, 14) else {}
    parser = Parser(prog=PROG, allow_abbrev=False, description="Start and manage background Claude Code sessions.", **plain)
    parser.add_argument("--data-dir", metavar="DIR", default=None, help="where jam keeps its notes (must precede the command)")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True, parser_class=Subcommand)
    for op in operations.OPERATIONS:
        add_command(commands, op)
    commands.add_parser("mcp", allow_abbrev=False)  # used by the manifest's mcpServers; deliberately has no help line
    return parser


def parsed(argv: list[str], stdout: IO[str], stderr: IO[str]) -> tuple[Optional[argparse.Namespace], int]:
    """The parsed arguments, or None with the exit code argparse chose (0 for --help, 2 for a usage error).

    argparse prints into memory and the text goes out afterwards through `emitted`.
    Printing straight to a stream whose reader has gone raises on Python 3.9, is
    swallowed on newer versions, and in both leaves text in the buffer for the
    exit-time flush to fail on.
    """
    said, complained = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(said), contextlib.redirect_stderr(complained):
        try:
            namespace, code = build_parser().parse_args(argv), 0
        except SystemExit as exit_:
            namespace, code = None, exit_.code if isinstance(exit_.code, int) else 2
    emitted(stdout, said.getvalue())
    emitted(stderr, complained.getvalue())
    return namespace, code


def arguments_of(op: operations.Operation, namespace: argparse.Namespace) -> dict[str, Any]:
    values = {param.name: getattr(namespace, param.name) for param in op.params}
    return {name: value for name, value in values.items() if value is not None}


def utf8(stream: IO[str]) -> IO[str]:
    """Make a real stream write any character; a non-UTF-8 locale must not crash the printer."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
    return stream


def writer(stream: IO[str]) -> Callable[[str], None]:
    """Write and flush at once, as a reply must not wait in a buffer; raise BrokenPipeError once the reader is gone."""

    def write(text: str) -> None:
        try:
            stream.write(text)
            stream.flush()
        except BrokenPipeError:
            silenced(stream)
            raise

    return write


def emitted(stream: IO[str], text: str) -> None:
    """Say `text` and flush it; that nobody is left to read it is not an error of whatever was being said."""
    if text:
        with contextlib.suppress(BrokenPipeError):
            writer(stream)(text)


def serve(runtime: operations.Runtime, stdin: IO[str], stdout: IO[str]) -> int:
    mcp.serve(runtime, getattr(stdin, "buffer", stdin), writer(stdout), compose.plugin_version())
    return 0


def run(op: operations.Operation, runtime: operations.Runtime, namespace: argparse.Namespace, stdout: IO[str], stderr: IO[str]) -> int:
    outcome = operations.call(runtime, op, arguments_of(op, namespace))
    if outcome.ok:
        emitted(stdout, outcome.text + "\n")  # the operation ran; that nobody reads its result is not its failure
        return 0
    emitted(stderr, f"{PROG}: {outcome.text}\n")
    return 1


def dispatched(namespace: argparse.Namespace, env: Mapping[str, str], build: Callable[..., operations.Runtime], stdin: IO[str], stdout: IO[str], stderr: IO[str]) -> int:
    runtime = build(namespace.data_dir, env)
    if namespace.command == "mcp":
        return serve(runtime, stdin, stdout)
    return run(operations.lookup(namespace.command), runtime, namespace, stdout, stderr)


def main(
    argv: list[str],
    env: Optional[Mapping[str, str]] = None,
    stdin: Optional[IO[str]] = None,
    stdout: Optional[IO[str]] = None,
    stderr: Optional[IO[str]] = None,
    build: Optional[Callable[..., operations.Runtime]] = None,
) -> int:
    """Run one command and return its exit code. Everything it touches can be passed in."""
    env = os.environ if env is None else env
    build = compose.build_runtime if build is None else build
    stdin = sys.stdin if stdin is None else stdin
    stdout = utf8(sys.stdout) if stdout is None else stdout
    stderr = utf8(sys.stderr) if stderr is None else stderr
    namespace, code = parsed(argv, stdout, stderr)
    if namespace is None:
        return code
    try:
        return dispatched(namespace, env, build, stdin, stdout, stderr)
    except KeyboardInterrupt:
        return INTERRUPTED  # whoever sent it knows; a traceback would only add paths
