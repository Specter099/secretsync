"""Read and write .env files, preserving comments and blank lines."""

from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path

from .models import EnvVar

# Matches:  KEY=value  or  KEY="value"  or  KEY='value'
# Handles optional `export` prefix, inline comments stripped.
_PAIR_RE = re.compile(
    r"""^
    (?:export\s+)?          # optional 'export' prefix
    ([A-Za-z_][A-Za-z0-9_]*)   # key
    \s*=\s*                 # equals sign with optional whitespace
    (.*)                    # raw value (we'll strip quotes below)
    $""",
    re.VERBOSE,
)

_COMMENT_RE = re.compile(r"^#")
_BLANK_RE = re.compile(r"^\s*$")


def _strip_inline_comment(raw: str) -> str:
    """Remove trailing inline comment (unquoted #...)."""
    # If the value is quoted, keep everything inside quotes.
    if raw and raw[0] in ('"', "'"):
        quote = raw[0]
        end = raw.rfind(quote, 1)
        if end > 0:
            return raw[1:end]
        # Malformed quote — return raw minus the leading quote
        return raw[1:]
    # Unquoted: strip from first unescaped '#' that follows whitespace
    result = re.sub(r"\s+#.*$", "", raw)
    return result.strip()


def _unescape(value: str) -> str:
    """Expand common escape sequences (\\n, \\t, \\r)."""
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
            key = m.group(1)
            raw_value = m.group(2).strip()
            pairs[key] = _unescape(_strip_inline_comment(raw_value))

    return pairs


def parse_env_file_as_vars(path: str | Path) -> list[EnvVar]:
    """Return parsed .env file as an ordered list of :class:`EnvVar`."""
    return [EnvVar(key=k, value=v) for k, v in parse_env_file(path).items()]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


class _Line:
    """Internal representation of a single line in an .env file."""

    __slots__ = ("raw", "key")

    def __init__(self, raw: str, key: str | None = None) -> None:
        self.raw = raw
        self.key = key  # None for comments / blank lines


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
                lines.append(_Line(raw, key=m.group(1)))
            else:
                lines.append(_Line(raw))
    return lines


def _quote_if_needed(value: str) -> str:
    """Wrap value in double-quotes if it contains spaces, #, or special chars."""
    needs_quote = any(c in value for c in (' ', '\t', '"', "'", '#', '$', '\\', '\n', '\r'))
    if needs_quote:
        escaped = (
            value.replace('\\', '\\\\').replace('"', '\\"')
            .replace('\n', '\\n').replace('\r', '\\r')
        )
        return f'"{escaped}"'
    return value


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
            new_lines.append(f"{line.key}={_quote_if_needed(updates[line.key])}")
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
            new_lines.append(f"{key}={_quote_if_needed(value)}")

    content = "\n".join(new_lines) + "\n"

    # Atomic write: write to a temp file in the same directory, then rename.
    # This prevents partial writes from corrupting the .env file.
    fd, tmp_path = tempfile.mkstemp(
        dir=file_path.parent,
        prefix=".env.tmp.",
        suffix="",
    )
    closed = False
    try:
        os.write(fd, content.encode("utf-8"))
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)  # 0600 — owner only
        os.close(fd)
        closed = True
        os.replace(tmp_path, file_path)
    except BaseException:
        if not closed:
            os.close(fd)
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
