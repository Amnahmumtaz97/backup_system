"""
Web Server - Flask API + UI server for Data Backup System
Run: python app.py
Then open: http://localhost:5000
"""

import os
import json
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, send_file
from core import BackupEngine, BackupScheduler, AuditLogger

app = Flask(__name__, static_folder="ui", static_url_path="")

# Load or create config
CONFIG_FILE = Path("config/config.json")
CONFIG_FILE.parent.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "source_path": str(Path.home() / "Documents"),
    "destination_path": "backups",
    "log_path": "logs/audit.log",
    "passphrase": "change_me_in_settings"
}

def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


_runtime_engine = None
_runtime_scheduler = None


def init_runtime():
    global _runtime_engine, _runtime_scheduler
    if _runtime_scheduler:
        _runtime_scheduler.shutdown()
    _runtime_engine = BackupEngine(load_config())
    _runtime_scheduler = BackupScheduler(_runtime_engine)
    if _runtime_scheduler.schedule.get("enabled", False):
        _runtime_scheduler.start()


def get_engine():
    global _runtime_engine
    if _runtime_engine is None:
        init_runtime()
    return _runtime_engine


def get_scheduler():
    global _runtime_scheduler
    if _runtime_scheduler is None:
        init_runtime()
    return _runtime_scheduler


# ─── STATIC UI ────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("ui", "index.html")


# ─── CONFIG API ───────────────────────────────────────────────────────────────
@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = load_config()
    cfg_safe = {k: v for k, v in cfg.items() if k != "passphrase"}
    cfg_safe["passphrase"] = "••••••••" if cfg.get("passphrase") else ""
    cfg_safe.setdefault("encrypt", True)
    return jsonify(cfg_safe)

@app.route("/api/config", methods=["POST"])
def update_config():
    data = request.json
    cfg = load_config()
    for k in ["source_path", "destination_path", "log_path"]:
        if k in data:
            cfg[k] = data[k]
    if "encrypt" in data:
        cfg["encrypt"] = bool(data["encrypt"])
    if data.get("passphrase") and data["passphrase"] != "••••••••":
        cfg["passphrase"] = data["passphrase"]
    save_config(cfg)
    init_runtime()
    return jsonify({"status": "ok"})


# ─── BACKUP API ───────────────────────────────────────────────────────────────
@app.route("/api/backup/run", methods=["POST"])
def run_backup():
    backup_type = request.json.get("type", "incremental")
    if backup_type not in ["full", "incremental", "differential"]:
        return jsonify({"status": "error", "message": "Invalid backup type"}), 400
    engine = get_engine()
    result = engine.run_backup(backup_type)
    return jsonify(result)

@app.route("/api/backup/list", methods=["GET"])
def list_backups():
    engine = get_engine()
    backups = engine.list_backups()
    return jsonify(backups)

@app.route("/api/backup/preview", methods=["GET"])
def preview_backup():
    backup_type = request.args.get("type", "incremental")
    if backup_type not in ["full", "incremental", "differential"]:
        return jsonify({"status": "error", "message": "Invalid backup type"}), 400
    engine = get_engine()
    return jsonify(engine.preview_backup(backup_type))

@app.route("/api/backup/detail/<name>", methods=["GET"])
def backup_detail(name):
    engine = get_engine()
    detail = engine.get_backup_detail(name)
    if not detail:
        return jsonify({"status": "error", "message": "Backup not found"}), 404
    return jsonify(detail)

@app.route("/api/backup/verify", methods=["POST"])
def verify_backup():
    data = request.json or {}
    name = data.get("name")
    engine = get_engine()
    if name:
        return jsonify(engine.verify_backup(name))
    return jsonify(engine.verify_all_backups())

@app.route("/api/backup/download/<name>", methods=["GET"])
def download_backup(name):
    cfg = load_config()
    destination = Path(cfg.get("destination_path", "backups"))
    archive = destination / f"{name}.zip"
    if not archive.exists():
        return jsonify({"status": "error", "message": "Backup archive not found"}), 404
    return send_file(archive, as_attachment=True, download_name=f"{name}.zip")

@app.route("/api/backup/restore", methods=["POST"])
def restore_backup():
    name = request.json.get("name")
    path = request.json.get("restore_path", str(Path.home() / "restored_backup"))
    if not name:
        return jsonify({"status": "error", "message": "Backup name required"}), 400
    engine = get_engine()
    result = engine.restore_backup(name, path)
    return jsonify(result)

@app.route("/api/backup/delete", methods=["POST"])
def delete_backup():
    name = request.json.get("name")
    if not name:
        return jsonify({"status": "error", "message": "Name required"}), 400
    engine = get_engine()
    result = engine.delete_backup(name)
    return jsonify(result)

@app.route("/api/stats", methods=["GET"])
def get_stats():
    engine = get_engine()
    return jsonify(engine.get_stats())


# ─── LOGS API ─────────────────────────────────────────────────────────────────
@app.route("/api/logs", methods=["GET"])
def get_logs():
    cfg = load_config()
    logger = AuditLogger(cfg.get("log_path", "logs/audit.log"))
    n = int(request.args.get("n", 100))
    return jsonify(logger.get_recent(n))


# ─── SCHEDULE API ─────────────────────────────────────────────────────────────
@app.route("/api/schedule", methods=["GET"])
def get_schedule():
    return jsonify(get_scheduler().get_status())

@app.route("/api/schedule", methods=["POST"])
def set_schedule():
    data = request.json
    scheduler = get_scheduler()
    scheduler.save_schedule(
        enabled=data.get("enabled", False),
        interval_hours=int(data.get("interval_hours", 24)),
        backup_type=data.get("backup_type", "incremental")
    )
    return jsonify({"status": "ok"})

@app.route("/api/schedule/run-now", methods=["POST"])
def run_schedule_now():
    engine = get_engine()
    backup_type = (request.json or {}).get("backup_type", "incremental")
    if backup_type not in ["full", "incremental", "differential"]:
        return jsonify({"status": "error", "message": "Invalid backup type"}), 400
    result = engine.run_backup(backup_type)
    return jsonify(result)


# ─── BROWSE SOURCE API ────────────────────────────────────────────────────────
@app.route("/api/browse", methods=["GET"])
def browse():
    path = request.args.get("path", str(Path.home()))
    p = Path(path)
    if not p.exists() or not p.is_dir():
        return jsonify({"error": "Invalid path"}), 400
    entries = []
    try:
        for item in sorted(p.iterdir()):
            entries.append({
                "name": item.name,
                "path": str(item),
                "is_dir": item.is_dir()
            })
    except PermissionError:
        pass
    return jsonify({"path": str(p), "parent": str(p.parent), "entries": entries})


if __name__ == "__main__":
    init_runtime()
    print("╔══════════════════════════════════════════╗")
    print("║      Data Backup System  v1.0             ║")
    print("║      http://localhost:5000                ║")
    print("╚══════════════════════════════════════════╝")
    app.run(debug=True, host="0.0.0.0", port=5000)
