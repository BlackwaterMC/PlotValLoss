"""Readers for AI-Toolkit training-loss SQLite logs, plus locating the AI-Toolkit folders.

Trimmed from ImageTools' ``aitk`` package (loss.py, paths.py, backend.py): only what the
loss viewer needs. Each run's ``loss_log.db`` has tables ``metrics(step, key, value_real)``
and ``steps(step, wall_time)``; ``aitk_db.db`` has a ``Job`` table with creation dates.
"""

import datetime
import os
import sqlite3

from config_store import config_path_for, load_config

LOSS_LOG_DB = "loss_log.db"
AITK_DB_NAME = "aitk_db.db"
AITK_OUTPUT_NAME = "output"


# --- Locating AI-Toolkit ---------------------------------------------------

def resolve_aitk_root() -> str:
    """AI-Toolkit root folder: ``AITK_ROOT`` env var, else ``aitk_root`` in
    ``plotvalloss_config.json``, else ``""`` (unconfigured). Native path separators."""
    env_root = os.environ.get("AITK_ROOT", "").strip()
    if env_root:
        return os.path.normpath(env_root)
    configured = str(load_config(config_path_for("plotvalloss")).get("aitk_root", "")).strip()
    return os.path.normpath(configured) if configured else ""


def default_output_dir(root: str | None = None) -> str:
    """``<root>/output``, where AI-Toolkit writes one folder per run."""
    return os.path.join(resolve_aitk_root() if root is None else root, AITK_OUTPUT_NAME)


def aitk_db_path(root: str) -> str:
    """``<root>/aitk_db.db`` -- the AI-Toolkit job database."""
    return os.path.join(root, AITK_DB_NAME)


def metrics_db_for(output_dir: str, run_name: str) -> str | None:
    """The metrics database of one run folder: ``loss_log.db`` if present, else the first
    ``*.db`` file in it, else ``None`` (also ``None`` if the folder does not exist)."""
    run_dir = os.path.join(output_dir, run_name)
    if not os.path.isdir(run_dir):
        return None
    preferred = os.path.join(run_dir, LOSS_LOG_DB)
    if os.path.isfile(preferred):
        return preferred
    dbs = sorted(
        f for f in os.listdir(run_dir)
        if f.endswith(".db") and os.path.isfile(os.path.join(run_dir, f))
    )
    return os.path.join(run_dir, dbs[0]) if dbs else None


# --- SQLite readers ----------------------------------------------------------

def connect_ro(db_path: str) -> sqlite3.Connection:
    """Open ``db_path`` read-only, falling back to a normal connection."""
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except Exception:
        return sqlite3.connect(db_path)


def _coerce_job_timestamp(c_at) -> str | None:
    """AITK ``Job.created_at`` -> ``"YYYY-MM-DD HH:MM"`` (epoch s/ms, or ISO string)."""
    try:
        if isinstance(c_at, (int, float)):
            ts = c_at / 1000.0 if c_at > 1e11 else float(c_at)
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        if isinstance(c_at, str):
            return c_at.split(".")[0].replace("T", " ")
    except Exception:
        return None
    return None


def _read_job_dates(db_path: str) -> dict | None:
    """``{Job.name: date_str}`` from one ``aitk_db.db``; ``None`` if it can't be read."""
    try:
        conn = connect_ro(db_path)
    except Exception:
        return None
    try:
        rows = conn.cursor().execute("SELECT name, created_at FROM Job").fetchall()
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass
    out: dict = {}
    for name, c_at in rows:
        if not name:
            continue
        date_str = _coerce_job_timestamp(c_at)
        if date_str is not None:
            out[name] = date_str
    return out


def get_job_dates_map(output_dir: str, fallback_db: str | None = None) -> dict:
    """Map ``Job.name`` -> ``"YYYY-MM-DD HH:MM"`` by reading ``aitk_db.db``.

    Looks for ``<output_dir>/../aitk_db.db`` first, then ``fallback_db``. Opened
    read-only. Returns ``{}`` if nothing is found or the table is unreadable.
    """
    for db_candidate in (os.path.join(output_dir, "..", AITK_DB_NAME), fallback_db):
        if not db_candidate:
            continue
        db_path = os.path.abspath(db_candidate)
        if not os.path.exists(db_path):
            continue
        dates = _read_job_dates(db_path)
        if dates is not None:
            return dates
    return {}


def get_run_date(folder_path: str, folder_name: str, db_path: str, job_dates: dict) -> str:
    """Run start date: ``aitk_db.db`` job entry, else db ctime, else folder mtime."""
    if folder_name in job_dates:
        return job_dates[folder_name]

    if os.path.exists(db_path):
        try:
            ctime = os.path.getctime(db_path)
            return datetime.datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

    try:
        mtime = os.path.getmtime(folder_path)
        return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "Unknown"


def load_series_from_db(db_path: str, metric_key: str = "val/loss"):
    """Return ``(steps, values, wall_times)`` for ``metric_key`` ordered by step.

    Rows with a NULL ``value_real`` are dropped. Returns ``([], [], [])`` when the metric
    has no rows, or when a just-created log has not written its tables yet. Raises if the
    database cannot be opened (callers guard with ``os.path.exists``).
    """
    conn = connect_ro(db_path)

    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT m.step, m.value_real, s.wall_time
                FROM metrics m
                LEFT JOIN steps s ON m.step = s.step
                WHERE m.key = ? AND m.value_real IS NOT NULL
                ORDER BY m.step ASC
                """,
                (metric_key,),
            )
        except sqlite3.OperationalError:
            return [], [], []
        rows = cur.fetchall()
        if not rows:
            return [], [], []
        steps = [r[0] for r in rows]
        values = [float(r[1]) for r in rows]
        wall_times = [r[2] for r in rows]
        return steps, values, wall_times
    finally:
        conn.close()
