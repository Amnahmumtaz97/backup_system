#!/usr/bin/env python3
"""
DataVault CLI - Command-line interface for the backup system
Usage: python cli.py [command] [options]
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure we can import core modules
sys.path.insert(0, str(Path(__file__).parent))
from core import BackupEngine, AuditLogger


def load_config():
    cfg_file = Path("config/config.json")
    if cfg_file.exists():
        with open(cfg_file) as f:
            return json.load(f)
    return {
        "source_path": str(Path.home() / "Documents"),
        "destination_path": "backups",
        "log_path": "logs/audit.log",
        "passphrase": "default_passphrase"
    }


def format_size(n):
    if n < 1024: return f"{n} B"
    if n < 1048576: return f"{n/1024:.1f} KB"
    if n < 1073741824: return f"{n/1048576:.1f} MB"
    return f"{n/1073741824:.2f} GB"


def cmd_backup(args):
    cfg = load_config()
    engine = BackupEngine(cfg)
    print(f"\n🔄 Starting {args.type} backup...")
    result = engine.run_backup(args.type)
    if result["status"] == "success":
        print(f"✅ Backup complete!")
        print(f"   Name    : {result['name']}")
        print(f"   Files   : {result['files']}")
        print(f"   Size    : {format_size(result['size'])}")
        print(f"   Duration: {result['duration']}s")
        print(f"   Encrypted: {'Yes' if result['encrypted'] else 'No'}")
    elif result["status"] == "up_to_date":
        print("ℹ️  Already up to date — no changes detected")
    else:
        print(f"❌ Error: {result.get('message')}")


def cmd_restore(args):
    cfg = load_config()
    engine = BackupEngine(cfg)
    print(f"\n↺  Restoring '{args.name}' to '{args.path}'...")
    result = engine.restore_backup(args.name, args.path)
    if result["status"] == "success":
        print(f"✅ Restore complete!")
        print(f"   Files   : {result['files']}")
        print(f"   Duration: {result['duration']}s")
        print(f"   Path    : {result['path']}")
    else:
        print(f"❌ Error: {result.get('message')}")


def cmd_list(args):
    cfg = load_config()
    engine = BackupEngine(cfg)
    backups = engine.list_backups()
    if not backups:
        print("\n📭 No backups found.")
        return
    print(f"\n{'Name':<35} {'Type':<14} {'Files':<8} {'Size':<12} {'Enc'}")
    print("─" * 85)
    for b in backups:
        enc = "🔐" if b["encrypted"] else "  "
        print(f"{b['name']:<35} {b['type']:<14} {b['files']:<8} {format_size(b['size']):<12} {enc}")


def cmd_stats(args):
    cfg = load_config()
    engine = BackupEngine(cfg)
    stats = engine.get_stats()
    print(f"\n📊 DataVault Statistics")
    print(f"   Total Backups : {stats['total_backups']}")
    print(f"   Storage Used  : {format_size(stats['total_size'])}")
    print(f"   Encryption    : {'AES-256 Active' if stats['encryption'] else 'Not available — install cryptography library'}")
    if stats['latest']:
        print(f"   Latest        : {stats['latest']['name']}")


def cmd_delete(args):
    cfg = load_config()
    engine = BackupEngine(cfg)
    confirm = input(f"Delete '{args.name}'? [y/N]: ")
    if confirm.lower() == 'y':
        engine.delete_backup(args.name)
        print(f"🗑️  Deleted '{args.name}'")
    else:
        print("Cancelled.")


def cmd_logs(args):
    cfg = load_config()
    logger = AuditLogger(cfg.get("log_path", "logs/audit.log"))
    logs = logger.get_recent(args.n)
    if not logs:
        print("\n📭 No log entries found.")
        return
    print(f"\n📋 Last {len(logs)} audit log entries:")
    print("─" * 70)
    for line in reversed(logs):
        print(line)


def main():
    parser = argparse.ArgumentParser(
        prog="datavault",
        description="DataVault — Secure Backup System CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py backup --type full
  python cli.py backup --type incremental
  python cli.py list
  python cli.py restore --name full_20240101_120000 --path /tmp/restored
  python cli.py stats
  python cli.py logs --n 20
  python cli.py delete --name full_20240101_120000
        """
    )
    sub = parser.add_subparsers(dest="command")

    # backup
    p_backup = sub.add_parser("backup", help="Run a backup")
    p_backup.add_argument("--type", choices=["full","incremental","differential"], default="incremental")

    # restore
    p_restore = sub.add_parser("restore", help="Restore a backup")
    p_restore.add_argument("--name", required=True)
    p_restore.add_argument("--path", required=True)

    # list
    sub.add_parser("list", help="List all backups")

    # stats
    sub.add_parser("stats", help="Show statistics")

    # delete
    p_del = sub.add_parser("delete", help="Delete a backup")
    p_del.add_argument("--name", required=True)

    # logs
    p_logs = sub.add_parser("logs", help="View audit logs")
    p_logs.add_argument("--n", type=int, default=50)

    args = parser.parse_args()

    if not args.command:
        print("""
  ╔══════════════════════════════════════╗
  ║   DataVault — Secure Backup System   ║
  ║   AES-256 + SHA-256 Integrity        ║
  ╚══════════════════════════════════════╝
  
  Web UI:  python app.py  →  http://localhost:5000
  CLI:     python cli.py --help
        """)
        parser.print_help()
        return

    dispatch = {
        "backup": cmd_backup,
        "restore": cmd_restore,
        "list": cmd_list,
        "stats": cmd_stats,
        "delete": cmd_delete,
        "logs": cmd_logs
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
