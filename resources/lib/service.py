"""FENtastic ratings service and coordinated skin reload worker."""
import json
import time
from queue import Queue, Empty, Full
from threading import Thread

import xbmc, xbmcgui
from modules.MDbList import MDbListAPI
from modules.skin_reload import SkinReloadWorker

logger = xbmc.log
empty_ratings = {
    "metascore": "", "metascoreImage": "", "tomatoMeter": "",
    "tomatoImage": "", "tomatoUserMeter": "", "tomatoUserImage": "",
    "imdbRating": "", "imdbImage": "", "popularRating": "",
    "popularImage": "", "tmdbRating": "", "tmdbImage": "",
    "trailer": "",
}


# Movie/TV charcoal headers: (row above, row below).
# Keep synchronized with the skin's directional header rules.
CHARCOAL_DIRECTIONAL_PAIRS = {
    19012664: (19011, 19012),
    19013664: (19012, 19013),
    19014664: (19013, 19014),
    22012664: (22011, 22012),
    22013664: (22012, 22013),
    # FENTASTIC_CUSTOM_DIRECTIONAL_ALL_V1
    23012664: (23011, 23012),  # Custom 1
    24012664: (24011, 24012),  # Custom 2
    25012664: (25011, 25012),  # Custom 3

}


class RatingsService(xbmc.Monitor):
    """One MDbList network worker, latest-selection queue, GUI writes on monitor."""
    def __init__(self):
        xbmc.Monitor.__init__(self)
        self.mdblist_api = MDbListAPI
        self.last_set_imdb_id = None
        self.last_set_window_id = None
        self.last_applied_key = None
        self.window = xbmcgui.Window
        self.get_window_id = xbmcgui.getCurrentWindowId
        self.get_infolabel = xbmc.getInfoLabel
        self.get_visibility = xbmc.getCondVisibility
        # At most one outstanding HTTP call; one replacement job may be queued.
        # Worker threads never set Kodi window properties.
        self.jobs = Queue(maxsize=1)
        self.results = Queue()
        self.pending_keys = set()
        self.retry_after = {}
        self.latest_key = None
        self._ratings_thread = Thread(
            target=self._ratings_worker, name="FENtastic-MDbList", daemon=True
        )
        self._ratings_thread.start()

    def onNotification(self, sender, method, data):
        if sender == "xbmc":
            if method in ("GUI.OnScreensaverActivated", "System.OnSleep"):
                self.window(self.get_window_id()).setProperty("pause_services", "true")
                logger("###FENtastic: Device is Asleep, PAUSING Ratings Service", 1)
            elif method in ("GUI.OnScreensaverDeactivated", "System.OnWake"):
                self.window(self.get_window_id()).clearProperty("pause_services")
                logger("###FENtastic: Device is Awake, RESUMING Ratings Service", 1)

    def _imdb_label(self, prefix):
        return (self.get_infolabel(prefix + "IMDBNumber") or
                self.get_infolabel(prefix + "Property(imdb_id)"))

    def _selected_imdb_id(self):
        """FENTASTIC_CHARCOAL_GLOBAL_IMDB_V1: use the focused header's live owner.

        There are no hard-coded header-to-row pairs here. The shared header
        focus control sets charcoal.widget_id for either travel direction,
        including sparse widget IDs (e.g. 25012 -> 25016).
        """
        if self.get_window_id() != 10000:
            return self._imdb_label("ListItem.")
        try:
            focused = int(self.get_infolabel("System.CurrentControlId"))
        except (ValueError, TypeError):
            return self._imdb_label("ListItem.")
        sections = (19, 22, 23, 24, 25)
        def section(row):
            return row // 1000 if 10000 <= row < 100000 else -1
        if section(focused) in sections and 11 <= focused % 1000 <= 99:
            return self._imdb_label("Container(%s).ListItem." % focused)
        focused_text = str(focused)
        if focused_text.endswith("664"):
            row = int(focused_text[:-3])
            if section(row) in sections:
                try:
                    owner = int(self.get_infolabel(
                        "Window(Home).Property(fentastic.charcoal.widget_id)"))
                    last = int(self.get_infolabel(
                        "Window(Home).Property(fentastic.diag.v7.last_list)"))
                except (ValueError, TypeError):
                    return ""
                # Stacked widgets store their child control ID with an extra digit.
                normalized = owner // 10 if owner >= 100000 else owner
                if (section(normalized) != section(row) or
                        normalized > row or normalized < section(row) * 1000 + 11 or
                        normalized != last):
                    return ""
                return self._imdb_label("Container(%s).ListItem." % owner)
            return ""
        if self.get_visibility("String.IsEqual(Window(Home).Property(fentastic.charcoal.active),yes)"):
            return ""
        return self._imdb_label("ListItem.")

    def _ratings_worker(self):
        """Reuse one HTTP session without unbounded ratings threads."""
        while not self.abortRequested():
            try:
                key = self.jobs.get(timeout=0.25)
            except Empty:
                continue
            # A queued title might no longer be selected. Skip needless API work.
            if key != self.latest_key:
                self.results.put((key, None, True))
                continue
            imdb_id, api_key = key
            api = None
            try:
                api = self.mdblist_api()
                ratings = api.fetch_info({"imdb_id": imdb_id}, api_key)
                self.results.put((key, ratings if isinstance(ratings, dict) else {}, False))
            except Exception as exc:
                # Never log an exception that might contain the API key in a URL.
                logger("FENtastic ratings: fetch failed (%s)" %
                       type(exc).__name__, xbmc.LOGWARNING)
                self.results.put((key, {}, False))
            finally:
                if api is not None:
                    try:
                        api.dbcon.close()
                    except Exception:
                        pass

    def _queue_ratings(self, imdb_id, api_key):
        key = (imdb_id, api_key)
        if key in self.pending_keys or time.monotonic() < self.retry_after.get(key, 0):
            return
        try:
            self.jobs.put_nowait(key)
        except Full:
            try:
                displaced = self.jobs.get_nowait()
                self.pending_keys.discard(displaced)
            except Empty:
                pass
            try:
                self.jobs.put_nowait(key)
            except Full:
                # Another thread picked up work; defer until the next poll.
                return
        self.pending_keys.add(key)

    def _apply_ratings(self, target, ratings):
        for property_name, value in ratings.items():
            if property_name in empty_ratings:
                target.setProperty("fentastic.%s" % property_name, str(value))

    def _clear_when_selection_changes(self, window_id, imdb_id):
        if (self.last_set_imdb_id == imdb_id and
                self.last_set_window_id == window_id):
            return
        self._apply_ratings(self.window(window_id), empty_ratings)
        self.last_set_imdb_id = imdb_id
        self.last_set_window_id = window_id
        self.last_applied_key = None

    def _consume_results(self, selected_id, api_key, window_id):
        while True:
            try:
                key, ratings, skipped = self.results.get_nowait()
            except Empty:
                return
            self.pending_keys.discard(key)
            if skipped:
                continue
            if not ratings:
                # Do not retry a failing API every 200ms; database snapshots stay.
                self.retry_after[key] = time.monotonic() + 60.0
                continue
            self.retry_after.pop(key, None)
            # The only Kodi window updates are made on the monitor thread.
            if (key != (selected_id, api_key) or
                    self.get_window_id() != window_id or
                    self._selected_imdb_id() != selected_id):
                continue
            target = self.window(window_id)
            target.setProperty("fentastic.cachedRatings.%s" % selected_id,
                               json.dumps(ratings))
            self._apply_ratings(target, ratings)
            self.last_applied_key = (window_id, selected_id)

    def listitem_monitor(self):
        while not self.abortRequested():
            window_id = self.get_window_id()
            selected_id = self._selected_imdb_id()
            api_key = self.get_infolabel("Skin.String(mdblist_api_key)")
            self.latest_key = (selected_id, api_key)
            self._consume_results(selected_id, api_key, window_id)
            if self.window(window_id).getProperty("pause_services") == "true":
                self.waitForAbort(2)
                continue
            if xbmc.getSkinDir() != "skin.fentastic":
                self.waitForAbort(15)
                continue
            if not api_key:
                self._clear_when_selection_changes(window_id, "")
                self.waitForAbort(10)
                continue
            if not self.get_visibility(
                "Window.IsVisible(videos) | Window.IsVisible(home) | Window.IsVisible(11121)"
            ):
                self.waitForAbort(2)
                continue
            if self.get_visibility("Container.Scrolling"):
                self.waitForAbort(0.2)
                continue
            if self.get_visibility("Skin.HasSetting(TrailerPlaying)"):
                self.waitForAbort(3)
                while xbmc.Player().isPlaying():
                    if self.waitForAbort(0.5):
                        break
                xbmc.executebuiltin("Skin.ToggleSetting(TrailerPlaying)")
                self.waitForAbort(0.2)
                continue
            self._clear_when_selection_changes(window_id, selected_id)
            if not selected_id or not selected_id.startswith("tt"):
                self.waitForAbort(0.2)
                continue
            target = self.window(window_id)
            cached = target.getProperty("fentastic.cachedRatings.%s" % selected_id)
            try:
                ratings = json.loads(cached) if cached else None
            except ValueError:
                ratings = None
            if isinstance(ratings, dict):
                if self.last_applied_key != (window_id, selected_id):
                    self._apply_ratings(target, ratings)
                    self.last_applied_key = (window_id, selected_id)
                self.waitForAbort(0.2)
                continue
            self._queue_ratings(selected_id, api_key)
            self.waitForAbort(0.2)


logger("###FENtastic: Ratings Service Started", 1)
ratings_service = RatingsService()
reload_worker = SkinReloadWorker(ratings_service)
reload_thread = Thread(target=reload_worker.run, name="FENtastic-SkinReload", daemon=True)
reload_thread.start()
try:
    ratings_service.listitem_monitor()
finally:
    # Kodi has signalled the shared Monitor to abort. Allow the
    # worker loops to exit before releasing the SWIG Monitor.
    reload_thread.join(timeout=2.0)
    ratings_service._ratings_thread.join(timeout=2.0)
    if reload_thread.is_alive() or ratings_service._ratings_thread.is_alive():
        logger("FENtastic: shutdown: background worker still active "
               "(Kodi calls cannot be force-cancelled)", xbmc.LOGWARNING)
    else:
        # Drop Python references to the monitor-backed workers
        # before the Kodi interpreter unloads its SWIG wrappers.
        del reload_worker
        del reload_thread
        del ratings_service
        import gc
        gc.collect()
    logger("###FENtastic: RatingsService Finished", 1)

# FENTASTIC_DIRECT_WIDGETS_RELOAD_GUARD_V1: ratings retained; persistent cache worker removed.
