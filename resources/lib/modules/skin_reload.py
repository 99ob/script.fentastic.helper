# -*- coding: utf-8 -*-
"""Signal a skin reload; only the persistent widget worker executes it.

The monotonically increasing request token coalesces rapid edits without a
shared thread or SQLite write. This module never calls ReloadSkin() itself.
"""
import time
import xbmcgui

RELOAD_REQUEST_PROPERTY = "fentastic.skin_reload.request_ns"


def request_skin_reload(reason="widget configuration"):
    """Request one deferred reload; safe from short-lived Kodi Python scripts."""
    # Window(10000) properties are shared between Kodi Python invocations.
    xbmcgui.Window(10000).setProperty(RELOAD_REQUEST_PROPERTY, str(time.monotonic_ns()))
