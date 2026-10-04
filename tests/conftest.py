import os
import sys
import sqlite3

# Make the repo root importable (mirrors `pythonpath = .` in pytest.ini).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# The AI-Toolkit per-run loss log: ``metrics`` holds one row per (step, key) sample,
# ``steps`` maps step -> wall_time. ``Job`` is the minimal shape of aitk_db.db's table.
LOSS_LOG_DDL = """
CREATE TABLE metrics (step INTEGER, key TEXT, value_real REAL);
CREATE TABLE steps (step INTEGER, wall_time REAL);
"""
LOSS_JOB_DDL = 'CREATE TABLE "Job" (name TEXT, created_at TEXT);'


def init_mock_loss_db(db_path, *, with_job=False):
    """Create a ``loss_log.db`` with ``metrics`` + ``steps`` (optionally ``Job``).

    Returns the open connection so the caller can insert rows; close it when done.
    """
    os.makedirs(os.path.dirname(str(db_path)) or ".", exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(LOSS_LOG_DDL + (LOSS_JOB_DDL if with_job else ""))
    conn.commit()
    return conn
