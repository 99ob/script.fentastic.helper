# -*- coding: utf-8 -*-
"""Lightweight FENtastic video plugin for search history and empty results.

Home widgets use their configured provider directly, not this plugin.
The legacy persistent widget cache has been permanently retired.
"""
import sys
from urllib.parse import parse_qs

import xbmcplugin


# FENTASTIC_LEGACY_WIDGET_CACHE_REMOVED_V1

def main():
    if len(sys.argv) < 3:
        return
    handle = int(sys.argv[1])
    args = parse_qs(sys.argv[2].lstrip('?'))
    mode = args.get('mode', [''])[0]
    if mode == 'search_history':
        from modules.search_history_plugin import serve_search_history
        serve_search_history()
    elif mode == 'search_history_pick':
        from modules.search_utils import SPaths
        SPaths().re_search_id(args.get('spath_id', [''])[0])
        xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)
    else:
        # Includes fentastic_empty_results, legacy widget_cache URLs, and
        # old empty-provider requests. Do not trigger a POV request.
        xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


if __name__ == '__main__':
    main()
