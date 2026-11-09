# -*- coding: utf-8 -*-
"""FENtastic search controls with per-row refresh (no ReloadSkin)."""

import sqlite3 as database
import time
from urllib.parse import quote

import xbmc
import xbmcgui
import xbmcvfs

settings_path = xbmcvfs.translatePath(
    "special://profile/addon_data/script.fentastic.helper/")
spath_database_path = xbmcvfs.translatePath(
    "special://profile/addon_data/script.fentastic.helper/spath_cache.db")

# The Home window stays alive across the search window. Kodi watches these
# properties through the content URLs to refresh changed lists independently.
_HOME = 10000
_SEARCH_WINDOWS = (1121, 11121)
_RESULTS_REVISION = "fentastic.search.results_revision"
_HISTORY_REVISION = "fentastic.search.history_revision"
_STACKED_TRAKT_IDS = (27017, 27018, 27019)


class SPaths:
    def __init__(self, spaths=None):
        self.connect_database()
        self.spaths = spaths if spaths is not None else []

    def connect_database(self):
        if not xbmcvfs.exists(settings_path):
            xbmcvfs.mkdir(settings_path)
        self.dbcon = database.connect(spath_database_path, timeout=20)
        self.dbcon.execute(
            "CREATE TABLE IF NOT EXISTS spath ("
            "spath_id INTEGER PRIMARY KEY AUTOINCREMENT, spath text)")
        self.dbcur = self.dbcon.cursor()

    @staticmethod
    def _refresh(results=False, history=False):
        """Publish new URLs after all related settings/DB writes are complete."""
        home = xbmcgui.Window(_HOME)
        revision = str(time.monotonic_ns())
        if results:
            home.setProperty(_RESULTS_REVISION, revision)
        if history:
            home.setProperty(_HISTORY_REVISION, revision)

    @staticmethod
    def _clear_trakt_children():
        """Avoid showing the previous query's stacked Trakt list."""
        # Do not probe inactive/nonexistent windows. Kodi logs an EXCEPTION
        # even if xbmcgui.Window() raises a catchable Python error.
        window_id = xbmcgui.getCurrentWindowId()
        if window_id not in _SEARCH_WINDOWS:
            return
        try:
            window = xbmcgui.Window(window_id)
        except (RuntimeError, ValueError):
            return
        for list_id in _STACKED_TRAKT_IDS:
            window.clearProperty("fentastic.%s.path" % list_id)
            window.clearProperty("fentastic.%s.label" % list_id)

    def add_spath_to_database(self, spath):
        self.dbcur.execute("INSERT INTO spath (spath) VALUES (?)", (spath,))
        self.dbcon.commit()

    def remove_spath_from_database(self, spath_id):
        self.dbcur.execute("DELETE FROM spath WHERE spath_id = ?", (spath_id,))
        self.dbcon.commit()

    def is_database_empty(self):
        return self.dbcur.execute("SELECT COUNT(*) FROM spath").fetchone()[0] == 0

    def remove_all_spaths(self):
        if not xbmcgui.Dialog().yesno("FENtastic", "Are you sure you want to clear "
                                     "all search history? Once cleared, these "
                                     "items cannot be recovered. Proceed?"):
            return
        self.dbcur.execute("DELETE FROM spath")
        self.dbcur.execute("DELETE FROM sqlite_sequence WHERE name='spath'")
        self.dbcon.commit()
        xbmcgui.Window(_HOME).setProperty("fentastic.search.query_ready", "0")
        xbmc.executebuiltin("Skin.Reset(SearchInput)")
        xbmc.executebuiltin("Skin.Reset(SearchInputEncoded)")
        xbmc.executebuiltin("Skin.SetString(SearchInputTraktEncoded,none)")
        xbmc.executebuiltin("Skin.SetString(DatabaseStatus,Empty)")
        self._clear_trakt_children()
        self._refresh(results=True, history=True)
        if xbmcgui.getCurrentWindowId() in _SEARCH_WINDOWS:
            xbmc.executebuiltin("SetFocus(27400)")

    def fetch_all_spaths(self):
        return self.dbcur.execute(
            "SELECT * FROM spath ORDER BY spath_id DESC").fetchall()

    def check_spath_exists(self, spath):
        row = self.dbcur.execute(
            "SELECT spath_id FROM spath WHERE spath = ?", (spath,)).fetchone()
        return row[0] if row else None

    def _ensure_provider(self):
        order = (("2", "plugin.video.umbrella"), ("3", "plugin.video.pov"))
        current = xbmc.getInfoLabel("Skin.String(current_search_provider)")
        if any(pid == current and xbmc.getCondVisibility(
                "System.AddonIsEnabled(%s)" % addon) for pid, addon in order):
            return
        for pid, addon in order:
            if xbmc.getCondVisibility("System.AddonIsEnabled(%s)" % addon):
                xbmc.executebuiltin("Skin.SetString(current_search_provider,%s)" % pid)
                return
        xbmc.log("FENtastic search: no enabled search provider", xbmc.LOGWARNING)

    def toggle_search_provider(self):
        order = (("2", "plugin.video.umbrella"), ("3", "plugin.video.pov"))
        active = xbmc.getInfoLabel("Skin.String(current_search_provider)")
        ids = [pid for pid, _ in order]
        start = ids.index(active) if active in ids else -1
        for step in range(1, len(order) + 1):
            pid, addon = order[(start + step) % len(order)]
            if not xbmc.getCondVisibility("System.AddonIsEnabled(%s)" % addon):
                continue
            if pid != active:
                xbmc.executebuiltin("Skin.SetString(current_search_provider,%s)" % pid)
                self._clear_trakt_children()
                self._refresh(results=True)
                xbmc.executebuiltin("ReloadSkin()")
            return
        xbmcgui.Dialog().notification("FENtastic", "No enabled search providers")

    def re_search_id(self, spath_id):
        if not str(spath_id).isdigit():
            return
        row = self.dbcur.execute(
            "SELECT spath FROM spath WHERE spath_id = ?", (int(spath_id),)
        ).fetchone()
        if row:
            self.search_input(row[0])

    def open_search_window(self):
        self._ensure_provider()
        empty = self.is_database_empty()
        if empty:
            xbmc.executebuiltin("Skin.SetString(DatabaseStatus,Empty)")
        else:
            xbmc.executebuiltin("Skin.Reset(DatabaseStatus)")
        xbmc.executebuiltin("Skin.Reset(SearchInput)")
        # FENTASTIC_QUERY_READY_GUARD_V3
        xbmcgui.Window(_HOME).setProperty("fentastic.search.query_ready", "0")
        xbmc.executebuiltin("Skin.Reset(SearchInputEncoded)")
        xbmc.executebuiltin("Skin.SetString(SearchInputTraktEncoded,none)")
        self._clear_trakt_children()
        self._refresh(results=True, history=True)
        if xbmcgui.getCurrentWindowId() == _HOME:
            xbmc.executebuiltin("ActivateWindow(1121)")
            xbmc.sleep(200)
            self._clear_trakt_children()
        xbmc.executebuiltin("SetFocus(%s)" % (27400 if empty else 803))

    def search_input(self, search_term=None):
        if search_term is None or not search_term.strip():
            prompt = "Search" if xbmcgui.getCurrentWindowId() == _HOME else "New Search"
            keyboard = xbmc.Keyboard("", prompt, False)
            keyboard.doModal()
            if not keyboard.isConfirmed():
                return
            search_term = keyboard.getText()
        if not search_term or not search_term.strip():
            return

        self._ensure_provider()
        encoded = quote(search_term, safe="")
        existing_id = self.check_spath_exists(search_term)
        if existing_id:
            self.remove_spath_from_database(existing_id)
        self.add_spath_to_database(search_term)
        xbmc.executebuiltin("Skin.Reset(DatabaseStatus)")
        xbmc.executebuiltin("Skin.SetString(SearchInputEncoded,%s)" % encoded)
        xbmc.executebuiltin("Skin.SetString(SearchInputTraktEncoded,%s)" % encoded)
        xbmc.executebuiltin("Skin.SetString(SearchInput,%s)" % search_term)
        xbmcgui.Window(_HOME).setProperty("fentastic.search.query_ready", "1")
        self._clear_trakt_children()
        self._refresh(results=True, history=True)
        if xbmcgui.getCurrentWindowId() == _HOME:
            xbmc.executebuiltin("ActivateWindow(1121)")
            xbmc.sleep(200)
            self._clear_trakt_children()
        xbmc.executebuiltin("SetFocus(2000)")
        # FENtastic experimental search refresh: no full ReloadSkin on query

    def re_search(self):
        self.search_input(xbmc.getInfoLabel("ListItem.Label"))
