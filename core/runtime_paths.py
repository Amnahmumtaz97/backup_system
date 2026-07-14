"""
Runtime path helpers for local runs and Render deployments.
"""

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_data_root() -> Path:
    """Return the base directory used for config, logs, and backups."""
    raw_root = os.getenv("DATAVAULT_DATA_DIR")
    if raw_root:
        root = Path(raw_root)
    elif os.getenv("RENDER"):
        root = Path("/var/data")
    else:
        root = PROJECT_ROOT / "data"

    root.mkdir(parents=True, exist_ok=True)
    return root


def get_data_path(*parts: str) -> Path:
    """Build a path under the data root and ensure its parent exists."""
    path = get_data_root().joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def resolve_runtime_path(value: str | None, *default_parts: str) -> Path:
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