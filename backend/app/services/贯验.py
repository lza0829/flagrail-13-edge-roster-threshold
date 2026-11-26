import math
from datetime import datetime, timezone

from app.db import 连接


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 跑贯验() -> dict:
    conn = 连接()
    try:
        版本数 = conn.execute("SELECT COUNT(*) FROM 开关版本").fetchone()[0]
        下发数 = conn.execute("SELECT COUNT(*) FROM 下发票").fetchone()[0]
        回读数 = conn.execute("SELECT COUNT(*) FROM 回读证").fetchone()[0]
        命运数 = conn.execute("SELECT COUNT(*) FROM 命运账").fetchone()[0]

        问题 = []
        # 已下发票必须有版本
        for r in conn.execute("SELECT 票号, 版本键 FROM 下发票 WHERE 状态='已下发'"):
            if not conn.execute(
                "SELECT 1 FROM 开关版本 WHERE 版本键=?", (r["版本键"],)
            ).fetchone():
                问题.append(f"悬空下发:{r['票号']}")
        # 确认回读必须对应已下发/已回滚票
        for r in conn.execute("SELECT 证号, 票号, 所见版本键, 结果 FROM 回读证 WHERE 结果='确认'"):
            t = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (r["票号"],)).fetchone()
            if not t:
                问题.append(f"悬空回读:{r['证号']}")
            elif t["版本键"] != r["所见版本键"] and t["状态"] == "已下发":
                问题.append(f"回读版本拧花:{r['证号']}")
        # 已回滚票应有命运条
        for r in conn.execute("SELECT 票号 FROM 下发票 WHERE 状态='已回滚'"):
            if not conn.execute(
                "SELECT 1 FROM 命运账 WHERE 对象类型='下发票' AND 对象键=? AND 命运='回滚'",
                (r["票号"],),
            ).fetchone():
                问题.append(f"回滚无命运:{r['票号']}")
        # 边缘名册门槛协同核证
        for g in conn.execute("SELECT * FROM 放量门"):
            票号 = g["票号"]
            最新 = conn.execute(
                "SELECT * FROM 门槛核证 WHERE 票号=? ORDER BY 编号 DESC LIMIT 1", (票号,)
            ).fetchone()
            if not 最新:
                问题.append(f"放量门无核证:{票号}")
                continue
            # 核证须带齐套口径与缺席清单字段（禁止只改接口文案）
            for col in ("名册人数", "已确认", "门槛", "缺席边缘", "valid", "策略"):
                if col not in 最新.keys():
                    问题.append(f"核证缺字段 {col}:{票号}")
            # 放量门状态须与最新核证 valid 一致，不得无核证漂移
            if g["状态"] == "已放量" and not 最新["valid"]:
                问题.append(f"已放量但核证 invalid:{票号}")
            if g["状态"] != "已放量" and 最新["valid"]:
                问题.append(f"核证 valid 却未放量:{票号}")
            # 放量成功必须落放量命运，禁止只返回 JSON
            if g["状态"] == "已放量" and not conn.execute(
                "SELECT 1 FROM 命运账 WHERE 对象类型='放量门' AND 对象键=? AND 命运='放量'",
                (票号,),
            ).fetchone():
                问题.append(f"放量无命运:{票号}")
            # 门槛口径自洽：多数=上取整(n/2)，全员=n
            期望门槛 = math.ceil(最新["名册人数"] / 2) if 最新["策略"] == "多数" else 最新["名册人数"]
            if 最新["名册人数"] > 0 and 最新["门槛"] != 期望门槛:
                问题.append(f"门槛算法漂移:{票号}")

        通过 = 1 if not 问题 else 0
        说明 = "齐" if 通过 else "; ".join(问题)
        conn.execute(
            """INSERT INTO 轨贯验(时刻, 版本数, 下发数, 回读数, 命运数, 是否通过, 说明)
               VALUES (?,?,?,?,?,?,?)""",
            (此刻(), 版本数, 下发数, 回读数, 命运数, 通过, 说明),
        )
        conn.commit()
        return {
            "是否通过": bool(通过),
            "版本数": 版本数,
            "下发数": 下发数,
            "回读数": 回读数,
            "命运数": 命运数,
            "说明": 说明,
        }
    finally:
        conn.close()
