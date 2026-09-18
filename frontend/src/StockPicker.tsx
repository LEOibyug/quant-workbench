import { useState } from "react";

const original = ["NVDA", "TSLA", "AAPL", "AMD", "SOFI"];
const stocks = [
  ["NVDA", "英伟达"], ["TSLA", "特斯拉"], ["AAPL", "苹果"],
  ["AMD", "超威半导体"], ["SOFI", "SoFi"],
  ["MSFT", "微软"], ["AMZN", "亚马逊"], ["GOOGL", "Alphabet"],
  ["META", "Meta"], ["AVGO", "博通"], ["ORCL", "甲骨文"],
  ["JPM", "摩根大通"], ["V", "Visa"], ["MA", "万事达"],
  ["BRK.B", "伯克希尔 B"], ["WMT", "沃尔玛"], ["COST", "好市多"],
  ["JNJ", "强生"], ["LLY", "礼来"], ["XOM", "埃克森美孚"],
];

export function StockPicker({ disabled }: { disabled: boolean }) {
  const [value, setValue] = useState(original.join(","));
  const selected = [...new Set(value.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean))];
  return <fieldset disabled={disabled} style={{ gridColumn: "1 / -1" }}>
    <legend>主要美股候选池 · 20 支</legend>
    <div className="checks">{stocks.map(([symbol, name]) => <label key={symbol}>
      <input type="checkbox" checked={selected.includes(symbol)} onChange={(e) => setValue(
        (e.target.checked ? [...selected, symbol] : selected.filter((s) => s !== symbol)).join(","),
      )} />{symbol} · {name}
    </label>)}</div>
    <div className="replay-buttons">
      <button type="button" onClick={() => setValue(stocks.map(([s]) => s).join(","))}>选择全部 20 支</button>
      <button type="button" onClick={() => setValue(original.join(","))}>仅原有 5 支</button>
      <button type="button" onClick={() => setValue("")}>清空选择</button>
    </div>
    <label>股票代码（逗号分隔，可自行修改）
      <input name="symbols" value={value} onChange={(e) => setValue(e.target.value)} required />
    </label>
    <p className="muted">已选 {selected.length} 支，最多 20 支。勾选不会下载数据；点击“通过 API 下载”才会获取行情。
      新股票取得数据并完成策略验证、发布后，才会进入展示页的模拟列表。</p>
  </fieldset>;
}
