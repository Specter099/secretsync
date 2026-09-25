"""Tests for secretsync.differ — diff computation and masking."""

from __future__ import annotations

from secretsync.differ import (
    apply_plan_to_local,
    build_sync_plan,
    compute_diff,
    mask_value,
    remote_changes,
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
# mask_value
# ---------------------------------------------------------------------------


def test_mask_value_masks_every_value_regardless_of_key():
    assert mask_value("localhost", True) == "********"
    assert mask_value("ab", True) == "**"


def test_mask_value_passthrough_when_disabled():
    assert mask_value("localhost", False) == "localhost"
    assert mask_value(None, True) is None


# ---------------------------------------------------------------------------
# remote_changes (push semantics)
# ---------------------------------------------------------------------------


def test_push_writes_only_added_and_changed_keys():
    local = {"SAME": "1", "NEW": "x", "CHG": "new"}
    remote = {"SAME": "1", "CHG": "old"}
    plan = build_sync_plan(local, remote, SyncDirection.PUSH)
    updates, deletes = remote_changes(plan)
    assert updates == {"NEW": "x", "CHG": "new"}
    assert deletes == []


def test_push_keeps_remote_only_keys_without_prune():
    plan = build_sync_plan({"A": "1"}, {"A": "1", "R": "y"}, SyncDirection.PUSH, prune=False)
    assert remote_changes(plan) == ({}, [])


def test_push_prune_deletes_remote_only_keys():
    plan = build_sync_plan({"A": "1"}, {"A": "1", "R": "y"}, SyncDirection.PUSH, prune=True)
    assert remote_changes(plan) == ({}, ["R"])


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
