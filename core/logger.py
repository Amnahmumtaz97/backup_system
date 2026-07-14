"""
Audit Logger - Tamper-evident logging of all backup operations
"""

import os
import hashlib
from datetime import datetime
from pathlib import Path

from .runtime_paths import resolve_runtime_path


class AuditLogger:
    LEVELS = {"DEBUG": "🔍", "INFO": "ℹ️ ", "WARNING": "⚠️ ", "SUCCESS": "✅", "ERROR": "❌"}

    def __init__(self, log_path: str | None = None):
        self.log_path = resolve_runtime_path(log_path, "logs", "audit.log")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        icon = self.LEVELS.get(level, "  ")
        line = f"[{timestamp}] [{level:7}] {icon} {message}\n"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line)

    def get_recent(self, n: int = 50) -> list:
        if not self.log_path.exists():
            return []
        with open(self.log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines[-n:]][::-1]

    def get_all(self) -> list:
        if not self.log_path.exists():
            return []
        with open(self.log_path, "r", encoding="utf-8") as f:
            return [l.rstrip() for l in f.readlines()][::-1]
