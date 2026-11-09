# -*- coding: utf-8 -*-
"""Signal a skin reload; only the persistent widget worker executes it.

The monotonically increasing request token coalesces rapid edits without a
shared thread or SQLite write. This module never calls ReloadSkin() itself.
"""
import time
import xbmcgui
import xbmc


RELOAD_REQUEST_PROPERTY = "fentastic.skin_reload.request_ns"


def request_skin_reload(reason="widget configuration"):
    """Request one deferred reload; safe from short-lived Kodi Python scripts."""
    # Window(10000) properties are shared between Kodi Python invocations.
    xbmcgui.Window(10000).setProperty(RELOAD_REQUEST_PROPERTY, str(time.monotonic_ns()))

# FENTASTIC_DIRECT_WIDGETS_RELOAD_GUARD_V1


class SkinReloadWorker:
    """Reload coordinator independent of the removed persistent widget cache.

    A minimum three-second interval applies to reloads initiated by FENtastic.
    Requests are coalesced: there is no backlog of delayed reloads.
    Search (window 1121) never causes a skin reload here.
    """
    def __init__(self, monitor):
        self.monitor = monitor
        self.home = xbmcgui.Window(10000)
        self.last_reload = 0.0
        self.last_seen = self.home.getProperty(RELOAD_REQUEST_PROPERTY)

    def run(self):
        while not self.monitor.abortRequested():
            if xbmc.getSkinDir() != "skin.fentastic":
                if self.monitor.waitForAbort(1.0):
                    return
                continue
            token = self.home.getProperty(RELOAD_REQUEST_PROPERTY)
            if not token or token == self.last_seen:
                if self.monitor.waitForAbort(0.25):
                    return
                continue
            now = time.monotonic()
            try:
                age = (time.monotonic_ns() - int(token)) / 1e9
            except (ValueError, TypeError):
                age = 0.0
            # Batch rapid edits into one reload; never reload during dialogs
            # or the search view. Once it is safe the last request wins.
            if age < 1.0 or now - self.last_reload < 3.0:
                if self.monitor.waitForAbort(0.25):
                    return
                continue
            if xbmcgui.getCurrentWindowId() in (10035, 1121):
                if self.monitor.waitForAbort(0.25):
                    return
                continue
            self.last_seen = token
            self.last_reload = now
            xbmc.log("FENtastic: coordinated widget/menu reload (3s guard)", xbmc.LOGINFO)
            xbmc.executebuiltin("ReloadSkin()")
            if self.monitor.waitForAbort(0.5):
                return
