# PlotValLoss

A small local web app that plots validation-loss curves from [AI-Toolkit](https://github.com/ostris/ai-toolkit)
training runs, so you can compare how runs converge. It reads each run's `loss_log.db` (read-only) and
draws them with Plotly.

- Step or relative-time x-axis, smoothing, linear/log y-axis, search, two filter dropdowns.
- Runs whose loss goes above 1.0 are hidden by default (one click shows them).
- Run dates come from AI-Toolkit's `aitk_db.db` when it can be found.
- The app exits by itself when you close the browser tab.

Originally part of ImageTools; moved here as its own project.

## Install

```
Install.bat
```

This creates the git-ignored `venv` folder, installs `requirements.txt` into it, and asks where AI-Toolkit
lives (saved to `plotvalloss_config.json`). It is safe to re-run: it detects and repairs a partial or broken
install. Manual equivalent:

```
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

```
PlotValLoss.bat
```

This starts the server on <http://127.0.0.1:5006> and opens your browser. Options (pass them to the `.bat`
or to `python plot_val_loss.py`):

| Option | Meaning |
|--------|---------|
| `--port N` | Port to listen on (default 5006) |
| `--output-dir PATH` | AI-Toolkit `output` folder (one sub-folder per run) |
| `--filters a b` | Only show runs whose folder name contains every word |
| `--metric KEY` | Metric to plot (default `val/loss`) |

## Telling it where AI-Toolkit is

The `output` folder is found in this order:

1. `--output-dir`
2. `AITK_ROOT` environment variable, then `<AITK_ROOT>\output`
3. `"aitk_root"` in `plotvalloss_config.json` (in this folder), then `<aitk_root>\output`

`plotvalloss_config.json` is created when you pick filters in the page; add `"aitk_root"` by hand if you
want to set the location there. It is git-ignored.

## Tests

```
python -m pytest
```
