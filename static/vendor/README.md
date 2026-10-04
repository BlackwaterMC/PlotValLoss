# Vendored third-party files

Files here are shipped exactly as downloaded, so the app works without internet.
`.gitattributes` marks this folder `-text` so git never changes their bytes.

## plotly-2.27.0.min.js

- What: plotly.js v2.27.0 (the charting library). MIT license (see the header inside the file).
- Source: https://cdn.plot.ly/plotly-2.27.0.min.js
- Size: 3,598,158 bytes
- SHA-256: `7f4930eba8f8541dbec28dca5bd5f787f8eef1cde0369ac9657b70bed230b3e0`
  (also in `plotly-2.27.0.min.js.sha256`; `tests/test_vendored_assets.py` checks it)

### Upgrading
1. Download the new version from https://cdn.plot.ly/plotly-<version>.min.js into this folder.
2. Add its `.sha256` file and a section above; update the `<script src="/static/vendor/...">`
   tag in `templates/plot_val_loss.html` and the file names in `tests/test_vendored_assets.py`.
3. Delete the old file (git keeps it in history) and re-run the tests.
