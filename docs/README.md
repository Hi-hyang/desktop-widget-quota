# Desktop Widget MVP

这是一个桌面托盘组件 MVP，当前已经接入**按当前 Linux 用户读取 quota 信息**，目标：

- CentOS 7.9 / Rocky 8.10
- GNOME / Xfce 图形桌面
- 登录后显示一个图标
- 悬停显示当前用户 quota 摘要
- 左键点击弹出当前用户 quota 详情窗口
- 右键菜单可刷新/退出
- 当前默认读取本地 SQLite，后续可切换到远程 HTTP 数据源

## 目录

- `bin/user_widget_mvp.py`：图形版主程序（tray / 窗口）
- `bin/quota_cli.py`：无图形界面的 CLI 查询工具
- `autostart/user-widget-mvp.desktop`：自启动文件模板
- `bin/install.sh`：安装脚本
- `icons/*.svg`：状态图标

## 当前数据源

默认读取：

- SQLite 数据库：`/opt/sqllite/quota.db`
- 表名：`quota`
- 字段：`volume, username, used, quota`

程序会按**当前登录的 Linux 用户名**查询：

```sql
SELECT volume, username, used, quota
FROM quota
WHERE username = ?
ORDER BY volume;
```

## 状态图标规则

- `normal`：最高使用率 < 80%
- `warn`：最高使用率 >= 80%
- `error`：最高使用率 >= 95%
- `offline`：数据库不可访问、远程接口失败、或没有可用数据

可通过环境变量调整阈值：

- `USER_WIDGET_WARN_RATIO`，默认 `0.8`
- `USER_WIDGET_ERROR_RATIO`，默认 `0.95`

## 依赖

### CentOS 7.9
```bash
sudo yum install -y python36 python36-gobject gtk3
```

### Rocky 8.10
```bash
sudo dnf install -y python3 python3-gobject gtk3
```

> 如果系统没有 sqlite 支持，需额外安装对应 Python sqlite 组件；大多数发行版默认自带。

## 安装

```bash
cd desktop-widget-mvp
sudo bash bin/install.sh
```

安装后会复制到：

- `/opt/user-widget-mvp/bin/user_widget_mvp.py`
- `/opt/user-widget-mvp/icons/*.svg`
- `/etc/xdg/autostart/user-widget-mvp.desktop`

## 手工测试

### 图形版：按当前登录用户测试

请在**图形桌面终端**中执行：

```bash
python3 /opt/user-widget-mvp/bin/user_widget_mvp.py
```

### 图形版：按指定用户测试（例如 jtang）

```bash
USER_WIDGET_TEST_USERNAME=jtang python3 /opt/user-widget-mvp/bin/user_widget_mvp.py
```

正常预期：

1. 右上角/通知区出现状态 SVG 图标
2. 鼠标悬停显示 quota 摘要
3. 左键点击显示表格详情窗口
4. 表格列包含 `volume / username / used / quota / usage`
5. 支持 `C400 / N9000` 双标签页
6. 右键显示菜单，可手动刷新

## CLI 模式（无图形界面）

对于没有图形界面的节点，可以直接使用 CLI 查询 quota：

### 按当前登录用户查询

```bash
python3 /opt/user-widget-mvp/bin/quota_cli.py
# 或更短：
/opt/user-widget-mvp/bin/quota-status
```

默认就是表格输出。

### 查询指定用户

```bash
python3 /opt/user-widget-mvp/bin/quota_cli.py --user gfjiang
# 或：
/opt/user-widget-mvp/bin/quota-status gfjiang
```

### 只看某个 profile

```bash
python3 /opt/user-widget-mvp/bin/quota_cli.py --profile C400
python3 /opt/user-widget-mvp/bin/quota_cli.py --profile N9000
# 或：
/opt/user-widget-mvp/bin/quota-status gfjiang C400
/opt/user-widget-mvp/bin/quota-status gfjiang N9000
```

### 输出表格

```bash
python3 /opt/user-widget-mvp/bin/quota_cli.py --format table
```

### 输出 JSON

```bash
python3 /opt/user-widget-mvp/bin/quota_cli.py --format json
# 或：
/opt/user-widget-mvp/bin/quota-status gfjiang all json
```

### 只显示前几条高风险记录

```bash
python3 /opt/user-widget-mvp/bin/quota_cli.py --format table --limit 5
```

CLI 设计和图形版保持一致：

- 继续复用同一个 SQLite / 远程 HTTP 数据源
- 继续复用 `warn/error` 阈值
- 继续支持 `C400 / N9000 / all`
- 默认按使用率从高到低排序
- 默认直接输出表格，更适合终端环境
- 头部只保留精简信息，并压成一行：`[C400/N9000] username collect_time`
- 表格默认显示核心列：`Volume / Used / Quota / Usage`
- 如需更简洁概览，可显式使用 `--format summary`

## 环境变量

### 本地 SQLite 模式（默认）

- `USER_WIDGET_DB_PATH`：数据库路径，默认 `/opt/sqllite/quota.db`
- `USER_WIDGET_DB_TABLE`：兼容旧配置的默认表名，默认 `quota`
- `USER_WIDGET_C400_DB_TABLE`：C400 表名，默认 `quota`
- `USER_WIDGET_N9000_DB_TABLE`：N9000 表名，默认 `quota_n9000`
- `USER_WIDGET_ICON_DIR`：图标目录，默认 `/opt/user-widget-mvp/icons`
- `USER_WIDGET_TEST_USERNAME`：测试指定用户名；设置后会优先显示这个用户，而不是当前 Linux 登录用户

### 远程 HTTP 模式（为后续拆分预留）

如果设置了：

- `USER_WIDGET_REMOTE_URL`

程序将不再读本地 SQLite，而是改为调用远程接口，例如：

```bash
export USER_WIDGET_REMOTE_URL='http://10.0.0.12:8080/quota'
python3 /opt/user-widget-mvp/bin/user_widget_mvp.py
```

请求方式：

```http
GET /quota?username=<当前linux用户名>
```

当前程序支持远程接口返回以下两种 JSON：

### 直接返回数组

```json
[
  {"volume": "vol01", "username": "alice", "used": 120, "quota": 200},
  {"volume": "vol02", "username": "alice", "used": 90, "quota": 100}
]
```

### 返回对象包装数组

```json
{
  "data": [
    {"volume": "vol01", "username": "alice", "used": 120, "quota": 200}
  ]
}
```

也兼容字段名为 `rows` 或 `result` 的包装。

## 自启动测试

退出图形桌面并重新登录，确认图标自动出现。

## 备注

- GNOME 下如果托盘图标不显示，通常不是程序挂了，而是桌面会话对传统 tray icon 的支持问题。Xfce 一般更稳。
- GNOME 可能需要启用托盘/AppIndicator 相关扩展。
- 这一版仍然是轻量方案，后续如果要更稳，可以切到 AppIndicator。
