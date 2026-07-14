"""
Scheduler - Automated backup scheduling
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .runtime_paths import resolve_runtime_path


class BackupScheduler:
    JOB_ID = "datavault_backup_job"

    def __init__(self, engine, schedule_file: Optional[str] = None):
        self.engine = engine
        self.schedule_file = resolve_runtime_path(schedule_file, "config", "schedule.json")
        self.schedule_file.parent.mkdir(parents=True, exist_ok=True)
        self._scheduler = BackgroundScheduler(daemon=True)
        self.schedule = self._load_schedule()

    def _load_schedule(self) -> dict:
        if self.schedule_file.exists():
            with open(self.schedule_file) as f:
                return json.load(f)
        return {"enabled": False, "interval_hours": 24, "backup_type": "incremental", "last_run": None}

    def save_schedule(self, enabled: bool, interval_hours: int, backup_type: str):
        self.schedule = {
            "enabled": enabled,
            "interval_hours": interval_hours,
            "backup_type": backup_type,
            "last_run": self.schedule.get("last_run")
        }
        with open(self.schedule_file, "w") as f:
            json.dump(self.schedule, f, indent=2)

        self.stop()
        if enabled:
            self.start()

    def start(self):
        if not self.schedule.get("enabled", False):
            return

        if not self._scheduler.running:
            self._scheduler.start()

        self._scheduler.add_job(
            self._run_backup_job,
            trigger=IntervalTrigger(hours=max(1, int(self.schedule.get("interval_hours", 24)))),
            id=self.JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

    def stop(self):
        if self._scheduler.get_job(self.JOB_ID):
            self._scheduler.remove_job(self.JOB_ID)

    def shutdown(self):
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def _run_backup_job(self):
        btype = self.schedule.get("backup_type", "incremental")
        self.engine.run_backup(btype)
        self.schedule["last_run"] = datetime.now().timestamp()
        with open(self.schedule_file, "w") as f:
            json.dump(self.schedule, f, indent=2)

    def get_status(self) -> dict:
        s = self.schedule.copy()
        s["running"] = bool(self._scheduler.get_job(self.JOB_ID))
        if s.get("last_run"):
            s["last_run_str"] = datetime.fromtimestamp(s["last_run"]).strftime("%Y-%m-%d %H:%M:%S")
            next_run = s["last_run"] + s.get("interval_hours", 24) * 3600
            s["next_run_str"] = datetime.fromtimestamp(next_run).strftime("%Y-%m-%d %H:%M:%S")
        elif s.get("enabled"):
            s["next_run_str"] = "Pending first run"
        return s
