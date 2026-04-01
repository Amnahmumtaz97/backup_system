# DataVault — Secure Data Backup System
### University Project | Information Security

A production-ready data backup system with AES-256 encryption, SHA-256 integrity verification, incremental/differential backup strategies, and a slick web UI.

---

## Features

| Feature | Details |
|---|---|
| Backup Types | Full, Incremental, Differential |
| Encryption | AES-256-CBC via PBKDF2 key derivation |
| Integrity | SHA-256 checksums on every backup |
| Scheduling | Automated backups via APScheduler |
| Audit Logging | Tamper-evident log of all operations |
| Web UI | Dark-themed dashboard at localhost:5000 |
| CLI | Full command-line interface |
| Restore | Integrity-verified restore to any path |

---

## Installation

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) Create a test source folder
mkdir -p ~/test_source
echo "Hello DataVault" > ~/test_source/test.txt

# 3. Configure (edit config/config.json or use the Settings page)
```

---

## Usage

### Option A — Web UI (Recommended)
```bash
python app.py
# Open http://localhost:5000 in your browser
```

### Option B — CLI
```bash
# Run a full backup
python cli.py backup --type full

# Run incremental backup
python cli.py backup --type incremental

# List all backups
python cli.py list

# Restore a backup
python cli.py restore --name full_20240101_120000 --path /tmp/restored

# View audit logs
python cli.py logs --n 30

# Statistics
python cli.py stats

# Delete a backup
python cli.py delete --name full_20240101_120000
```

---

## Project Structure

```
backup_system/
├── app.py               ← Flask web server + REST API
├── cli.py               ← Command-line interface
├── requirements.txt     ← Python dependencies
├── core/
│   ├── backup_engine.py ← Core backup/restore logic
│   ├── manifest.py      ← Backup metadata manager
│   ├── logger.py        ← Audit logging
│   └── scheduler.py     ← Automated scheduling
├── ui/
│   └── index.html       ← Web UI (served by Flask)
├── config/              ← Auto-created on first run
├── backups/             ← Backup archives (.zip)
├── logs/                ← Audit logs
└── tests/
    └── test_backup.py   ← Unit tests
```

---

## Security Design

- **Encryption**: AES-256-CBC using the `cryptography` library. Key is derived via PBKDF2-HMAC-SHA256 with 100,000 iterations.
- **Integrity**: SHA-256 hash of every backup archive stored in the manifest; verified before each restore.
- **Audit Logging**: Every backup, restore, and error is logged with timestamp and severity.
- **Access Control**: Passphrase required to decrypt any backup archive.

---

## Configuration

Edit `config/config.json` or use the Settings page:

```json
{
  "source_path": "/home/user/Documents",
  "destination_path": "backups",
  "log_path": "logs/audit.log",
  "passphrase": "your_secure_passphrase"
}
```

---

## Running Tests

```bash
python -m pytest tests/ -v
```

---

*Built for Information Security — University Project*
