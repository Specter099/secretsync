"""Read and write .env files, preserving comments and blank lines."""

from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path

# Matches:  KEY=value  or  KEY="value"  or  KEY='value'
# Handles optional `export` prefix, inline comments stripped.
_PAIR_RE = re.compile(
    r"""^
    (export\s+)?            # optional 'export' prefix
    ([A-Za-z_][A-Za-z0-9_]*)   # key
    \s*=\s*                 # equals sign with optional whitespace
    (.*)                    # raw value (we'll strip quotes below)
    $""",
    re.VERBOSE,
)

_COMMENT_RE = re.compile(r"^#")
_BLANK_RE = re.compile(r"^\s*$")


# Escapes understood inside double quotes (mirrors what _quote writes).
_DQ_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "$": "$", "`": "`"}


def _parse_value(raw: str) -> str:
    """Decode a raw value: quotes removed, escapes expanded, inline comment dropped."""
    if raw.startswith("'"):
        # Single quotes are literal, as in the shell.
        end = raw.find("'", 1)
        return raw[1:end] if end > 0 else raw[1:]
    if raw.startswith('"'):
        out: list[str] = []
        i = 1
        while i < len(raw):
            c = raw[i]
            if c == '"':
                break
            if c == "\\" and i + 1 < len(raw):
                nxt = raw[i + 1]
                out.append(_DQ_ESCAPES.get(nxt, c + nxt))
                i += 2
                continue
            out.append(c)
            i += 1
        return "".join(out)
    # Unquoted: strip an inline comment ('#' preceded by whitespace), expand \n \t \r.
    value = re.sub(r"\s+#.*$", "", raw).strip()
    return value.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")


def parse_env_file(path: str | Path) -> dict[str, str]:
    """Parse a .env file and return a key→value mapping.

    - Comments (#) and blank lines are ignored.
    - Inline comments after unquoted values are stripped.
    - Quoted values have their quotes removed.
    - ``export KEY=value`` syntax is supported.
    """
    pairs: dict[str, str] = {}
    file_path = Path(path)
    if not file_path.exists():
        return pairs

    for line in file_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if _BLANK_RE.match(stripped) or _COMMENT_RE.match(stripped):
            continue
        m = _PAIR_RE.match(stripped)
        if m:
            key = m.group(2)
            pairs[key] = _parse_value(m.group(3).strip())

    return pairs


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


class _Line:
    """Internal representation of a single line in an .env file."""

    __slots__ = ("raw", "key", "export")

    def __init__(self, raw: str, key: str | None = None, export: bool = False) -> None:
        self.raw = raw
        self.key = key  # None for comments / blank lines
        self.export = export


def _read_lines(path: Path) -> list[_Line]:
    """Read an existing .env file into structured line objects."""
    lines: list[_Line] = []
    if not path.exists():
        return lines
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if _BLANK_RE.match(stripped) or _COMMENT_RE.match(stripped):
            lines.append(_Line(raw))
        else:
            m = _PAIR_RE.match(stripped)
            if m:
                lines.append(_Line(raw, key=m.group(2), export=bool(m.group(1))))
            else:
                lines.append(_Line(raw))
    return lines


# Characters that are safe unquoted both for this parser and for `source .env`.
_SAFE_BARE_RE = re.compile(r"[A-Za-z0-9_@%+=:,./-]*")


def _quote(value: str) -> str:
    """Encode *value* so it round-trips through :func:`parse_env_file` and is
    inert when the file is sourced by a POSIX shell (no expansion or command
    substitution)."""
    if _SAFE_BARE_RE.fullmatch(value):
        return value
    if not any(c in value for c in "'\n\r\t"):
        return f"'{value}'"
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def write_env_file(
    path: str | Path,
    updates: dict[str, str],
    *,
    prune: bool = False,
) -> None:
    """Write *updates* into the .env file at *path*.

    Existing comments and blank lines are preserved.  If *prune* is True,
    keys present in the file but absent from *updates* are removed.

    Args:
        path: Path to the .env file.
        updates: Mapping of key→value to write.
        prune: When True, delete keys not present in *updates*.
    """
    file_path = Path(path)
    lines = _read_lines(file_path)

    # Track which keys we've already written so we can append new ones.
    written: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        if line.key is None:
            # Comment or blank — keep as-is
            new_lines.append(line.raw)
        elif line.key in updates:
            # Update existing key
            prefix = "export " if line.export else ""
            new_lines.append(f"{prefix}{line.key}={_quote(updates[line.key])}")
            written.add(line.key)
        elif prune:
            # Key not in updates and prune is on — drop it
            pass
        else:
            # Keep existing key unchanged
            new_lines.append(line.raw)
            written.add(line.key)

    # Append brand-new keys (not previously in the file)
    for key, value in updates.items():
        if key not in written:
            new_lines.append(f"{key}={_quote(value)}")

    content = "\n".join(new_lines) + "\n"

    # Atomic write: write to a temp file in the same directory, then rename.
    # This prevents partial writes from corrupting the .env file.
    fd, tmp_path = tempfile.mkstemp(
        dir=file_path.parent,
        prefix=".env.tmp.",
        suffix="",
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            os.fchmod(fh.fileno(), stat.S_IRUSR | stat.S_IWUSR)  # 0600 — owner only
            fh.write(content.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, file_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
