# -*- coding: utf-8 -*-
"""Live history listing for the search window (never rewrites skin XML)."""
import sqlite3
import sys

import xbmc
import xbmcgui
import xbmcplugin
import xbmcvfs


def serve_search_history():
    handle = int(sys.argv[1])
    path = xbmcvfs.translatePath(
        "special://profile/addon_data/script.fentastic.helper/spath_cache.db")
    rows = []
    db = None
    try:
        db = sqlite3.connect(path, timeout=5)
        rows = db.execute("SELECT spath_id,spath FROM spath "
                          "ORDER BY spath_id DESC").fetchall()
    except sqlite3.Error as exc:
        xbmc.log("FENtastic search history: %s" % exc, xbmc.LOGDEBUG)
    finally:
        if db is not None:
            db.close()
    items = []
    for spath_id, term in rows:
        if not term:
            continue
        item = xbmcgui.ListItem(label=term)
        item.setProperty("fentastic.spath_id", str(spath_id))
        url = "plugin://script.fentastic.helper/?mode=search_history_pick&spath_id=%s" % spath_id
        items.append((url, item, False))
    if items:
        xbmcplugin.addDirectoryItems(handle, items, totalItems=len(items))
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)
