"""The page, its scripts and the server agree with each other.

* every ``/api/...`` URL the JavaScript calls exists as a route on the server (a renamed
  route would otherwise only be noticed by clicking the broken button);
* the page renders and every ``/static/...`` file it references exists;
* every element id the shared scripts look up exists in the page.
"""

import os
import re

import pytest

import plot_val_loss
from config_store import PROJECT_ROOT

FRONTEND_FILES = ["static/plot_val_loss.js", "static/shared.js", "templates/plot_val_loss.html"]

_URL = re.compile(r"""['"`](/api/[^'"`\n?#]*)""")


def _read(rel):
    with open(os.path.join(PROJECT_ROOT, *rel.split("/")), encoding="utf-8") as f:
        return f.read()


def _routes():
    return {rule.rule for rule in plot_val_loss.app.url_map.iter_rules()}


@pytest.mark.parametrize("rel", FRONTEND_FILES)
def test_every_api_url_in_the_frontend_is_a_real_route(rel):
    routes = _routes()
    urls = set(_URL.findall(_read(rel)))
    missing = sorted(u for u in urls if u not in routes)
    assert not missing, f"{rel} calls URLs with no route: {missing}"


def test_frontend_actually_calls_some_api_urls():
    # Guards the regex above: if it stopped matching, the test above would pass vacuously.
    assert "/api/data" in _read("static/plot_val_loss.js")
    assert len(_URL.findall(_read("static/plot_val_loss.js"))) >= 4


def test_index_renders_and_its_static_files_exist():
    plot_val_loss.app.config["TESTING"] = True
    res = plot_val_loss.app.test_client().get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Validation Loss Explorer" in html
    refs = re.findall(r"""(?:src|href)=["'](/static/[^"']+)["']""", html)
    assert "/static/shared.js" in refs and "/static/plot_val_loss.js" in refs
    for ref in refs:
        assert os.path.isfile(os.path.join(PROJECT_ROOT, *ref.lstrip("/").split("/"))), ref


def test_progress_overlay_element_ids_exist_in_the_page():
    html = _read("templates/plot_val_loss.html")
    js = _read("static/plot_val_loss.js")
    block = re.search(r"new ProgressOverlayController\(\{(.*?)\}\)", js, re.S).group(1)
    ids = re.findall(r"""\w+Id:\s*['"]([^'"]+)['"]""", block)
    assert len(ids) == 7
    for element_id in ids:
        assert f'id="{element_id}"' in html, element_id


def test_shared_js_defines_what_the_page_script_uses():
    shared = _read("static/shared.js")
    assert "class ProgressOverlayController" in shared
    assert "function initAutoShutdown" in shared
