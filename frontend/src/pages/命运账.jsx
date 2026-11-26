import React, { useEffect, useState } from "react";
import { get, postFixture } from "../api.js";

export default function 命运账() {
  const [rows, setRows] = useState([]);
  const [核证, set核证] = useState([]);
  const [讯, set讯] = useState("");
  const 刷 = async () => {
    setRows(await get("/命运账"));
    set核证(await get("/门槛核证"));
  };
  useEffect(() => { 刷().catch((e) => set讯(String(e))); }, []);
  const 放量核证 = 核证.filter((r) => r.valid);
  return (
    <div>
      <h1 className="题">命运账</h1>
      <p className="述">回滚 / 失效 / 放量写命运。放量成功必须落放量命运，并可翻当时缺席边缘与门槛算法。</p>
      <div className="行">
        <button className="焰" onClick={async () => { await postFixture("回滚样例"); await 刷(); set讯("已灌回滚样例"); }}>灌回滚样例</button>
        <button className="次" onClick={() => 刷()}>刷新</button>
      </div>
      {讯 && <p className="讯">{讯}</p>}

      <h2 className="题" style={{ fontSize: 16 }}>放量命运 · 缺席边缘清单</h2>
      {!放量核证.length ? <div className="空态">尚无放量命运（门槛达标后落账）</div> : (
        <table>
          <thead><tr><th>票号</th><th>口径</th><th>门槛算法</th><th>确认/门槛/名册</th><th>缺席边缘</th></tr></thead>
          <tbody>{放量核证.map((r) => (
            <tr key={r.证号}><td>{r.票号}</td><td>{r.策略}</td>
            <td><code>{r.策略 === "多数" ? "上取整(n/2)" : "全员=n"}</code></td>
            <td>{r.已确认}/{r.门槛}/{r.名册人数}</td>
            <td><b>{(r.缺席边缘 || []).join(", ") || "无"}</b></td></tr>
          ))}</tbody>
        </table>
      )}

      <h2 className="题" style={{ fontSize: 16, marginTop: "1.2rem" }}>全量命运条</h2>
      {!rows.length ? <div className="空态">尚无命运条</div> : (
        <table>
          <thead><tr><th>#</th><th>对象类型</th><th>对象键</th><th>命运</th><th>时刻</th><th>说明</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.编号}><td>{r.编号}</td><td>{r.对象类型}</td><td>{r.对象键}</td>
            <td><span className="徽章 败">{r.命运}</span></td><td>{r.时刻}</td><td>{r.说明}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
