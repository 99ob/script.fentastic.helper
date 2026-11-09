# -*- coding: utf-8 -*-
"""Kodi listing wrapper for FENtastic persistent widget snapshots.

Keeps the cached-listing design. Restores video identifiers (for ratings),
resume/watched state when JSON-RPC supplies them, and a safe way to reopen
POV's original listing to access its native context menu.
"""
import re
import sys
from urllib.parse import parse_qs, urlsplit

import xbmc
import xbmcgui
import xbmcplugin

from modules.widget_cache import get_snapshot, get_source


IMDB_ID = re.compile(r"^tt\d+$", re.IGNORECASE)
MEDIA_TYPES = {"movie", "tvshow", "episode", "musicvideo", "season"}
# All supported video fields now use InfoTagVideo methods.


def _id_string(value):
    return str(value).strip() if value is not None else ""


def _identifiers(row):
    """Use only genuine IDs from the cached metadata or original item URL."""
    raw_ids = row.get("uniqueid")
    ids = {}
    if isinstance(raw_ids, dict):
        for provider in ("imdb", "tmdb", "tvdb"):
            value = _id_string(raw_ids.get(provider))
            if value:
                ids[provider] = value
    path = row.get("file") or ""
    try:
        params = parse_qs(urlsplit(path).query)
    except (ValueError, TypeError):
        params = {}

    imdb_candidates = [row.get("imdbnumber"), row.get("imdb_id"), ids.get("imdb")]
    imdb_candidates += [params.get(k, [""])[0] for k in ("imdb_id", "imdb", "imdbnumber")]
    for value in imdb_candidates:
        value = _id_string(value)
        if IMDB_ID.fullmatch(value):
            ids["imdb"] = value
            break

    if not ids.get("tmdb"):
        value = _id_string(row.get("tmdb_id") or params.get("tmdb_id", [""])[0])
        if value.isdigit():
            ids["tmdb"] = value
    if not ids.get("tvdb"):
        value = _id_string(row.get("tvdb_id") or params.get("tvdb_id", [""])[0])
        if value.isdigit():
            ids["tvdb"] = value
    return ids


def _apply_video_tag(item, row):
    try:
        tag = item.getVideoInfoTag()
    except (AttributeError, RuntimeError):
        return
    ids = _identifiers(row)
    if ids:
        try:
            tag.setUniqueIDs(ids, "imdb" if "imdb" in ids else "tmdb" if "tmdb" in ids else "tvdb")
        except (AttributeError, TypeError, RuntimeError) as exc:
            xbmc.log("FENtastic cache: unique IDs failed: %s" % exc, xbmc.LOGDEBUG)
    if "imdb" in ids:
        try:
            tag.setIMDBNumber(ids["imdb"])
        except (AttributeError, TypeError, RuntimeError):
            pass
        item.setProperty("imdb_id", ids["imdb"])
    for provider in ("tmdb", "tvdb"):
        if provider in ids:
            item.setProperty(provider + "_id", ids[provider])

    try:
        query = parse_qs(urlsplit(row.get("file") or "").query)
    except (ValueError, TypeError):
        query = {}
    media_type = _id_string(row.get("mediatype") or row.get("type") or query.get("mediatype", [""])[0]).lower()
    if media_type in MEDIA_TYPES:
        try:
            tag.setMediaType(media_type)
        except (AttributeError, TypeError, RuntimeError):
            pass

    if row.get("rating") is not None:
        try:
            tag.setRating(float(row["rating"]))
        except (TypeError, ValueError, AttributeError, RuntimeError):
            pass
    if row.get("playcount") is not None:
        try:
            tag.setPlaycount(int(row["playcount"]))
        except (TypeError, ValueError, AttributeError, RuntimeError):
            pass
    if row.get("userrating") is not None:
        try:
            tag.setUserRating(int(row["userrating"]))
        except (TypeError, ValueError, AttributeError, RuntimeError):
            pass
    resume = row.get("resume")
    if isinstance(resume, dict) and resume.get("position") is not None:
        try:
            tag.setResumePoint(float(resume["position"]), float(resume.get("total") or 0))
        except (TypeError, ValueError, AttributeError, RuntimeError):
            pass


def _restore_info_tag(item, row):
    """Copy the metadata actually present in the cached POV directory listing."""
    try:
        tag = item.getVideoInfoTag()
    except (AttributeError, RuntimeError):
        return
    for field, method in (("year", "setYear"), ("duration", "setDuration"),
                          ("season", "setSeason"), ("episode", "setEpisode")):
        value = row.get(field)
        if value is None or value == "":
            continue
        try:
            # JSON-RPC duration values are in seconds; do not reinterpret as minutes.
            getattr(tag, method)(int(float(value)))
        except (TypeError, ValueError, AttributeError, RuntimeError):
            pass
    for field, method in (("title", "setTitle"), ("plot", "setPlot"),
                          ("plotoutline", "setPlotOutline"), ("mpaa", "setMpaa"),
                          ("premiered", "setPremiered"), ("firstaired", "setFirstAired"),
                          ("tagline", "setTagLine"), ("originaltitle", "setOriginalTitle"),
                          ("tvshowtitle", "setTvShowTitle"),
                          ("dateadded", "setDateAdded"), ("trailer", "setTrailer")):
        value = row.get(field)
        if not value:
            continue
        try:
            getattr(tag, method)(str(value))
        except (TypeError, ValueError, AttributeError, RuntimeError):
            pass
    for field, method in (("genre", "setGenres"), ("director", "setDirectors"),
                          ("writer", "setWriters"), ("studio", "setStudios")):
        value = row.get(field)
        if not value:
            continue
        values = value if isinstance(value, list) else [value]
        try:
            getattr(tag, method)([str(v) for v in values if v is not None and str(v)])
        except (TypeError, ValueError, AttributeError, RuntimeError):
            pass
    if row.get("votes") is not None:
        try:
            tag.setVotes(int(str(row["votes"]).replace(",", "")))
        except (ValueError, TypeError, AttributeError, RuntimeError):
            pass
    if row.get("watchedepisodes") is not None:
        item.setProperty("WatchedEpisodes", str(row["watchedepisodes"]))


def _browse_original_action(source):
    """Offer POV's real context menu by opening the original source listing.

    We do not fabricate provider-specific action URLs: JSON-RPC does not give
    us the original item context-menu entries. The user can select the item
    inside POV's own listing to access every supported action.
    """
    if not isinstance(source, str) or not source.startswith("plugin://plugin.video.pov/"):
        return None
    # Kodi builtins use commas / closing parentheses as argument delimiters.
    safe = source.replace(",", "%2C").replace(")", "%29")
    return ("Open original POV list (full menu)", "ActivateWindow(Videos,%s,return)" % safe)


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
        source_override = xbmcgui.Window(10000).getProperty("fentastic.%s.path" % parent)
    rows = get_snapshot(slot, source_override=source_override)
    if rows is None:
        xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)
        return
    source = get_source(slot, source_override)
    open_source_action = _browse_original_action(source)
    imdb_items = sum(1 for row in rows if "imdb" in _identifiers(row))
    xbmc.log("FENtastic cache: widget %s has IMDb IDs for %s/%s cached items" %
             (slot, imdb_items, len(rows)), xbmc.LOGINFO)
    kodi_items = []
    for row in rows:
        try:
            path = row.get("file", "")
            if not path:
                continue
            folder = row.get("filetype") in ("directory", "folder")
            item = xbmcgui.ListItem(label=row.get("label") or row.get("title") or "", path=path)
            art = dict(row.get("art") or {})
            if row.get("thumbnail"):
                art.setdefault("thumb", row["thumbnail"])
                art.setdefault("poster", row["thumbnail"])
                art.setdefault("icon", row["thumbnail"])
            if row.get("fanart"):
                art.setdefault("fanart", row["fanart"])
            if art:
                item.setArt(art)
            # Kodi 22+: deprecated legacy video metadata calls removed.
            # Tags are filled using typed InfoTagVideo setters below.
            _apply_video_tag(item, row)
            _restore_info_tag(item, row)
            item.setProperty("fentastic.cache_item", "true")
            # The skin can identify cached media even if JSON-RPC omits
            # Genre or DBType. Original ratings layout remains unchanged.
            if "imdb" in _identifiers(row):
                item.setProperty("fentastic.cache_item", "true")
            if open_source_action:
                item.addContextMenuItems([open_source_action])
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
