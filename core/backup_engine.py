"""
Backup Engine - Core backup/restore logic
Handles full, incremental, and differential backups with AES-256 encryption
"""

import os
import json
import hashlib
import zipfile
import shutil
import time
import base64
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False

from .manifest import ManifestManager
from .logger import AuditLogger


class BackupEngine:
    ENCRYPTION_MAGIC = b"DVT1"

    def __init__(self, config: dict):
        self.config = config
        self.source = Path(config.get("source_path", ""))
        self.destination = Path(config.get("destination_path", "backups"))
        self.destination.mkdir(parents=True, exist_ok=True)
        self.manifest_mgr = ManifestManager(self.destination / "manifests")
        self.logger = AuditLogger(config.get("log_path", "logs/audit.log"))
        self.encrypt_enabled = config.get("encrypt", True)
        self.passphrase = config.get("passphrase", "default_passphrase")

    def _derive_key(self, passphrase: str, salt: bytes) -> bytes:
        """Derive AES-256 key from passphrase using PBKDF2 and caller-provided salt."""
        if not ENCRYPTION_AVAILABLE:
            return b""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        return kdf.derive(passphrase.encode())

    def _hash_file(self, filepath: Path) -> str:
        """Compute SHA-256 hash of a file"""
        sha256 = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    sha256.update(chunk)
        except (IOError, OSError):
            return ""
        return sha256.hexdigest()

    def _scan_source(self) -> dict:
        """Scan source directory and return file metadata"""
        files = {}
        if not self.source.exists():
            return files
        for path in self.source.rglob("*"):
            if path.is_file():
                rel = str(path.relative_to(self.source))
                try:
                    stat = path.stat()
                    files[rel] = {
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        "hash": self._hash_file(path)
                    }
                except OSError:
                    pass
        return files

    def _detect_changes(self, current: dict, previous: dict) -> dict:
        """Detect new, modified, and deleted files"""
        changes = {"added": [], "modified": [], "deleted": []}
        for f, meta in current.items():
            if f not in previous:
                changes["added"].append(f)
            elif meta["hash"] != previous[f].get("hash", ""):
                changes["modified"].append(f)
        for f in previous:
            if f not in current:
                changes["deleted"].append(f)
        return changes

    def _encrypt_data(self, data: bytes) -> bytes:
        """Encrypt data using AES-256-CBC with per-backup random salt and IV."""
        if not ENCRYPTION_AVAILABLE or not self.encrypt_enabled:
            return data

        salt = os.urandom(16)
        key = self._derive_key(self.passphrase, salt)
        iv = os.urandom(16)
        padder = padding.PKCS7(128).padder()
        padded = padder.update(data) + padder.finalize()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(padded) + encryptor.finalize()
        return self.ENCRYPTION_MAGIC + salt + iv + encrypted

    def _decrypt_data(self, data: bytes) -> bytes:
        """Decrypt AES-256-CBC data and support legacy archive format."""
        if not ENCRYPTION_AVAILABLE or not self.encrypt_enabled:
            return data

        # New format: magic(4) + salt(16) + iv(16) + encrypted
        if data.startswith(self.ENCRYPTION_MAGIC) and len(data) > 36:
            salt = data[4:20]
            iv = data[20:36]
            encrypted = data[36:]
            key = self._derive_key(self.passphrase, salt)
        else:
            # Legacy format compatibility: iv(16) + encrypted using fixed salt.
            salt = b"backupsystem_salt_v1"
            iv = data[:16]
            encrypted = data[16:]
            key = self._derive_key(self.passphrase, salt)

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        padded = decryptor.update(encrypted) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return unpadder.update(padded) + unpadder.finalize()

    def _safe_extract(self, zf: zipfile.ZipFile, restore_dir: Path) -> int:
        """Extract zip members with path traversal protection."""
        extracted = 0
        restore_root = restore_dir.resolve()
        for member in zf.infolist():
            target = (restore_dir / member.filename).resolve()
            if not str(target).startswith(str(restore_root)):
                self.logger.log(f"Blocked unsafe archive entry: {member.filename}", "WARNING")
                continue
            zf.extract(member, restore_dir)
            if not member.is_dir():
                extracted += 1
        return extracted

    def _build_restore_chain(self, backup_name: str) -> list:
        """Return ordered backup names needed to reconstruct the requested backup."""
        chain = []
        visited = set()
        current = self.manifest_mgr.get(backup_name)

        while current:
            name = current.get("name")
            if not name or name in visited:
                break
            visited.add(name)

            btype = current.get("type")
            if btype == "full":
                chain.append(name)
                break
            if btype == "differential":
                base_name = current.get("base_backup")
                if base_name:
                    chain.append(base_name)
                chain.append(name)
                break

            # Incremental backup
            chain.append(name)
            base_name = current.get("base_backup")
            if not base_name:
                break
            current = self.manifest_mgr.get(base_name)

        return list(reversed(chain))

    def preview_backup(self, backup_type: str = "incremental") -> dict:
        """Preview what would be backed up without creating an archive."""
        current_files = self._scan_source()
        last_manifest = self.manifest_mgr.get_latest()

        if backup_type == "full" or not last_manifest:
            return {
                "type": "full" if not last_manifest else backup_type,
                "added": sorted(list(current_files.keys())),
                "modified": [],
                "deleted": [],
                "total_candidates": len(current_files)
            }

        if backup_type == "incremental":
            changes = self._detect_changes(current_files, last_manifest.get("files", {}))
            changes["type"] = "incremental"
            changes["total_candidates"] = len(changes["added"]) + len(changes["modified"])
            return changes

        full_manifest = self.manifest_mgr.get_last_full()
        base = full_manifest.get("files", {}) if full_manifest else {}
        changes = self._detect_changes(current_files, base)
        changes["type"] = "differential"
        changes["total_candidates"] = len(changes["added"]) + len(changes["modified"])
        return changes

    def run_backup(self, backup_type: str = "incremental") -> dict:
        """Run a backup job. Returns result dict."""
        start_time = time.time()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_name = f"{backup_type}_{timestamp}"
        backup_path = self.destination / f"{backup_name}.zip"

        self.logger.log(f"Starting {backup_type} backup: {backup_name}", "INFO")

        # Scan current state
        current_files = self._scan_source()
        last_manifest = self.manifest_mgr.get_latest()

        # Decide which files to back up
        if backup_type == "full" or not last_manifest:
            backup_type = "full" if not last_manifest else backup_type
            files_to_backup = list(current_files.keys())
            deleted_files = []
            base_backup = None
            self.logger.log(f"Full backup: {len(files_to_backup)} files", "INFO")
        elif backup_type == "incremental":
            changes = self._detect_changes(current_files, last_manifest.get("files", {}))
            files_to_backup = changes["added"] + changes["modified"]
            deleted_files = changes["deleted"]
            base_backup = last_manifest.get("name")
            self.logger.log(f"Incremental: {len(files_to_backup)} changed files", "INFO")
        else:  # differential
            full_manifest = self.manifest_mgr.get_last_full()
            base = full_manifest.get("files", {}) if full_manifest else {}
            changes = self._detect_changes(current_files, base)
            files_to_backup = changes["added"] + changes["modified"]
            deleted_files = changes["deleted"]
            base_backup = full_manifest.get("name") if full_manifest else None
            self.logger.log(f"Differential: {len(files_to_backup)} files since last full", "INFO")

        if not files_to_backup and not deleted_files:
            self.logger.log("No files to backup — already up to date", "INFO")
            return {"status": "up_to_date", "files": 0, "size": 0, "duration": 0, "name": backup_name}

        # Create ZIP archive
        total_size = 0
        file_checksums = {}
        tmp_zip = self.destination / f"{backup_name}_tmp.zip"

        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_path in files_to_backup:
                abs_path = self.source / rel_path
                if abs_path.exists():
                    try:
                        zf.write(abs_path, rel_path)
                        total_size += abs_path.stat().st_size
                        file_checksums[rel_path] = current_files[rel_path]["hash"]
                    except (IOError, OSError) as e:
                        self.logger.log(f"Skipped {rel_path}: {e}", "WARNING")

        # Encrypt the archive
        with open(tmp_zip, "rb") as f:
            raw_data = f.read()
        encrypted_data = self._encrypt_data(raw_data)
        with open(backup_path, "wb") as f:
            f.write(encrypted_data)
        os.remove(tmp_zip)

        duration = round(time.time() - start_time, 2)

        # Save manifest
        manifest = {
            "name": backup_name,
            "type": backup_type,
            "timestamp": timestamp,
            "files": current_files,
            "backed_up_files": files_to_backup,
            "deleted_files": deleted_files,
            "base_backup": base_backup,
            "checksums": file_checksums,
            "archive_hash": self._hash_file(backup_path),
            "total_size": total_size,
            "encrypted": ENCRYPTION_AVAILABLE and self.encrypt_enabled,
            "duration": duration
        }
        self.manifest_mgr.save(backup_name, manifest)
        self.logger.log(f"Backup complete: {len(files_to_backup)} files, {total_size} bytes in {duration}s", "SUCCESS")

        return {
            "status": "success",
            "name": backup_name,
            "type": backup_type,
            "files": len(files_to_backup),
            "size": total_size,
            "duration": duration,
            "path": str(backup_path),
            "encrypted": ENCRYPTION_AVAILABLE and self.encrypt_enabled
        }

    def restore_backup(self, backup_name: str, restore_path: str) -> dict:
        """Restore a backup to a given path"""
        start_time = time.time()
        manifest = self.manifest_mgr.get(backup_name)
        if not manifest:
            self.logger.log(f"Restore failed: manifest not found: {backup_name}", "ERROR")
            return {"status": "error", "message": "Backup manifest not found"}

        self.logger.log(f"Starting restore: {backup_name} -> {restore_path}", "INFO")
        restore_dir = Path(restore_path)
        restore_dir.mkdir(parents=True, exist_ok=True)

        chain = self._build_restore_chain(backup_name)
        if not chain:
            self.logger.log(f"Restore failed: could not resolve restore chain for {backup_name}", "ERROR")
            return {"status": "error", "message": "Could not resolve restore chain"}

        restored = 0
        try:
            for idx, name in enumerate(chain):
                step_manifest = self.manifest_mgr.get(name)
                if not step_manifest:
                    return {"status": "error", "message": f"Missing manifest in restore chain: {name}"}

                backup_file = self.destination / f"{name}.zip"
                if not backup_file.exists():
                    return {"status": "error", "message": f"Backup file not found: {name}"}

                current_hash = self._hash_file(backup_file)
                if step_manifest.get("archive_hash") and current_hash != step_manifest["archive_hash"]:
                    self.logger.log(f"INTEGRITY CHECK FAILED for {name}", "ERROR")
                    return {"status": "error", "message": f"Integrity check failed for {name}"}

                with open(backup_file, "rb") as f:
                    encrypted_data = f.read()
                raw_data = self._decrypt_data(encrypted_data)

                tmp_zip = self.destination / f"_restore_tmp_{idx}.zip"
                with open(tmp_zip, "wb") as f:
                    f.write(raw_data)

                try:
                    with zipfile.ZipFile(tmp_zip, "r") as zf:
                        restored += self._safe_extract(zf, restore_dir)
                finally:
                    if tmp_zip.exists():
                        os.remove(tmp_zip)

                for deleted in step_manifest.get("deleted_files", []):
                    target = restore_dir / deleted
                    try:
                        if target.is_dir():
                            shutil.rmtree(target)
                        elif target.exists():
                            target.unlink()
                    except OSError as e:
                        self.logger.log(f"Could not apply deletion '{deleted}': {e}", "WARNING")
        except ValueError:
            self.logger.log("Restore failed: invalid passphrase or corrupted encrypted data", "ERROR")
            return {"status": "error", "message": "Decryption failed. Check passphrase or archive integrity."}
        except zipfile.BadZipFile:
            self.logger.log("Restore failed: decrypted payload is not a valid zip", "ERROR")
            return {"status": "error", "message": "Backup payload is corrupted or passphrase is invalid."}

        duration = round(time.time() - start_time, 2)
        self.logger.log(f"Restore complete: {restored} files in {duration}s (chain: {', '.join(chain)})", "SUCCESS")

        return {
            "status": "success",
            "files": restored,
            "duration": duration,
            "path": restore_path,
            "chain": chain
        }

    def list_backups(self) -> list:
        """Return list of all available backups"""
        return self.manifest_mgr.list_all()

    def get_backup_detail(self, backup_name: str) -> Optional[dict]:
        """Return full manifest details for a backup."""
        return self.manifest_mgr.get(backup_name)

    def verify_backup(self, backup_name: str) -> dict:
        """Verify archive integrity for a single backup."""
        manifest = self.manifest_mgr.get(backup_name)
        if not manifest:
            return {"status": "error", "name": backup_name, "message": "Manifest not found"}

        archive = self.destination / f"{backup_name}.zip"
        if not archive.exists():
            return {"status": "error", "name": backup_name, "message": "Archive not found"}

        expected = manifest.get("archive_hash")
        current = self._hash_file(archive)
        ok = bool(expected) and expected == current
        return {
            "status": "success" if ok else "error",
            "name": backup_name,
            "valid": ok,
            "expected_hash": expected,
            "actual_hash": current,
            "message": "Integrity verified" if ok else "Integrity mismatch"
        }

    def verify_all_backups(self) -> dict:
        """Verify all backups and return summary."""
        backups = self.list_backups()
        results = [self.verify_backup(b["name"]) for b in backups]
        valid = sum(1 for r in results if r.get("valid"))
        invalid = sum(1 for r in results if r.get("status") == "error")
        return {
            "status": "success",
            "total": len(results),
            "valid": valid,
            "invalid": invalid,
            "results": results
        }

    def delete_backup(self, backup_name: str) -> dict:
        """Delete a backup and its manifest"""
        backup_file = self.destination / f"{backup_name}.zip"
        if backup_file.exists():
            os.remove(backup_file)
        self.manifest_mgr.delete(backup_name)
        self.logger.log(f"Deleted backup: {backup_name}", "INFO")
        return {"status": "success"}

    def get_stats(self) -> dict:
        """Return summary statistics"""
        backups = self.list_backups()
        total_size = sum(
            (self.destination / f"{b['name']}.zip").stat().st_size
            for b in backups
            if (self.destination / f"{b['name']}.zip").exists()
        )
        return {
            "total_backups": len(backups),
            "total_size": total_size,
            "latest": backups[0] if backups else None,
            "encryption": ENCRYPTION_AVAILABLE and self.encrypt_enabled
        }
