#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage:
  import_quota_data.sh c400 [csv_path] [collect_time]
  import_quota_data.sh n9000 [csv_path] [collect_time]

Examples:
  import_quota_data.sh c400 /opt/sqllite/quota.csv
  import_quota_data.sh n9000 /opt/sqllite/n900_quota.csv
  import_quota_data.sh c400 /opt/sqllite/quota.csv "2026-04-07 09:58:08"
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

profile="${1,,}"
csv_path="${2:-}"
collect_time="${3:-}"

case "$profile" in
  c400)
    importer="$SCRIPT_DIR/import_c400_csv.py"
    default_csv="/opt/sqllite/quota.csv"
    ;;
  n9000)
    importer="$SCRIPT_DIR/import_n9000_csv.py"
    default_csv="/opt/sqllite/n900_quota.csv"
    ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    echo "Unsupported profile: $profile" >&2
    usage
    exit 1
    ;;
esac

if [[ -z "$csv_path" ]]; then
  csv_path="$default_csv"
fi

if [[ -n "$collect_time" ]]; then
  python3 "$importer" "$csv_path" "$collect_time"
else
  python3 "$importer" "$csv_path"
fi
