"""边缘名册门槛。

同票三件套：名册（边缘名册）、确认集（回读证 结果='确认'）、放量（放量门）。
门槛只谈齐套计数，与「偏差隔离」无关——确认集只统计结果为「确认」的回读证，
偏差/其它结果不计入已确认，但也不改变门槛口径。

两种正确性口径（必须可区分，2/3 确认时成败相反）：
- 全员：以名册全员为准，缺一则放量失败，门槛 = 名册人数。
- 多数：达上取整多数即可放量，门槛 = ceil(n/2)，核证列出缺席边缘。

并发硬约束：
- 名册变更与放量都在同一把 SQLite 写锁（BEGIN IMMEDIATE）内完成，
  名册版本/门槛在同一事务快照内计算，门槛不漂移。
- 与回读并发取锁失败时 fail-close（503），绝不无核证放行。
- 放量成功必须落放量命运（命运账），禁止只返回 JSON。
"""

import json
import math
import sqlite3
from datetime import datetime, timezone

from fastapi import HTTPException

from app.db import 连接

策略集 = ("全员", "多数")


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 算门槛(策略: str, 人数: int) -> int:
    """门槛只看齐套计数。空名册无门槛可言 → 0，由调用方按 fail-close 拒绝。"""
    if 人数 <= 0:
        return 0
    if 策略 == "多数":
        return math.ceil(人数 / 2)
    return 人数  # 全员：缺一则不足


def _取写锁(conn: sqlite3.Connection) -> None:
    """BEGIN IMMEDIATE 立即拿写锁；与回读/另一个写者冲突时 fail-close。"""
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as e:  # database is locked
        raise HTTPException(503, f"并发写冲突，fail-close 拒绝:{e}")


def _快照(conn: sqlite3.Connection, 票号: str) -> dict:
    """在当前事务快照内取名册/确认集/策略/版本，保证门槛瞬时一致。"""
    名册 = [
        r["边缘键"]
        for r in conn.execute(
            "SELECT 边缘键 FROM 边缘名册 WHERE 票号=? ORDER BY 边缘键", (票号,)
        )
    ]
    名册版本行 = conn.execute(
        "SELECT COALESCE(MAX(版本), 0) AS v FROM 边缘名册 WHERE 票号=?", (票号,)
    ).fetchone()
    名册版本 = 名册版本行["v"]
    策略行 = conn.execute(
        "SELECT 策略, 版本 FROM 门槛策略 WHERE 票号=?", (票号,)
    ).fetchone()
    策略 = 策略行["策略"] if 策略行 else "全员"
    策略版本 = 策略行["版本"] if 策略行 else 0
    # 确认集：仅统计落在名册内、结果为「确认」的回读证（齐套计数，不论偏差隔离）
    已确认边缘 = [
        r["边缘键"]
        for r in conn.execute(
            """SELECT DISTINCT r.边缘键 FROM 回读证 r
               JOIN 边缘名册 m ON m.票号=r.票号 AND m.边缘键=r.边缘键
               WHERE r.票号=? AND r.结果='确认' ORDER BY r.边缘键""",
            (票号,),
        )
    ]
    缺席 = [e for e in 名册 if e not in set(已确认边缘)]
    人数 = len(名册)
    门槛 = 算门槛(策略, 人数)
    return {
        "名册": 名册,
        "名册版本": 名册版本,
        "策略": 策略,
        "策略版本": 策略版本,
        "已确认边缘": 已确认边缘,
        "已确认": len(已确认边缘),
        "缺席": 缺席,
        "人数": 人数,
        "门槛": 门槛,
    }


def _写核证(conn: sqlite3.Connection, 票号: str, snap: dict, 成败: str, 说明: str) -> dict:
    证号 = f"核-{票号}-{snap['名册版本']}-{snap['策略版本']}-{datetime.now(timezone.utc).strftime('%H%M%S%f')}"
    valid = 1 if 成败 == "成功" else 0
    conn.execute(
        """INSERT INTO 门槛核证
           (证号, 票号, 时刻, 策略, 名册版本, 策略版本, 名册人数, 名册边缘,
            已确认, 门槛, 缺席边缘, valid, 成败, 说明)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            证号, 票号, 此刻(), snap["策略"], snap["名册版本"], snap["策略版本"],
            snap["人数"], json.dumps(snap["名册"], ensure_ascii=False),
            snap["已确认"], snap["门槛"], json.dumps(snap["缺席"], ensure_ascii=False),
            valid, 成败, 说明,
        ),
    )
    return {
        "证号": 证号,
        "票号": 票号,
        "策略": snap["策略"],
        "名册": snap["名册"],
        "名册人数": snap["人数"],
        "已确认": snap["已确认"],
        "门槛": snap["门槛"],
        "缺席边缘": snap["缺席"],
        "valid": bool(valid),
        "成败": 成败,
        "名册版本": snap["名册版本"],
        "策略版本": snap["策略版本"],
        "说明": 说明,
    }


def 写名册(体: dict) -> dict:
    """落名册表。全量覆盖该票名册，删人/加人都 bump 名册版本，门槛随之重算。"""
    票号 = 体["票号"]
    边缘 = list(dict.fromkeys(体.get("边缘") or []))  # 去重保序
    conn = 连接()
    try:
        _取写锁(conn)
        ticket = conn.execute(
            "SELECT 1 FROM 下发票 WHERE 票号=?", (票号,)
        ).fetchone()
        if not ticket:
            conn.rollback()
            raise HTTPException(400, f"下发票不存在，名册无主:{票号}")
        旧 = [r["边缘键"] for r in conn.execute(
            "SELECT 边缘键 FROM 边缘名册 WHERE 票号=?", (票号,))]
        旧版本 = conn.execute(
            "SELECT COALESCE(MAX(版本), 0) AS v FROM 边缘名册 WHERE 票号=?", (票号,)
        ).fetchone()["v"]
        # 内容变化才 bump；首次建名册版本为 1
        新版本 = 旧版本 + 1 if 旧 and sorted(旧) != sorted(边缘) else max(旧版本, 1)
        conn.execute("DELETE FROM 边缘名册 WHERE 票号=?", (票号,))
        now = 此刻()
        for e in 边缘:
            conn.execute(
                "INSERT INTO 边缘名册(票号, 边缘键, 加入时, 版本) VALUES (?,?,?,?)",
                (票号, e, now, 新版本),
            )
        # 名册首次出现即建默认策略行（全员），已存在则保留口径与版本
        conn.execute(
            """INSERT INTO 门槛策略(票号, 策略, 更新时, 版本)
               VALUES (?, '全员', ?, 1)
               ON CONFLICT(票号) DO UPDATE SET 更新时=excluded.更新时""",
            (票号, now),
        )
        conn.execute(
            """INSERT INTO 放量门(票号, 状态, 更新时) VALUES (?, '未放量', ?)
               ON CONFLICT(票号) DO UPDATE SET 更新时=excluded.更新时""",
            (票号, now),
        )
        conn.commit()
        return {"票号": 票号, "名册": 边缘, "人数": len(边缘), "名册版本": 新版本}
    except HTTPException:
        raise
    except sqlite3.OperationalError as e:
        conn.rollback()
        raise HTTPException(503, f"名册写冲突 fail-close:{e}")
    finally:
        conn.close()


def 写策略(体: dict) -> dict:
    """落门槛策略（全员/多数）。切换 bump 策略版本，门槛在下次放量时按新口径重算。"""
    票号 = 体["票号"]
    策略 = 体.get("策略", "全员")
    if 策略 not in 策略集:
        raise HTTPException(400, f"未知门槛策略:{策略}（仅 全员/多数）")
    conn = 连接()
    try:
        _取写锁(conn)
        if not conn.execute("SELECT 1 FROM 下发票 WHERE 票号=?", (票号,)).fetchone():
            conn.rollback()
            raise HTTPException(400, f"下发票不存在:{票号}")
        row = conn.execute("SELECT 版本 FROM 门槛策略 WHERE 票号=?", (票号,)).fetchone()
        新版本 = (row["版本"] + 1) if row else 1
        conn.execute(
            """INSERT INTO 门槛策略(票号, 策略, 更新时, 版本) VALUES (?,?,?,?)
               ON CONFLICT(票号) DO UPDATE SET
                 策略=excluded.策略, 更新时=excluded.更新时, 版本=门槛策略.版本+1""",
            (票号, 策略, 此刻(), 新版本),
        )
        conn.commit()
        return {"票号": 票号, "策略": 策略, "策略版本": 新版本}
    except HTTPException:
        raise
    except sqlite3.OperationalError as e:
        conn.rollback()
        raise HTTPException(503, f"策略写冲突 fail-close:{e}")
    finally:
        conn.close()


def 试放量(体: dict) -> dict:
    """核证门槛并尝试放量。无论成败都落核证；成功才落放量命运并置放量门。"""
    票号 = 体["票号"]
    指定策略 = 体.get("策略")  # 可空：缺省用票上已落的策略
    conn = 连接()
    try:
        _取写锁(conn)
        ticket = conn.execute(
            "SELECT * FROM 下发票 WHERE 票号=?", (票号,)
        ).fetchone()
        if not ticket:
            conn.rollback()
            raise HTTPException(400, f"下发票不存在:{票号}")
        if 指定策略:
            if 指定策略 not in 策略集:
                conn.rollback()
                raise HTTPException(400, f"未知门槛策略:{指定策略}")
            row = conn.execute("SELECT 版本 FROM 门槛策略 WHERE 票号=?", (票号,)).fetchone()
            新版本 = (row["版本"] + 1) if row else 1
            conn.execute(
                """INSERT INTO 门槛策略(票号, 策略, 更新时, 版本) VALUES (?,?,?,?)
                   ON CONFLICT(票号) DO UPDATE SET
                     策略=excluded.策略, 更新时=excluded.更新时, 版本=门槛策略.版本+1""",
                (票号, 指定策略, 此刻(), 新版本),
            )
        snap = _快照(conn, 票号)
        门 = conn.execute("SELECT 状态 FROM 放量门 WHERE 票号=?", (票号,)).fetchone()
        已放量 = bool(门 and 门["状态"] == "已放量")

        # fail-close：空名册无门槛，禁止放行
        if snap["人数"] == 0:
            核 = _写核证(conn, 票号, snap, "失败", "空名册，无门槛可核，fail-close 拒绝")
            conn.commit()
            raise HTTPException(409, 核)

        if 已放量:
            核 = _写核证(conn, 票号, snap, "成功", "已放量，幂等复核")
            conn.commit()
            return {**核, "幂等": True, "放量": True}

        达标 = snap["已确认"] >= snap["门槛"]
        if not 达标:
            说法 = (
                f"全员口径缺边缘:{snap['缺席']}"
                if snap["策略"] == "全员"
                else f"多数门槛 {snap['门槛']}，已确认 {snap['已确认']}，缺席:{snap['缺席']}"
            )
            核 = _写核证(conn, 票号, snap, "失败", 说法)
            conn.execute(
                """INSERT INTO 放量门(票号, 状态, 策略版本, 名册版本, 门槛, 更新时)
                   VALUES (?, '未放量', ?, ?, ?, ?)
                   ON CONFLICT(票号) DO UPDATE SET
                     状态='未放量', 策略版本=excluded.策略版本,
                     名册版本=excluded.名册版本, 门槛=excluded.门槛, 更新时=excluded.更新时""",
                (票号, snap["策略版本"], snap["名册版本"], snap["门槛"], 此刻()),
            )
            conn.commit()
            # 失败也必须返回核证（409 体即核证），调用方可读缺席清单
            raise HTTPException(409, 核)

        # 达标：放量成功 → 落放量门 + 放量命运，禁止只返回 JSON
        conn.execute(
            """INSERT INTO 放量门(票号, 状态, 策略版本, 名册版本, 门槛, 更新时)
               VALUES (?, '已放量', ?, ?, ?, ?)
               ON CONFLICT(票号) DO UPDATE SET
                 状态='已放量', 策略版本=excluded.策略版本,
                 名册版本=excluded.名册版本, 门槛=excluded.门槛, 更新时=excluded.更新时""",
            (票号, snap["策略版本"], snap["名册版本"], snap["门槛"], 此刻()),
        )
        命运说明 = (
            f"边缘名册门槛放量成功（{snap['策略']} 门槛{snap['门槛']}/"
            f"名册{snap['人数']}/确认{snap['已确认']}）；缺席边缘:{snap['缺席']}；"
            f"门槛算法:{'全员=名册人数' if snap['策略'] == '全员' else '多数=上取整(名册人数/2)'}"
        )
        conn.execute(
            "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES (?,?,?,?,?)",
            ("放量门", 票号, "放量", 此刻(), 命运说明),
        )
        conn.execute(
            "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES (?,?,?,?,?)",
            ("下发票", 票号, "放量", 此刻(), "门槛达标，随放量门放量"),
        )
        核 = _写核证(conn, 票号, snap, "成功", "门槛达标，放量成功并落命运")
        conn.commit()
        return {**核, "幂等": False, "放量": True}
    except HTTPException:
        raise
    except sqlite3.OperationalError as e:
        conn.rollback()
        raise HTTPException(503, f"放量并发冲突 fail-close:{e}")
    finally:
        conn.close()


def _读核证(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("名册边缘", "缺席边缘"):
        try:
            d[k] = json.loads(d[k])
        except Exception:
            d[k] = []
    return {
        "证号": d["证号"],
        "票号": d["票号"],
        "时刻": d["时刻"],
        "策略": d["策略"],
        "名册": d["名册边缘"],
        "名册人数": d["名册人数"],
        "已确认": d["已确认"],
        "门槛": d["门槛"],
        "缺席边缘": d["缺席边缘"],
        "valid": bool(d["valid"]),
        "成败": d["成败"],
        "名册版本": d["名册版本"],
        "策略版本": d["策略版本"],
        "说明": d["说明"],
    }


def 列核证(票号: str = "") -> list:
    conn = 连接()
    try:
        if 票号:
            rows = conn.execute(
                "SELECT * FROM 门槛核证 WHERE 票号=? ORDER BY 编号 DESC LIMIT 100", (票号,)
            )
        else:
            rows = conn.execute("SELECT * FROM 门槛核证 ORDER BY 编号 DESC LIMIT 200")
        return [_读核证(r) for r in rows]
    finally:
        conn.close()


def 列名册(票号: str = "") -> list:
    conn = 连接()
    try:
        sql = (
            "SELECT m.票号, m.边缘键, m.加入时, m.版本 AS 名册版本,"
            " COALESCE(p.策略, '全员') AS 策略, COALESCE(p.版本, 0) AS 策略版本"
            " FROM 边缘名册 m LEFT JOIN 门槛策略 p ON p.票号=m.票号"
        )
        rows = conn.execute(
            sql + (" WHERE m.票号=? ORDER BY m.票号, m.边缘键" if 票号 else " ORDER BY m.票号, m.边缘键"),
            (票号,) if 票号 else (),
        )
        return [dict(r) for r in rows]
    finally:
        conn.close()


def 列放量门() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM 放量门 ORDER BY 票号")]
    finally:
        conn.close()


def 票门槛视图(票号: str) -> dict:
    """单票即时门槛视图：回读台/命运账据此翻缺席清单。只读快照。"""
    conn = 连接()
    try:
        snap = _快照(conn, 票号)
        门 = conn.execute("SELECT * FROM 放量门 WHERE 票号=?", (票号,)).fetchone()
        return {
            "票号": 票号,
            "策略": snap["策略"],
            "名册": snap["名册"],
            "名册人数": snap["人数"],
            "已确认": snap["已确认"],
            "已确认边缘": snap["已确认边缘"],
            "门槛": snap["门槛"],
            "缺席边缘": snap["缺席"],
            "名册版本": snap["名册版本"],
            "策略版本": snap["策略版本"],
            "放量状态": 门["状态"] if 门 else "未放量",
            "达标": snap["已确认"] >= snap["门槛"] if snap["人数"] > 0 else False,
        }
    finally:
        conn.close()


def 装名册夹具(体: dict) -> dict:
    """同票编排：先名册+策略，再灌确认回读，最后按口径试放量。

    预期内的放量失败（HTTP 409，体即核证）转成结构化结果返回，
    以便一个夹具同时演示「2/3 全员失败 / 多数成功」的口径分叉。
    """
    from app.services import 回读 as 回读服务
    from app.services import 入轨 as 入轨服务
    from app.services import 分桶 as 分桶服务
    from app.services import 下发 as 下发服务

    批次 = 体.get("批次编号") or f"名册-{此刻()}"
    步骤 = []
    # 可选前置：让名册夹具自包含（入轨→分桶→下发→回读），不依赖外部已灌数据
    前置 = 体.get("前置") or {}
    if 前置.get("入轨"):
        步骤.append({"步": "前置入轨", "结果": 入轨服务.入一批({"版本": 前置["入轨"]})})
    for b in 前置.get("分桶") or []:
        步骤.append({"步": "前置分桶", "结果": 分桶服务.写桶(b)})
    for d in 前置.get("下发") or []:
        步骤.append({"步": "前置下发", "结果": 下发服务.下一票(d)})
    for r in 体.get("名册组") or []:
        票号 = r["票号"]
        名册体 = {"票号": 票号, "边缘": r.get("边缘") or []}
        步骤.append({"步": "写名册", "结果": 写名册(名册体)})
        if r.get("策略"):
            步骤.append({"步": "写策略", "结果": 写策略({"票号": 票号, "策略": r["策略"]})})
        for c in r.get("确认") or []:
            步骤.append({
                "步": "回读确认",
                "结果": 回读服务.记回读({
                    "票号": 票号,
                    "边缘键": c["边缘键"],
                    "所见版本键": c.get("所见版本键", ""),
                    "结果": "确认",
                }),
            })
        try:
            核 = 试放量({"票号": 票号, "策略": r.get("放量策略", "")})
            步骤.append({"步": "放量", "结果": 核})
        except HTTPException as e:
            # 409：门槛未达，detail 即核证（dict 或 JSON 串均兼容）
            if isinstance(e.detail, dict):
                核 = e.detail
            else:
                try:
                    核 = json.loads(e.detail)
                except Exception:
                    核 = {"成败": "失败", "说明": str(e.detail)}
            步骤.append({"步": "放量", "HTTP": e.status_code, "结果": 核})

    conn = 连接()
    try:
        报告 = {"类型": "边缘名册", "步骤": 步骤}
        conn.execute(
            "INSERT OR REPLACE INTO 装载批次(编号, 时刻, 报告) VALUES (?,?,?)",
            (批次, 此刻(), json.dumps(报告, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"批次编号": 批次, "报告": 报告}
