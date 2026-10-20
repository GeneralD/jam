"""Tests for repository identity: what a path belongs to, found by reading files and never by running git.

The hand-built layouts need no git binary. Whatever sits above the temp
directory (a checkout, a dotfiles repository) must not decide the outcome, so
those tests hide every `.git` outside their own tree.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts src/ on sys.path)

import gitrepo
from test_operations import lazy

repos = lazy("jam.repos")

LEVELS = 64  # the number of directories the walk looks at, the start included


@contextlib.contextmanager
def git_entries_seen_through(handler, real=os.lstat):
    """Replace the lstat of a `.git` entry by `handler(path, real_lstat)`; every other lstat is the real one."""

    def lstat(path, *args, **kwargs):
        text = os.fspath(path)
        if os.path.basename(text) == ".git":
            return handler(text, real)
        return real(path, *args, **kwargs)

    with mock.patch("jam.repos.os.lstat", lstat):
        yield


def vanished(text, real):
    raise FileNotFoundError(errno.ENOENT, "hidden", text)


class RepoTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)

    def hidden_above_root(self):
        """Make every `.git` outside the temp tree look absent."""
        prefix = str(self.root) + os.sep

        def handler(text, real):
            if text.startswith(prefix):
                return real(text)
            return vanished(text, real)

        context = git_entries_seen_through(handler)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def plain(self, name="app"):
        path = self.root / name
        (path / ".git").mkdir(parents=True)
        return path

    def linked_worktree(self, main, name="wt", relative=False):
        """A linked worktree laid out as git does: a `.git` file naming <main>/.git/worktrees/<name>, which holds `commondir`."""
        gitdir = main / ".git" / "worktrees" / name
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
        tree = self.root / name
        tree.mkdir()
        target = os.path.relpath(gitdir, tree) if relative else str(gitdir)
        (tree / ".git").write_text(f"gitdir: {target}\n", encoding="utf-8")
        return tree

    def pointer(self, data, name="app"):
        """A directory whose `.git` is a file holding `data`."""
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        (path / ".git").write_bytes(data)
        return path


class ResolvedTest(RepoTestCase):
    def test_what_is_not_an_absolute_path_without_nul_is_none(self):
        for bad in ("", "relative/path", ".", "a\0b", "/a\0b", None, 5, b"/x", ["/x"]):
            with self.subTest(bad=repr(bad)):
                self.assertIsNone(repos.resolved(bad))

    def test_an_existing_path_is_its_real_path(self):
        (self.root / "dir").mkdir()
        self.assertEqual(repos.resolved(str(self.root / "dir")), str(self.root / "dir"))

    def test_a_link_is_followed_and_the_missing_tail_is_kept(self):
        (self.root / "real").mkdir()
        (self.root / "link").symlink_to(self.root / "real")
        self.assertEqual(repos.resolved(str(self.root / "link" / "new" / "deep" / "f.txt")), str(self.root / "real" / "new" / "deep" / "f.txt"))

    def test_a_lookup_that_fails_in_the_file_system_is_none_for_it_and_for_everything_built_on_it(self):
        # A link removed between the lstat that found it and the readlink that follows it makes realpath raise on some versions.
        (self.root / "dir").mkdir()
        with mock.patch("jam.repos.os.path.realpath", side_effect=OSError(errno.EINVAL, "Invalid argument")):
            self.assertIsNone(repos.resolved(str(self.root / "dir")))
            self.assertIsNone(repos.repo_of(str(self.root / "dir")))

    def test_dot_dot_after_a_missing_part_is_folded_away(self):
        self.assertEqual(repos.resolved(str(self.root / "missing" / ".." / "x")), str(self.root / "x"))


class NearestDirectoryTest(RepoTestCase):
    def test_an_existing_directory_is_its_own_nearest_directory(self):
        self.assertEqual(repos.nearest_directory(str(self.root)), str(self.root))

    def test_a_file_has_its_parent(self):
        (self.root / "f.txt").write_text("x")
        self.assertEqual(repos.nearest_directory(str(self.root / "f.txt")), str(self.root))

    def test_a_missing_tail_is_cut_down_to_the_deepest_existing_directory(self):
        (self.root / "a").mkdir()
        self.assertEqual(repos.nearest_directory(str(self.root / "a" / "b" / "c" / "f.txt")), str(self.root / "a"))

    def test_a_path_below_a_file_starts_at_the_directory_holding_the_file(self):
        (self.root / "f.txt").write_text("x")
        self.assertEqual(repos.nearest_directory(str(self.root / "f.txt" / "x" / "y")), str(self.root))


class PlainRepositoryTest(RepoTestCase):
    def setUp(self):
        super().setUp()
        self.hidden_above_root()

    def test_a_plain_repository_has_its_git_directory_as_identity_and_its_working_tree_as_root(self):
        app = self.plain()
        repo = repos.repo_of(str(app))
        self.assertEqual((repo.root, repo.identity), (str(app), str(app / ".git")))

    def test_a_nested_directory_belongs_to_the_repository_above_it(self):
        app = self.plain()
        (app / "src" / "deep").mkdir(parents=True)
        self.assertEqual(repos.repo_of(str(app / "src" / "deep")).root, str(app))

    def test_a_file_that_exists_belongs_to_the_repository_holding_it(self):
        app = self.plain()
        (app / "f.txt").write_text("x")
        self.assertEqual(repos.repo_of(str(app / "f.txt")).root, str(app))

    def test_a_target_that_does_not_exist_yet_is_judged_by_its_nearest_existing_directory(self):
        app = self.plain()
        repo = repos.repo_of(str(app / "new" / "a" / "b" / "file.ts"))
        self.assertEqual((repo.root, repo.identity), (str(app), str(app / ".git")))

    def test_a_path_below_a_regular_file_is_judged_by_the_directory_holding_it(self):
        app = self.plain()
        (app / "f.txt").write_text("x")
        self.assertEqual(repos.repo_of(str(app / "f.txt" / "x" / "y")).root, str(app))

    def test_no_repository_anywhere_is_none(self):
        (self.root / "plain" / "dir").mkdir(parents=True)
        self.assertIsNone(repos.repo_of(str(self.root / "plain" / "dir" / "f.txt")))

    def test_a_path_that_is_not_an_absolute_path_is_none(self):
        self.plain()
        for bad in ("", "app", "a\0b", None, 5):
            with self.subTest(bad=repr(bad)):
                self.assertIsNone(repos.repo_of(bad))

    def test_the_innermost_repository_wins(self):
        outer = self.plain("outer")
        inner = outer / "vendor" / "inner"
        (inner / ".git").mkdir(parents=True)
        self.assertEqual(repos.repo_of(str(inner / "f.txt")).root, str(inner))
        self.assertEqual(repos.repo_of(str(outer / "vendor" / "f.txt")).root, str(outer))

    def test_a_path_through_a_symbolic_link_is_the_repository_the_link_leads_to(self):
        app = self.plain()
        (app / "src").mkdir()
        (self.root / "shortcut").symlink_to(app)
        through = repos.repo_of(str(self.root / "shortcut" / "src" / "new.ts"))
        direct = repos.repo_of(str(app / "src" / "new.ts"))
        self.assertEqual((through.root, through.identity), (direct.root, direct.identity))
        self.assertEqual(through.root, str(app))


class WalkBoundTest(RepoTestCase):
    """The walk looks at the start directory and the ones above it, 64 directories in all."""

    def setUp(self):
        super().setUp()
        self.hidden_above_root()

    def chain(self, length):
        top = self.plain("top")
        leaf = top.joinpath(*(["d"] * length))
        leaf.mkdir(parents=True)
        return top, leaf

    def test_a_repository_at_the_64th_directory_is_found(self):
        top, leaf = self.chain(LEVELS - 1)
        self.assertEqual(repos.repo_of(str(leaf / "f.txt")).root, str(top))

    def test_a_repository_at_the_65th_directory_is_not(self):
        top, leaf = self.chain(LEVELS)
        self.assertIsNone(repos.repo_of(str(leaf / "f.txt")))


class LinkedWorktreeTest(RepoTestCase):
    def setUp(self):
        super().setUp()
        self.hidden_above_root()
        self.main = self.plain("main")

    def test_a_linked_worktree_is_the_repository_of_its_main_checkout(self):
        tree = self.linked_worktree(self.main)
        (tree / "src").mkdir()
        linked, main = repos.repo_of(str(tree / "src" / "f.ts")), repos.repo_of(str(self.main / "f.ts"))
        self.assertEqual(linked, main)
        self.assertEqual(linked.identity, str(self.main / ".git"))
        self.assertEqual((linked.root, main.root), (str(tree), str(self.main)))

    def test_a_relative_gitdir_is_resolved_against_the_directory_of_the_git_file(self):
        tree = self.linked_worktree(self.main, relative=True)
        self.assertEqual(repos.repo_of(str(tree)), repos.repo_of(str(self.main)))
        self.assertEqual(repos.repo_of(str(tree)).root, str(tree))

    def test_a_gitdir_without_commondir_is_its_own_repository(self):
        # The shape of a submodule: its git directory lives inside the superproject's, but it is not a worktree of it.
        sub = self.main / "sub"
        modules = self.main / ".git" / "modules" / "sub"
        modules.mkdir(parents=True)
        sub.mkdir()
        (sub / ".git").write_text("gitdir: ../.git/modules/sub\n", encoding="utf-8")
        inner, outer = repos.repo_of(str(sub / "f.ts")), repos.repo_of(str(self.main / "f.ts"))
        self.assertEqual((inner.root, inner.identity), (str(sub), str(modules)))
        self.assertNotEqual(inner, outer)

    def test_the_git_file_may_end_without_a_newline_and_carry_spaces_after_the_colon(self):
        for text in ("gitdir:%s", "gitdir: %s", "gitdir:   %s  \r\n"):
            with self.subTest(text=text):
                gitdir = self.main / ".git" / "worktrees" / "w"
                gitdir.mkdir(parents=True, exist_ok=True)
                (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
                tree = self.pointer((text % gitdir).encode("utf-8"), "tree")
                self.assertEqual(repos.repo_of(str(tree)).identity, str(self.main / ".git"))


class UnusableLayoutTest(RepoTestCase):
    """Anything odd about `.git` or `commondir` means "not a repository", never an error."""

    def setUp(self):
        super().setUp()
        self.hidden_above_root()
        self.real = self.plain("real")

    def assertNoRepository(self, directory):
        self.assertIsNone(repos.repo_of(str(directory / "f.ts")))

    def test_a_git_file_that_is_not_text_with_a_gitdir_line_is_none(self):
        pointing = f"gitdir: {self.real / '.git'}"
        cases = {
            "binary": b"\x00\x01\x02gitdir: x\n",
            "nul inside": (pointing + "\0\n").encode("utf-8"),
            "no gitdir prefix": b"hello\n",
            "a prefix of the same length, spelled differently": f"gitdir;{self.real / '.git'}\n".encode("utf-8"),
            "a prefix in capitals": f"GITDIR:{self.real / '.git'}\n".encode("utf-8"),
            "prefix not first": ("\n" + pointing).encode("utf-8"),
            "empty": b"",
            "nothing after the prefix": b"gitdir:\n",
            "only blanks after the prefix": b"gitdir:   \n",
            "one byte over 4096": (pointing + " " * (4097 - len(pointing) - 1) + "\n").encode("utf-8"),
            "missing directory": b"gitdir: " + bytes(self.root / "nowhere") + b"\n",
            "a file, not a directory": b"gitdir: " + bytes(self.real / ".git" / "HEAD") + b"\n",
        }
        (self.real / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        for name, data in cases.items():
            with self.subTest(case=name):
                self.assertNoRepository(self.pointer(data, "odd"))

    def test_a_git_file_of_exactly_4096_bytes_is_still_read(self):
        pointing = f"gitdir: {self.real / '.git'}"
        data = (pointing + " " * (4096 - len(pointing) - 1) + "\n").encode("utf-8")
        self.assertEqual(len(data), 4096)
        self.assertEqual(repos.repo_of(str(self.pointer(data, "edge") / "f.ts")).identity, str(self.real / ".git"))

    def test_a_git_entry_that_is_neither_a_directory_nor_a_regular_file_is_none(self):
        link = self.root / "linked"
        link.mkdir()
        (link / ".git").symlink_to(self.real / ".git")
        self.assertNoRepository(link)
        pipe = self.root / "piped"
        pipe.mkdir()
        os.mkfifo(pipe / ".git")  # a plain open would wait for a writer forever
        self.assertNoRepository(pipe)

    def test_a_git_entry_that_cannot_be_examined_is_none_and_the_walk_does_not_go_on(self):
        inner = self.real / "inner"
        inner.mkdir()

        def handler(text, real):
            if text == str(inner / ".git"):
                raise PermissionError(errno.EACCES, "Permission denied")
            return real(text)  # the repository one level up is readable, and must not be reached around the error

        with git_entries_seen_through(handler):
            self.assertIsNone(repos.repo_of(str(inner / "f.ts")))

    def test_a_commondir_that_cannot_be_used_is_none(self):
        variants = {
            "empty": lambda common: common.write_bytes(b""),
            "blank": lambda common: common.write_bytes(b"\n"),
            "one byte over 4096": lambda common: common.write_bytes(b"../.." + b" " * 4091 + b"\n"),
            "binary": lambda common: common.write_bytes(b"..\x00/..\n"),
            "a directory": lambda common: common.mkdir(),
            "a link": lambda common: common.symlink_to(self.real / ".git"),
        }
        for number, (name, make) in enumerate(variants.items()):
            with self.subTest(case=name):
                main = self.plain(f"main{number}")
                tree = self.linked_worktree(main, name=f"wt{number}")
                common = main / ".git" / "worktrees" / f"wt{number}" / "commondir"
                common.unlink()
                make(common)
                self.assertNoRepository(tree)


class KeyTest(RepoTestCase):
    def setUp(self):
        super().setUp()
        self.hidden_above_root()

    def test_the_key_is_sixteen_lowercase_hex_digits_of_the_sha256_of_the_identity(self):
        repo = repos.repo_of(str(self.plain()))
        self.assertRegex(repo.key(), r"[0-9a-f]{16}")
        self.assertEqual(repo.key(), hashlib.sha256(repo.identity.encode("utf-8")).hexdigest()[:16])

    def test_a_worktree_and_its_main_checkout_share_a_key_and_two_repositories_do_not(self):
        main = self.plain("main")
        other = self.plain("other")
        tree = self.linked_worktree(main)
        keys = [repos.repo_of(str(path)).key() for path in (main, tree, other)]
        self.assertEqual(keys[0], keys[1])
        self.assertNotEqual(keys[0], keys[2])

    def test_equality_follows_the_identity_and_not_the_root(self):
        main = self.plain("main")
        tree = self.linked_worktree(main)
        self.assertEqual(repos.repo_of(str(main)), repos.repo_of(str(tree)))
        self.assertEqual(hash(repos.repo_of(str(main))), hash(repos.repo_of(str(tree))))


@unittest.skipIf(gitrepo.GIT is None, "git is not installed")
class AgainstRealGitTest(RepoTestCase):
    """The hand-built layouts above are what git itself writes."""

    def setUp(self):
        super().setUp()
        self.home = self.root / "home"
        self.home.mkdir()
        self.main = self.root / "main"
        self.main.mkdir()
        gitrepo.git(self.home, self.main, "init", "-q")
        gitrepo.git(self.home, self.main, "commit", "-q", "--allow-empty", "-m", "first")

    def test_a_worktree_added_by_git_has_the_identity_of_its_main_checkout(self):
        tree = self.root / "tree"
        gitrepo.git(self.home, self.main, "worktree", "add", "-q", str(tree), "-b", "topic")
        (tree / "src").mkdir()
        linked, main = repos.repo_of(str(tree / "src" / "f.ts")), repos.repo_of(str(self.main / "f.ts"))
        self.assertEqual(linked, main)
        self.assertEqual((linked.root, main.root), (str(tree), str(self.main)))

    def test_a_submodule_added_by_git_is_its_own_repository(self):
        library = self.root / "library"
        library.mkdir()
        gitrepo.git(self.home, library, "init", "-q")
        gitrepo.git(self.home, library, "commit", "-q", "--allow-empty", "-m", "first")
        gitrepo.git(self.home, self.main, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(library), "vendor")
        inner, outer = repos.repo_of(str(self.main / "vendor" / "f.ts")), repos.repo_of(str(self.main / "f.ts"))
        self.assertEqual(inner.root, str(self.main / "vendor"))
        self.assertNotEqual(inner, outer)


if __name__ == "__main__":
    unittest.main()
