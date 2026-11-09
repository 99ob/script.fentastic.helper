# -*- coding: utf-8 -*-
"""Kodi plugin wrapper for FENtastic's persistent widget listing snapshots."""
import sys
from urllib.parse import parse_qs

import xbmc
import xbmcgui
import xbmcplugin

from modules.widget_cache import VIDEO_FIELDS, get_snapshot


def serve():
    handle = int(sys.argv[1])
    args = parse_qs(sys.argv[2].lstrip("?"))
    slot = args.get("slot", [""])[0]
    if not slot.isdigit() and not (slot.endswith(".child") and slot[:-6].isdigit()):
        xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
        return
    source_override = None
    if slot.endswith(".child"):
        parent = slot[:-6]
        source_override = xbmcgui.Window(10000).getProperty(
            "fentastic.%s.path" % parent)
    rows = get_snapshot(slot, source_override=source_override)
    if rows is None:
        xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)
        return
    kodi_items = []
    for row in rows:
        try:
            path = row.get("file", "")
            if not path:
                continue
            folder = row.get("filetype") in ("directory", "folder")
            item = xbmcgui.ListItem(label=row.get("label") or row.get("title") or "",
                                    path=path)
            art = dict(row.get("art") or {})
            if row.get("thumbnail"):
                art.setdefault("thumb", row["thumbnail"])
                art.setdefault("poster", row["thumbnail"])
                art.setdefault("icon", row["thumbnail"])
            if row.get("fanart"):
                art.setdefault("fanart", row["fanart"])
            if art:
                item.setArt(art)
            info = {key: row[key] for key in VIDEO_FIELDS if key in row and
                    row[key] is not None and key != "imdbnumber"}
            if info:
                try:
                    item.setInfo("video", info)
                except Exception as exc:
                    xbmc.log("FENtastic cache: item metadata degraded: %s" % exc,
                             xbmc.LOGDEBUG)
            if row.get("imdbnumber"):
                item.setProperty("imdb_id", str(row["imdbnumber"]))
            if not folder:
                item.setProperty("IsPlayable", "true")
            kodi_items.append((path, item, folder))
        except Exception as exc:
            xbmc.log("FENtastic cache: item ignored: %s" % exc, xbmc.LOGWARNING)
    if kodi_items:
        xbmcplugin.addDirectoryItems(handle, kodi_items, totalItems=len(kodi_items))
    xbmcplugin.setContent(handle, "videos")
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


if __name__ == "__main__":
    serve()
