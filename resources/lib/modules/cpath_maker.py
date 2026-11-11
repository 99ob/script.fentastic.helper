# -*- coding: utf-8 -*-
"""FENtastic saved menu/widget paths and generated Kodi skin XML.

Direct provider URLs and per-row revision properties are preserved. XML writes
continue to use the existing coordinated reload request (no new ReloadSkin).
"""
import json
import sqlite3 as database

import xbmc
import xbmcgui
import xbmcvfs

from modules import xmls
from modules.skin_reload import request_skin_reload
from modules.widget_refresh import revision_url


dialog = xbmcgui.Dialog()
window = xbmcgui.Window(10000)
Listitem = xbmcgui.ListItem
max_widgets = 10

settings_path = xbmcvfs.translatePath(
    "special://profile/addon_data/script.fentastic.helper/"
)
database_path = xbmcvfs.translatePath(
    "special://profile/addon_data/script.fentastic.helper/cpath_cache.db"
)

# suffix, widget include, main-menu include, home widget base ID
_SECTION_INFO = {
    "movie": ("movies", "MovieWidgets", "MoviesMainMenu", 19010),
    "tvshow": ("tvshows", "TVShowWidgets", "TVShowsMainMenu", 22010),
    "custom1": ("custom1", "Custom1Widgets", "Custom1MainMenu", 23010),
    "custom2": ("custom2", "Custom2Widgets", "Custom2MainMenu", 24010),
    "custom3": ("custom3", "Custom3Widgets", "Custom3MainMenu", 25010),
}
_CPATH_COLUMNS = (
    "cpath_setting", "cpath_path", "cpath_header", "cpath_type", "cpath_label"
)

# Retain existing module globals for addons that may import them.
movies_widgets_xml = "script-fentastic-widget_movies"
tvshows_widgets_xml = "script-fentastic-widget_tvshows"
custom1_widgets_xml = "script-fentastic-widget_custom1"
custom2_widgets_xml = "script-fentastic-widget_custom2"
custom3_widgets_xml = "script-fentastic-widget_custom3"
movies_main_menu_xml = "script-fentastic-main_menu_movies"
tvshows_main_menu_xml = "script-fentastic-main_menu_tvshows"
custom1_main_menu_xml = "script-fentastic-main_menu_custom1"
custom2_main_menu_xml = "script-fentastic-main_menu_custom2"
custom3_main_menu_xml = "script-fentastic-main_menu_custom3"

default_xmls = {}
for _kind, (_suffix, _widget_include, _menu_include, _base) in _SECTION_INFO.items():
    default_xmls[_kind + ".widget"] = (
        "script-fentastic-widget_" + _suffix, xmls.default_widget, _widget_include
    )
    default_xmls[_kind + ".main_menu"] = (
        "script-fentastic-main_menu_" + _suffix, xmls.default_main_menu, _menu_include
    )
main_include_dict = {
    kind: {"main_menu": None, "widget": values[1]}
    for kind, values in _SECTION_INFO.items()
}

widget_types = (
    ("Poster", "WidgetListPoster"),
    ("BigPoster", "WidgetListBigPoster"),
    ("Landscape", "WidgetListLandscape"),
    ("BigLandscape", "WidgetListBigLandscape"),
    ("LandscapeInfo", "WidgetListEpisodes"),
    ("BigLandscapeInfo", "WidgetListBigEpisodes"),
    ("Category", "WidgetListCategory"),
)
default_path = "addons://sources/video"


def _cpath_dict(row):
    return dict(zip(_CPATH_COLUMNS, row))


def _strip_markup(label):
    """Preserve the existing path browser text cleanup."""
    label = label.replace("[B]", "").replace("[/B]", "")
    while "[COLOR" in label:
        start = label.find("[COLOR")
        end = label.find("]", start) + 1
        label = label[:start] + label[end:]
    return label.replace("[/COLOR]", "")


def _path_item(label, secondary, path, thumbnail, original_label=None):
    item = Listitem(label, secondary, offscreen=True)
    item.setArt({"icon": thumbnail})
    item.setProperty("item", json.dumps({
        "label": label if original_label is None else original_label,
        "file": path,
        "thumbnail": thumbnail,
    }))
    return item


class CPaths:

    def __init__(self, cpath_setting):
        self.connect_database()
        self.cpath_setting = cpath_setting
        self.cpath_lookup = "'%s'" % (self.cpath_setting + "%")
        self.media_type, self.path_type = self.cpath_setting.split(".")
        self.main_include = main_include_dict[self.media_type][self.path_type]
        self.refresh_cpaths, self.last_cpath = False, None

    def connect_database(self):
        if not xbmcvfs.exists(settings_path):
            xbmcvfs.mkdir(settings_path)
        self.dbcon = database.connect(database_path, timeout=20)
        self.dbcon.execute(
            "CREATE TABLE IF NOT EXISTS custom_paths (cpath_setting text unique, cpath_path text, cpath_header text, cpath_type text, cpath_label text)"
        )
        self.dbcur = self.dbcon.cursor()

    def add_cpath_to_database(
        self, cpath_setting, cpath_path, cpath_header, cpath_type, cpath_label
    ):
        self.refresh_cpaths = True
        self.dbcur.execute(
            "INSERT OR REPLACE INTO custom_paths VALUES (?, ?, ?, ?, ?)",
            (cpath_setting, cpath_path, cpath_header, cpath_type, cpath_label),
        )
        self.dbcon.commit()

    def update_cpath_in_database(
        self, cpath_setting, cpath_path, cpath_header, cpath_type, cpath_label
    ):
        self.refresh_cpaths = True
        self.dbcur.execute(
            """
            UPDATE custom_paths
            SET cpath_path = ?, cpath_header = ?, cpath_type = ?, cpath_label = ?
            WHERE cpath_setting = ?
        """,
            (cpath_path, cpath_header, cpath_type, cpath_label, cpath_setting),
        )
        self.dbcon.commit()

    def remove_cpath_from_database(self, cpath_setting):
        self.refresh_cpaths = True
        self.dbcur.execute(
            "DELETE FROM custom_paths WHERE cpath_setting = ?", (cpath_setting,)
        )
        self.dbcon.commit()

    def fetch_current_cpaths(self):
        results = self.dbcur.execute(
            "SELECT * FROM custom_paths WHERE cpath_setting LIKE %s" % self.cpath_lookup
        ).fetchall()
        try:
            results.sort(key=lambda row: int(row[0].split(".")[-1]))
        except (TypeError, ValueError):
            pass
        current = {}
        for row in results:
            try:
                key = int(row[0].split(".")[-1])
            except (TypeError, ValueError):
                key = row[0]
            current[key] = _cpath_dict(row)
        return current

    def fetch_one_cpath(self, cpath_setting):
        row = self.dbcur.execute(
            "SELECT * FROM custom_paths WHERE cpath_setting = ?", (cpath_setting,)
        ).fetchone()
        return _cpath_dict(row) if row is not None else None

    def path_browser(self, label="", file=default_path, thumbnail=""):
        show_busy_dialog()
        label = self.clean_header(label)
        results = files_get_directory(file)
        hide_busy_dialog()
        list_items = []
        if file != default_path:
            list_items.append(_path_item(
                "Use [COLOR dodgerblue]%s[/COLOR] as path" % label,
                "Set as path", file, thumbnail, original_label=label,
            ))
        for row in results:
            list_items.append(_path_item(
                "%s »" % _strip_markup(row["label"]),
                "Browse path...", row["file"], row["thumbnail"],
                original_label=row["label"],
            ))
        choice = dialog.select("Choose path", list_items, useDetails=True)
        if choice == -1:
            return {}
        selected = json.loads(list_items[choice].getProperty("item"))
        if selected["file"] == file:
            return selected
        return self.path_browser(**selected)

    def make_main_menu_xml(self, active_cpaths):
        if not self.refresh_cpaths:
            return
        if not active_cpaths:
            # Avoid generating a second, invalid menu after writing the default.
            self.make_default_xml()
            return
        suffix = _SECTION_INFO[self.media_type][0]
        xml_file = "special://skin/xml/script-fentastic-main_menu_%s.xml" % suffix
        template = getattr(xmls, "main_menu_%s_xml" % suffix)
        entry = active_cpaths[self.media_type + ".main_menu"]
        final_format = template.format(
            main_menu_path=entry["cpath_path"],
            cpath_header=entry.get("cpath_header", ""),
        )
        if "&amp;" not in final_format:
            final_format = final_format.replace("&", "&amp;")
        self.write_xml(xml_file, final_format)
        self.update_skin_strings()

    def make_widget_xml(self, active_cpaths, reload_skin=True):
        if not self.refresh_cpaths:
            return
        if not active_cpaths:
            self.make_default_xml()
            return
        suffix, _, _, base_id = _SECTION_INFO[self.media_type]
        xml_file = "special://skin/xml/script-fentastic-widget_%s.xml" % suffix
        final_format = xmls.media_xml_start.format(main_include=self.main_include)
        previous_list_id = None
        previous_widget_id = None
        # Bind each header to its actual previous row (IDs may be sparse).
        charcoal_panels = []
        charcoal_fanart = []
        ordered_cpaths = list(active_cpaths.items())
        for row_position, (index, entry) in enumerate(ordered_cpaths):
            list_id = base_id + index
            next_list_id = (base_id + ordered_cpaths[row_position + 1][0]
                            if row_position + 1 < len(ordered_cpaths) else None)
            body = (xmls.stacked_media_xml_body if "Stacked" in entry["cpath_label"]
                    else xmls.media_xml_body)
            body = body.format(
                cpath_type=entry["cpath_type"],
                cpath_path=revision_url(entry["cpath_path"], list_id),
                cpath_header=entry["cpath_header"],
                cpath_list_id=list_id,
                has_next_header="true" if next_list_id is not None else "false",
                next_header_id=(str(next_list_id) + "664"
                                if next_list_id is not None else 0),
                focusable_header="true" if previous_list_id is not None else "false",
                previous_list_id=previous_list_id or 0,
                previous_widget_id=previous_widget_id or 0,
                previous_stacked_list_id=(str(previous_list_id) + "1"
                                          if previous_list_id is not None else 0),
            )
            if "&amp;" not in body:
                body = body.replace("&", "&amp;")
            final_format += body
            if previous_list_id is not None:
                header_id = str(list_id) + "664"
                charcoal_panels.append(
                    '        <include content="FentasticCharcoalLivePanel">\n'
                    '            <param name="widget_id" value="%s"/>\n'
                    '            <param name="header_id" value="%s"/>\n'
                    '        </include>' % (previous_widget_id, header_id)
                )
                charcoal_fanart.append(
                    '        <value condition="Control.HasFocus(%s)">'
                    '$INFO[Container(%s).ListItem.Art(fanart)]</value>' %
                    (header_id, previous_widget_id)
                )
            previous_list_id = list_id
            previous_widget_id = int(str(list_id) + "1") if "Stacked" in entry["cpath_label"] else list_id
        final_format += xmls.media_xml_end
        # The charcoal controls use live references in the generated XML, never
        # window-property snapshots. Header-to-widget mapping is exact even
        # with gaps in configured widget row numbers.
        extra = ('\n    <include name="FentasticCharcoalPanels%s">\n%s\n'
                 '    </include>\n'
                 '    <variable name="FentasticCharcoalFanart%s">\n%s\n'
                 '        <value></value>\n    </variable>\n') % (
                    self.main_include, '\n'.join(charcoal_panels),
                    self.main_include, '\n'.join(charcoal_fanart))
        if not final_format.endswith('</includes>'):
            raise RuntimeError('Unexpected generated widget XML end')
        final_format = final_format[:-len('</includes>')] + extra + '</includes>'
        self.write_xml(xml_file, final_format, reload_skin=reload_skin)

    def write_xml(self, xml_file, final_format, reload_skin=True):
        if xbmcvfs.exists(xml_file):
            try:
                with xbmcvfs.File(xml_file, "r") as f:
                    if f.read() == final_format:
                        return False
            except (OSError, IOError):
                pass
        with xbmcvfs.File(xml_file, "w") as f:
            f.write(final_format)
        if reload_skin:
            self.reload_skin()
        return True

    def handle_path_browser_results(self, cpath_setting, context):
        result = self.path_browser()
        if not result:
            return None
        cpath_path = result.get("file", None)
        if not cpath_path:
            return None
        default_header = result.get("label", None)
        if context == "widget":
            cpath_header = self.widget_header(default_header)
            if not cpath_header:
                return None
            self.create_and_update_widget(cpath_setting, cpath_path, cpath_header)
        else:  # context == 'main_menu'
            cpath_header = self.main_menu_header(default_header)
            if not cpath_header:
                return None
            self.add_cpath_to_database(cpath_setting, cpath_path, cpath_header, "", "")
            self.update_skin_strings()
        return True

    def manage_action_and_check(self, cpath_setting, context):
        action_choice = self.manage_action(cpath_setting, context)
        if action_choice == "clear_path":
            self.make_default_xml()
            dialog.ok("FENtastic", "Path cleared")
            return None
        if action_choice is None:
            return None
        return True

    def manage_main_menu_path(self):
        active_cpaths = self.fetch_current_cpaths()
        if active_cpaths and not self.manage_action_and_check(
            self.cpath_setting, "main_menu"
        ):
            return
        if not self.handle_path_browser_results(self.cpath_setting, "main_menu"):
            return self.make_main_menu_xml(active_cpaths)
        self.make_main_menu_xml(self.fetch_current_cpaths())

    def manage_widgets(self):
        active_cpaths = self.fetch_current_cpaths()
        widget_choices = [
            "Widget %s : %s"
            % (count, active_cpaths.get(count, {}).get("cpath_label", ""))
            for count in range(1, 11)
        ]
        choice = dialog.select("Choose widget", widget_choices)
        if choice == -1:
            return self.make_widget_xml(active_cpaths)
        active_cpath_check = choice + 1
        if active_cpath_check in active_cpaths:
            cpath_setting = active_cpaths[active_cpath_check]["cpath_setting"]
            if not self.manage_action_and_check(cpath_setting, "widget"):
                return self.manage_widgets()
        else:
            cpath_setting = "%s.%s" % (self.cpath_setting, active_cpath_check)
        if not self.handle_path_browser_results(cpath_setting, "widget"):
            return self.manage_widgets()
        return self.manage_widgets()

    def widget_header(self, default_header):
        header = dialog.input("Set widget label", defaultt=default_header)
        return header or None

    def main_menu_header(self, default_header):
        header = dialog.input("Set Main Menu label", defaultt=default_header)
        return header or None

    def get_widget_type(self, cpath_type):
        for widget_type, widget_list_type in widget_types:
            if widget_list_type == cpath_type:
                return widget_type
            elif "Stacked" in cpath_type and widget_list_type in cpath_type:
                return widget_type
        return None

    def widget_type(self, label="Choose widget display type", type_limit=7):
        choice = dialog.select(label, [i[0] for i in widget_types[0:type_limit]])
        if choice == -1:
            return None
        return widget_types[choice]

    def update_skin_strings(self):
        labels = (
            ("movie", "MenuMovieLabel", lambda: xbmc.getLocalizedString(342)),
            ("tvshow", "MenuTVShowLabel", lambda: xbmc.getLocalizedString(20343)),
            ("custom1", "MenuCustom1Label", lambda: "Custom 1"),
            ("custom2", "MenuCustom2Label", lambda: "Custom 2"),
            ("custom3", "MenuCustom3Label", lambda: "Custom 3"),
        )
        for media_type, label_id, fallback in labels:
            path = self.fetch_one_cpath(media_type + ".main_menu")
            label = path.get("cpath_header") if path else None
            xbmc.executebuiltin("Skin.SetString(%s,%s)" % (label_id, label or fallback()))

    def manage_action(self, cpath_setting, context="widget"):
        choices = [
            ("Rename", "rename_path"),
            ("Remake", "remake_path"),
            ("Remove", "clear_path"),
        ]
        if context == "widget":
            choices = [
                ("Move up", "move_up"),
                ("Move down", "move_down"),
                ("Display type", "display_type"),
            ] + choices
        choice = dialog.select(
            "%s options" % self.path_type.capitalize().replace("_", " "),
            [i[0] for i in choices],
        )
        if choice == -1:
            return None
        action = choices[choice][1]
        if action in ["move_up", "move_down"]:
            parts = cpath_setting.split(".")
            current_order = int(parts[-1])
            if len(parts) < 3 or not parts[-1].isdigit():
                dialog.ok("FENtastic", "Cannot move this widget")
                return None
            if current_order == 1 and action == "move_up":
                new_order = max_widgets
            elif current_order == max_widgets and action == "move_down":
                new_order = 1
            else:
                new_order = (
                    current_order - 1 if action == "move_up" else current_order + 1
                )
            self.swap_widgets(parts, current_order, new_order)
        elif action == "remake_path":
            self.remove_cpath_from_database(cpath_setting)
            result = self.path_browser()
            if result:
                cpath_path = result.get("file", None)
                if context == "widget":
                    self.handle_widget_remake(result, cpath_setting)
                elif context == "main_menu":
                    default_header = result.get("label", None)
                    cpath_header = self.main_menu_header(default_header)
                    if not cpath_header:
                        return None
                    self.add_cpath_to_database(
                        cpath_setting, cpath_path, cpath_header, "", ""
                    )
                    self.make_main_menu_xml(self.fetch_current_cpaths())
                    dialog.ok("FENtastic", "Main menu remade")
        elif action == "rename_path":
            result = self.fetch_one_cpath(cpath_setting)
            if not result:
                return None
            cpath_path = result.get("cpath_path", None)
            cpath_type = result.get("cpath_type", None)
            cpath_label = result.get("cpath_label", None)
            if not cpath_path:
                return None
            default_header = result.get("cpath_header", None)
            if context == "widget":
                cpath_header = self.widget_header(default_header)
                if not cpath_header:
                    return None
                widget_type = self.get_widget_type(result["cpath_type"])
                if not widget_type:
                    return None
                if "Stacked" in cpath_type:
                    cpath_label = "%s | Stacked (%s) | Category" % (
                        cpath_header,
                        widget_type,
                    )
                else:
                    cpath_label = "%s | %s" % (cpath_header, widget_type)
                self.update_cpath_in_database(
                    cpath_setting,
                    cpath_path,
                    cpath_header,
                    result["cpath_type"],
                    cpath_label,
                )
            if context == "main_menu":
                cpath_header = self.main_menu_header(default_header)
                if not cpath_header or cpath_header.strip() == "":
                    cpath_map = {
                        "movie.main_menu": xbmc.getLocalizedString(342),
                        "tvshow.main_menu": xbmc.getLocalizedString(20343),
                        "custom1.main_menu": "Custom 1",
                        "custom2.main_menu": "Custom 2",
                        "custom3.main_menu": "Custom 3",
                    }
                    cpath_header = cpath_map.get(
                        cpath_setting, "Default main menu label not found"
                    )
                self.update_cpath_in_database(
                    cpath_setting, cpath_path, cpath_header, "", ""
                )
                self.make_main_menu_xml(self.fetch_current_cpaths())
        elif action == "display_type":
            result = self.fetch_one_cpath(cpath_setting)
            if not result:
                return None
            cpath_path = result.get("cpath_path", None)
            cpath_header = result.get("cpath_header", None)
            cpath_label = result.get("cpath_label", None)
            if not cpath_path:
                return None
            self.create_and_update_widget(
                cpath_setting, cpath_path, cpath_header, add_to_db=False
            )
        elif action == "clear_path":
            self.remove_cpath_from_database(cpath_setting)
            if context == "main_menu":
                self.make_default_xml()
                dialog.ok("FENtastic", "Path cleared")
        return None

    def swap_widgets(self, parts, current_order, new_order):
        current_widget = f"{parts[0]}.{parts[1]}.{current_order}"
        adjacent_widget = f"{parts[0]}.{parts[1]}.{new_order}"
        self.refresh_cpaths = True
        self.dbcur.execute(
            "UPDATE custom_paths SET cpath_setting = ? WHERE cpath_setting = ?",
            (f"{parts[0]}.{parts[1]}.temp", current_widget),
        )
        self.dbcur.execute(
            "UPDATE custom_paths SET cpath_setting = ? WHERE cpath_setting = ?",
            (current_widget, adjacent_widget),
        )
        self.dbcur.execute(
            "UPDATE custom_paths SET cpath_setting = ? WHERE cpath_setting = ?",
            (adjacent_widget, f"{parts[0]}.{parts[1]}.temp"),
        )
        self.dbcon.commit()

    def handle_widget_remake(self, result, cpath_setting):
        cpath_path, default_header = result.get("file", None), result.get("label", None)
        cpath_header = self.widget_header(default_header)
        if not cpath_header:
            return
        self.create_and_update_widget(cpath_setting, cpath_path, cpath_header)

    def create_and_update_widget(
        self, cpath_setting, cpath_path, cpath_header, add_to_db=True
    ):
        widget_type = self.widget_type()
        if widget_type is None:
            # Display-type chooser was cancelled; preserve widget settings.
            return
        if widget_type[0] == "Category" and dialog.yesno(
            "Stacked widget",
            "Make [COLOR accent_color][B]%s[/B][/COLOR] a stacked widget?"
            % cpath_header,
        ):
            widget_type = self.widget_type(label="Choose stacked widget display type")
            if widget_type is None:
                return
            cpath_type, cpath_label = "%sStacked" % widget_type[
                1
            ], "%s | Stacked (%s) | Category" % (cpath_header, widget_type[0])
        else:
            cpath_type, cpath_label = widget_type[1], "%s | %s" % (
                cpath_header,
                widget_type[0],
            )
        if add_to_db:
            self.add_cpath_to_database(
                cpath_setting, cpath_path, cpath_header, cpath_type, cpath_label
            )
        else:
            self.update_cpath_in_database(
                cpath_setting, cpath_path, cpath_header, cpath_type, cpath_label
            )

    def reload_skin(self):
        # Preserve the worker's three-second guard; do not call ReloadSkin here.
        request_skin_reload("widget/menu XML updated")

    def clean_header(self, header):
        return header.replace("[B]", "").replace("[/B]", "").replace(" >>", "")

    def remake_main_menus(self):
        self.refresh_cpaths = True
        active_cpaths = self.fetch_current_cpaths()
        if active_cpaths:
            self.make_main_menu_xml(active_cpaths)
        else:
            self.make_default_xml()

    def remake_widgets(self):
        self.refresh_cpaths = True
        active_cpaths = self.fetch_current_cpaths()
        if active_cpaths:
            self.make_widget_xml(active_cpaths)
        else:
            self.make_default_xml()

    def make_default_xml(self):
        item = default_xmls[self.cpath_setting]
        final_format = item[1].format(includes_type=item[2])
        xml_file = "special://skin/xml/%s.xml" % item[0]
        changed = self.write_xml(xml_file, final_format, reload_skin=False)
        self.update_skin_strings()
        if changed:
            self.reload_skin()



def files_get_directory(directory, properties=["title", "file", "thumbnail"]):
    command = {
        "jsonrpc": "2.0",
        "id": "plugin.video.fen",
        "method": "Files.GetDirectory",
        "params": {"directory": directory, "media": "files", "properties": properties},
    }
    try:
        results = [
            i
            for i in get_jsonrpc(command).get("files")
            if i["file"].startswith("plugin://") and i["filetype"] == "directory"
        ]
    except:
        results = None
    return results


def get_jsonrpc(request):
    response = xbmc.executeJSONRPC(json.dumps(request))
    result = json.loads(response)
    return result.get("result", None)


def remake_all_cpaths(silent=False):
    # Widget XML first, then main menus, as in the original implementation.
    for path_type, method in (("widget", "remake_widgets"),
                              ("main_menu", "remake_main_menus")):
        for media_type in _SECTION_INFO:
            maker = CPaths(media_type + "." + path_type)
            try:
                getattr(maker, method)()
            finally:
                maker.dbcon.close()
    if not silent:
        xbmcgui.Dialog().ok("FENtastic", "Menus and widgets remade")


def starting_widgets():
    # Compatibility signal for other FENtastic modules; no cache is used.
    xbmcgui.Window(10000).setProperty("fentastic.starting_widgets", "finished")


def show_busy_dialog():
    return xbmc.executebuiltin("ActivateWindow(busydialognocancel)")


def hide_busy_dialog():
    xbmc.executebuiltin("Dialog.Close(busydialognocancel)")
    xbmc.executebuiltin("Dialog.Close(busydialog)")

# FENTASTIC_CHARCOAL_HEADER_FOCUS_V1: display/navigation only; manual remake entrypoints unchanged.
