"""Tests for secretsync.differ — diff computation and masking."""

from __future__ import annotations

import pytest

from secretsync.differ import (
    apply_plan_to_local,
    apply_plan_to_remote,
    build_sync_plan,
    compute_diff,
    is_sensitive,
)
from secretsync.models import DiffStatus, SyncDirection

# ---------------------------------------------------------------------------
# compute_diff
# ---------------------------------------------------------------------------


def test_diff_identical_state():
    state = {"A": "1", "B": "2"}
    entries = compute_diff(state, state)
    assert all(e.status == DiffStatus.UNCHANGED for e in entries)


def test_diff_added_keys():
    local = {"A": "1", "NEW": "x"}
    remote = {"A": "1"}
    by_key = {e.key: e for e in compute_diff(local, remote)}
    assert by_key["NEW"].status == DiffStatus.ADDED
    assert by_key["NEW"].local_value == "x"
    assert by_key["NEW"].remote_value is None


def test_diff_removed_keys():
    local = {"A": "1"}
    remote = {"A": "1", "OLD": "y"}
    by_key = {e.key: e for e in compute_diff(local, remote)}
    assert by_key["OLD"].status == DiffStatus.REMOVED
    assert by_key["OLD"].remote_value == "y"
    assert by_key["OLD"].local_value is None


def test_diff_changed_keys():
    local = {"A": "new"}
    remote = {"A": "old"}
    by_key = {e.key: e for e in compute_diff(local, remote)}
    assert by_key["A"].status == DiffStatus.CHANGED
    assert by_key["A"].local_value == "new"
    assert by_key["A"].remote_value == "old"


def test_diff_sorted_by_key():
    local = {"Z": "1", "A": "1", "M": "1"}
    remote = {}
    entries = compute_diff(local, remote)
    assert [e.key for e in entries] == ["A", "M", "Z"]


def test_diff_empty_both():
    assert compute_diff({}, {}) == []


def test_diff_empty_local():
    entries = compute_diff({}, {"A": "1"})
    assert entries[0].status == DiffStatus.REMOVED


def test_diff_empty_remote():
    entries = compute_diff({"A": "1"}, {})
    assert entries[0].status == DiffStatus.ADDED


# ---------------------------------------------------------------------------
# is_sensitive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", [
    "DB_PASSWORD", "API_KEY", "SECRET_TOKEN", "PRIVATE_KEY",
    "AWS_SECRET_ACCESS_KEY", "AUTH_TOKEN", "CERT_PEM",
    "DATABASE_URL", "CONNECTION_STRING", "REDIS_DSN",
])
def test_is_sensitive_positive(key):
    assert is_sensitive(key)


@pytest.mark.parametrize("key", [
    "DB_HOST", "APP_PORT", "LOG_LEVEL", "FEATURE_FLAG",
    "CACHE_KEY_PREFIX", "KEYBOARD_LAYOUT",
])
def test_is_sensitive_negative(key):
    assert not is_sensitive(key)


# ---------------------------------------------------------------------------
# apply_plan_to_remote (push semantics)
# ---------------------------------------------------------------------------


def test_push_adds_new_local_keys():
    local = {"A": "1", "NEW": "x"}
    remote = {"A": "1"}
    plan = build_sync_plan(local, remote, SyncDirection.PUSH)
    result = apply_plan_to_remote(plan)
    assert result["NEW"] == "x"


def test_push_updates_changed_keys():
    local = {"A": "new"}
    remote = {"A": "old"}
    plan = build_sync_plan(local, remote, SyncDirection.PUSH)
    result = apply_plan_to_remote(plan)
    assert result["A"] == "new"


def test_push_keeps_remote_only_keys_without_prune():
    local = {"A": "1"}
    remote = {"A": "1", "REMOTE_ONLY": "y"}
    plan = build_sync_plan(local, remote, SyncDirection.PUSH, prune=False)
    result = apply_plan_to_remote(plan)
    assert "REMOTE_ONLY" in result


def test_push_prune_removes_remote_only_keys():
    local = {"A": "1"}
    remote = {"A": "1", "REMOTE_ONLY": "y"}
    plan = build_sync_plan(local, remote, SyncDirection.PUSH, prune=True)
    result = apply_plan_to_remote(plan)
    assert "REMOTE_ONLY" not in result


# ---------------------------------------------------------------------------
# apply_plan_to_local (pull semantics)
# ---------------------------------------------------------------------------


def test_pull_adds_remote_only_keys():
    local = {"A": "1"}
    remote = {"A": "1", "REMOTE_ONLY": "r"}
    plan = build_sync_plan(local, remote, SyncDirection.PULL)
    result = apply_plan_to_local(plan)
    assert result["REMOTE_ONLY"] == "r"


def test_pull_remote_wins_on_changed():
    local = {"A": "local"}
    remote = {"A": "remote"}
    plan = build_sync_plan(local, remote, SyncDirection.PULL)
    result = apply_plan_to_local(plan)
    assert result["A"] == "remote"


def test_pull_keeps_local_only_without_prune():
    local = {"A": "1", "LOCAL_ONLY": "l"}
    remote = {"A": "1"}
    plan = build_sync_plan(local, remote, SyncDirection.PULL, prune=False)
    result = apply_plan_to_local(plan)
    assert "LOCAL_ONLY" in result


def test_pull_prune_removes_local_only_keys():
    local = {"A": "1", "LOCAL_ONLY": "l"}
    remote = {"A": "1"}
    plan = build_sync_plan(local, remote, SyncDirection.PULL, prune=True)
    result = apply_plan_to_local(plan)
    assert "LOCAL_ONLY" not in result


def test_pull_unchanged_keys_preserved():
    state = {"A": "1", "B": "2"}
    plan = build_sync_plan(state, state, SyncDirection.PULL)
    result = apply_plan_to_local(plan)
    assert result == {"A": "1", "B": "2"}


# ---------------------------------------------------------------------------
# SyncPlan properties
# ---------------------------------------------------------------------------


def test_plan_has_changes_false_when_identical():
    state = {"A": "1"}
    plan = build_sync_plan(state, state, SyncDirection.PUSH)
    assert not plan.has_changes


def test_plan_has_changes_true_when_different():
    plan = build_sync_plan({"A": "new"}, {"A": "old"}, SyncDirection.PUSH)
    assert plan.has_changes


def test_plan_changes_excludes_unchanged():
    local = {"A": "new", "B": "same"}
    remote = {"A": "old", "B": "same"}
    plan = build_sync_plan(local, remote, SyncDirection.PUSH)
    keys = {e.key for e in plan.changes}
    assert "A" in keys
    assert "B" not in keys
