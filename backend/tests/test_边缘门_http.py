"""边缘名册门槛 HTTP 层自动化（FastAPI TestClient，独立临时库）。"""
import os
import sys
import tempfile

sys.path.insert(0, "/workspace/backend")
os.environ["数据目录"] = tempfile.mkdtemp(prefix="flagrail-http-")
os.environ["夹具目录"] = "/workspace/fixtures"

from fastapi.testclient import TestClient  # noqa: E402

from app import seed  # noqa: E402
from app.main import app  # noqa: E402

seed.初始化库()
c = TestClient(app)
n = 0


def check(cond, 名):
    global n
    assert cond, f"FAIL: {名}"
    n += 1
    print(f"  ok · {名}")


r = c.get("/api/健康")
check(r.status_code == 200 and r.json()["正常"] is True, "健康")

# 自包含夹具：前置入轨/分桶/下发 + 名册/确认/放量编排
r = c.post("/api/装载/夹具", params={"名": "边缘名册样例"})
check(r.status_code == 200, f"夹具装载 200（{r.status_code}）")
报告 = r.json()["报告"]
放量步 = [s for s in 报告["步骤"] if s["步"] == "放量"]
check(len(放量步) == 3, "三次放量尝试")
第一票 = [s for s in 放量步 if s["结果"]["票号"] == "票-checkout.new_tax@3-gray10"]
check(第一票[0]["HTTP"] == 409 and 第一票[0]["结果"]["valid"] is False,
      "2/3 全员放量失败 409 且带核证")
check(第一票[0]["结果"]["缺席边缘"] == ["edge-c"], "失败核证列缺席 edge-c")
check(第一票[1]["结果"]["valid"] is True and 第一票[1]["结果"]["放量"] is True,
      "同票切多数 2/3 放量成功（口径分叉可区分）")
乙 = [s for s in 放量步 if s["结果"]["票号"] == "票-rm.edge@1-gray5"][0]
check(乙["HTTP"] == 409 and 乙["结果"]["已确认"] == 1 and 乙["结果"]["门槛"] == 3,
      "1 确认时乙全员失败")

# GET 端点
r = c.get("/api/放量门")
check(r.status_code == 200 and len(r.json()) == 2, "放量门列表")
check(any(g["状态"] == "已放量" for g in r.json()), "存在已放量门")
r = c.get("/api/门槛核证")
核证 = r.json()
check(r.status_code == 200 and len(核证) >= 3, "核证列表含多次记录")
for a in 核证:
    for k in ("名册", "已确认", "门槛", "缺席边缘", "valid", "策略"):
        check(k in a, f"核证字段齐备:{k}")
r = c.get("/api/门槛视图", params={"票号": "票-rm.edge@1-gray5"})
v = r.json()
check(v["名册人数"] == 3 and v["已确认"] == 1 and v["缺席边缘"] == ["edge-b", "edge-c"],
      "门槛视图翻缺席清单")
r = c.get("/api/边缘名册")
check(r.status_code == 200 and len(r.json()) >= 6, "名册落表")

# 放量成功必落放量命运（禁止只返回 JSON）
r = c.get("/api/命运账")
放量命运 = [x for x in r.json() if x["对象类型"] == "放量门" and x["命运"] == "放量"]
check(len(放量命运) >= 1 and "缺席边缘" in 放量命运[0]["说明"],
      "放量命运记下缺席边缘与门槛算法")

# 缺策略/字段错误 → 422/400，不允许脏口径
r = c.post("/api/门槛策略", json={"票号": "票-rm.edge@1-gray5", "策略": "拍脑袋"})
check(r.status_code == 400, f"非法策略 400（{r.status_code}）")

# 无主票名册 → 400
r = c.post("/api/边缘名册", json={"票号": "票-不存在", "边缘": ["x"]})
check(r.status_code == 400, "无主票名册拒绝")

# 补齐乙票后可全员放量
for e in ("edge-b", "edge-c"):
    rr = c.post("/api/回读", json={
        "票号": "票-rm.edge@1-gray5", "边缘键": e,
        "所见版本键": "rm.edge@1", "结果": "确认"})
    check(rr.status_code == 200, f"补齐确认 {e}")
r = c.post("/api/放量", json={"票号": "票-rm.edge@1-gray5"})
check(r.status_code == 200 and r.json()["valid"] is True, "补齐后全员放量成功")

# 空名册 fail-close：新建票+空名册
c.post("/api/入轨", json={"版本": [{"开关键": "kEmpty", "版本号": 1, "版本键": "kEmpty@1"}]})
c.post("/api/分桶", json={"桶键": "bEmpty", "开关键": "kEmpty", "桶类型": "名单", "规则": {}})
c.post("/api/下发", json={"票号": "票-empty", "版本键": "kEmpty@1", "桶键": "bEmpty"})
c.post("/api/边缘名册", json={"票号": "票-empty", "边缘": []})
r = c.post("/api/放量", json={"票号": "票-empty"})
check(r.status_code == 409 and r.json()["detail"]["valid"] is False,
      "空名册放量 fail-close 且仍落核证")

# 贯验协同通过
r = c.post("/api/贯验")
check(r.json()["是否通过"] is True, f"贯验通过：{r.json()['说明']}")

# 总览含新刻度
r = c.get("/api/总览")
for k in ("边缘名册票", "放量门", "已放量", "门槛核证", "核证通过"):
    check(k in r.json(), f"总览刻度:{k}")

# 空桩表：本模块已实现
r = c.get("/api/空桩")
行 = {x["名"]: x["状态"] for x in r.json()}
check(行.get("边缘名册门槛") == "已实现", "空桩标记为已实现")

print(f"\nHTTP 层全部通过 · {n} 项断言")
