"""Small JSON settings file helpers (trimmed from ImageTools' abstract_config / abstract_fs.paths).

Saves are all-or-nothing and keep the last good copy as ``<file>.bak``; an unreadable
file is set aside as ``<file>.corrupt`` before a save overwrites it. Standard library only.
"""

import json
import logging
import os
import re
import shutil
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("config_store")

# This repo's root folder: it holds static/, templates/ and plotvalloss_config.json.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

_io_lock = threading.RLock()


def config_path_for(name: str) -> str:
    """Absolute path to ``<name>_config.json`` in the repo root."""
    return os.path.join(PROJECT_ROOT, f"{name}_config.json")


def natural_sort_key(s: object) -> List[object]:
    """Natural alphanumeric sort key (run2 before run10)."""
    return [int(text) if i % 2 else text.lower() for i, text in enumerate(re.split(r"(\d+)", str(s)))]


def robust_rename(src: str, dst: str, max_retries: int = 15, delay: float = 0.1) -> bool:
    """``os.replace`` with retries for transient Windows file locks."""
    max_retries = max(1, max_retries)
    for i in range(max_retries):
        try:
            os.replace(src, dst)
            return True
        except OSError:
            if i < max_retries - 1:
                time.sleep(delay)
            else:
                raise


def _backup_path(filepath: str) -> str:
    return filepath + ".bak"


def _corrupt_path(filepath: str) -> str:
    return filepath + ".corrupt"


def _read_json_dict(filepath: str) -> Optional[Dict[str, Any]]:
    """The JSON object in ``filepath``, or ``None`` if missing, unreadable, or not an object."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _read_json_dict_retrying(filepath: str, attempts: int = 3, delay: float = 0.05) -> Optional[Dict[str, Any]]:
    """Like :func:`_read_json_dict`, but retries if the file is briefly locked by a save."""
    for i in range(attempts):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except OSError:
            if i < attempts - 1:
                time.sleep(delay)
        except Exception:
            return None
    return None


def _write_json_atomic(filepath: str, data: Any) -> None:
    """Replace ``filepath`` with ``data`` as JSON, all or nothing (temp file, then swap)."""
    payload = json.dumps(data, indent=4)
    tmp = f"{filepath}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(filepath):
            try:
                if _read_json_dict(filepath) is not None:
                    shutil.copyfile(filepath, _backup_path(filepath))
                else:
                    shutil.copyfile(filepath, _corrupt_path(filepath))
                    logger.warning("Config file %s was unreadable; kept a copy as %s before overwriting it",
                                   filepath, _corrupt_path(filepath))
            except OSError as exc:
                logger.warning("Could not back up config file %s (%s); saving anyway", filepath, exc)
        robust_rename(tmp, filepath)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def load_config(config_path: str) -> Dict[str, Any]:
    """Load a JSON settings file; falls back to its ``.bak``, then to ``{}``."""
    with _io_lock:
        if not os.path.exists(config_path):
            return {}
        data = _read_json_dict_retrying(config_path)
        if data is not None:
            return data
        backup = _read_json_dict(_backup_path(config_path))
        if backup is not None:
            logger.warning("Config file %s is unreadable; using its last good backup", config_path)
            return backup
        logger.warning("Config file %s is unreadable and has no usable backup; using empty settings", config_path)
        return {}


def save_config(config_path: str, data: Any) -> None:
    """Save a JSON settings file atomically; a failed save leaves the old file as it was."""
    with _io_lock:
        os.makedirs(os.path.dirname(os.path.abspath(config_path)), exist_ok=True)
        try:
            _write_json_atomic(config_path, data)
        except Exception:
            logger.exception("Could not save config file %s; the previous file was left as it was", config_path)
