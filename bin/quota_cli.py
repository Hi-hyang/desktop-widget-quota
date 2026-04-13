#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import configparser
import getpass
import json
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request

HEADER_PADDING = "  "
TABLE_PADDING = "    "

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


DB_PATH = get_env_or_config("USER_WIDGET_DB_PATH", "paths", "db_path", "/opt/sqllite/quota.db")
C400_DB_TABLE = get_env_or_config("USER_WIDGET_C400_DB_TABLE", "tables", "c400_table", os.environ.get("USER_WIDGET_DB_TABLE", "quota"))
N9000_DB_TABLE = get_env_or_config("USER_WIDGET_N9000_DB_TABLE", "tables", "n9000_table", "quota_n9000")
REMOTE_URL = get_env_or_config("USER_WIDGET_REMOTE_URL", "remote", "url", "").strip()
HTTP_TIMEOUT = get_env_or_config_float("USER_WIDGET_HTTP_TIMEOUT", "remote", "timeout", 5)
WARN_RATIO = get_env_or_config_float("USER_WIDGET_WARN_RATIO", "thresholds", "warn_ratio", 0.8)
ERROR_RATIO = get_env_or_config_float("USER_WIDGET_ERROR_RATIO", "thresholds", "error_ratio", 0.95)


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


class QuotaCLI:
    def __init__(self):
        self.profile_names = ["C400", "N9000"]
        self.data_source = self.build_data_source()

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

    def get_source_label(self):
        return "remote" if REMOTE_URL else "sqlite"

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
        if text:
            return text
        return "-"

    def get_state(self, ratio_value):
        if ratio_value < 0:
            return "offline"
        if ratio_value >= ERROR_RATIO:
            return "error"
        if ratio_value >= WARN_RATIO:
            return "warn"
        return "normal"

    def pick_state(self, rows):
        if not rows:
            return "offline"
        max_ratio = max((self.get_ratio_value(row.get("used"), row.get("quota")) for row in rows), default=-1.0)
        return self.get_state(max_ratio)

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

    def fetch_quota_info(self, username, profile_name):
        rows = self.data_source.get_quota(username, profile_name)
        sorted_rows = sorted(rows, key=lambda row: self.get_ratio_value(row.get("used"), row.get("quota")), reverse=True)
        state = self.pick_state(sorted_rows)
        top_row = self.get_top_row(sorted_rows)
        latest_collect_time = self.get_latest_collect_time(sorted_rows)

        return {
            "profile": profile_name,
            "username": username,
            "state": state,
            "source": self.get_source_label(),
            "collect_time": latest_collect_time,
            "rows": sorted_rows,
            "top": top_row,
            "count": len(sorted_rows),
        }

    def pad_rows(self, rows, headers):
        widths = [len(header) for header in headers]
        for row in rows:
            for i, value in enumerate(row):
                widths[i] = max(widths[i], len(str(value)))
        return widths

    def render_table(self, rows):
        headers = ["Volume", "Used", "Quota", "Usage"]
        body = []
        for row in rows:
            body.append([
                str(row.get("volume", "")),
                self.format_value(row.get("used")),
                self.format_value(row.get("quota")),
                self.format_ratio(row.get("used"), row.get("quota")),
            ])

        if not body:
            return TABLE_PADDING + "(no records)"

        widths = self.pad_rows(body, headers)
        sep = "  "
        lines = []
        lines.append(TABLE_PADDING + sep.join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        lines.append(TABLE_PADDING + sep.join("-" * widths[i] for i in range(len(headers))))
        for row in body:
            lines.append(TABLE_PADDING + sep.join(str(row[i]).ljust(widths[i]) for i in range(len(headers))))
        return "\n".join(lines)

    def render_summary_block(self, info):
        return f"{HEADER_PADDING}[{info['profile']}] {info['username']} {info.get('collect_time') or '-'}"


def parse_args():
    parser = argparse.ArgumentParser(description="Quota CLI for headless environments")
    parser.add_argument("--user", dest="username", help="quota username to query; defaults to current login user")
    parser.add_argument("--profile", choices=["C400", "N9000", "all"], default="all", help="quota profile to query")
    parser.add_argument("--format", dest="output_format", choices=["summary", "table", "json"], default="table", help="output format")
    parser.add_argument("--limit", type=int, default=0, help="limit rows shown in table output; 0 means all")
    parser.add_argument("--show-empty", action="store_true", help="also print empty profiles")
    return parser.parse_args()


def main():
    args = parse_args()
    cli = QuotaCLI()
    username = (args.username or os.environ.get("USER_WIDGET_TEST_USERNAME") or getpass.getuser()).strip()
    profiles = cli.profile_names if args.profile == "all" else [args.profile]

    infos = []
    exit_code = 0

    for profile in profiles:
        try:
            info = cli.fetch_quota_info(username, profile)
        except Exception as exc:
            info = {
                "profile": profile,
                "username": username,
                "state": "offline",
                "source": cli.get_source_label(),
                "collect_time": None,
                "rows": [],
                "top": None,
                "count": 0,
                "error": str(exc),
            }
            exit_code = 1
        infos.append(info)

    visible_infos = infos if args.show_empty else [info for info in infos if info.get("count", 0) > 0 or info.get("error")]
    if not visible_infos:
        visible_infos = infos if infos else []

    if args.output_format == "json":
        print(json.dumps(visible_infos, ensure_ascii=False, indent=2))
        sys.exit(exit_code)

    blocks = []
    for info in visible_infos:
        lines = [cli.render_summary_block(info)]
        if info.get("error"):
            lines.append(f"error: {info['error']}")
        if args.output_format == "table":
            rows = info.get("rows", [])
            if args.limit and args.limit > 0:
                rows = rows[: args.limit]
            lines.append("")
            lines.append(cli.render_table(rows))
        blocks.append("\n".join(lines))

    print("\n\n".join(blocks))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
