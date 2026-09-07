# tests/storage/test_db_refresh.py
"""
Cloud DB-freshness path: get_current_etag() -> _download_snapshot(etag).

These protect the "no manual reboot" behavior:
  (a) an unchanged etag is a cache hit — no second S3 download
  (b) a new etag (cron uploaded a fresh DB) triggers a fresh download to
      its own per-etag path
  (c) pruning keeps only the 3 most recent snapshots and tolerates a file
      that's still in use
"""

import os
import time

import pytest

from leagueintel.storage import database


@pytest.fixture
def snapshot_dir(tmp_path, monkeypatch):
    """Redirect per-etag snapshot files off /tmp into a scratch dir."""
    monkeypatch.setattr(database, "SNAPSHOT_DIR", str(tmp_path))
    # drop any memoized snapshot paths from a prior test / real runtime
    for fn in (database._download_snapshot, database.get_current_etag):
        try:
            fn.clear()
        except Exception:
            pass
    return tmp_path


@pytest.fixture
def fake_s3(monkeypatch):
    """
    Stand-in S3 client. download_file writes a stub file (so the
    file-exists short-circuit in _download_snapshot behaves realistically)
    and counts calls.
    """

    class FakeS3:
        def __init__(self):
            self.download_calls = []

        def download_file(self, bucket, key, dest):
            self.download_calls.append(dest)
            with open(dest, "w") as fh:
                fh.write("stub-db")

    client = FakeS3()
    monkeypatch.setattr(database, "_s3_client", lambda: client)
    return client


# ── (a) unchanged etag → cache hit, no re-download ────────────────────────────


def test_same_etag_does_not_redownload(snapshot_dir, fake_s3):
    first = database._download_snapshot("abcdef123456")
    second = database._download_snapshot("abcdef123456")

    assert first == second
    assert os.path.dirname(first) == str(snapshot_dir)
    assert len(fake_s3.download_calls) == 1  # only the first call hit S3


# ── (b) new etag → fresh download to its own path ────────────────────────────


def test_new_etag_triggers_fresh_download(snapshot_dir, fake_s3):
    old_path = database._download_snapshot("aaaaaaaa1111")
    new_path = database._download_snapshot("bbbbbbbb2222")

    assert old_path != new_path
    assert fake_s3.download_calls == [old_path, new_path]
    assert os.path.exists(old_path) and os.path.exists(new_path)
    # filename is keyed by the first 8 chars of the etag
    assert os.path.basename(new_path) == "leagueintel_bbbbbbbb.db"


# ── (c) pruning ─────────────────────────────────────────────────────────────


def _make_snapshot(dir_, name, mtime):
    path = os.path.join(dir_, name)
    with open(path, "w") as fh:
        fh.write("x")
    os.utime(path, (mtime, mtime))
    return path


def test_prune_keeps_three_most_recent(snapshot_dir):
    now = time.time()
    paths = [
        _make_snapshot(str(snapshot_dir), f"leagueintel_{i}.db", now - i * 100)
        for i in range(5)  # i=0 newest ... i=4 oldest
    ]

    database._prune_snapshots(keep=3)

    survivors = set(os.listdir(str(snapshot_dir)))
    assert survivors == {os.path.basename(p) for p in paths[:3]}


def test_prune_skips_file_that_is_in_use(snapshot_dir, monkeypatch):
    now = time.time()
    paths = [
        _make_snapshot(str(snapshot_dir), f"leagueintel_{i}.db", now - i * 100)
        for i in range(5)
    ]
    locked = paths[4]  # oldest — would normally be pruned first

    real_remove = os.remove

    def flaky_remove(path):
        if path == locked:
            raise OSError("still open in another session")
        real_remove(path)

    monkeypatch.setattr(database.os, "remove", flaky_remove)

    database._prune_snapshots(keep=3)  # must not raise

    survivors = set(os.listdir(str(snapshot_dir)))
    # 3 newest kept, the other prunable one removed, the locked one left behind
    assert survivors == {
        os.path.basename(paths[0]),
        os.path.basename(paths[1]),
        os.path.basename(paths[2]),
        os.path.basename(locked),
    }


# ── local dev short-circuit ─────────────────────────────────────────────────


def test_resolve_db_path_local_dev_skips_s3(monkeypatch):
    monkeypatch.setattr(database, "_in_cloud", lambda: False)
    try:
        database.get_current_etag.clear()
    except Exception:
        pass

    def boom():
        raise AssertionError("S3 must not be touched in local dev")

    monkeypatch.setattr(database, "_s3_client", boom)

    assert database.resolve_db_path() == str(database.DEFAULT_DB_PATH)
