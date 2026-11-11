# -*- coding: utf-8 -*-
"""Coordinate FENtastic menu/layout reloads without the widget cache.

The monotonically increasing request token coalesces rapid edits without a
shared thread or SQLite write. This module never calls ReloadSkin() itself.
"""
import time
import xbmcgui
import xbmc


RELOAD_REQUEST_PROPERTY = "fentastic.skin_reload.request_ns"
WIDGET_XML_SCHEMA = "FENTASTIC_CHARCOAL_LIVE_XML_SCHEMA_V2"


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


    @staticmethod
    def _xml_is_current(filename, include_name, path_type):
        """Read-only schema/structure test; never touches the selected media."""
        import xml.etree.ElementTree as ET
        import xbmcvfs

        if not xbmcvfs.exists(filename):
            return False
        try:
            with xbmcvfs.File(filename, "r") as source:
                contents = source.read()
            root = ET.fromstring(contents)
            if root.tag != "includes":
                return False
            names = {element.get("name") for element in root.findall("include")}
            if include_name not in names:
                return False
            if path_type == "widget":
                if WIDGET_XML_SCHEMA not in contents:
                    return False
                if "FentasticCharcoalPanels" + include_name not in names:
                    return False
                variables = {element.get("name") for element in root.findall("variable")}
                if "FentasticCharcoalFanart" + include_name not in variables:
                    return False
            return True
        except (OSError, IOError, ValueError, ET.ParseError, TypeError):
            return False

    def _recover_missing_cpaths(self):
        """Reconcile missing/stale skin includes from the existing saved paths.

        Rebuilding is independent of selected movie, widget focus, or Up/Down.
        Existing compatible XML is read only and never rewritten. A skin ZIP
        can remove generated includes, or leave an old schema after upgrading.
        All needed sections are recreated before requesting ONE skin reload.
        """
        from modules.cpath_maker import CPaths, _SECTION_INFO

        rebuilt = 0
        for kind, (suffix, widget_include, menu_include, _) in _SECTION_INFO.items():
            for path_type in ("widget", "main_menu"):
                if self.monitor.abortRequested() or xbmc.getSkinDir() != "skin.fentastic":
                    return
                filename = ("special://skin/xml/script-fentastic-%s_%s.xml" %
                            (path_type, suffix))
                include_name = widget_include if path_type == "widget" else menu_include
                if self._xml_is_current(filename, include_name, path_type):
                    continue
                maker = None
                try:
                    key = "%s.%s" % (kind, path_type)
                    maker = CPaths(key)
                    saved = maker.fetch_current_cpaths()
                    maker.refresh_cpaths = True
                    if path_type == "widget" and saved:
                        maker.make_widget_xml(saved, reload_skin=False)
                    elif (path_type == "main_menu" and key in saved and
                          saved[key].get("cpath_path")):
                        maker.make_main_menu_xml(saved, reload_skin=False)
                    else:
                        # Empty *include declarations* for unconfigured sections;
                        # never substitute movie metadata, fanart, or ratings.
                        maker.make_default_xml(reload_skin=False)
                    if not self._xml_is_current(filename, include_name, path_type):
                        raise RuntimeError("Generated XML still invalid or outdated")
                    rebuilt += 1
                    xbmc.log("FENtastic: rebuilt %s %s generated XML" %
                             (suffix, path_type), xbmc.LOGINFO)
                except Exception as exc:
                    xbmc.log("FENtastic XML recovery failed (%s/%s): %s: %s" %
                             (suffix, path_type, type(exc).__name__, str(exc)),
                             xbmc.LOGWARNING)
                finally:
                    if maker is not None:
                        try:
                            maker.dbcon.close()
                        except Exception:
                            pass
        if rebuilt:
            xbmc.log("FENtastic: %s generated includes ready; requesting one reload" %
                     rebuilt, xbmc.LOGINFO)
            request_skin_reload("repaired generated charcoal/widget XML")

    def run(self):
        last_cpath_check = 0.0
        while not self.monitor.abortRequested():
            if xbmc.getSkinDir() != "skin.fentastic":
                if self.monitor.waitForAbort(1.0):
                    return
                continue
            # Reconcile only while Home is active. A reinstall can remove its
            # generated files even if the widget IDs and settings never change.
            # Three-second read-only checks are NOT tied to focus navigation.
            if (xbmcgui.getCurrentWindowId() == 10000 and
                    time.monotonic() - last_cpath_check >= 3.0):
                last_cpath_check = time.monotonic()
                self._recover_missing_cpaths()
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
