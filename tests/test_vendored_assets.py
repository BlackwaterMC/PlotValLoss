"""The page loads Plotly from our own copy (static/vendor/), not from a third-party server.

Why: the chart then works with no internet, and no outside script runs inside a page served
by a local app. The copy is shipped exactly as downloaded; its checksum is recorded next to it
so an accidental edit or a bad checkout is noticed.
"""

import hashlib
import os
import re

from config_store import PROJECT_ROOT

STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
VENDOR_DIR = os.path.join(STATIC_DIR, "vendor")
PLOTLY = "plotly-2.27.0.min.js"

_SCRIPT_SRC = re.compile(r"""<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def test_page_loads_no_script_from_another_server():
    with open(os.path.join(TEMPLATES_DIR, "plot_val_loss.html"), encoding="utf-8") as f:
        sources = _SCRIPT_SRC.findall(f.read())
    external = [s for s in sources if re.match(r"(?:https?:)?//", s)]
    assert not external, f"page loads scripts from another server: {external}"


def test_page_loads_the_vendored_plotly():
    with open(os.path.join(TEMPLATES_DIR, "plot_val_loss.html"), encoding="utf-8") as f:
        assert f'src="/static/vendor/{PLOTLY}"' in f.read()


def test_vendored_plotly_matches_its_recorded_checksum():
    with open(os.path.join(VENDOR_DIR, PLOTLY + ".sha256"), encoding="utf-8") as f:
        recorded = f.read().split()[0].lower()
    with open(os.path.join(VENDOR_DIR, PLOTLY), "rb") as f:
        data = f.read()
    assert hashlib.sha256(data).hexdigest() == recorded, (
        f"{PLOTLY} differs from the checksum recorded in static/vendor/ -- was it edited, "
        f"or converted by git (check .gitattributes marks static/vendor/* as -text)?")


def test_the_app_serves_the_vendored_plotly_byte_for_byte():
    import plot_val_loss

    with open(os.path.join(VENDOR_DIR, PLOTLY), "rb") as f:
        on_disk = f.read()
    res = plot_val_loss.app.test_client().get(f"/static/vendor/{PLOTLY}")
    assert res.status_code == 200
    assert res.data == on_disk
    assert "javascript" in res.mimetype
    res.close()


def test_vendored_plotly_is_the_expected_version_and_licensed():
    with open(os.path.join(VENDOR_DIR, PLOTLY), "rb") as f:
        header = f.read(400).decode("utf-8", "replace")
    assert "plotly.js v2.27.0" in header
    assert "MIT" in header
