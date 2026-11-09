# -*- coding: utf-8 -*-
"""Direct FENtastic home widget refresh; no snapshots, no provider prefetch."""
import time


def revision_url(path, slot):
    """Append a Kodi Home-property revision to a direct plugin URL only.

    Non-plugin schemes are left unchanged. This function is called while widget
    XML is generated, and does not alter the configured source URL in SQLite.
    """
    if not isinstance(path, str) or not path.startswith('plugin://'):
        return path
    if 'fentastic_rev=' in path:
        return path
    separator = '&amp;' if '?' in path else '?'
    return (path + separator + 'fentastic_rev=' +
            '$INFO[Window(Home).Property(fentastic.widget.%s.revision)]' % slot)


def refresh_widget(list_id):
    """Refresh one home widget without rebuilding XML or reloading the skin.

    Entry: RunScript(script.fentastic.helper,mode=refresh_widget,list_id=19011)
    IDs cover 19011..19020, 22011..22020, and custom 230xx..250xx.
    """
    import xbmc
    import xbmcgui
    try:
        slot = int(str(list_id))
    except (TypeError, ValueError):
        xbmc.log('FENtastic direct widget: invalid row ID', xbmc.LOGWARNING)
        return False
    if slot not in {base + i for base in (19010, 22010, 23010, 24010, 25010)
                    for i in range(1, 11)}:
        xbmc.log('FENtastic direct widget: unsupported row %s' % slot,
                 xbmc.LOGWARNING)
        return False
    xbmcgui.Window(10000).setProperty('fentastic.widget.%s.revision' % slot,
                                      str(time.monotonic_ns()))
    xbmc.log('FENtastic: requested direct refresh for row %s' % slot,
             xbmc.LOGINFO)
    return True
