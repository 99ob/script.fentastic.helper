# -*- coding: utf-8 -*-
"""Coordinate FENtastic menu/layout reloads without the widget cache.

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
    Search (windows 1121 and 11121) never causes a skin reload here.
    """
    def __init__(self, monitor):
        self.monitor = monitor
        self.home = xbmcgui.Window(10000)
        self.last_reload = 0.0
        self.last_seen = self.home.getProperty(RELOAD_REQUEST_PROPERTY)


    def _recover_missing_menus(self):
        """Restore *missing* generated menu includes after skin reinstall.

        This checks just the five generated menu files, not widget snapshots.
        Existing menu files and configured paths are never overwritten here.
        """
        import xbmcvfs
        from modules.cpath_maker import CPaths
        for kind, suffix in (("movie", "movies"), ("tvshow", "tvshows"),
                             ("custom1", "custom1"), ("custom2", "custom2"),
                             ("custom3", "custom3")):
            if self.monitor.abortRequested() or xbmc.getSkinDir() != 'skin.fentastic':
                return
            filename = 'special://skin/xml/script-fentastic-main_menu_%s.xml' % suffix
            if xbmcvfs.exists(filename):
                continue
            maker = None
            try:
                key = kind + '.main_menu'
                maker = CPaths(key)
                saved = maker.fetch_current_cpaths()
                maker.refresh_cpaths = True
                if saved and key in saved and saved[key].get('cpath_path'):
                    maker.make_main_menu_xml(saved)
                else:
                    maker.make_default_xml()
                xbmc.log('FENtastic: recovered missing %s menu XML' % suffix,
                         xbmc.LOGINFO)
            except Exception as exc:
                xbmc.log('FENtastic menu recovery failed (%s): %s' %
                         (suffix, type(exc).__name__), xbmc.LOGWARNING)
            finally:
                if maker is not None:
                    try:
                        maker.dbcon.close()
                    except Exception:
                        pass

    def run(self):
        last_menu_check = 0.0
        while not self.monitor.abortRequested():
            if xbmc.getSkinDir() != "skin.fentastic":
                if self.monitor.waitForAbort(1.0):
                    return
                continue
            if time.monotonic() - last_menu_check >= 30.0:
                last_menu_check = time.monotonic()
                self._recover_missing_menus()
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
            if xbmcgui.getCurrentWindowId() in (10035, 1121, 11121):
                if self.monitor.waitForAbort(0.25):
                    return
                continue
            self.last_seen = token
            self.last_reload = now
            xbmc.log("FENtastic: coordinated widget/menu reload (3s guard)", xbmc.LOGINFO)
            xbmc.executebuiltin("ReloadSkin()")
            if self.monitor.waitForAbort(0.5):
                return
