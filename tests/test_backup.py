"""
Unit Tests for DataVault Backup System
Run: python -m pytest tests/ -v
"""

import pytest
import tempfile
import os
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.backup_engine import BackupEngine
from core.manifest import ManifestManager
from core.logger import AuditLogger


@pytest.fixture
def temp_dirs(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    logs = tmp_path / "logs"
    logs.mkdir()
    return source, dest, logs


@pytest.fixture
def engine(temp_dirs):
    source, dest, logs = temp_dirs
    config = {
        "source_path": str(source),
        "destination_path": str(dest),
        "log_path": str(logs / "test.log"),
        "passphrase": "test_passphrase_123"
    }
    return BackupEngine(config), source, dest


def test_full_backup_creates_archive(engine):
    eng, source, dest = engine
    (source / "file1.txt").write_text("Hello World")
    (source / "file2.txt").write_text("Test data")
    result = eng.run_backup("full")
    assert result["status"] == "success"
    assert result["files"] == 2
    assert (dest / f"{result['name']}.zip").exists()


def test_incremental_detects_changes(engine):
    eng, source, dest = engine
    (source / "file1.txt").write_text("Original")
    eng.run_backup("full")

    # Modify a file
    (source / "file1.txt").write_text("Modified")
    (source / "new_file.txt").write_text("New content")

    result = eng.run_backup("incremental")
    assert result["status"] == "success"
    assert result["files"] == 2  # modified + new


def test_incremental_no_changes_is_up_to_date(engine):
    eng, source, dest = engine
    (source / "file1.txt").write_text("Static content")
    eng.run_backup("full")
    result = eng.run_backup("incremental")
    assert result["status"] == "up_to_date"


def test_restore_integrity_check(engine):
    eng, source, dest = engine
    (source / "important.txt").write_text("Critical data")
    backup_result = eng.run_backup("full")

    restore_dir = dest / "restored"
    result = eng.restore_backup(backup_result["name"], str(restore_dir))
    assert result["status"] == "success"
    assert (restore_dir / "important.txt").exists()
    assert (restore_dir / "important.txt").read_text() == "Critical data"


def test_restore_fails_on_tampered_archive(engine):
    eng, source, dest = engine
    (source / "data.txt").write_text("Sensitive")
    backup_result = eng.run_backup("full")

    # Tamper with the archive
    archive = dest / f"{backup_result['name']}.zip"
    data = bytearray(archive.read_bytes())
    data[50] ^= 0xFF  # flip some bits
    archive.write_bytes(data)

    restore_dir = dest / "restored"
    result = eng.restore_backup(backup_result["name"], str(restore_dir))
    assert result["status"] == "error"
    assert "integrity" in result["message"].lower() or "corrupt" in result["message"].lower()


def test_restore_incremental_chain_reconstructs_state(engine):
    eng, source, dest = engine
    (source / "a.txt").write_text("v1")
    full = eng.run_backup("full")

    (source / "a.txt").write_text("v2")
    (source / "b.txt").write_text("new")
    inc = eng.run_backup("incremental")

    # Remove file to verify deleted-file propagation in chain restores.
    (source / "b.txt").unlink()
    inc2 = eng.run_backup("incremental")

    restore_dir = dest / "restored_chain"
    result = eng.restore_backup(inc2["name"], str(restore_dir))
    assert result["status"] == "success"
    assert (restore_dir / "a.txt").exists()
    assert (restore_dir / "a.txt").read_text() == "v2"
    assert not (restore_dir / "b.txt").exists()


def test_restore_fails_with_wrong_passphrase(temp_dirs):
    source, dest, logs = temp_dirs
    cfg_good = {
        "source_path": str(source),
        "destination_path": str(dest),
        "log_path": str(logs / "test.log"),
        "passphrase": "correct-pass"
    }
    cfg_bad = {
        "source_path": str(source),
        "destination_path": str(dest),
        "log_path": str(logs / "test.log"),
        "passphrase": "wrong-pass"
    }

    (source / "secret.txt").write_text("top-secret")
    eng_good = BackupEngine(cfg_good)
    result = eng_good.run_backup("full")

    eng_bad = BackupEngine(cfg_bad)
    restore_dir = dest / "wrong_pass_restore"
    restored = eng_bad.restore_backup(result["name"], str(restore_dir))
    assert restored["status"] == "error"
    assert "decrypt" in restored["message"].lower() or "passphrase" in restored["message"].lower()


def test_list_backups(engine):
    eng, source, dest = engine
    (source / "a.txt").write_text("a")
    eng.run_backup("full")
    eng.run_backup("incremental")
    backups = eng.list_backups()
    # At minimum the full backup should be there (incremental may be up_to_date)
    assert len(backups) >= 1


def test_delete_backup(engine):
    eng, source, dest = engine
    (source / "f.txt").write_text("data")
    result = eng.run_backup("full")
    name = result["name"]
    eng.delete_backup(name)
    backups = eng.list_backups()
    assert not any(b["name"] == name for b in backups)


def test_manifest_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = ManifestManager(Path(tmpdir))
        data = {"name": "test_backup", "type": "full", "files": {"a.txt": {"hash": "abc"}}}
        mgr.save("test_backup", data)
        loaded = mgr.get("test_backup")
        assert loaded["type"] == "full"
        assert "a.txt" in loaded["files"]


def test_audit_logger():
    with tempfile.NamedTemporaryFile(suffix=".log", delete=False, mode='w') as f:
        log_path = f.name
    try:
        logger = AuditLogger(log_path)
        logger.log("Test message", "SUCCESS")
        logger.log("Error occurred", "ERROR")
        recent = logger.get_recent(10)
        assert len(recent) == 2
        assert any("SUCCESS" in l for l in recent)
        assert any("ERROR" in l for l in recent)
    finally:
        os.unlink(log_path)


def test_subdirectory_backup(engine):
    eng, source, dest = engine
    subdir = source / "subdir" / "nested"
    subdir.mkdir(parents=True)
    (subdir / "deep.txt").write_text("Deep file")
    (source / "root.txt").write_text("Root file")
    result = eng.run_backup("full")
    assert result["files"] == 2

    restore_dir = dest / "restored"
    restore_result = eng.restore_backup(result["name"], str(restore_dir))
    assert restore_result["status"] == "success"
    assert (restore_dir / "subdir" / "nested" / "deep.txt").exists()


def test_preview_backup_reports_changes(engine):
    eng, source, _ = engine
    (source / "x.txt").write_text("v1")
    full_preview = eng.preview_backup("full")
    assert full_preview["type"] == "full"
    assert "x.txt" in full_preview["added"]

    eng.run_backup("full")
    (source / "x.txt").write_text("v2")
    (source / "y.txt").write_text("new")
    incr_preview = eng.preview_backup("incremental")
    assert "x.txt" in incr_preview["modified"]
    assert "y.txt" in incr_preview["added"]


def test_verify_backup_success(engine):
    eng, source, _ = engine
    (source / "ok.txt").write_text("ok")
    result = eng.run_backup("full")
    verify = eng.verify_backup(result["name"])
    assert verify["status"] == "success"
    assert verify["valid"] is True
