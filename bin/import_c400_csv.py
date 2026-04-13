#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import configparser
import csv
import os
import re
import sqlite3
import sys
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(BASE_DIR), "conf", "widget.ini")
CONFIG_PATH = os.environ.get("USER_WIDGET_CONFIG", DEFAULT_CONFIG_PATH)
DEFAULT_DB_PATH = "/opt/sqllite/quota.db"
DEFAULT_CSV_PATH = "/opt/sqllite/quota.csv"
TABLE_NAME = "quota"
HEADER_ROW = ("vserver", "volume", "index", "quota-target", "disk-used", "disk-limit")
DISPLAY_HEADER_ROW = (
    "Vserver Name",
    "Volume Name",
    "Index",
    "Quota Target",
    "Disk Space Used",
    "Disk Space Limit",
)


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


def get_db_path():
    return get_env_or_config("USER_WIDGET_DB_PATH", "paths", "db_path", DEFAULT_DB_PATH)


def get_default_csv_path():
    return os.environ.get("USER_WIDGET_C400_CSV_PATH", DEFAULT_CSV_PATH)


def normalize_row(row):
    values = [str(x).strip() for x in row[:6]]
    while len(values) < 6:
        values.append("")
    return tuple(values)


def parse_collect_time(csv_path):
    pattern = re.compile(r"Last login time:\s*(.+)$", re.IGNORECASE)
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        for line in f:
            match = pattern.search(line.strip())
            if match:
                return match.group(1).strip()
    return None


def iter_data_rows(csv_path):
    header_found = False

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for raw_row in reader:
            if not raw_row or all(not str(x).strip() for x in raw_row):
                continue

            row = normalize_row(raw_row)
            if row == HEADER_ROW:
                header_found = True
                continue
            if row == DISPLAY_HEADER_ROW:
                continue
            if not header_found:
                continue

            vserver, volume, index_value, quota_target, disk_used, disk_limit = row
            yield {
                "vserver": vserver,
                "volume": volume,
                "quota_target": quota_target,
                "disk_used": disk_used,
                "disk_limit": disk_limit,
            }


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].strip() else Path(get_default_csv_path())
    collect_time = sys.argv[2] if len(sys.argv) > 2 else parse_collect_time(csv_path)
    db_path = get_db_path()

    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    db_dir = Path(db_path).parent
    if not db_dir.exists():
        raise SystemExit(f"DB directory not found: {db_dir}")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
    cur.execute(
        f'''
        CREATE TABLE {TABLE_NAME} (
          volume TEXT,
          username TEXT,
          used TEXT,
          quota TEXT,
          collect_time TEXT
        )
        '''
    )

    rows = []
    for item in iter_data_rows(csv_path):
        rows.append(
            (
                item["volume"],
                item["quota_target"],
                item["disk_used"],
                item["disk_limit"],
                collect_time,
            )
        )

    if not rows:
        raise SystemExit("No quota rows parsed from CSV")

    cur.executemany(
        f"INSERT INTO {TABLE_NAME} (volume, username, used, quota, collect_time) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_username ON {TABLE_NAME}(username)")
    conn.commit()

    count = cur.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
    print(f"Imported {count} rows into {TABLE_NAME} (db: {db_path})")

    conn.close()


if __name__ == "__main__":
    main()
