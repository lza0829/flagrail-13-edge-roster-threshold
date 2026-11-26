import React, { useEffect, useState } from "react";
import { get, postFixture } from "../api.js";

export default function 回读台() {
  const [rows, setRows] = useState([]);
  const [核证, set核证] = useState([]);
  const [讯, set讯] = useState("");
  const 刷 = async () => {
    setRows(await get("/回读证"));
    set核证(await get("/门槛核证"));
  };
  useEffect(() => { 刷().catch((e) => set讯(String(e))); }, []);
  return (
    <div>
      <h1 className="题">回读台</h1>
      <p className="述">边缘对下发票的确认。所见版本与票面不一致 → 记「偏差」。名册门槛据此齐套计数，并翻缺席边缘。</p>
      <div className="行">
        <button onClick={async () => { await postFixture("回读样例"); await 刷(); set讯("已灌回读样例"); }}>灌回读样例</button>
        <button className="次" onClick={() => 刷()}>刷新</button>
      </div>
      {讯 && <p className="讯">{讯}</p>}
      {!rows.length ? <div className="空态">尚无回读证</div> : (
        <table>
          <thead><tr><th>证号</th><th>票号</th><th>边缘</th><th>所见版本</th><th>结果</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.证号}><td>{r.证号}</td><td>{r.票号}</td><td>{r.边缘键}</td>
            <td>{r.所见版本键}</td>
            <td><span className={"徽章 " + (r.结果 === "确认" ? "通" : "败")}>{r.结果}</span></td></tr>
          ))}</tbody>
        </table>
      )}

      <h2 className="题" style={{ fontSize: 16, marginTop: "1.2rem" }}>门槛核证 · 缺席清单</h2>
      {!核证.length ? <div className="空态">尚无门槛核证（见边缘门）</div> : (
        <table>
          <thead><tr><th>票号</th><th>口径</th><th>确认/门槛/名册</th><th>缺席边缘</th><th>valid</th></tr></thead>
          <tbody>{核证.map((r) => (
            <tr key={r.证号}><td>{r.票号}</td><td>{r.策略}</td>
            <td>{r.已确认}/{r.门槛}/{r.名册人数}</td>
            <td><b>{(r.缺席边缘 || []).join(", ") || "无"}</b></td>
            <td><span className={"徽章 " + (r.valid ? "通" : "败")}>{r.成败}</span></td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
