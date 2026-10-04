"""plot_val_loss.py - Web-based validation loss explorer for AI-Toolkit training runs.

Runs as a lightweight Flask web app with auto-shutdown on browser disconnect, interactive
Plotly visualization, relative time toggling, run date detection, and automatic hiding of
runs that exceed 1.0 validation loss.
"""

import os
import argparse
import logging

from flask import render_template, request

from background import BackgroundTaskWorker, dispatch_worker_task
from config_store import config_path_for, natural_sort_key
from loss_reader import (
    aitk_db_path,
    default_output_dir,
    get_job_dates_map,
    get_run_date,
    load_series_from_db,
    metrics_db_for,
    resolve_aitk_root,
)
from web_support import api_error, api_success, create_app, make_config_routes, register_progress_routes

app, auto_shutdown_manager = create_app(__name__)
scan_worker = BackgroundTaskWorker(auto_shutdown_manager=auto_shutdown_manager)

CONFIG_FILE = config_path_for("plotvalloss")
DEFAULT_FILTERS = []
DEFAULT_METRIC = "val/loss"

# In-memory cache for fast subsequent queries
CACHED_DATA = {"runs": [], "output_dir": "", "filters": [], "metric": ""}

DEFAULT_OUTPUT_DIR = default_output_dir()


def _native(path) -> str:
    """``path`` with the OS's own separators and no padding; nothing usable gives ``""``."""
    text = "" if path is None else str(path).strip()
    return os.path.normpath(text) if text else ""


def scan_runs(output_dir: str, filters: list[str] = None, metric_key: str = "val/loss", progress_cb=None) -> list[dict]:
    """Scans ``output_dir`` for immediate subfolders matching all filters (if provided), extracting loss series."""
    output_dir = _native(output_dir) or default_output_dir()
    if not os.path.exists(output_dir):
        return []

    job_dates = get_job_dates_map(output_dir, fallback_db=aitk_db_path(resolve_aitk_root()))
    subdirs = [d for d in os.listdir(output_dir) if os.path.isdir(os.path.join(output_dir, d))]

    matching_dirs = []
    for d in subdirs:
        if filters:
            d_lower = d.lower()
            if all(f.lower() in d_lower for f in filters):
                matching_dirs.append(d)
        else:
            matching_dirs.append(d)

    matching_dirs.sort(key=natural_sort_key)
    runs = []
    tot = max(1, len(matching_dirs))

    for idx, folder_name in enumerate(matching_dirs, 1):
        if progress_cb:
            progress_cb(idx, tot, f"Reading loss_log.db from {folder_name}...")
        folder_path = os.path.join(output_dir, folder_name)
        db_path = metrics_db_for(output_dir, folder_name)
        if not db_path:
            continue

        try:
            steps, values, wall_times = load_series_from_db(db_path, metric_key=metric_key)
            if not steps:
                continue

            # Calculate relative elapsed hours from the first recorded wall_time
            valid_wall_times = [wt for wt in wall_times if wt is not None]
            first_time = valid_wall_times[0] if valid_wall_times else 0.0

            relative_hours = []
            for wt in wall_times:
                if wt is not None and first_time:
                    relative_hours.append(round((wt - first_time) / 3600.0, 4))
                else:
                    relative_hours.append(0.0)

            run_date = get_run_date(folder_path, folder_name, db_path, job_dates)
            max_val = max(values) if values else 0.0

            # Hide by default any plot that exceeds 1.0 (Option A)
            default_visible = bool(max_val <= 1.0)

            runs.append({
                "name": folder_name,
                "steps": steps,
                "values": values,
                "relative_hours": relative_hours,
                "run_date": run_date,
                "max_value": max_val,
                "default_visible": default_visible,
                "point_count": len(steps)
            })
        except Exception as e:
            print(f"Error reading {folder_name}: {e}")

    return runs


# --- Flask Routes ---
@app.route("/")
def index():
    return render_template("plot_val_loss.html")


make_config_routes(app, lambda: CONFIG_FILE, ("filter1", "filter2"), coerce=str)


@app.route("/api/data", methods=["GET", "POST"])
def api_data():
    force_refresh = request.args.get("refresh") == "1"
    output_dir = request.args.get("output_dir") or DEFAULT_OUTPUT_DIR
    metric = request.args.get("metric") or DEFAULT_METRIC
    filter_params = request.args.getlist("filter")
    filters = filter_params if filter_params else DEFAULT_FILTERS
    is_async = request.args.get("async") == "1"

    global CACHED_DATA

    if is_async:
        def _runner(cancel_event, progress_cb):
            runs = scan_runs(output_dir, filters=filters, metric_key=metric, progress_cb=progress_cb)
            CACHED_DATA["runs"] = runs
            CACHED_DATA["output_dir"] = output_dir
            CACHED_DATA["filters"] = filters
            CACHED_DATA["metric"] = metric
            progress_cb(status="Completed", current=len(runs), total=len(runs), ready=True, extra={"runs_count": len(runs)})

        return dispatch_worker_task(
            scan_worker,
            _runner,
            total=100,
            status_msg="Scanning validation loss logs...",
            api_success=api_success,
            api_error=api_error,
        )

    cache_matches = (
        CACHED_DATA.get("output_dir") == output_dir
        and CACHED_DATA.get("metric") == metric
        and list(CACHED_DATA.get("filters") or []) == list(filters)
    )
    if force_refresh or not CACHED_DATA.get("runs") or not cache_matches:
        runs = scan_runs(output_dir, filters=filters, metric_key=metric)
        CACHED_DATA = {
            "runs": runs,
            "output_dir": output_dir,
            "filters": filters,
            "metric": metric
        }

    return api_success(data={"runs": CACHED_DATA["runs"]})


register_progress_routes(
    app, scan_worker,
    progress_rule="/api/scan_progress", cancel_rule="/api/scan_cancel",
    cancel_message="Scan cancellation requested",
)


def main():
    global DEFAULT_OUTPUT_DIR, DEFAULT_FILTERS, DEFAULT_METRIC

    parser = argparse.ArgumentParser(description="Web validation loss viewer for AI-Toolkit.")
    parser.add_argument("--port", type=int, default=5006, help="Port to listen on (default: 5006)")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="AI-Toolkit output directory")
    parser.add_argument("--filters", nargs="*", default=DEFAULT_FILTERS, help="Folder filter keywords")
    parser.add_argument("--metric", default=DEFAULT_METRIC, help="Metric key to plot")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    DEFAULT_OUTPUT_DIR = args.output_dir
    DEFAULT_FILTERS = args.filters
    DEFAULT_METRIC = args.metric

    print("=" * 60)
    print(" AI-Toolkit Loss Explorer - Starting Web Server")
    print(f" Port       : {args.port}")
    print(f" Directory  : {DEFAULT_OUTPUT_DIR}")
    print(f" Filters    : {DEFAULT_FILTERS}")
    print(f" Metric     : {DEFAULT_METRIC}")
    print(f" URL        : http://127.0.0.1:{args.port}")
    print("=" * 60)

    # Start auto-shutdown monitor watchdog
    auto_shutdown_manager.start_watchdog()

    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
