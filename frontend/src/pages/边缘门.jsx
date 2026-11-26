import React, { useEffect, useState } from "react";
import { get, post, postFixture } from "../api.js";

export default function 边缘门() {
  const [名册, set名册] = useState([]);
  const [门, set门] = useState([]);
  const [核证, set核证] = useState([]);
  const [视图, set视图] = useState(null);
  const [票号, set票号] = useState("票-checkout.new_tax@3-gray10");
  const [讯, set讯] = useState("");

  const 刷 = async () => {
    const [m, g, a] = await Promise.all([get("/边缘名册"), get("/放量门"), get("/门槛核证")]);
    set名册(m); set门(g); set核证(a);
  };
  useEffect(() => { 刷().catch((e) => set讯(String(e))); }, []);

  const 看门槛 = async () => {
    try { set视图(await get(`/门槛视图?票号=${encodeURIComponent(票号)}`)); set讯(""); }
    catch (e) { set讯(String(e)); }
  };
  const 切策略 = async (策略) => {
    try { await post("/门槛策略", { 票号, 策略 }); await 刷(); set讯(`已切 ${策略} 口径`); }
    catch (e) { set讯(String(e)); }
  };
  const 放量 = async () => {
    try { const r = await post("/放量", { 票号 }); set讯(`放量 ${r.成败}：${r.说明}`); }
    catch (e) { set讯(`放量被门槛拒绝：${e.message}`); }
    await 刷();
  };

  return (
    <div>
      <h1 className="题">边缘门 · 边缘名册门槛</h1>
      <p className="述">
        名册 / 确认集 / 放量同票。门槛只看齐套计数。<b>全员</b>缺一则失败；
        <b>多数</b>达上取整多数即可，核证列缺席边缘。放量成败都落核证，成功必落放量命运。
      </p>
      <div className="行">
        <button onClick={async () => { await postFixture("边缘名册样例"); await 刷(); set讯("已灌边缘名册样例（2/3 全员失败、多数成功、1 确认失败）"); }}>灌边缘名册样例</button>
        <button className="次" onClick={() => 刷()}>刷新</button>
      </div>

      <div className="行">
        <input value={票号} onChange={(e) => set票号(e.target.value)} placeholder="票号" style={{ minWidth: 280 }} />
        <button className="次" onClick={看门槛}>看门槛视图</button>
        <button className="次" onClick={() => 切策略("全员")}>切全员</button>
        <button className="次" onClick={() => 切策略("多数")}>切多数</button>
        <button className="焰" onClick={放量}>试放量</button>
      </div>
      {讯 && <p className="讯">{讯}</p>}

      {视图 && (
        <div className="卡">
          <div className="行">
            <b>{视图.票号}</b>
            <span className={"徽章 " + (视图.达标 ? "通" : "败")}>
              {视图.策略} · 门槛 {视图.门槛} · 确认 {视图.已确认}/{视图.名册人数}
            </span>
            <span className="徽章 次">{视图.放量状态}</span>
          </div>
          <div className="述">
            名册：{视图.名册.join(", ") || "（空）"}　|
            缺席边缘：<b>{视图.缺席边缘.join(", ") || "无"}</b>
            （名册版本 {视图.名册版本} / 策略版本 {视图.策略版本}）
          </div>
        </div>
      )}

      <h2 className="题" style={{ fontSize: 16 }}>放量门</h2>
      {!门.length ? <div className="空态">尚无放量门</div> : (
        <table>
          <thead><tr><th>票号</th><th>状态</th><th>门槛</th><th>名册版本</th><th>策略版本</th><th>更新时</th></tr></thead>
          <tbody>{门.map((r) => (
            <tr key={r.票号}><td>{r.票号}</td>
            <td><span className={"徽章 " + (r.状态 === "已放量" ? "通" : "败")}>{r.状态}</span></td>
            <td>{r.门槛}</td><td>{r.名册版本}</td><td>{r.策略版本}</td><td>{r.更新时}</td></tr>
          ))}</tbody>
        </table>
      )}

      <h2 className="题" style={{ fontSize: 16 }}>边缘名册</h2>
      {!名册.length ? <div className="空态">尚无名册</div> : (
        <table>
          <thead><tr><th>票号</th><th>边缘</th><th>名册版本</th><th>口径</th><th>策略版本</th></tr></thead>
          <tbody>{名册.map((r, i) => (
            <tr key={`${r.票号}-${r.边缘键}-${i}`}><td>{r.票号}</td><td>{r.边缘键}</td>
            <td>{r.名册版本}</td><td>{r.策略}</td><td>{r.策略版本}</td></tr>
          ))}</tbody>
        </table>
      )}

      <h2 className="题" style={{ fontSize: 16 }}>门槛核证（含缺席清单）</h2>
      {!核证.length ? <div className="空态">尚无核证</div> : (
        <table>
          <thead><tr><th>证号</th><th>票号</th><th>口径</th><th>确认/门槛/名册</th><th>缺席边缘</th><th>valid</th><th>说明</th></tr></thead>
          <tbody>{核证.map((r) => (
            <tr key={r.证号}><td><code>{r.证号}</code></td><td>{r.票号}</td><td>{r.策略}</td>
            <td>{r.已确认}/{r.门槛}/{r.名册人数}</td>
            <td>{(r.缺席边缘 || []).join(", ") || "无"}</td>
            <td><span className={"徽章 " + (r.valid ? "通" : "败")}>{r.成败}</span></td>
            <td>{r.说明}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
