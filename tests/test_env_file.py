"""Tests for secretsync.env_file — parsing and writing .env files."""

from __future__ import annotations

import os
import stat

import pytest

from secretsync.env_file import parse_env_file, write_env_file

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_simple_pairs(tmp_path):
    f = tmp_path / ".env"
    f.write_text("DB_HOST=localhost\nDB_PORT=5432\n")
    result = parse_env_file(f)
    assert result == {"DB_HOST": "localhost", "DB_PORT": "5432"}


def test_parse_skips_comments(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# This is a comment\nKEY=value\n")
    assert parse_env_file(f) == {"KEY": "value"}


def test_parse_skips_blank_lines(tmp_path):
    f = tmp_path / ".env"
    f.write_text("\n\nKEY=value\n\n")
    assert parse_env_file(f) == {"KEY": "value"}


def test_parse_double_quoted_value(tmp_path):
    f = tmp_path / ".env"
    f.write_text('SECRET="my secret value"\n')
    assert parse_env_file(f) == {"SECRET": "my secret value"}


def test_parse_single_quoted_value(tmp_path):
    f = tmp_path / ".env"
    f.write_text("SECRET='my secret value'\n")
    assert parse_env_file(f) == {"SECRET": "my secret value"}


def test_parse_inline_comment_stripped(tmp_path):
    f = tmp_path / ".env"
    f.write_text("KEY=value # this is inline\n")
    assert parse_env_file(f) == {"KEY": "value"}


def test_parse_inline_comment_inside_quotes_preserved(tmp_path):
    f = tmp_path / ".env"
    f.write_text('KEY="value # not a comment"\n')
    assert parse_env_file(f) == {"KEY": "value # not a comment"}


def test_parse_export_prefix(tmp_path):
    f = tmp_path / ".env"
    f.write_text("export DB_HOST=localhost\nexport DB_PORT=5432\n")
    assert parse_env_file(f) == {"DB_HOST": "localhost", "DB_PORT": "5432"}


def test_parse_empty_value(tmp_path):
    f = tmp_path / ".env"
    f.write_text("EMPTY=\n")
    assert parse_env_file(f) == {"EMPTY": ""}


def test_parse_empty_quoted_value(tmp_path):
    f = tmp_path / ".env"
    f.write_text('EMPTY=""\n')
    assert parse_env_file(f) == {"EMPTY": ""}


def test_parse_value_with_equals(tmp_path):
    f = tmp_path / ".env"
    f.write_text("TOKEN=abc=def==\n")
    assert parse_env_file(f) == {"TOKEN": "abc=def=="}


def test_parse_missing_file_returns_empty(tmp_path):
    result = parse_env_file(tmp_path / "nonexistent.env")
    assert result == {}


def test_parse_escape_sequences(tmp_path):
    f = tmp_path / ".env"
    f.write_text("MSG=hello\\nworld\n")
    assert parse_env_file(f) == {"MSG": "hello\nworld"}


def test_parse_spaces_around_equals(tmp_path):
    f = tmp_path / ".env"
    f.write_text("KEY = value\n")
    assert parse_env_file(f) == {"KEY": "value"}


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_write_new_file(tmp_path):
    f = tmp_path / ".env"
    write_env_file(f, {"DB_HOST": "localhost", "DB_PORT": "5432"})
    result = parse_env_file(f)
    assert result == {"DB_HOST": "localhost", "DB_PORT": "5432"}


def test_write_updates_existing_key(tmp_path):
    f = tmp_path / ".env"
    f.write_text("DB_HOST=old\n")
    write_env_file(f, {"DB_HOST": "new"})
    assert parse_env_file(f) == {"DB_HOST": "new"}


def test_write_preserves_comments(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# database\nDB_HOST=old\n")
    write_env_file(f, {"DB_HOST": "new"})
    content = f.read_text()
    assert "# database" in content
    assert "DB_HOST=new" in content


def test_write_preserves_blank_lines(tmp_path):
    f = tmp_path / ".env"
    f.write_text("A=1\n\nB=2\n")
    write_env_file(f, {"A": "1", "B": "2"})
    content = f.read_text()
    assert "\n\n" in content


def test_write_appends_new_keys(tmp_path):
    f = tmp_path / ".env"
    f.write_text("A=1\n")
    write_env_file(f, {"A": "1", "B": "2"})
    result = parse_env_file(f)
    assert result["B"] == "2"


def test_write_prune_removes_missing_keys(tmp_path):
    f = tmp_path / ".env"
    f.write_text("A=1\nB=2\n")
    write_env_file(f, {"A": "1"}, prune=True)
    result = parse_env_file(f)
    assert "B" not in result


def test_write_no_prune_keeps_extra_keys(tmp_path):
    f = tmp_path / ".env"
    f.write_text("A=1\nB=2\n")
    write_env_file(f, {"A": "99"}, prune=False)
    result = parse_env_file(f)
    assert result["B"] == "2"


def test_write_value_with_spaces_gets_quoted(tmp_path):
    f = tmp_path / ".env"
    write_env_file(f, {"MSG": "hello world"})
    content = f.read_text()
    assert "MSG='hello world'" in content
    # And must round-trip correctly
    assert parse_env_file(f)["MSG"] == "hello world"


def test_write_round_trip(tmp_path):
    original = {
        "DB_HOST": "localhost",
        "DB_PASS": "s3cr3t!",
        "EMPTY": "",
        "MSG": "hello world",
    }
    f = tmp_path / ".env"
    write_env_file(f, original)
    assert parse_env_file(f) == original


TRICKY_VALUES = {
    "BACKSLASH": "C:\\path\\new",
    "DQUOTE": 'he said "hi"',
    "SQUOTE": "it's",
    "BOTH": """it's "x" $HOME""",
    "NEWLINE": "line1\nline2",
    "TAB": "a\tb",
    "HASH": "a #b",
    "SUBST": "$(touch pwned)",
    "BACKTICK": "`touch pwned`",
    "SEMI": "x;touch pwned",
    "PIPE": "a|touch pwned",
    "AMP": "a&&touch pwned",
    "LEADING_SPACE": "  padded ",
}


def test_write_round_trip_tricky_values_is_stable(tmp_path):
    f = tmp_path / ".env"
    write_env_file(f, TRICKY_VALUES)
    assert parse_env_file(f) == TRICKY_VALUES
    # A second pull of the same values must not change the file.
    first = f.read_text()
    write_env_file(f, parse_env_file(f))
    assert f.read_text() == first


def test_written_file_is_inert_when_sourced(tmp_path):
    import shutil
    import subprocess

    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("no POSIX shell")
    f = tmp_path / ".env"
    values = {k: v for k, v in TRICKY_VALUES.items() if "\n" not in v and "\t" not in v}
    write_env_file(f, values)
    script = f"set -a; . {f}; " + "; ".join(f'printf "%s\\0" "${k}"' for k in values)
    out = subprocess.run([sh, "-c", script], cwd=tmp_path, capture_output=True, check=True)
    assert out.stdout.decode().split("\0")[:-1] == list(values.values())
    assert not (tmp_path / "pwned").exists()


def test_write_preserves_export_prefix(tmp_path):
    f = tmp_path / ".env"
    f.write_text("export A=1\nB=2\n")
    write_env_file(f, {"A": "10", "B": "20"})
    assert f.read_text() == "export A=10\nB=20\n"


# ---------------------------------------------------------------------------
# Security: file permissions and atomic writes
# ---------------------------------------------------------------------------


def test_write_sets_owner_only_permissions(tmp_path):
    f = tmp_path / ".env"
    write_env_file(f, {"SECRET": "value"})
    mode = os.stat(f).st_mode
    assert mode & stat.S_IRUSR  # owner can read
    assert mode & stat.S_IWUSR  # owner can write
    assert not (mode & stat.S_IRGRP)  # group cannot read
    assert not (mode & stat.S_IROTH)  # others cannot read


def test_write_no_temp_file_left_on_success(tmp_path):
    f = tmp_path / ".env"
    write_env_file(f, {"A": "1"})
    leftover = list(tmp_path.glob(".env.tmp.*"))
    assert leftover == []
