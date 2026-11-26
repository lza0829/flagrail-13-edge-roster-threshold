from datetime import datetime, timezone

from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 站规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 开关版本 (
  版本键 TEXT PRIMARY KEY,
  开关键 TEXT NOT NULL,
  版本号 INTEGER NOT NULL,
  载荷 TEXT NOT NULL DEFAULT '{}',
  状态 TEXT NOT NULL DEFAULT '已入轨',
  入轨时 TEXT NOT NULL,
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 分桶规 (
  桶键 TEXT PRIMARY KEY,
  开关键 TEXT NOT NULL,
  桶类型 TEXT NOT NULL,
  规则 TEXT NOT NULL DEFAULT '{}',
  状态 TEXT NOT NULL DEFAULT '生效',
  更新时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 下发票 (
  票号 TEXT PRIMARY KEY,
  开关键 TEXT NOT NULL,
  版本键 TEXT NOT NULL,
  桶键 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '待下发',
  下发时 TEXT NOT NULL DEFAULT '',
  世代 INTEGER NOT NULL DEFAULT 1,
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 回读证 (
  证号 TEXT PRIMARY KEY,
  票号 TEXT NOT NULL,
  边缘键 TEXT NOT NULL,
  所见版本键 TEXT NOT NULL DEFAULT '',
  结果 TEXT NOT NULL,
  回读时 TEXT NOT NULL,
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 命运账 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  对象类型 TEXT NOT NULL,
  对象键 TEXT NOT NULL,
  命运 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 轨贯验 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  版本数 INTEGER NOT NULL,
  下发数 INTEGER NOT NULL,
  回读数 INTEGER NOT NULL,
  命运数 INTEGER NOT NULL,
  是否通过 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 空桩 (
  名 TEXT PRIMARY KEY,
  状态 TEXT NOT NULL DEFAULT '空桩'
);
CREATE TABLE IF NOT EXISTS 边缘名册 (
  票号 TEXT NOT NULL,
  边缘键 TEXT NOT NULL,
  加入时 TEXT NOT NULL,
  版本 INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (票号, 边缘键)
);
CREATE TABLE IF NOT EXISTS 门槛策略 (
  票号 TEXT PRIMARY KEY,
  策略 TEXT NOT NULL DEFAULT '全员',
  更新时 TEXT NOT NULL,
  版本 INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS 放量门 (
  票号 TEXT PRIMARY KEY,
  状态 TEXT NOT NULL DEFAULT '未放量',
  策略版本 INTEGER NOT NULL DEFAULT 0,
  名册版本 INTEGER NOT NULL DEFAULT 0,
  门槛 INTEGER NOT NULL DEFAULT 0,
  更新时 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 门槛核证 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  证号 TEXT NOT NULL UNIQUE,
  票号 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  策略 TEXT NOT NULL,
  名册版本 INTEGER NOT NULL,
  策略版本 INTEGER NOT NULL,
  名册人数 INTEGER NOT NULL,
  名册边缘 TEXT NOT NULL DEFAULT '[]',
  已确认 INTEGER NOT NULL,
  门槛 INTEGER NOT NULL,
  缺席边缘 TEXT NOT NULL DEFAULT '[]',
  valid INTEGER NOT NULL,
  成败 TEXT NOT NULL,
  说明 TEXT NOT NULL DEFAULT ''
);
"""


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 初始化库() -> None:
    conn = 连接()
    conn.executescript(建表)
    if conn.execute("SELECT COUNT(*) AS c FROM 站规").fetchone()["c"] == 0:
        for k, v in {
            "站名": "灰度轨",
            "领域": "基础设施",
            "子方向": "中间件",
            "默认灰度比": "10",
            "回读齐套策略": "全边缘确认才可晋升",
            "名册门槛默认策略": "全员",
            "骨架": "开关版本入轨→分桶灰度下发→回读确认→失效/回滚互证",
        }.items():
            conn.execute("INSERT INTO 站规(键, 值) VALUES (?, ?)", (k, v))
    for name in [
        "下发回读计划同票", "偏差隔离升", "分桶比例冲突", "变体必填准入",
        "名单百分比互斥", "回声冲突裁定", "回滚槽互斥", "回读截止收口",
        "回读时间窗", "失效写闸", "失效回声处置", "开关键竞态准入",
        "意图去重键", "比例热切命运", "环境域绑定", "跨环境串扰",
        "轨贯验三联", "载荷纪元", "金丝雀影子道",
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO 空桩(名, 状态) VALUES (?, '空桩')", (name,)
        )
    conn.execute(
        "INSERT OR IGNORE INTO 空桩(名, 状态) VALUES (?, '已实现')",
        ("边缘名册门槛",),
    )
    conn.commit()
    conn.close()
