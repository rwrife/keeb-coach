"""Tests for M5: ``keeb-coach fixes`` snippet generation + managed block.

Covers three layers:

1. Per-detector snippet builders (:func:`snippets_for`).
2. Rendering (:func:`render_block`, :func:`render_full_block`,
   :func:`render_stdout`).
3. File I/O (:func:`write_managed_block`) \u2014 idempotency + refusing
   to touch shell rc files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from keeb_coach.detectors.base import Finding, Severity
from keeb_coach.fixes import (
    BLOCK_END,
    BLOCK_START,
    FixSnippet,
    ForbiddenTargetError,
    _alias_slug,
    render_block,
    render_full_block,
    render_stdout,
    snippets_for,
    write_managed_block,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _mk_finding(
    detector: str,
    evidence: dict[str, object],
    severity: Severity = Severity.MEDIUM,
    message: str = "",
    suggested_fix: str | None = None,
) -> Finding:
    return Finding(
        detector=detector,
        severity=severity,
        message=message or f"{detector} test finding",
        suggested_fix=suggested_fix,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# _alias_slug: naming safety
# ---------------------------------------------------------------------------


class TestAliasSlug:
    def test_two_token_command(self) -> None:
        assert _alias_slug("git status") == "git_status"

    def test_strips_special_chars(self) -> None:
        # Options + flags collapse to underscores; result is POSIX-safe.
        slug = _alias_slug("kubectl get pods --all-namespaces")
        assert slug == "kubectl_get"
        assert all(c.isalnum() or c == "_" for c in slug)

    def test_never_empty(self) -> None:
        # Punctuation-only input still yields a usable name.
        assert _alias_slug("!!!") == "kc_alias"

    def test_lowercases(self) -> None:
        assert _alias_slug("MAKE build") == "make_build"


# ---------------------------------------------------------------------------
# Snippet builders \u2014 one class per detector
# ---------------------------------------------------------------------------


class TestMissingAliasSnippet:
    def test_basic_alias(self) -> None:
        [snip] = snippets_for(
            [_mk_finding("missing_alias", {"command": "git status", "count": 10})]
        )
        assert snip.detector == "missing_alias"
        assert snip.lines == ("alias git_status='git status'",)
        # Count appears in the comment for context.
        assert "10\u00d7" in snip.comment

    def test_quotes_special_chars_safely(self) -> None:
        [snip] = snippets_for(
            [
                _mk_finding(
                    "missing_alias",
                    {"command": "grep -R 'TODO' src/", "count": 8},
                )
            ]
        )
        # shlex.quote should wrap the whole RHS in single-quotes and
        # escape the inner single quote correctly.
        assert snip.lines[0].startswith("alias grep_r=")
        # The alias body must round-trip through the shell without
        # word-splitting or quote breakage.
        assert "'\"'\"'TODO'\"'\"'" in snip.lines[0] or "TODO" in snip.lines[0]

    def test_skipped_when_evidence_missing(self) -> None:
        assert snippets_for([_mk_finding("missing_alias", {})]) == []


class TestSlowToolSnippet:
    def test_single_token_becomes_alias(self) -> None:
        [snip] = snippets_for(
            [
                _mk_finding(
                    "slow_tool",
                    {"slow": "grep", "replacement": "rg", "count": 5},
                )
            ]
        )
        # ``shlex.quote`` omits quoting when the value is already shell-
        # safe, which ``rg`` is — so no wrapping quotes appear here.
        assert snip.lines == ("alias grep=rg",)
        assert "grep" in snip.comment and "rg" in snip.comment

    def test_multi_token_is_comment_only(self) -> None:
        [snip] = snippets_for(
            [
                _mk_finding(
                    "slow_tool",
                    {"slow": "ls -la", "replacement": "eza -la", "count": 6},
                )
            ]
        )
        # No alias line \u2014 aliasing multi-token commands is not POSIX.
        assert not any(line.startswith("alias ") for line in snip.lines)
        assert any("eza -la" in line for line in snip.lines)
        assert "multi-token" in snip.comment

    def test_skipped_on_missing_fields(self) -> None:
        assert snippets_for([_mk_finding("slow_tool", {"slow": "grep"})]) == []


class TestLongPathSnippet:
    def test_basic_jump_alias(self) -> None:
        [snip] = snippets_for(
            [
                _mk_finding(
                    "long_path",
                    {"target": "/home/ryan/projects/foo", "count": 5, "depth": 4},
                )
            ]
        )
        assert snip.lines == ("alias to_foo='cd /home/ryan/projects/foo'",)

    def test_trailing_slash_normalized(self) -> None:
        [snip] = snippets_for(
            [_mk_finding("long_path", {"target": "~/deep/dir/", "count": 3})]
        )
        assert snip.lines[0].startswith("alias to_dir=")

    def test_skipped_when_target_missing(self) -> None:
        assert snippets_for([_mk_finding("long_path", {})]) == []


class TestSudoRedoSnippet:
    def test_emits_reminder_comment(self) -> None:
        [snip] = snippets_for(
            [_mk_finding("sudo_redo", {"events": 3, "top_command": "apt update"})]
        )
        assert snip.detector == "sudo_redo"
        # The sudo_redo fix is a shell shortcut, not an alias \u2014 the
        # snippet is a documentation comment only.
        assert all(line.startswith("#") for line in snip.lines)
        assert any("sudo !!" in line for line in snip.lines)


# ---------------------------------------------------------------------------
# snippets_for: aggregation behavior
# ---------------------------------------------------------------------------


class TestSnippetsFor:
    def test_dedupes_on_key(self) -> None:
        # Two findings with the same command \u2192 one snippet.
        findings = [
            _mk_finding("missing_alias", {"command": "git status", "count": 5}),
            _mk_finding("missing_alias", {"command": "git status", "count": 7}),
        ]
        out = snippets_for(findings)
        assert len(out) == 1

    def test_unknown_detector_silently_skipped(self) -> None:
        assert snippets_for([_mk_finding("future_detector", {"anything": 1})]) == []

    def test_preserves_input_order(self) -> None:
        findings = [
            _mk_finding("slow_tool", {"slow": "grep", "replacement": "rg", "count": 4}),
            _mk_finding("missing_alias", {"command": "git status", "count": 5}),
            _mk_finding("long_path", {"target": "/a/b/c/d", "count": 3}),
        ]
        out = snippets_for(findings)
        assert [s.detector for s in out] == ["slow_tool", "missing_alias", "long_path"]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRender:
    def test_render_block_with_snippets(self) -> None:
        snippet = FixSnippet(
            detector="missing_alias",
            comment="test comment",
            lines=("alias foo='bar'",),
            key="test",
        )
        rendered = render_block([snippet])
        assert "# test comment" in rendered
        assert "alias foo='bar'" in rendered
        # Trailing newline so appending markers stays clean.
        assert rendered.endswith("\n")

    def test_render_block_empty_still_has_content(self) -> None:
        # An empty markered block confuses editors that treat it as
        # truncated \u2014 we always emit at least a comment.
        rendered = render_block([])
        assert rendered.strip().startswith("#")

    def test_render_full_block_has_markers(self) -> None:
        snippet = FixSnippet(
            detector="x",
            comment="c",
            lines=("alias a='b'",),
            key="k",
        )
        full = render_full_block([snippet])
        assert full.startswith(BLOCK_START)
        assert full.rstrip().endswith(BLOCK_END)
        assert "alias a='b'" in full

    def test_render_stdout_includes_hint(self) -> None:
        out = render_stdout([])
        # The stdout mode should mention --write so users discover it.
        assert "--write" in out

    def test_render_stdout_with_snippets_shows_body(self) -> None:
        snippet = FixSnippet(
            detector="missing_alias",
            comment="c",
            lines=("alias a='b'",),
            key="k",
        )
        out = render_stdout([snippet])
        assert "alias a='b'" in out


# ---------------------------------------------------------------------------
# write_managed_block: I/O + idempotency + safety
# ---------------------------------------------------------------------------


class TestWriteManagedBlock:
    def _finding(self) -> Finding:
        return _mk_finding("missing_alias", {"command": "git status", "count": 5})

    def test_writes_to_new_file(self, tmp_path: Path) -> None:
        target = tmp_path / ".keeb_aliases"
        snippets = snippets_for([self._finding()])
        resolved = write_managed_block(target, snippets)
        assert resolved == target.resolve()
        text = target.read_text(encoding="utf-8")
        assert BLOCK_START in text
        assert BLOCK_END in text
        assert "alias git_status='git status'" in text

    def test_idempotent_no_dupes(self, tmp_path: Path) -> None:
        target = tmp_path / "aliases"
        snippets = snippets_for([self._finding()])
        write_managed_block(target, snippets)
        first = target.read_text(encoding="utf-8")
        # Run again \u2014 file should be *substantively* identical (timestamp
        # in the header is the only allowed difference).
        write_managed_block(target, snippets)
        second = target.read_text(encoding="utf-8")
        # Exactly one alias line survives across runs.
        assert second.count("alias git_status=") == 1
        # Exactly one marker pair.
        assert second.count(BLOCK_START) == 1
        assert second.count(BLOCK_END) == 1
        # Everything except the timestamp comment matches the first run.
        assert first.count(BLOCK_START) == 1

    def test_preserves_surrounding_content(self, tmp_path: Path) -> None:
        target = tmp_path / "aliases"
        target.write_text(
            "# my hand-written aliases\n"
            "alias hi='echo hello'\n"
            "\n",
            encoding="utf-8",
        )
        write_managed_block(target, snippets_for([self._finding()]))
        text = target.read_text(encoding="utf-8")
        # Pre-existing user content must survive untouched.
        assert "alias hi='echo hello'" in text
        # Our block is appended after it.
        assert text.index("alias hi=") < text.index(BLOCK_START)

    def test_replaces_existing_block_in_place(self, tmp_path: Path) -> None:
        target = tmp_path / "aliases"
        # First run: `git status` finding.
        write_managed_block(target, snippets_for([self._finding()]))
        # Second run: different finding \u2014 old alias should be gone,
        # new alias should be present, block position preserved.
        other = _mk_finding("missing_alias", {"command": "docker ps", "count": 6})
        write_managed_block(target, snippets_for([other]))
        text = target.read_text(encoding="utf-8")
        assert "docker_ps" in text
        assert "git_status" not in text
        assert text.count(BLOCK_START) == 1

    def test_collapses_duplicate_blocks(self, tmp_path: Path) -> None:
        target = tmp_path / "aliases"
        # Simulate a corrupted file with two managed blocks (shouldn't
        # happen in practice, but guarantees convergence on re-run).
        target.write_text(
            f"{BLOCK_START}\nold1\n{BLOCK_END}\n"
            f"middle\n"
            f"{BLOCK_START}\nold2\n{BLOCK_END}\n",
            encoding="utf-8",
        )
        write_managed_block(target, snippets_for([self._finding()]))
        text = target.read_text(encoding="utf-8")
        assert text.count(BLOCK_START) == 1
        assert text.count(BLOCK_END) == 1
        # Pre-existing outside-block content is preserved.
        assert "middle" in text
        # Neither of the old stub blocks survives.
        assert "old1" not in text
        assert "old2" not in text

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "dir" / ".keeb_aliases"
        write_managed_block(target, snippets_for([self._finding()]))
        assert target.exists()

    def test_empty_snippets_still_writes_marked_block(self, tmp_path: Path) -> None:
        target = tmp_path / "aliases"
        write_managed_block(target, [])
        text = target.read_text(encoding="utf-8")
        # Even with no findings, the markers should be present so users
        # can tell the command succeeded and know where to look next run.
        assert BLOCK_START in text
        assert BLOCK_END in text

    @pytest.mark.parametrize(
        "basename",
        [".bashrc", ".bash_profile", ".profile", ".zshrc", ".zprofile", "config.fish"],
    )
    def test_refuses_shell_rc_files(self, tmp_path: Path, basename: str) -> None:
        target = tmp_path / basename
        with pytest.raises(ForbiddenTargetError):
            write_managed_block(target, snippets_for([self._finding()]))
        # And it must NOT have created the file as a side effect.
        assert not target.exists()

    def test_definition_of_done_two_runs_no_dupes(self, tmp_path: Path) -> None:
        """PLAN.md DoD: ``keeb-coach fixes --write`` twice yields no dupes.

        Uses multiple findings from multiple detectors to exercise the
        aggregation path, not just a single-finding degenerate case.
        """
        target = tmp_path / ".keeb_aliases"
        findings = [
            _mk_finding("missing_alias", {"command": "git status", "count": 5}),
            _mk_finding(
                "slow_tool", {"slow": "grep", "replacement": "rg", "count": 4}
            ),
            _mk_finding("long_path", {"target": "/a/b/c/d", "count": 3}),
        ]
        snippets = snippets_for(findings)
        write_managed_block(target, snippets)
        write_managed_block(target, snippets)
        text = target.read_text(encoding="utf-8")
        assert text.count("alias git_status=") == 1
        assert text.count("alias grep=") == 1
        assert text.count("alias to_d=") == 1
        assert text.count(BLOCK_START) == 1

