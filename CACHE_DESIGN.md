# FENtastic persistent widget cache (Kodi 22 prototype)

## Overview

The skin's generated widget include paths become stable `plugin://script.fentastic.helper/?mode=widget_cache&slot=<id>` URLs. The helper's plugin extension only reads SQLite. The helper service collects **every configured widget source URL** from `cpath_cache.db` and refreshes them through one service thread, sequentially, using Kodi JSON-RPC `Files.GetDirectory`. Each result is normalized, retained in `widget_cache.db`, and replayed to Kodi as `xbmcgui.ListItem` objects, preserving the original `file` path for normal navigation and playback. An existing snapshot remains accessible while refreshing or when a fetch fails.

**Initial cold start:** Empty rows are normal until a source completes. The worker triggers one initial skin reload after the first successful snapshot, and can refresh the skin after the remaining updates. Later startups render the persisted snapshots immediately. The worker continually checks for new or changed configurations, for all five home-menu sections, not just the visible section. It prioritizes the active section.

## Cache database

- `sources`: widget slot, complete original source URL, URL SHA-256, heading, time indexed.
- `snapshots`: URL SHA-256, fetch time, JSON listing; snapshots are keyed by the entire URL, including all query parameters, to avoid cross-contamination.
- `failures`: failed URL hash, retry deadline, retry count, error; exponential backoff.
- Inactive source snapshots older than 30 days are pruned on a six-hour maintenance pass; active source snapshots remain available.
- All data is saved locally in `userdata/addon_data/script.fentastic.helper/widget_cache.db` (SQLite WAL). Widget paths may contain private tokens, so treat the database as private. No cache telemetry or external service is added.

## Refresh policy

- Continue watching/next episodes/progress: 5 minutes.
- Default dynamic widgets: 30 minutes.
- Trending/popular: 60 minutes.
- Collections/watchlists/favorites: 6 hours.
- Failed fetch: keep previous snapshot and retry after bounded backoff.
- Exactly one upstream `Files.GetDirectory` invocation at a time from this worker. Multiple local reads by Kodi are fine.

## Stacked widgets

The parent category listing is cached as a regular request. Its first child is selected from the cached listing rather than by an extra startup provider call. The existing widget-selection monitor updates the source-path property; the worker detects the change and refreshes the selected child as another queued request. The child plugin reads the snapshot for the current selected source URL hash. Switching selection may show an empty child until its first cache fetch and skin refresh.

## Known limitations / validation gates

1. **Kodi JSON-RPC does not expose every POV `ListItem` property or its context-menu actions.** The wrapper preserves file URLs, labels, basic video info, and artwork to the extent returned. Ratings, resume information, context menus, custom properties, and some provider-specific actions may differ. Validate playback and watched indicators with your own widgets before deploying as a permanent replacement.
2. The worker is serialized at its own queue, not at the entire Kodi process level. If another Kodi screen or add-on launches POV independently, those requests are outside this queue.
3. `Files.GetDirectory` may block for an unbounded period inside Kodi. It cannot be reliably canceled by this worker. Other rows then remain stale, not loaded concurrently.
4. Kodi might not refresh an empty plugin-backed widget automatically when its backing SQLite data changes. The worker uses `ReloadSkin()` sparingly (first result and subsequent updates), which may interrupt focus/navigation. This behavior requires Kodi 22 RC1 runtime testing.
5. The initial cache is empty; no performance benefit is possible until at least one snapshot has been fetched successfully.
6. Metadata is capped at the first 200 items per source. Cached directory contents are snapshots, not perfect binary copies of original provider objects.

## Recovery

Do not delete your `cpath_cache.db` widget configurations. If widget presentation or playback is broken, run `fentastic_widget_cache_rollback_and_push.py` while the cache experiment commits are still the latest commits in both repositories. It reverts the cache experiment, also removes the previously broken sequential-property gate, and publishes higher rollback versions. Reinstall the matching helper and skin and restart Kodi. SQLite snapshots are independent of the widget configuration and may be deleted when the helper is not running.

## Runtime acceptance test

1. Back up your Kodi `userdata` profile. Install helper before skin.
2. Turn on Kodi debug logging. Start on Movies and wait for the first widget to populate.
3. Restart Kodi and confirm previously populated widgets appear from cache, without network fetches first.
4. Switch to TV Shows: cached data should display; remaining refreshes should proceed sequentially.
5. Exercise a POV movie's playback, TV episode playback, folder navigation, artwork, context menus, watched indicators, and stacked widget selection.
6. Check for `FENtastic cache: updated widget ...` messages. Confirm one service-side upstream request is in flight at a time, and no repeated reload loop occurs.
7. Test provider failure: stale cached results should stay visible.

## References

- Kodi `Addon.xml`: multi-extension add-ons and plugin entry points: https://kodi.wiki/view/Addon.xml
- Kodi `Plugin sources`: plugin listings and playback URLs: https://kodi.wiki/view/Plugin_sources
- Kodi `Files.GetDirectory` JSON-RPC API: https://kodi.wiki/view/JSON-RPC_API/v12
