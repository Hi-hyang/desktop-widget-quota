# Quota Widget Deployment

## 推荐共享盘目录结构

```text
/share/apps/quota-widget/
├── current -> /share/apps/quota-widget/releases/2026-04-01
├── releases/
│   └── 2026-04-01/
│       ├── autostart/
│       │   └── quota-widget.desktop
│       ├── bin/
│       │   ├── launch_quota_widget.sh
│       │   ├── user_widget_mvp.py
│       │   ├── quota_cli.py
│       │   ├── import_c400_csv.py
│       │   ├── import_n9000_csv.py
│       │   └── import_quota_data.sh
│       ├── conf/
│       │   └── widget.ini
│       ├── docs/
│       └── icons/
└── data/
    └── quota.db
```

## 配置

编辑共享盘配置文件：

```ini
[paths]
db_path=/share/apps/quota-widget/data/quota.db
icon_dir=/share/apps/quota-widget/current/icons

[tables]
c400_table=quota
n9000_table=quota_n9000

[refresh]
interval_ms=1800000
```

## 自动启动

将后台自启动项 `autostart/quota-widget.desktop` 安装到每台机器：

```bash
cp /share/apps/quota-widget/current/autostart/quota-widget.desktop /etc/xdg/autostart/
```

这个 desktop 文件仅负责登录后静默启动后台进程，默认不在应用菜单里显示。

另外建议把 `autostart/user-widget-mvp.desktop` 作为桌面/应用菜单入口分发给用户：

```bash
cp /share/apps/quota-widget/current/autostart/user-widget-mvp.desktop /usr/share/applications/
```

如果共享盘路径不是 `/share/apps/quota-widget/current`，请先修改两个 desktop 文件里的 `Exec=` / `Icon=`。

## 测试与调试

### 指定测试用户启动

在测试机上，无需真的切换 Linux 登录用户，可以通过环境变量指定要查看的 quota 用户：

```bash
USER_WIDGET_TEST_USERNAME=gfjiang bash bin/launch_quota_widget.sh --show
```

例如：
- `USER_WIDGET_TEST_USERNAME=gfjiang`
- `USER_WIDGET_TEST_USERNAME=yylan`
- `USER_WIDGET_TEST_USERNAME=slqi`

这个变量只影响 widget 内查询 quota 时使用的用户名，不会改变当前系统登录用户。

### 常用测试方式

```bash
USER_WIDGET_TEST_USERNAME=gfjiang bash bin/launch_quota_widget.sh --show
USER_WIDGET_TEST_USERNAME=yylan bash bin/launch_quota_widget.sh --show
USER_WIDGET_TEST_USERNAME=dliu bash bin/launch_quota_widget.sh --show
```

如果需要恢复按当前登录用户显示，直接不要设置 `USER_WIDGET_TEST_USERNAME` 即可。

## CLI 模式（无图形界面节点）

对于没有 X11 / GNOME / tray 的环境，不建议强行启动图形 widget，直接使用 CLI：

```bash
python3 /share/apps/quota-widget/current/bin/quota_cli.py
```

常用示例：

```bash
python3 /share/apps/quota-widget/current/bin/quota_cli.py --user gfjiang
python3 /share/apps/quota-widget/current/bin/quota_cli.py --profile C400 --format table
python3 /share/apps/quota-widget/current/bin/quota_cli.py --profile N9000 --format table --limit 10
python3 /share/apps/quota-widget/current/bin/quota_cli.py --format json
```

CLI 输出设计原则：

- 默认直接输出表格，适合无图形终端直接查看
- 头部仅保留一行：`[C400/N9000] username collect_time`
- 表格字段和图形详情页核心信息保持一致：`Volume / Used / Quota / Usage`
- 默认按使用率从高到低排序，便于直接看到最危险的 volume
- `--format summary` 可切到概览模式，`--format json` 可给脚本调用
- `--limit` 可用于脚本里只取前几条高风险记录
- 返回码非 0 表示至少有一个 profile 查询失败，便于被 shell / cron / 监控调用

## 启动行为

- 用户登录图形桌面后自动启动
- 同一用户同一 DISPLAY 只启动一个实例
- 没有 DISPLAY 时直接退出
- 配置文件默认读取：`$APP_ROOT/conf/widget.ini`
- 可以通过环境变量 `USER_WIDGET_CONFIG` 覆盖配置文件路径
- 程序优先尝试 tray 模式；如果当前桌面环境不支持 `Gtk.StatusIcon`，默认不自动弹窗，而是等待用户从 launcher 打开主窗口
- 可通过配置项 `startup.show_window_on_tray_fallback=true` 或环境变量 `USER_WIDGET_SHOW_WINDOW_ON_TRAY_FALLBACK=1` 改成 fallback 时自动弹窗
- tray 模式下关闭窗口仅隐藏；无 tray 且从 launcher 打开的窗口，关闭后会退出程序
- launcher 会调用 `launch_quota_widget.sh --show`：若后台进程已在运行，则请求现有进程显示主窗口；若尚未运行，则直接以显示窗口模式启动

## 数据导入

### 默认数据文件位置

导入脚本使用和主程序一致的数据库路径优先级：

1. 环境变量 `USER_WIDGET_DB_PATH`
2. 配置文件 `conf/widget.ini` 中的 `[paths] db_path`
3. 默认回退 `/opt/sqllite/quota.db`

建议把采集得到的原始 CSV 放在：

```text
/opt/sqllite/quota.csv
/opt/sqllite/n900_quota.csv
```

也可以放在别的位置，导入时手动传路径。

### 导入 C400 数据

```bash
bash /share/apps/quota-widget/current/bin/import_quota_data.sh c400 /opt/sqllite/quota.csv
```

说明：
- 导入目标表：`quota`
- 脚本会全量覆盖当前 `quota` 表
- 如果 CSV 中包含 `Last login time: ...`，会自动写入 `collect_time`

### 导入 N9000 数据

```bash
bash /share/apps/quota-widget/current/bin/import_quota_data.sh n9000 /opt/sqllite/n900_quota.csv
```

说明：
- 导入目标表：`quota_n9000`
- 脚本会全量覆盖当前 `quota_n9000` 表
- 如果 CSV 中包含 `Last login time: ...`，会自动写入 `collect_time`
- 如果原始 N9000 CSV 不带时间头，`collect_time` 会为空；此时可手动补时间参数

### 手动指定采集时间

```bash
bash /share/apps/quota-widget/current/bin/import_quota_data.sh c400 /opt/sqllite/quota.csv "2026-04-07 09:58:08"
bash /share/apps/quota-widget/current/bin/import_quota_data.sh n9000 /opt/sqllite/n900_quota.csv "2026-04-07 09:58:08"
```

### 定时导入示例

可由采集机或定时任务在更新 CSV 后执行：

```bash
bash /share/apps/quota-widget/current/bin/import_quota_data.sh c400 /opt/sqllite/quota.csv
bash /share/apps/quota-widget/current/bin/import_quota_data.sh n9000 /opt/sqllite/n900_quota.csv
```

如果数据库实际放在共享盘，例如：

```bash
export USER_WIDGET_DB_PATH=/share/apps/quota-widget/data/quota.db
bash /share/apps/quota-widget/current/bin/import_quota_data.sh c400 /opt/sqllite/quota.csv
bash /share/apps/quota-widget/current/bin/import_quota_data.sh n9000 /opt/sqllite/n900_quota.csv
```

## 更新发布

1. 在 `releases/` 下准备新版本目录
2. 更新 `current` 软链接
3. 无需修改用户 home 目录
4. 新登录用户自动使用新版本

## 注意事项

- 当前设计适合共享 NFS 上的 SQLite 只读访问
- 建议只有单一数据采集流程写入 SQLite
- 已为 `quota(username)` 和 `quota_n9000(username)` 建索引
- tray 状态自动刷新周期为 30 分钟
- 点击打开窗口会立即刷新一次
```