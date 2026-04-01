"""
Manifest Manager - Stores and retrieves backup metadata
"""

import json
import os
from pathlib import Path
from typing import Optional


class ManifestManager:
    def __init__(self, manifest_dir: Path):
        self.dir = Path(manifest_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, data: dict):
        path = self.dir / f"{name}.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def get(self, name: str) -> Optional[dict]:
        path = self.dir / f"{name}.json"
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)

    def delete(self, name: str):
        path = self.dir / f"{name}.json"
        if path.exists():
            os.remove(path)

    def list_all(self) -> list:
        manifests = []
        for p in sorted(self.dir.glob("*.json"), reverse=True):
            try:
                with open(p) as f:
                    data = json.load(f)
                    manifests.append({
                        "name": data.get("name", p.stem),
                        "type": data.get("type", "unknown"),
                        "timestamp": data.get("timestamp", ""),
                        "files": len(data.get("backed_up_files", [])),
                        "size": data.get("total_size", 0),
                        "duration": data.get("duration", 0),
                        "encrypted": data.get("encrypted", False)
                    })
            except Exception:
                pass
        return manifests

    def get_latest(self) -> Optional[dict]:
        all_m = sorted(self.dir.glob("*.json"), reverse=True)
        if not all_m:
            return None
        with open(all_m[0]) as f:
            return json.load(f)

    def get_last_full(self) -> Optional[dict]:
        for p in sorted(self.dir.glob("full_*.json"), reverse=True):
            with open(p) as f:
                return json.load(f)
        return None
