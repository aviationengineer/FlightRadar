"""Google Analytics (GA4) — tiny, import-safe, off-by-default helper.

How it works
------------
* The Measurement ID is read from Streamlit secrets (``GA_MEASUREMENT_ID``)
  first, falling back to the ``GA_MEASUREMENT_ID`` constant in the app's
  config (``""`` by default — see ``GA_MEASUREMENT_ID`` below). With no ID
  configured the helper does nothing: no script is injected, nothing is
  tracked, and the app behaves exactly as before.
* When an ID is configured, a GA4 ``gtag.js`` loader is injected once per
  session via ``streamlit.components.v1.html`` (height 0). The loader
  installs ``gtag`` on the parent window (the component iframe is
  same-origin on Streamlit Cloud) so the hit is recorded against the app
  URL rather than the iframe URL; if the parent is not reachable it falls
  back to loading inside the iframe.
* The loader's ``gtag('config', ...)`` sends a ``page_view`` on app load.
  When the page changes, ``inject_analytics`` sends a ``page_navigation``
  event with the page name as the ``page_name`` parameter.

Privacy
-------
No personal data is sent: no user IDs, no custom dimensions, no PII of any
kind. Only the page name (a dashboard page label) is sent as an event
parameter. GA4 anonymises IP addresses by default.

Import safety
--------------
Importing this module never requires a running Streamlit app: the
``streamlit`` import is guarded, and all Streamlit calls happen inside
``inject_analytics`` behind try/except. Unit tests can therefore import
and exercise the pure helpers (ID validation, snippet building) without
Streamlit at all.
"""

from __future__ import annotations

import json
import re

try:
    import streamlit as st
except Exception:  # pragma: no cover - streamlit unavailable in tests
    st = None  # type: ignore[assignment]

# Fallback Measurement ID when Streamlit secrets carry none. Keep empty:
# the real ID is set in Streamlit Cloud secrets (GA_MEASUREMENT_ID), never
# committed to the repo. The app's config constant (if the app has one)
# takes precedence over this module constant — see resolve_measurement_id.
GA_MEASUREMENT_ID = ""

_ID_RE = re.compile(r"^G-[A-Za-z0-9]{4,}$")

_SESSION_LOADED_KEY = "_ga4_loaded"
_SESSION_LAST_PAGE_KEY = "_ga4_last_page"

_LOADER_TEMPLATE = """<script>
(function () {
  var id = __MEASUREMENT_ID__;
  var targetWin, targetDoc;
  try {
    targetWin = window.parent;
    targetDoc = window.parent.document;
    void targetDoc.head;  // throws if the parent is not same-origin
  } catch (e) {
    targetWin = window;
    targetDoc = document;
  }
  targetWin.dataLayer = targetWin.dataLayer || [];
  targetWin.gtag = targetWin.gtag || function () {
    targetWin.dataLayer.push(arguments);
  };
  var s = targetDoc.createElement('script');
  s.async = true;
  s.src = 'https://www.googletagmanager.com/gtag/js?id=' + id;
  targetDoc.head.appendChild(s);
  targetWin.gtag('js', new Date());
  targetWin.gtag('config', id);
})();
</script>"""

_EVENT_TEMPLATE = """<script>
(function () {
  var targetWin;
  try {
    targetWin = window.parent;
    void targetWin.document.head;  // throws if not same-origin
  } catch (e) {
    targetWin = window;
  }
  if (targetWin.gtag) {
    targetWin.gtag('event', __EVENT_NAME__, __PARAMS__);
  }
})();
</script>"""


def is_valid_measurement_id(value) -> bool:
    """True for a plausible GA4 Measurement ID (G- + 4 or more letters/digits)."""
    return isinstance(value, str) and bool(_ID_RE.match(value.strip()))


def resolve_measurement_id(config_default: str = "") -> str:
    """Resolve the Measurement ID: Streamlit secrets first, then the config
    constant, then this module's ``GA_MEASUREMENT_ID``. Returns "" when
    nothing valid is configured (tracking stays off). An invalid value in
    an earlier source falls through to the next one."""
    candidates: list = []
    if st is not None:
        try:
            candidates.append(st.secrets.get("GA_MEASUREMENT_ID"))
        except Exception:
            pass  # no secrets file / secrets unavailable: fall through
    candidates.append(config_default)
    candidates.append(GA_MEASUREMENT_ID)
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            candidate = candidate.strip()
            if is_valid_measurement_id(candidate):
                return candidate
    return ""


def loader_snippet(measurement_id: str) -> str:
    """HTML that installs gtag and sends the load page_view.

    Returns "" when the ID is invalid, so callers can treat an empty
    snippet as 'do not inject'.
    """
    if not is_valid_measurement_id(measurement_id):
        return ""
    return _LOADER_TEMPLATE.replace(
        "__MEASUREMENT_ID__", json.dumps(measurement_id.strip()))


def event_snippet(measurement_id: str, event_name: str,
                  params: dict | None = None) -> str:
    """HTML that fires one gtag event on the parent window.

    Returns "" when the ID is invalid.
    """
    if not is_valid_measurement_id(measurement_id):
        return ""
    return (_EVENT_TEMPLATE
            .replace("__EVENT_NAME__", json.dumps(event_name))
            .replace("__PARAMS__", json.dumps(params or {})))


def _get_components_html():
    """Import the Streamlit HTML component lazily (keeps module import safe)."""
    from streamlit.components.v1 import html
    return html


def inject_analytics(config_default: str = "",
                     page_name: str | None = None) -> bool:
    """Inject GA4 once per session; fire a navigation event on page change.

    ``config_default`` is the app's ``GA_MEASUREMENT_ID`` config constant
    ("" when the app has none); Streamlit secrets take precedence over it.
    ``page_name`` is the current page label: on the first call it is
    remembered without an extra event (the loader's ``gtag('config')``
    already sends the load page_view); on later calls with a different
    page it fires a ``page_navigation`` event with that page name.

    Returns True when tracking is active (an ID is configured), False when
    tracking is off (no ID) or Streamlit is not running.
    """
    measurement_id = resolve_measurement_id(config_default)
    if not measurement_id:
        return False
    if st is None:
        return False
    try:
        session = st.session_state
    except Exception:
        return False
    try:
        html = _get_components_html()
    except Exception:
        return False
    try:
        if not session.get(_SESSION_LOADED_KEY):
            html(loader_snippet(measurement_id), height=0)
            session[_SESSION_LOADED_KEY] = True
            if page_name is not None:
                session[_SESSION_LAST_PAGE_KEY] = page_name
            return True
        last_page = session.get(_SESSION_LAST_PAGE_KEY)
        if (page_name is not None and last_page is not None
                and page_name != last_page):
            html(event_snippet(measurement_id, "page_navigation",
                               {"page_name": page_name}), height=0)
        if page_name is not None:
            session[_SESSION_LAST_PAGE_KEY] = page_name
        return True
    except Exception:
        return False
