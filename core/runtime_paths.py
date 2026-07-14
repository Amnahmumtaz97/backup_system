"""
Runtime path helpers for local runs and Render deployments.
"""

import os
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DATA_ROOT: Optional[Path] = None


def _ensure_writable_directory(path: Path) -> Optional[Path]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return path
    except OSError:
        return None


def get_data_root() -> Path:
    """Return the base directory used for config, logs, and backups."""
    global _DATA_ROOT

    if _DATA_ROOT is not None:
        return _DATA_ROOT

    candidates = []
    raw_root = os.getenv("DATAVAULT_DATA_DIR")
    if raw_root:
        candidates.append(Path(raw_root))

    if os.getenv("RENDER"):
        candidates.append(Path("/var/data"))

    candidates.append(PROJECT_ROOT / "data")
    candidates.append(Path("/tmp/datavault"))

    for candidate in candidates:
        root = _ensure_writable_directory(candidate)
        if root is not None:
            _DATA_ROOT = root
            return root

    raise RuntimeError("Unable to locate a writable DataVault data directory")


def get_data_path(*parts: str) -> Path:
    """Build a path under the data root and ensure its parent exists."""
    path = get_data_root().joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def resolve_runtime_path(value: Optional[str], *default_parts: str) -> Path:
    """Resolve a configured path, keeping relative paths under the data root."""
    if value:
        path = Path(value)
        if path.is_absolute():
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        resolved = get_data_root().joinpath(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    return get_data_path(*default_parts)