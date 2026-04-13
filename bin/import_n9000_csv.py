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
DEFAULT_CSV_PATH = "/opt/sqllite/n900_quota.csv"
TABLE_NAME = "quota_n9000"
SKIP_HEADERS = {
    ("Block", "Limits", "File", "Limits"),
    ("Name", "fileset", "blocks", "quota"),
    ("username", "volume", "used", "quota"),
}


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
    return os.environ.get("USER_WIDGET_N9000_CSV_PATH", DEFAULT_CSV_PATH)


def normalize_row(row):
    values = [str(x).strip() for x in row[:4]]
    while len(values) < 4:
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
          username TEXT,
          volume TEXT,
          used TEXT,
          quota TEXT,
          collect_time TEXT
        )
        '''
    )

    rows = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or all(not str(x).strip() for x in row):
                continue
            values = normalize_row(row)
            if values in SKIP_HEADERS:
                continue
            username, volume, used, quota = values
            rows.append((username, volume, used, quota, collect_time))

    if not rows:
        raise SystemExit("No quota rows parsed from CSV")

    cur.executemany(
        f"INSERT INTO {TABLE_NAME} (username, volume, used, quota, collect_time) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_username ON {TABLE_NAME}(username)")
    conn.commit()

    count = cur.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
    print(f"Imported {count} rows into {TABLE_NAME} (db: {db_path})")

    conn.close()


if __name__ == "__main__":
    main()
