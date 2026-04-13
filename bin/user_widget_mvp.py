#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Desktop Widget MVP for CentOS 7.9 / Rocky 8.10

Goal:
- show a tray/status icon after GUI login
- hover shows tooltip
- left click opens a quota details window
- right click shows menu
- read quota from local SQLite now
- keep room for future remote datasource
"""

import configparser
import getpass
import os
import re
import signal
import socket
import sqlite3
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk

APP_NAME = "Desktop Widget MVP"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(BASE_DIR), "conf", "widget.ini")
CONFIG_PATH = os.environ.get("USER_WIDGET_CONFIG", DEFAULT_CONFIG_PATH)


def load_config(path):
    parser = configparser.ConfigParser()
    if path and os.path.exists(path):
        parser.read(path, encoding="utf-8")
    return parser


CONFIG = load_config(CONFIG_PATH)


def get_config(section, option, default=""):
    if CONFIG.has_option(section, option):
        return CONFIG.get(section, option)
    return default


def get_env_or_config(env_name, section, option, default=""):
    value = os.environ.get(env_name)
    if value is not None and str(value).strip() != "":
        return value
    return get_config(section, option, default)


def get_env_or_config_float(env_name, section, option, default):
    value = get_env_or_config(env_name, section, option, str(default))
    return float(value)


def get_env_or_config_int(env_name, section, option, default):
    value = get_env_or_config(env_name, section, option, str(default))
    return int(value)


REFRESH_MS = get_env_or_config_int("USER_WIDGET_REFRESH_MS", "refresh", "interval_ms", 1800000)
SHOW_WINDOW_ON_TRAY_FALLBACK = get_env_or_config("USER_WIDGET_SHOW_WINDOW_ON_TRAY_FALLBACK", "startup", "show_window_on_tray_fallback", "false").strip().lower() in ("1", "true", "yes", "on")
ICON_DIR = get_env_or_config("USER_WIDGET_ICON_DIR", "paths", "icon_dir", os.path.join(os.path.dirname(BASE_DIR), "icons"))
ICON_PATHS = {
    "normal": os.path.join(ICON_DIR, "user-widget-normal.svg"),
    "warn": os.path.join(ICON_DIR, "user-widget-warn.svg"),
    "error": os.path.join(ICON_DIR, "user-widget-error.svg"),
    "offline": os.path.join(ICON_DIR, "user-widget-offline.svg"),
}
DB_PATH = get_env_or_config("USER_WIDGET_DB_PATH", "paths", "db_path", "/opt/sqllite/quota.db")
C400_DB_TABLE = get_env_or_config("USER_WIDGET_C400_DB_TABLE", "tables", "c400_table", os.environ.get("USER_WIDGET_DB_TABLE", "quota"))
N9000_DB_TABLE = get_env_or_config("USER_WIDGET_N9000_DB_TABLE", "tables", "n9000_table", "quota_n9000")
REMOTE_URL = get_env_or_config("USER_WIDGET_REMOTE_URL", "remote", "url", "").strip()
HTTP_TIMEOUT = get_env_or_config_float("USER_WIDGET_HTTP_TIMEOUT", "remote", "timeout", 5)
WARN_RATIO = get_env_or_config_float("USER_WIDGET_WARN_RATIO", "thresholds", "warn_ratio", 0.8)
ERROR_RATIO = get_env_or_config_float("USER_WIDGET_ERROR_RATIO", "thresholds", "error_ratio", 0.95)
TEST_USERNAME = os.environ.get("USER_WIDGET_TEST_USERNAME", "").strip()
FORCE_SHOW_ON_START = os.environ.get("USER_WIDGET_FORCE_SHOW_ON_START", "").strip().lower() in ("1", "true", "yes", "on")
SHOW_SIGNAL_FILE_TEMPLATE = "/tmp/quota-widget-{session_key}.show"


class QuotaDataSource:
    def get_quota(self, username, profile="C400"):
        raise NotImplementedError


class SQLiteQuotaDataSource(QuotaDataSource):
    def __init__(self, db_path, table_map):
        self.db_path = db_path
        self.table_map = table_map

    def get_quota(self, username, profile="C400"):
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"数据库不存在: {self.db_path}")

        table_name = self.table_map.get(profile)
        if not table_name:
            return []

        query = (
            f"SELECT volume, username, used, quota, collect_time "
            f"FROM {table_name} WHERE username = ? ORDER BY volume"
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, (username,)).fetchall()

        return [dict(row) for row in rows]


class RemoteQuotaDataSource(QuotaDataSource):
    def __init__(self, base_url, timeout=5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_quota(self, username, profile="C400"):
        params = urllib.parse.urlencode({"username": username, "profile": profile})
        url = f"{self.base_url}?{params}" if params else self.base_url
        request = urllib.request.Request(url, headers={"Accept": "application/json"})

        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = response.read().decode("utf-8")

        import json

        data = json.loads(payload)
        if isinstance(data, dict):
            rows = data.get("data") or data.get("rows") or data.get("result") or []
        elif isinstance(data, list):
            rows = data
        else:
            raise ValueError("远程接口返回格式不支持")

        normalized = []
        for row in rows:
            normalized.append(
                {
                    "volume": row.get("volume", ""),
                    "username": row.get("username", username),
                    "used": row.get("used", 0),
                    "quota": row.get("quota", 0),
                    "collect_time": row.get("collect_time", ""),
                }
            )
        return normalized


class QuotaTab:
    def __init__(self, app, profile_name):
        self.app = app
        self.profile_name = profile_name

        self.container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        summary = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        summary.set_border_width(16)
        summary.get_style_context().add_class("quota-summary")
        self.container.pack_start(summary, False, False, 0)

        self.summary_line = Gtk.Label()
        self.summary_line.set_xalign(0)
        self.summary_line.set_use_markup(True)
        self.summary_line.set_line_wrap(True)
        summary.pack_start(self.summary_line, True, True, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_border_width(16)
        self.container.pack_start(scrolled, True, True, 0)

        self.store = Gtk.ListStore(str, str, str, str, str)
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.set_size_request(820, 320)
        self.tree.set_headers_visible(True)
        self.tree.set_enable_search(False)
        self.tree.set_grid_lines(Gtk.TreeViewGridLines.HORIZONTAL)
        self.tree.set_activate_on_single_click(False)
        self.tree.set_headers_clickable(True)
        scrolled.add(self.tree)

        columns = [
            ("Volume", 0, 220),
            ("Username", 1, 120),
            ("Used", 2, 120),
            ("Quota", 3, 120),
            ("Usage", 4, 120),
        ]
        for title_text, index, width in columns:
            renderer = Gtk.CellRendererText()
            renderer.set_property("ypad", 7)
            renderer.set_property("xpad", 6)
            column = Gtk.TreeViewColumn(title_text, renderer, markup=index)
            column.set_resizable(True)
            column.set_min_width(width)
            column.set_expand(index == 0)
            column.set_sort_column_id(index)
            self.tree.append_column(column)

    def fill_table(self, rows):
        self.store.clear()
        sorted_rows = sorted(rows, key=lambda row: self.app.get_ratio_value(row.get("used"), row.get("quota")), reverse=True)

        for row in sorted_rows:
            ratio_value = self.app.get_ratio_value(row.get("used"), row.get("quota"))
            ratio_text = self.app.format_ratio(row.get("used"), row.get("quota"))
            ratio_color = self.app.get_ratio_color(ratio_value)
            self.store.append([
                GLib.markup_escape_text(str(row.get("volume", ""))),
                GLib.markup_escape_text(str(row.get("username", ""))),
                GLib.markup_escape_text(self.app.format_value(row.get("used"))),
                GLib.markup_escape_text(self.app.format_value(row.get("quota"))),
                f"<span foreground='{ratio_color}'><b>{GLib.markup_escape_text(ratio_text)}</b></span>",
            ])

    def update_info(self, quota_info):
        rows = quota_info.get("rows", [])
        latest_collect_time = self.app.get_latest_collect_time(rows)

        summary_text = f"{len(rows)} records"
        if latest_collect_time:
            summary_text += f" · collected at {latest_collect_time}"

        if quota_info.get("error"):
            summary_text += f" · {quota_info.get('error')}"

        self.summary_line.set_markup(
            f"<span foreground='#667085'>{GLib.markup_escape_text(summary_text)}</span>"
        )
        self.fill_table(rows)


class DetailWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(title="Quota Details")
        self.app = app
        self.tabs = {}
        self.close_button = None

        self.set_default_size(900, 560)
        self.set_border_width(0)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_resizable(True)

        self.apply_css()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.get_style_context().add_class("quota-window")
        self.add(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_border_width(12)
        header.get_style_context().add_class("quota-header")
        root.pack_start(header, False, False, 0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        header.pack_start(title_box, True, True, 0)

        title = Gtk.Label()
        title.set_xalign(0)
        title.set_use_markup(True)
        title.set_markup("<span size='medium'><b>Quota Details</b></span>")
        title_box.pack_start(title, False, False, 0)

        header_right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.pack_end(header_right, False, False, 0)

        peak_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        header_right.pack_start(peak_box, False, False, 0)

        self.peak_caption = Gtk.Label()
        self.peak_caption.set_xalign(1.0)
        self.peak_caption.set_use_markup(True)
        peak_box.pack_start(self.peak_caption, False, False, 0)

        self.peak_value = Gtk.Label()
        self.peak_value.set_xalign(1.0)
        self.peak_value.set_use_markup(True)
        peak_box.pack_start(self.peak_value, False, False, 0)

        self.peak_note = Gtk.Label()
        self.peak_note.set_xalign(1.0)
        self.peak_note.set_use_markup(True)
        peak_box.pack_start(self.peak_note, False, False, 0)

        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_right.pack_end(action_box, False, False, 0)

        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", self.on_refresh)
        action_box.pack_start(refresh_btn, False, False, 0)

        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", self.on_close_clicked)
        action_box.pack_start(close_btn, False, False, 0)
        self.close_button = close_btn

        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(False)
        self.notebook.connect("switch-page", self.on_switch_page)
        root.pack_start(self.notebook, True, True, 0)

        self.add_tab("C400")
        self.add_tab("N9000")

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_border_width(16)
        footer.get_style_context().add_class("quota-footer")
        root.pack_end(footer, False, False, 0)

        self.connect("delete-event", self.on_delete_event)
        self.update_info()

    def add_tab(self, profile_name):
        quota_tab = QuotaTab(self.app, profile_name)
        self.tabs[profile_name] = quota_tab
        label = Gtk.Label(label=profile_name)
        self.notebook.append_page(quota_tab.container, label)

    def get_active_profile(self):
        page = self.notebook.get_current_page()
        if page < 0:
            return "C400"
        child = self.notebook.get_nth_page(page)
        for profile_name, quota_tab in self.tabs.items():
            if quota_tab.container == child:
                return profile_name
        return "C400"

    def apply_css(self):
        css = b'''
        .quota-window {
            background: #F6F7F9;
        }
        .quota-header {
            background: #FFFFFF;
            border-bottom: 1px solid #D8DCE3;
        }
        .quota-summary {
            background: #FFFFFF;
            border-bottom: 1px solid #E6EAF0;
        }
        .quota-footer {
            background: #FFFFFF;
            border-top: 1px solid #E6EAF0;
        }
        notebook header {
            background: #FFFFFF;
            border-bottom: 1px solid #E6EAF0;
        }
        notebook tab {
            background: #F8FAFC;
            border: 1px solid #E6EAF0;
            padding: 6px 12px;
        }
        notebook tab:checked {
            background: #FFFFFF;
        }
        treeview.view {
            background: #FFFFFF;
            color: #1F2329;
        }
        treeview.view header button {
            background: #F8FAFC;
            color: #475467;
            border: none;
            border-bottom: 1px solid #E6EAF0;
            padding: 8px;
        }
        treeview.view:selected {
            background: #EAF2FF;
            color: #1F2329;
        }
        button {
            background: #FFFFFF;
            border: 1px solid #D0D5DD;
            border-radius: 6px;
            box-shadow: none;
            color: #344054;
            padding: 4px 10px;
        }
        button:hover {
            background: #F9FAFB;
        }
        '''
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        screen = self.get_screen()
        if screen:
            Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def update_peak(self, quota_info):
        rows = quota_info.get("rows", [])
        top_row = self.app.get_top_row(rows)

        self.peak_caption.set_markup("<span foreground='#667085' size='small'>Peak</span>")
        if top_row:
            ratio_value = self.app.get_ratio_value(top_row.get("used"), top_row.get("quota"))
            ratio_color = self.app.get_ratio_color(ratio_value)
            self.peak_value.set_markup(
                f"<span foreground='{ratio_color}' size='large'><b>{GLib.markup_escape_text(self.app.format_ratio(top_row.get('used'), top_row.get('quota')))}</b></span>"
            )
            self.peak_note.set_markup(
                f"<span foreground='#667085' size='small'>{GLib.markup_escape_text(str(top_row.get('volume', '-')))}</span>"
            )
        else:
            self.peak_value.set_markup("<span foreground='#98A2B3' size='xx-large'><b>N/A</b></span>")
            self.peak_note.set_markup("<span foreground='#667085'>No volume data</span>")

    def update_info(self):
        for profile_name, quota_tab in self.tabs.items():
            quota_tab.update_info(self.app.last_quota_info_map.get(profile_name, self.app.empty_quota_info()))

        active_profile = self.get_active_profile()
        self.update_peak(self.app.last_quota_info_map.get(active_profile, self.app.empty_quota_info()))

    def on_refresh(self, *_):
        self.app.refresh_state(show_window=True)

    def on_switch_page(self, *_):
        active_profile = self.get_active_profile()
        self.update_peak(self.app.last_quota_info_map.get(active_profile, self.app.empty_quota_info()))

    def on_close_clicked(self, *_):
        if self.app.tray_mode:
            self.hide()
        else:
            Gtk.main_quit()

    def on_delete_event(self, *_):
        if self.app.tray_mode:
            self.hide()
            return True
        return False


class DesktopWidgetMVP:
    def __init__(self):
        self.actual_username = getpass.getuser()
        self.username = TEST_USERNAME or self.actual_username
        self.hostname = socket.gethostname()
        self.session_key = f"{self.actual_username}-{self.hostname}-{self.sanitize_display(os.environ.get('DISPLAY', ''))}"
        self.show_signal_file = SHOW_SIGNAL_FILE_TEMPLATE.format(session_key=self.session_key)
        self.profile_names = ["C400", "N9000"]
        self.last_quota_info_map = {
            profile_name: self.empty_quota_info()
            for profile_name in self.profile_names
        }
        self.tray_mode = False
        self.tray_checked = False
        self.window = DetailWindow(self)
        self.current_state = "offline"
        self.data_source = self.build_data_source()

        self.status_icon = Gtk.StatusIcon()
        self.status_icon.set_visible(True)
        self.set_status_icon(self.current_state)
        self.status_icon.connect("activate", self.on_activate)
        self.status_icon.connect("popup-menu", self.on_popup_menu)

        self.menu = self.build_menu()
        self.refresh_state()
        GLib.timeout_add(800, self.detect_tray_mode)
        GLib.timeout_add(1000, self.check_show_signal)
        GLib.timeout_add(REFRESH_MS, self.on_timer)

    def sanitize_display(self, value):
        return re.sub(r"[^A-Za-z0-9_.-]", "_", value or "no-display")

    def empty_quota_info(self):
        return {
            "state": "offline",
            "summary": "尚未加载 quota 数据",
            "rows": [],
            "source": self.get_source_label(),
            "error": None,
        }

    def get_source_label(self):
        return "remote" if REMOTE_URL else "sqlite"

    def build_data_source(self):
        if REMOTE_URL:
            return RemoteQuotaDataSource(REMOTE_URL, HTTP_TIMEOUT)
        return SQLiteQuotaDataSource(
            DB_PATH,
            {
                "C400": C400_DB_TABLE,
                "N9000": N9000_DB_TABLE,
            },
        )

    def set_status_icon(self, state):
        icon_path = ICON_PATHS.get(state) or ICON_PATHS["normal"]
        if os.path.exists(icon_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, 24, 24)
                self.status_icon.set_from_pixbuf(pixbuf)
                return
            except Exception:
                traceback.print_exc()
        self.status_icon.set_from_icon_name("dialog-information")

    def build_menu(self):
        menu = Gtk.Menu()

        show_item = Gtk.MenuItem(label="显示详情")
        show_item.connect("activate", lambda *_: self.show_window())
        menu.append(show_item)

        refresh_item = Gtk.MenuItem(label="刷新")
        refresh_item.connect("activate", lambda *_: self.refresh_state())
        menu.append(refresh_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="退出")
        quit_item.connect("activate", lambda *_: Gtk.main_quit())
        menu.append(quit_item)

        menu.show_all()
        return menu

    def safe_float(self, value):
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip()
        if not text or text == "-":
            return 0.0

        try:
            return float(text)
        except ValueError:
            pass

        match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([kmgtpe]?b)?\s*$", text, re.IGNORECASE)
        if not match:
            return 0.0

        number = float(match.group(1))
        unit = (match.group(2) or "").upper()
        factors = {
            "": 1.0,
            "B": 1.0,
            "KB": 1024.0,
            "MB": 1024.0 ** 2,
            "GB": 1024.0 ** 3,
            "TB": 1024.0 ** 4,
            "PB": 1024.0 ** 5,
            "EB": 1024.0 ** 6,
        }
        return number * factors.get(unit, 1.0)

    def get_ratio_value(self, used, quota):
        used_num = self.safe_float(used)
        quota_num = self.safe_float(quota)
        if quota_num <= 0:
            return -1.0
        return used_num / quota_num

    def format_ratio(self, used, quota):
        ratio_value = self.get_ratio_value(used, quota)
        if ratio_value < 0:
            return "N/A"
        return f"{ratio_value * 100:.1f}%"

    def format_value(self, value):
        text = "" if value is None else str(value).strip()
        if text and text != "-":
            return text
        number = self.safe_float(value)
        if number.is_integer():
            return str(int(number))
        return f"{number:.2f}"

    def get_ratio_color(self, ratio_value):
        if ratio_value < 0:
            return "#98A2B3"
        if ratio_value >= ERROR_RATIO:
            return "#C24141"
        if ratio_value >= WARN_RATIO:
            return "#D97706"
        return "#2F855A"

    def get_top_row(self, rows):
        if not rows:
            return None
        return max(rows, key=lambda row: self.get_ratio_value(row.get("used"), row.get("quota")))

    def get_latest_collect_time(self, rows):
        values = []
        for row in rows:
            value = str(row.get("collect_time", "") or "").strip()
            if value:
                values.append(value)
        if not values:
            return None
        return max(values)

    def max_ratio_text(self, rows):
        max_ratio = max((self.get_ratio_value(row.get("used"), row.get("quota")) for row in rows), default=-1.0)
        if max_ratio < 0:
            return "N/A"
        return f"{max_ratio * 100:.1f}%"

    def pick_state(self, rows):
        if not rows:
            return "offline"
        max_ratio = max((self.get_ratio_value(row.get("used"), row.get("quota")) for row in rows), default=-1.0)
        if max_ratio >= ERROR_RATIO:
            return "error"
        if max_ratio >= WARN_RATIO:
            return "warn"
        return "normal"

    def fetch_quota_info(self, profile_name):
        rows = self.data_source.get_quota(self.username, profile_name)
        state = self.pick_state(rows)
        if not rows:
            summary = f"No quota records found for {self.username}"
        else:
            latest_collect_time = self.get_latest_collect_time(rows)
            summary = f"{len(rows)} records · peak usage {self.max_ratio_text(rows)}"
            if latest_collect_time:
                summary += f" · collected at {latest_collect_time}"
        return {
            "state": state,
            "summary": summary,
            "rows": rows,
            "source": self.get_source_label(),
            "error": None,
        }

    def get_overall_state(self):
        states = [self.last_quota_info_map[name]["state"] for name in self.profile_names]
        if "error" in states:
            return "error"
        if "warn" in states:
            return "warn"
        if "normal" in states:
            return "normal"
        return "offline"

    def format_tooltip_text(self):
        c400_info = self.last_quota_info_map.get("C400", self.empty_quota_info())
        rows = c400_info.get("rows", [])
        if c400_info.get("error"):
            return f"{self.username} · 数据读取失败"
        if not rows:
            return f"{self.username} · 暂无 quota 数据"
        top_row = self.get_top_row(rows)
        top_text = ""
        if top_row:
            top_text = f" · 最高 {top_row.get('volume', '-')} {self.format_ratio(top_row.get('used'), top_row.get('quota'))}"
        return f"{self.username} · {len(rows)} 条记录{top_text}"

    def refresh_state(self, show_window=False):
        refreshed_map = {}
        for profile_name in self.profile_names:
            try:
                refreshed_map[profile_name] = self.fetch_quota_info(profile_name)
            except (sqlite3.Error, FileNotFoundError, urllib.error.URLError, ValueError) as exc:
                refreshed_map[profile_name] = {
                    "state": "offline",
                    "summary": "quota 数据获取失败",
                    "rows": [],
                    "source": self.get_source_label(),
                    "error": str(exc),
                }
            except Exception as exc:
                traceback.print_exc()
                refreshed_map[profile_name] = {
                    "state": "offline",
                    "summary": "quota 数据获取失败",
                    "rows": [],
                    "source": self.get_source_label(),
                    "error": str(exc),
                }

        self.last_quota_info_map = refreshed_map
        self.current_state = self.get_overall_state()
        self.set_status_icon(self.current_state)
        self.status_icon.set_tooltip_text(self.format_tooltip_text())
        self.window.update_info()

        if show_window:
            self.show_window()

    def detect_tray_mode(self):
        embedded = False
        try:
            embedded = bool(self.status_icon.is_embedded())
        except Exception:
            traceback.print_exc()

        self.tray_mode = embedded
        self.tray_checked = True

        print(f"[quota-widget] tray visible={self.status_icon.get_visible()} embedded={embedded}")

        if FORCE_SHOW_ON_START:
            print("[quota-widget] force show on start requested")
            self.show_window()
            return False

        if not embedded:
            if SHOW_WINDOW_ON_TRAY_FALLBACK:
                print("[quota-widget] tray unavailable, fallback to window mode")
                self.show_window()
            else:
                print("[quota-widget] tray unavailable, waiting for launcher entry")

        return False

    def show_window(self):
        self.window.show_all()
        self.window.present()
        return False

    def check_show_signal(self):
        if os.path.exists(self.show_signal_file):
            try:
                os.remove(self.show_signal_file)
            except OSError:
                pass
            print("[quota-widget] launcher requested window show")
            self.refresh_state(show_window=True)
        return True

    def on_activate(self, *_):
        self.refresh_state(show_window=True)

    def on_popup_menu(self, icon, button, activate_time):
        if self.tray_mode:
            self.menu.popup(None, None, None, None, button, activate_time)

    def on_timer(self):
        self.refresh_state()
        return True


def install_signal_handlers(app_holder):
    def _handle_signal(signum, _frame):
        print(f"[quota-widget] received signal {signum}, quitting")
        app = app_holder.get("app")
        if app is not None:
            try:
                app.status_icon.set_visible(False)
            except Exception:
                pass
        GLib.idle_add(Gtk.main_quit)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except Exception:
            pass


def main():
    app_holder = {}
    try:
        install_signal_handlers(app_holder)
        app = DesktopWidgetMVP()
        app_holder["app"] = app
        Gtk.main()
    except KeyboardInterrupt:
        Gtk.main_quit()
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
