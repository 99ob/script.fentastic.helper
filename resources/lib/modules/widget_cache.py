# -*- coding: utf-8 -*-
"""Persistent, single-upstream-request FENtastic home widget cache.

Kodi 22 prototype: Files.GetDirectory -> normalized JSON -> SQLite -> plugin listing.
Upstream requests run ONLY in this one worker. Plugin instances serve local SQLite.
No dynamic empty XML paths, no Python plugin recursion, no external network service.
"""
import hashlib
from contextlib import contextmanager
import json
import sqlite3
import time

import xbmc
import xbmcgui
import xbmcvfs

DB = xbmcvfs.translatePath(
    "special://profile/addon_data/script.fentastic.helper/widget_cache.db"
)
CONFIG_DB = xbmcvfs.translatePath(
    "special://profile/addon_data/script.fentastic.helper/cpath_cache.db"
)
SECTIONS = (("movies", "movie", 19010), ("tvshows", "tvshow", 22010),
            ("custom1", "custom1", 23010), ("custom2", "custom2", 24010),
            ("custom3", "custom3", 25010))
# JSON-RPC does not expose every original ListItem property/context-menu entry.
PROPERTIES = (
    "title", "plot", "year", "thumbnail", "art", "fanart", "rating",
    "playcount", "resume", "duration", "premiered", "genre", "season",
    "episode", "showtitle", "imdbnumber", "originaltitle", "dateadded",
    "studio", "mpaa", "votes", "director", "writer", "trailer", "uniqueid",
    "tagline", "plotoutline", "firstaired", "runtime", "userrating", "watchedepisodes",
)
VIDEO_FIELDS = (
    "title", "plot", "year", "rating", "playcount", "duration", "premiered",
    "genre", "season", "episode", "tvshowtitle", "originaltitle", "dateadded",
    "studio", "mpaa", "votes", "director", "writer", "trailer", "imdbnumber",
    "tagline", "plotoutline",
)
CACHE_EXTRA_FIELDS = {"uniqueid", "resume", "userrating", "mediatype", "type",
                      "tmdb_id", "tvdb_id", "imdb_id", "firstaired", "watchedepisodes"}
# Keep older snapshots visible while forcing a one-time metadata refresh.
CACHE_FORMAT_VERSION = "3"


def digest(path):
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=3)
    try:
        db.execute("PRAGMA busy_timeout=3000")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS sources (slot TEXT PRIMARY KEY, "
                   "source TEXT NOT NULL, source_hash TEXT NOT NULL, header TEXT, "
                   "updated_at REAL NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS snapshots (source_hash TEXT PRIMARY KEY, "
                   "updated_at REAL NOT NULL, payload TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS failures (source_hash TEXT PRIMARY KEY, "
                   "retry_after REAL NOT NULL, tries INTEGER NOT NULL, error TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS cache_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        version_row = db.execute("SELECT value FROM cache_meta WHERE key='format'").fetchone()
        if version_row is None or version_row[0] != CACHE_FORMAT_VERSION:
            db.execute("UPDATE snapshots SET updated_at=0")
            db.execute("INSERT OR REPLACE INTO cache_meta(key,value) VALUES ('format',?)",
                       (CACHE_FORMAT_VERSION,))
        db.commit()
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_snapshot(slot, source_override=None):
    """Read cache by exact URL hash, never show a stale *different* widget."""
    try:
        with connect() as db:
            if source_override:
                h = digest(source_override)
            else:
                entry = db.execute(
                    "SELECT source_hash FROM sources WHERE slot=?", (slot,)
                ).fetchone()
                if not entry:
                    return None
                h = entry[0]
            result = db.execute(
                "SELECT payload, updated_at FROM snapshots WHERE source_hash=?", (h,)
            ).fetchone()
        if result:
            return json.loads(result[0])
    except (sqlite3.Error, ValueError) as exc:
        xbmc.log("FENtastic cache: failed to read widget %s: %s" %
                 (slot, exc), xbmc.LOGWARNING)
    return None


def get_source(slot, source_override=None):
    """Return the original provider directory for the cached row's context menu."""
    if source_override:
        return source_override
    try:
        with connect() as db:
            row = db.execute("SELECT source FROM sources WHERE slot=?", (slot,)).fetchone()
        return row[0] if row else ""
    except sqlite3.Error as exc:
        xbmc.log("FENtastic cache: cannot read source for %s: %s" %
                 (slot, exc), xbmc.LOGWARNING)
        return ""


def ttl(path, label):
    lower = (path + " " + label).lower()
    if any(x in lower for x in ("next_episode", "next episode", "progress", "in_progress",
                                  "continue watching", "watched", "upnext")):
        return 300
    if any(x in lower for x in ("trending", "popular", "most_watched")):
        return 3600
    if any(x in lower for x in ("collection", "watchlist", "favorites", "favourites")):
        return 21600
    return 1800


def _get_sources():
    """Read *all* configured widget requests (not only visible menu items)."""
    try:
        with sqlite3.connect(CONFIG_DB, timeout=3) as db:
            records = db.execute(
                "SELECT cpath_setting,cpath_path,cpath_header,cpath_label FROM custom_paths "
                "WHERE cpath_setting LIKE '%.widget.%'"
            ).fetchall()
    except sqlite3.Error as exc:
        xbmc.log("FENtastic cache: widget config unavailable: %s" % exc,
                 xbmc.LOGWARNING)
        return []
    items = []
    for setting, path, header, label in records:
        parts = (setting or "").split(".")
        if len(parts) != 3 or parts[1] != "widget" or not path:
            continue
        try:
            index = int(parts[2])
        except (TypeError, ValueError):
            continue
        section = next(((menu, base) for menu, kind, base in SECTIONS
                        if kind == parts[0]), None)
        if not section or not 1 <= index <= 10:
            continue
        menu, base = section
        if path.startswith("plugin://script.fentastic.helper/"):
            continue  # Never recursively cache our own plugin source.
        items.append({"slot": str(base + index), "path": path,
                      "menu": menu, "index": index,
                      "header": header or "", "stacked": "Stacked" in (label or "")})
    items.sort(key=lambda r: (next(i for i, s in enumerate(SECTIONS) if s[0] == r["menu"]),
                              r["index"]))
    return items


def _request_directory(path):
    """JSON-RPC requests are serial here. Fall back if a media property is unsupported."""
    attempts = (("video", list(PROPERTIES)),
                ("video", ["title", "plot", "year", "genre", "duration",
                           "premiered", "studio", "mpaa", "director",
                           "thumbnail", "art", "rating", "imdbnumber",
                           "uniqueid", "showtitle", "season", "episode"]),
                ("video", ["title", "plot", "thumbnail", "art", "rating",
                           "imdbnumber", "uniqueid"]),
                ("files", ["title", "plot", "thumbnail", "art", "year", "playcount"]),
                ("files", ["title", "thumbnail"]))
    last_error = ""
    for media, props in attempts:
        query = {"jsonrpc": "2.0", "id": 1, "method": "Files.GetDirectory",
                 "params": {"directory": path, "media": media, "properties": props}}
        try:
            response = json.loads(xbmc.executeJSONRPC(json.dumps(query)))
            if "error" in response:
                last_error = str(response["error"])[:200]
                continue
            files = response.get("result", {}).get("files", [])
            if files is None:
                files = []
            if not isinstance(files, list):
                raise ValueError("invalid Files.GetDirectory result")
            return files
        except (ValueError, TypeError) as exc:
            last_error = str(exc)[:200]
    raise RuntimeError("Kodi Files.GetDirectory failed: " + last_error)


def _normalize(files):
    clean = []
    for item in files[:200]:
        if not isinstance(item, dict):
            continue
        file_path = item.get("file", "")
        if not isinstance(file_path, str) or not file_path:
            continue
        # Preserve original POV URLs; do not proxy playback or action routes.
        row = {k: v for k, v in item.items()
               if k in set(VIDEO_FIELDS) | CACHE_EXTRA_FIELDS |
               {"file", "filetype", "label", "thumbnail", "fanart", "art"}}
        # Kodi JSON-RPC calls this showtitle, but ListItem.setInfo()
        # and InfoTagVideo call it tvshowtitle. Never request the
        # unsupported tvshowtitle property from Files.GetDirectory.
        if item.get("showtitle"):
            row["tvshowtitle"] = item["showtitle"]
        if not row.get("duration") and item.get("runtime"):
            row["duration"] = item["runtime"]
        if not row.get("premiered") and item.get("firstaired"):
            row["premiered"] = item["firstaired"]
        clean.append(row)
    return clean


def _remember(db, slot, path, header):
    h = digest(path)
    # Avoid rewriting every row to SQLite on every five-second queue scan.
    db.execute("INSERT INTO sources(slot,source,source_hash,header,updated_at) "
               "VALUES(?,?,?,?,?) ON CONFLICT(slot) DO UPDATE SET "
               "source=excluded.source,source_hash=excluded.source_hash, "
               "header=excluded.header,updated_at=excluded.updated_at "
               "WHERE sources.source_hash != excluded.source_hash "
               "OR sources.header != excluded.header",
               (slot, path, h, header, time.time()))
    return h


class WidgetCacheWorker:
    def __init__(self, monitor):
        self.monitor = monitor
        self.home = xbmcgui.Window(10000)
        self.first_reload = False
        self.last_reload = 0
        self.modified = False
        self.pending_reload = False
        self.last_prune = 0

    def _abort(self, delay):
        return self.monitor.waitForAbort(delay)

    def _migrate(self):
        """Regenerate existing XML containing broken fentastic.seq paths once."""
        from modules.cpath_maker import CPaths
        changed = False
        for menu, kind, base in SECTIONS:
            name = "movies" if kind == "movie" else "tvshows" if kind == "tvshow" else kind
            filename = "special://skin/xml/script-fentastic-widget_%s.xml" % name
            maker = None
            try:
                maker = CPaths(kind + ".widget")
                configured = maker.fetch_current_cpaths()
                if not configured:
                    continue
                try:
                    with xbmcvfs.File(filename, "r") as fh:
                        old = fh.read()
                except Exception:
                    old = ""
                if "mode=widget_cache" in old:
                    continue
                maker.refresh_cpaths = True
                maker.make_widget_xml(configured, reload_skin=False)
                changed = True
            except Exception as exc:
                xbmc.log("FENtastic cache: migration %s failed: %s" %
                         (kind, exc), xbmc.LOGERROR)
            finally:
                if maker:
                    maker.dbcon.close()
        if changed:
            xbmc.log("FENtastic cache: rebuilt widget includes", xbmc.LOGINFO)
            xbmc.executebuiltin("ReloadSkin()")
            self._abort(1)

    def _reload_ui(self, first=False):
        now = time.time()
        if xbmcgui.getCurrentWindowId() != 10000:
            return False
        # At most two reloads per cold-fill batch: first data, then the rest.
        min_delay = 3 if first else 5
        if now - self.last_reload < min_delay:
            return False
        self.last_reload = now
        xbmc.log("FENtastic cache: refreshing skin for cached widget results", xbmc.LOGINFO)
        xbmc.executebuiltin("ReloadSkin()")
        return True

    def _load(self, slot, path, header):
        try:
            with connect() as db:
                h = _remember(db, slot, path, header)
                cached = db.execute(
                    "SELECT updated_at,payload FROM snapshots WHERE source_hash=?", (h,)
                ).fetchone()
                fail = db.execute("SELECT retry_after FROM failures WHERE source_hash=?",
                                  (h,)).fetchone()
                db.commit()
            now = time.time()
            if cached and now - cached[0] < ttl(path, header):
                return False
            if fail and now < fail[0]:
                return False
            # A single service thread executes this. The wrapper does not call this.
            files = _request_directory(path)
            cleaned = _normalize(files)
            snapshot = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
            changed = not cached or cached[1] != snapshot
            with connect() as db:
                db.execute("INSERT OR REPLACE INTO snapshots(source_hash,updated_at,payload) "
                           "VALUES(?,?,?)", (h, time.time(), snapshot))
                db.execute("DELETE FROM failures WHERE source_hash=?", (h,))
            available = {key: sum(1 for r in cleaned if r.get(key))
                         for key in ("year", "genre", "duration", "mpaa", "studio")}
            xbmc.log("FENtastic cache: updated widget %s (%d items; "
                     "year=%d genre=%d runtime=%d mpaa=%d studio=%d)" %
                     (slot, len(cleaned), available["year"], available["genre"],
                      available["duration"], available["mpaa"],
                      available["studio"]), xbmc.LOGINFO)
            if changed:
                self.modified = True
                self.pending_reload = True
                if not self.first_reload and len(cleaned) > 0 and not cached:
                    self.first_reload = True
                    if self._reload_ui(first=True):
                        self.pending_reload = False
            return changed
        except Exception as exc:
            # Network/provider failure never deletes the last good cached snapshot.
            try:
                with connect() as db:
                    h = digest(path)
                    old = db.execute("SELECT tries FROM failures WHERE source_hash=?", (h,)).fetchone()
                    tries = 1 + (old[0] if old else 0)
                    retry = time.time() + min(900, 30 * (2 ** min(tries, 5)))
                    db.execute("INSERT OR REPLACE INTO failures VALUES(?,?,?,?)",
                               (h, retry, tries, str(exc)[:250]))
            except sqlite3.Error:
                pass
            xbmc.log("FENtastic cache: failed to refresh %s: %s" %
                     (slot, exc), xbmc.LOGWARNING)
            return False

    def _child(self, entry):
        """Stacked widget's selected child, without issuing an extra provider request."""
        parent = entry["slot"]
        path = self.home.getProperty("fentastic.%s.path" % parent)
        if not path:
            snapshot = get_snapshot(parent)
            first = next((x for x in (snapshot or []) if x.get("filetype") == "directory"
                          or x.get("filetype") == "folder"), None)
            if first:
                path = first.get("file", "")
                self.home.setProperty("fentastic.%s.path" % parent, path)
                self.home.setProperty("fentastic.%s.label" % parent, first.get("label", ""))
        if path and not path.startswith("plugin://script.fentastic.helper/"):
            return {"slot": parent + ".child", "path": path,
                    "header": self.home.getProperty("fentastic.%s.label" % parent),
                    "menu": entry["menu"], "index": entry["index"]}
        return None

    def _configured(self):
        rows = _get_sources()
        menu = xbmc.getInfoLabel("Container(9000).ListItem.Property(id)")
        rows.sort(key=lambda x: (0 if x["menu"] == menu else 1,
                                 next(i for i,s in enumerate(SECTIONS) if s[0] == x["menu"]),
                                 x["index"]))
        expanded = []
        for entry in rows:
            expanded.append(entry)
            if entry["stacked"]:
                child = self._child(entry)
                if child:
                    expanded.append(child)
        return expanded

    def run(self):
        while not self.monitor.abortRequested():
            if xbmc.getSkinDir() == "skin.fentastic":
                break
            if self._abort(1):
                return
        try:
            with connect():
                pass
            self._migrate()
        except Exception as exc:
            xbmc.log("FENtastic cache: startup error: %s" % exc, xbmc.LOGERROR)
        while not self.monitor.abortRequested():
            if xbmc.getSkinDir() != "skin.fentastic":
                if self._abort(2):
                    return
                continue
            self.modified = False
            if time.time() - self.last_prune >= 21600:
                try:
                    with connect() as db:
                        cutoff = time.time() - (30 * 86400)
                        db.execute("DELETE FROM snapshots WHERE updated_at < ? AND "
                                   "source_hash NOT IN (SELECT source_hash FROM sources)",
                                   (cutoff,))
                        db.execute("DELETE FROM failures WHERE retry_after < ?",
                                   (cutoff,))
                    self.last_prune = time.time()
                except sqlite3.Error:
                    pass
            rows = self._configured()
            if not rows:
                if self._abort(3):
                    return
                continue
            for entry in rows:
                if self.monitor.abortRequested() or xbmc.getSkinDir() != "skin.fentastic":
                    return
                self._load(entry["slot"], entry["path"], entry["header"])
                if self._abort(0.05):
                    return
            if self.pending_reload and self._reload_ui():
                self.pending_reload = False
            if self._abort(5):
                return
