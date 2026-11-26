"""边缘名册门槛 端到端自动化。独立临时库，不污染 /data。"""
import math
import os
import sys
import tempfile
import threading

sys.path.insert(0, "/workspace/backend")
_tmp = tempfile.mkdtemp(prefix="flagrail-test-")
os.environ["数据目录"] = _tmp
os.environ["夹具目录"] = "/workspace/fixtures"

from fastapi import HTTPException  # noqa: E402

from app import seed  # noqa: E402
from app.services import 入轨, 分桶, 下发, 回读, 边缘门, 贯验  # noqa: E402
from app.db import 连接  # noqa: E402

seed.初始化库()
通过 = 0


def check(cond, 名):
    global 通过
    assert cond, f"FAIL: {名}"
    通过 += 1
    print(f"  ok · {名}")


def 期望409(fn, 名):
    try:
        fn()
        raise AssertionError(f"FAIL: {名} 应失败却放行")
    except HTTPException as e:
        check(e.status_code in (409, 503), f"{名} fail-close({e.status_code})")
        if e.status_code != 409:
            return {}
        import json
        return e.detail if isinstance(e.detail, dict) else json.loads(e.detail)


def 建票(票号, 版本键, 开关键, 桶键):
    入轨.入一批({"批次编号": f"b-{票号}", "版本": [
        {"开关键": 开关键, "版本号": 1, "版本键": 版本键, "载荷": {"x": 1}}]})
    分桶.写桶({"桶键": 桶键, "开关键": 开关键, "桶类型": "名单", "规则": {}})
    下发.下一票({"票号": 票号, "版本键": 版本键, "桶键": 桶键})


def 确认(票号, 边缘, 版本键):
    回读.记回读({"票号": 票号, "边缘键": 边缘, "所见版本键": 版本键, "结果": "确认"})


print("== 门槛数学 ==")
check(边缘门.算门槛("全员", 3) == 3, "全员门槛=名册人数")
check(边缘门.算门槛("多数", 3) == 2, "多数 3 人门槛=2 上取整")
check(边缘门.算门槛("多数", 4) == 2, "多数 4 人门槛=2 上取整")
check(边缘门.算门槛("多数", 1) == 1, "多数 1 人门槛=1")
check(边缘门.算门槛("多数", 0) == 0, "空名册门槛 0（由调用方 fail-close）")

print("== 口径分叉：3 名册 2 确认，2/3 成败可区分 ==")
票A = "票-A"
建票(票A, "vA@1", "kA", "bA")
边缘门.写名册({"票号": 票A, "边缘": ["edge-a", "edge-b", "edge-c"]})
确认(票A, "edge-a", "vA@1")
确认(票A, "edge-b", "vA@1")
边缘门.写策略({"票号": 票A, "策略": "全员"})
核败 = 期望409(lambda: 边缘门.试放量({"票号": 票A, "策略": "全员"}), "全员 2/3 缺 edge-c")
check(核败.get("valid") is False, "全员核证 valid=False")
check(核败.get("门槛") == 3 and 核败.get("已确认") == 2, "全员门槛3/确认2")
check(核败.get("缺席边缘") == ["edge-c"], "全员核证列缺席 edge-c")
check(核败.get("名册") == ["edge-a", "edge-b", "edge-c"], "核证含完整名册")

# 同一票切多数：2/3 达标 → 成功
核胜 = 边缘门.试放量({"票号": 票A, "策略": "多数"})
check(核胜["valid"] is True and 核胜["放量"] is True, "多数 2/3 放量成功")
check(核胜["门槛"] == 2, "多数门槛=2")
check(核胜["缺席边缘"] == ["edge-c"], "多数成功仍列缺席 edge-c")
conn = 连接()
门 = conn.execute("SELECT * FROM 放量门 WHERE 票号=?", (票A,)).fetchone()
check(门["状态"] == "已放量", "放量门落库=已放量（非只返回 JSON）")
命运 = conn.execute(
    "SELECT COUNT(*) c FROM 命运账 WHERE 对象类型='放量门' AND 对象键=? AND 命运='放量'", (票A,)
).fetchone()["c"]
check(命运 >= 1, "放量成功落放量命运")
conn.close()

print("== 1 确认时乙也必须失败（3 名册 1 确认）==")
票B = "票-B"
建票(票B, "vB@1", "kB", "bB")
边缘门.写名册({"票号": 票B, "边缘": ["edge-a", "edge-b", "edge-c"]})
确认(票B, "edge-a", "vB@1")
乙多 = 期望409(lambda: 边缘门.试放量({"票号": 票B, "策略": "多数"}), "多数 1/3 乙失败")
check(乙多.get("门槛") == 2 and 乙多.get("已确认") == 1, "多数门槛2 仅确认1")
check(set(乙多.get("缺席边缘", [])) == {"edge-b", "edge-c"}, "乙缺席 b,c")
期望409(lambda: 边缘门.试放量({"票号": 票B, "策略": "全员"}), "全员 1/3 也失败")

print("== 补齐后甲（乙票）可升 ==")
确认(票B, "edge-b", "vB@1")
确认(票B, "edge-c", "vB@1")
升 = 边缘门.试放量({"票号": 票B, "策略": "全员"})
check(升["valid"] and 升["已确认"] == 3 and 升["缺席边缘"] == [], "补齐 3/3 全员放量")

print("== 空名册 fail-close，禁止无门槛放行 ==")
票C = "票-C"
建票(票C, "vC@1", "kC", "bC")
边缘门.写名册({"票号": 票C, "边缘": []})
期望409(lambda: 边缘门.试放量({"票号": 票C}), "空名册放量 fail-close")
conn = 连接()
check(conn.execute("SELECT 状态 FROM 放量门 WHERE 票号=?", (票C,)).fetchone()["状态"] != "已放量",
      "空名册未置已放量")
conn.close()

print("== 名册中途删人，门槛重算与放量门瞬时一致 ==")
票D = "票-D"
建票(票D, "vD@1", "kD", "bD")
边缘门.写名册({"票号": 票D, "边缘": ["e1", "e2", "e3", "e4"]})  # 多数门槛2
边缘门.写策略({"票号": 票D, "策略": "多数"})
r1 = 边缘门.写名册({"票号": 票D, "边缘": ["e1", "e2", "e3"]})      # 删 1 人 → 仍门槛2，版本 bump
check(r1["名册版本"] == 2, "删人 bump 名册版本=2")
v = 边缘门.票门槛视图(票D)
check(v["门槛"] == 2 and v["名册人数"] == 3 and v["名册版本"] == 2, "删人后门槛按现名册重算=2")
确认(票D, "e1", "vD@1")
确认(票D, "e2", "vD@1")
核D = 边缘门.试放量({"票号": 票D, "策略": "多数"})
conn = 连接()
门D = conn.execute("SELECT * FROM 放量门 WHERE 票号=?", (票D,)).fetchone()
check(门D["名册版本"] == 核D["名册版本"] == 2 and 门D["门槛"] == 核D["门槛"] == 2,
      "放量门快照与核证门槛/名册版本瞬时一致")
conn.close()

print("== 并发：名册变更 × 回读 × 放量，不得无核证放行 ==")
票E = "票-E"
建票(票E, "vE@1", "kE", "bE")
边缘门.写名册({"票号": 票E, "边缘": [f"e{i}" for i in range(5)]})
错误 = []


def 干活(tid):
    try:
        for i in range(15):
            选 = i % 3
            if 选 == 0:
                边缘门.写名册({"票号": 票E, "边缘": [f"e{j}" for j in range(5)]})
            elif 选 == 1:
                确认(票E, f"e{tid % 5}", "vE@1")
            else:
                try:
                    边缘门.试放量({"票号": 票E, "策略": "多数"})
                except HTTPException:
                    pass  # 409 门槛未达 / 503 锁冲突，均为 fail-close，合法
    except Exception as ex:  # noqa: BLE001
        错误.append(str(ex))


ts = [threading.Thread(target=干活, args=(i,)) for i in range(8)]
[t.start() for t in ts]
[t.join() for t in ts]
check(not 错误, f"并发无异常（fail-close 已吞合法冲突）:{错误[:1]}")
conn = 连接()
# 不变量：每个已放量门都有 valid 核证 + 放量命运；不存在 valid 核证却未放量
for g in conn.execute("SELECT * FROM 放量门 WHERE 状态='已放量'"):
    t = g["票号"]
    hv = conn.execute("SELECT 1 FROM 门槛核证 WHERE 票号=? AND valid=1", (t,)).fetchone()
    hf = conn.execute(
        "SELECT 1 FROM 命运账 WHERE 对象类型='放量门' AND 对象键=? AND 命运='放量'", (t,)
    ).fetchone()
    check(bool(hv) and bool(hf), f"并发后 {t} 已放量必有核证与命运")
    最新 = conn.execute(
        "SELECT * FROM 门槛核证 WHERE 票号=? ORDER BY 编号 DESC LIMIT 1", (t,)
    ).fetchone()
    check(最新["门槛"] == g["门槛"] and 最新["名册版本"] == g["名册版本"],
          f"并发后 {t} 核证门槛与放量门不漂移")
conn.close()

print("== 贯验协同 ==")
g = 贯验.跑贯验()
check(g["是否通过"] is True, f"全链路贯验通过：{g['说明']}")

print(f"\n全部通过 · {通过} 项断言")
