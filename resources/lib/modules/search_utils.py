# -*- coding: utf-8 -*-
"""Search settings and live search-history updates without ReloadSkin()."""
import sqlite3 as database
import time
from urllib.parse import quote

import xbmc
import xbmcgui
import xbmcvfs

SETTINGS_PATH = xbmcvfs.translatePath("special://profile/addon_data/script.fentastic.helper/")
DATABASE_PATH = xbmcvfs.translatePath(
    "special://profile/addon_data/script.fentastic.helper/spath_cache.db")
HOME = xbmcgui.Window(10000)
# Keep previous skin-provider switch order; only visit installed/enabled providers.
PROVIDERS = (("0", "plugin.video.fen"), ("1", "plugin.video.fenlight"),
             ("3", "plugin.video.pov"), ("2", "plugin.video.umbrella"),
             ("4", "plugin.video.seren"))


def enabled(addon_id):
    return xbmc.getCondVisibility("System.AddonIsEnabled(%s)" % addon_id)


def publish_history_revision():
    HOME.setProperty("fentastic.search.history_rev", str(time.monotonic_ns()))


def publish_query_revision():
    HOME.setProperty("fentastic.search.query_rev", str(time.monotonic_ns()))


class SPaths:
    def __init__(self, spaths=None):
        self.spaths = spaths or []
        self.refresh_spaths = False
        self.connect_database()

    def connect_database(self):
        if not xbmcvfs.exists(SETTINGS_PATH):
            xbmcvfs.mkdir(SETTINGS_PATH)
        self.dbcon = database.connect(DATABASE_PATH, timeout=20)
        self.dbcon.execute("CREATE TABLE IF NOT EXISTS spath ("
                           "spath_id INTEGER PRIMARY KEY AUTOINCREMENT, spath text)")
        self.dbcur = self.dbcon.cursor()

    def add_spath_to_database(self, spath):
        self.dbcur.execute("INSERT INTO spath (spath) VALUES (?)", (spath,))
        self.dbcon.commit()
        publish_history_revision()

    def remove_spath_from_database(self, spath_id):
        self.dbcur.execute("DELETE FROM spath WHERE spath_id = ?", (spath_id,))
        self.dbcon.commit()
        publish_history_revision()

    def is_database_empty(self):
        return self.dbcur.execute("SELECT COUNT(*) FROM spath").fetchone()[0] == 0

    def fetch_all_spaths(self):
        return self.dbcur.execute(
            "SELECT * FROM spath ORDER BY spath_id DESC").fetchall()

    def check_spath_exists(self, spath):
        result = self.dbcur.execute(
            "SELECT spath_id FROM spath WHERE spath = ?", (spath,)).fetchone()
        return result[0] if result else None

    def _ensure_provider(self):
        chosen = xbmc.getInfoLabel("Skin.String(current_search_provider)")
        if any(pid == chosen and enabled(addon) for pid, addon in PROVIDERS):
            return
        # POV is the preferred fallback on this fork; otherwise use any installed provider.
        for pid, addon in sorted(PROVIDERS, key=lambda row: row[0] != "3"):
            if enabled(addon):
                xbmc.executebuiltin("Skin.SetString(current_search_provider,%s)" % pid)
                publish_query_revision()
                return
        xbmc.log("FENtastic search: no enabled search providers", xbmc.LOGWARNING)

    def toggle_search_provider(self):
        current = xbmc.getInfoLabel("Skin.String(current_search_provider)")
        ids = [item[0] for item in PROVIDERS]
        start = ids.index(current) if current in ids else -1
        for step in range(1, len(PROVIDERS) + 1):
            pid, addon = PROVIDERS[(start + step) % len(PROVIDERS)]
            if enabled(addon):
                xbmc.executebuiltin("Skin.SetString(current_search_provider,%s)" % pid)
                publish_query_revision()
                return
        xbmcgui.Dialog().notification("FENtastic", "No enabled search providers")

    def remove_all_spaths(self):
        if not xbmcgui.Dialog().yesno("FENtastic",
                "Are you sure you want to clear all search history? "
                "Once cleared, these items cannot be recovered. Proceed?"):
            return
        self.dbcur.execute("DELETE FROM spath")
        self.dbcur.execute("DELETE FROM sqlite_sequence WHERE name='spath'")
        self.dbcon.commit()
        xbmc.executebuiltin("Skin.SetString(SearchInput,)")
        xbmc.executebuiltin("Skin.SetString(SearchInputEncoded,)")
        xbmc.executebuiltin("Skin.SetString(SearchInputTraktEncoded,none)")
        xbmc.executebuiltin("Skin.SetString(DatabaseStatus,Empty)")
        publish_query_revision()
        publish_history_revision()
        if xbmcgui.getCurrentWindowId() == 1121:
            xbmc.executebuiltin("SetFocus(27400)")

    def open_search_window(self):
        self._ensure_provider()
        empty = self.is_database_empty()
        if empty:
            xbmc.executebuiltin("Skin.SetString(DatabaseStatus,Empty)")
            focus_id = 27400
        else:
            xbmc.executebuiltin("Skin.Reset(DatabaseStatus)")
            focus_id = 803
        for key in ("SearchInput", "SearchInputEncoded"):
            xbmc.executebuiltin("Skin.Reset(%s)" % key)
        xbmc.executebuiltin("Skin.SetString(SearchInputTraktEncoded,none)")
        publish_query_revision()
        publish_history_revision()
        if xbmcgui.getCurrentWindowId() == 10000:
            xbmc.executebuiltin("ActivateWindow(1121)")
            xbmc.sleep(200)
        xbmc.executebuiltin("SetFocus(%s)" % focus_id)

    def search_input(self, search_term=None):
        if search_term is None or not search_term.strip():
            prompt = "Search" if xbmcgui.getCurrentWindowId() == 10000 else "New Search"
            keyboard = xbmc.Keyboard("", prompt, False)
            keyboard.doModal()
            if not keyboard.isConfirmed():
                return
            search_term = keyboard.getText()
        if not search_term or not search_term.strip():
            return
        self._ensure_provider()
        prior = self.check_spath_exists(search_term)
        if prior:
            self.dbcur.execute("DELETE FROM spath WHERE spath_id = ?", (prior,))
        self.dbcur.execute("INSERT INTO spath (spath) VALUES (?)", (search_term,))
        self.dbcon.commit()
        encoded = quote(search_term)
        xbmc.executebuiltin("Skin.Reset(DatabaseStatus)")
        xbmc.executebuiltin("Skin.SetString(SearchInputEncoded,%s)" % encoded)
        xbmc.executebuiltin("Skin.SetString(SearchInputTraktEncoded,%s)" % encoded)
        # Query string LAST, followed by unique URL revisions. No full skin reload.
        xbmc.executebuiltin("Skin.SetString(SearchInput,%s)" % search_term)
        publish_query_revision()
        publish_history_revision()
        if xbmcgui.getCurrentWindowId() == 10000:
            xbmc.executebuiltin("ActivateWindow(1121)")
            xbmc.sleep(200)
        xbmc.executebuiltin("SetFocus(2000)")

    def re_search(self):
        self.search_input(xbmc.getInfoLabel("ListItem.Label"))

    def re_search_id(self, spath_id):
        if not str(spath_id).isdigit():
            return
        result = self.dbcur.execute(
            "SELECT spath FROM spath WHERE spath_id = ?", (int(spath_id),)).fetchone()
        if result:
            self.search_input(result[0])

    # Compatibility with older callers: history is now a live plugin list.
    def make_search_history_xml(self, active_spaths):
        publish_history_revision()
        return False

    def remake_search_history(self):
        publish_history_revision()
        return False

    def make_default_xml(self):
        publish_history_revision()
        return False
