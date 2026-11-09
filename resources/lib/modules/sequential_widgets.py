# -*- coding: utf-8 -*-
"""Sequential loader for configured FENtastic home widgets.

Do not replace providers with a proxy: leave their original metadata and actions intact.
Only publish ONE widget content path at a time. Kodi's dynamic content provider
then refreshes the single eligible container. Previously loaded rows remain visible.
"""
import sqlite3

import xbmc
import xbmcgui
import xbmcvfs

from modules.cpath_maker import CPaths, files_get_directory


SECTIONS = (
    ("movies", "movie", 19010),
    ("tvshows", "tvshow", 22010),
    ("custom1", "custom1", 23010),
    ("custom2", "custom2", 24010),
    ("custom3", "custom3", 25010),
)
DATABASE_PATH = xbmcvfs.translatePath(
    "special://profile/addon_data/script.fentastic.helper/cpath_cache.db"
)


class SequentialWidgets:
    def __init__(self, monitor):
        self.monitor = monitor
        self.home = xbmcgui.Window(10000)
        self.done = set()
        self.pending = {}
        self.active = False
        self.off_home_ticks = 0

    def stop(self, duration):
        return self.monitor.waitForAbort(duration)

    def _rows(self, section):
        """Read configured widgets in their displayed order, including stacked rows."""
        media_type, base = section
        rows = []
        try:
            db = sqlite3.connect(DATABASE_PATH, timeout=3)
            try:
                records = db.execute(
                    "SELECT cpath_setting,cpath_path,cpath_label FROM custom_paths "
                    "WHERE cpath_setting LIKE ? ORDER BY cpath_setting",
                    (media_type + ".widget.%",),
                ).fetchall()
            finally:
                db.close()
        except Exception as exc:
            xbmc.log("FENtastic sequential widgets: database: %s" % exc, xbmc.LOGWARNING)
            return rows
        for setting, path, label in records:
            try:
                index = int(setting.rsplit(".", 1)[1])
            except (ValueError, IndexError):
                continue
            if index < 1 or index > 10 or not path:
                continue
            list_id = str(base + index)
            rows.append((list_id, path))
            if "Stacked" in label:
                # Stacked child rows are delayed as well; the initial path
                # is supplied by the existing starting_widgets() routine.
                rows.append((list_id + "1", None))
        return rows

    def _clear_all(self):
        for _, _, base in SECTIONS:
            for i in range(1, 11):
                key = str(base + i)
                self.home.clearProperty("fentastic.seq.%s.path" % key)
                self.home.clearProperty("fentastic.seq.%s1.path" % key)
                self.home.clearProperty("fentastic.seq.%s1.pending" % key)
        self.done.clear()

    def _finished(self, list_id):
        """Observe Kodi's actual container state, never just sleep between requests.

        Treat quick cache hits as complete. A missing/broken widget is eventually
        skipped so it cannot prevent the remaining rows from appearing.
        """
        started = False
        quiet = 0.0
        elapsed = 0.0
        while not self.monitor.abortRequested():
            if xbmcgui.getCurrentWindowId() != 10000:
                return False
            updating = xbmc.getCondVisibility("Container(%s).IsUpdating" % list_id)
            try:
                count = int(xbmc.getInfoLabel("Container(%s).NumItems" % list_id) or "0")
            except ValueError:
                count = 0
            if updating or count > 0:
                started = True
            if started and not updating:
                quiet += 0.2
                if quiet >= 1.0:
                    return True
            else:
                quiet = 0.0
            # Kodi may have no control for an invalid row or a provider may fail.
            # Do not release a second source during a known ongoing update.
            if not started and elapsed >= 12.0:
                xbmc.log("FENtastic sequential widgets: widget %s never started" % list_id,
                         xbmc.LOGWARNING)
                return True
            if started and elapsed >= 90.0:
                xbmc.log("FENtastic sequential widgets: widget %s exceeded 90s" % list_id,
                         xbmc.LOGWARNING)
                # A stuck Kodi request cannot be forcibly canceled here.
                # Keep queue blocked rather than launch a concurrent provider.
                while not self.monitor.abortRequested() and xbmcgui.getCurrentWindowId() == 10000:
                    if not xbmc.getCondVisibility("Container(%s).IsUpdating" % list_id):
                        return True
                    self.stop(0.5)
                return False
            if self.stop(0.2):
                return False
            elapsed += 0.2
        return False

    def _release(self, list_id, path):
        key = "fentastic.seq.%s.path" % list_id
        if self.home.getProperty(key) != path:
            self.home.setProperty(key, path)
        if not self._finished(list_id):
            return False
        self.done.add(list_id)
        return True

    def _migrate_existing_widgets(self):
        """Convert users' generated widget XML once, without five skin reloads."""
        updated = False
        for _, media_type, _ in SECTIONS:
            item = media_type + ".widget"
            maker = CPaths(item)
            try:
                existing = maker.fetch_current_cpaths()
                if not existing:
                    continue
                name = "script-fentastic-widget_%s.xml" % (
                    "movies" if media_type == "movie" else
                    "tvshows" if media_type == "tvshow" else media_type
                )
                path = "special://skin/xml/" + name
                try:
                    with xbmcvfs.File(path, "r") as f:
                        contents = f.read()
                except Exception:
                    contents = ""
                if "fentastic.seq." not in contents:
                    maker.refresh_cpaths = True
                    maker.make_widget_xml(existing, reload_skin=False)
                    updated = True
            finally:
                maker.dbcon.close()
        if updated:
            xbmc.log("FENtastic: migrated configured widget paths to sequential loading", xbmc.LOGINFO)
            xbmc.executebuiltin("ReloadSkin()")
            self.stop(1.0)

    def run(self):
        # special://skin always resolves to the *active* skin. Never generate
        # FENtastic widget files while Estuary or another skin is selected.
        while not self.monitor.abortRequested() and xbmc.getSkinDir() != "skin.fentastic":
            self.stop(1.0)
        if self.monitor.abortRequested():
            return
        try:
            self._migrate_existing_widgets()
        except Exception as exc:
            xbmc.log("FENtastic sequential widgets: migration error: %s" % exc,
                     xbmc.LOGERROR)
        while not self.monitor.abortRequested():
            if xbmc.getSkinDir() != "skin.fentastic":
                if self.active:
                    self._clear_all()
                self.active = False
                self.stop(1.0)
                continue
            if xbmcgui.getCurrentWindowId() != 10000:
                if self.active:
                    self.off_home_ticks += 1
                    if self.off_home_ticks > 4:
                        self._clear_all()
                        self.active = False
                self.stop(0.25)
                continue
            self.active = True
            self.off_home_ticks = 0
            menu = xbmc.getInfoLabel("Container(9000).ListItem.Property(id)")
            section = next(((media_type, base) for key, media_type, base in SECTIONS
                            if key == menu), None)
            if not section:
                self.stop(0.3)
                continue
            rows = self._rows(section)
            if not rows:
                self.stop(0.5)
                continue

            # Prioritize changed stacked-child selection after the current widget
            # completes. The monitor only publishes a pending request; never loads it.
            changed = False
            for list_id, original in rows:
                if original is not None:
                    continue
                key = "fentastic.seq.%s.pending" % list_id
                wanted = self.home.getProperty(key)
                if wanted:
                    self.home.clearProperty(key)
                    self.done.discard(list_id)
                    self._release(list_id, wanted)
                    changed = True
                    break
            if changed:
                continue

            # Exactly one uncompleted widget gets a populated dynamic content path.
            for list_id, original in rows:
                if list_id in self.done:
                    continue
                if original is None:
                    parent = list_id[:-1]
                    original = self.home.getProperty("fentastic.%s.path" % parent)
                    if not original:
                        # Read the first item of the already-loaded category list.
                        original = xbmc.getInfoLabel("Container(%s).ListItem.FolderPath" % parent)
                        label = xbmc.getInfoLabel("Container(%s).ListItem.Label" % parent)
                        if not original:
                            # Fallback for providers not exposing ListItem.FolderPath.
                            category_path = next((p for k, p in rows if k == parent), None)
                            if category_path:
                                try:
                                    first = files_get_directory(category_path)
                                    if first:
                                        original = first[0].get("file", "")
                                        label = first[0].get("label", "")
                                except Exception as exc:
                                    xbmc.log("FENtastic stacked category %s: %s" % (parent, exc),
                                             xbmc.LOGWARNING)
                        if original:
                            self.home.setProperty("fentastic.%s.path" % parent, original)
                            self.home.setProperty("fentastic.%s.label" % parent, label)
                    if not original:
                        # No populated category: skip this child, not the entire menu.
                        self.done.add(list_id)
                        continue
                if not self._release(list_id, original):
                    break
                break
            else:
                self.stop(0.5)
