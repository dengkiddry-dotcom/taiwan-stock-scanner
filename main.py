import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
import time
import os
import json


# ── 抓取中文名稱對照表 ────────────────────────────────────────
def fetch_name_map() -> dict:
    name_map = {}
    try:
        r = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
            timeout=10
        )
        for item in r.json():
            name_map[item["Code"]] = item["Name"]
        print(f"[名稱] 上市取得 {len(name_map)} 筆")
    except Exception as e:
        print(f"[名稱] 上市 API 失敗：{e}")
    try:
        r = requests.get(
            "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes",
            timeout=10
        )
        before = len(name_map)
        for item in r.json():
            name_map[item["SecuritiesCompanyCode"]] = item["CompanyName"]
        print(f"[名稱] 上櫃取得 {len(name_map)-before} 筆")
    except Exception as e:
        print(f"[名稱] 上櫃 API 失敗：{e}")
    return name_map


# ── 股票清單 ─────────────────────────────────────────────────
def get_list():
    tw = [
        "1101","1102","1216","1301","1303","1402","1503","1504","1513","1514",
        "1519","1605","1608","1609","1611","1722","1773","2002","2006","2301",
        "2303","2308","2313","2317","2324","2327","2330","2337","2344","2352",
        "2353","2356","2357","2360","2367","2368","2371","2376","2377","2379",
        "2382","2383","2385","2395","2408","2409","2412","2449","2451","2454",
        "2458","2474","2498","2542","2603","2606","2609","2610","2615","2618",
        "2880","2881","2882","2883","2884","2885","2886","2887","2890","2891",
        "2892","3005","3008","3017","3019","3023","3034","3035","3037","3044",
        "3045","3231","3406","3443","3481","3576","3653","3661","3702","3711",
        "4904","4915","4919","4938","4958","5269","5871","5880","6239","6278",
        "6414","6415","6505","6669","8046"
    ]
    two = [
        "1560","1580","1590","1785","1795","1815","2233","3068","3078","3081",
        "3105","3131","3141","3163","3207","3211","3217","3218","3227","3228",
        "3234","3260","3264","3289","3293","3324","3363","3376","3455","3491",
        "3511","3526","3529","3546","3548","3558","3580","3587","3592","3611",
        "3624","3664","3680","4105","4107","4114","4123","4128","4162","4303",
        "4510","4513","4528","4533","4541","4721","4736","4743","4760","4908",
        "4909","4931","4944","4953","4966","4979","5009","5211","5227","5274",
        "5289","5309","5347","5351","5371","5381","5425","5439","5443","5457",
        "5478","5483","5512","6104","6111","6121","6125","6138","6143","6146",
        "6147","6150","6170","6173","6180","6182","6185","6187","6188","6208",
        "6217","6219","6223","6231","6233","6237","6244","6245","6261","6266",
        "6274","6275","6276","6279","6284","6290","6411","6417","6418","6435",
        "6441","6446","6462","6472","6485","6488","6496","6510","6532","6548",
        "6561","6568","6589","6613","6643","6654","6679","6683","6732","6741",
        "8027","8044","8054","8064","8069","8076","8085","8086","8091","8096",
        "8111","8155","8255","8299","8358","8415","8436","8916","8936","8938"
    ]
    return [f"{c}.TW" for c in tw] + [f"{c}.TWO" for c in two]


# ── K 線圖 HTML ──────────────────────────────────────────────
def generate_chart_html(symbol, name, df, limit_days, is_washing, wash_info):
    code   = symbol.split('.')[0]
    market = "上市" if symbol.endswith(".TW") else "上櫃"

    records = []
    limit_set = {d.strftime('%Y-%m-%d') for d in limit_days}
    for idx, row in df.iterrows():
        records.append({
            "date":   idx.strftime('%m/%d'),
            "open":   round(float(row['Open']),  2),
            "high":   round(float(row['High']),  2),
            "low":    round(float(row['Low']),   2),
            "close":  round(float(row['Close']), 2),
            "volume": int(row['Volume']),
            "limit":  idx.strftime('%Y-%m-%d') in limit_set,
        })

    data_json   = json.dumps(records, ensure_ascii=False)
    last_close  = records[-1]['close'] if records else 0
    limit_count = len(limit_days)
    status_html = (
        "<span style='background:#d93025;color:#fff;padding:3px 10px;"
        "border-radius:5px;font-weight:700;'>🔥 準備起飛</span>"
        if is_washing else
        "<span style='background:#444;color:#ccc;padding:3px 10px;"
        "border-radius:5px;'>📊 盤整觀察</span>"
    )

    vol_ratio  = wash_info.get('vol_ratio', '-')
    ma20_ok    = "✅ 站上月線" if wash_info.get('above_ma20') else "❌ 跌破月線"
    hold_low   = "✅ 守住起漲點" if wash_info.get('hold_low') else "❌ 跌破起漲點"

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{code} {name} K線圖</title>
<style>
  :root {{
    --bg:#0d1117; --panel:#161b22; --border:#30363d;
    --text:#e6edf3; --muted:#8b949e;
    --up:#26a641; --down:#f85149; --limit:#ffa500; --accent:#58a6ff;
  }}
  *{{ box-sizing:border-box; margin:0; padding:0; }}
  body{{ background:var(--bg); color:var(--text);
         font-family:'SF Mono','Fira Code',monospace; padding:24px; }}
  .header{{ display:flex; align-items:baseline; gap:14px; margin-bottom:18px; flex-wrap:wrap; }}
  .code{{ font-size:2rem; font-weight:700; color:var(--accent); }}
  .name{{ font-size:1.1rem; color:var(--text); font-weight:500; }}
  .tag{{ font-size:.8rem; background:var(--panel); border:1px solid var(--border);
          border-radius:4px; padding:3px 9px; color:var(--muted); }}
  .stats{{ display:flex; gap:20px; background:var(--panel); border:1px solid var(--border);
           border-radius:8px; padding:14px 20px; margin-bottom:18px; flex-wrap:wrap; }}
  .stat{{ display:flex; flex-direction:column; gap:4px; }}
  .s-label{{ font-size:.68rem; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }}
  .s-val{{ font-size:1rem; font-weight:600; }}
  .wash-info{{ background:var(--panel); border:1px solid var(--border); border-radius:8px;
               padding:14px 20px; margin-bottom:18px; font-size:.85rem; line-height:2; }}
  .wrap{{ background:var(--panel); border:1px solid var(--border);
          border-radius:8px; padding:14px; margin-bottom:12px; position:relative; }}
  canvas{{ display:block; width:100%; cursor:crosshair; }}
  #tip{{ position:absolute; background:#1c2128; border:1px solid var(--border);
         border-radius:6px; padding:10px 14px; font-size:.78rem; pointer-events:none;
         display:none; z-index:10; line-height:1.9; min-width:130px; }}
  .legend{{ display:flex; gap:18px; font-size:.72rem; color:var(--muted); margin-top:8px; }}
  .dot{{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; }}
  .vol-title{{ font-size:.68rem; color:var(--muted); text-transform:uppercase;
               letter-spacing:.06em; margin-bottom:8px; }}
</style>
</head>
<body>

<div class="header">
  <div class="code">📊 {code}</div>
  <div class="name">{name}</div>
  <div class="tag">{market}</div>
</div>

<div class="stats">
  <div class="stat">
    <span class="s-label">最新收盤</span>
    <span class="s-val" style="color:var(--accent)">{last_close}</span>
  </div>
  <div class="stat">
    <span class="s-label">漲停次數（近10交易日）</span>
    <span class="s-val"><span style="background:var(--limit);color:#000;font-weight:700;padding:2px 10px;border-radius:4px">🔥 {limit_count} 次</span></span>
  </div>
  <div class="stat">
    <span class="s-label">洗盤狀態</span>
    <span class="s-val">{status_html}</span>
  </div>
</div>

<div class="wash-info">
  <strong>洗盤指標</strong><br>
  今日量 / 漲停量：<b>{vol_ratio}</b>（&lt;50% 視為縮量）&nbsp;&nbsp;
  {ma20_ok}&nbsp;&nbsp;{hold_low}
</div>

<div class="wrap">
  <canvas id="kc"></canvas>
  <div id="tip"></div>
</div>
<div class="legend">
  <span><span class="dot" style="background:var(--up)"></span>上漲</span>
  <span><span class="dot" style="background:var(--down)"></span>下跌</span>
  <span><span class="dot" style="background:var(--limit)"></span>漲停</span>
</div>

<div class="wrap" style="padding:12px 14px; margin-top:12px;">
  <div class="vol-title">成交量</div>
  <canvas id="vc"></canvas>
</div>

<script>
const DATA = {data_json};
const DPR  = window.devicePixelRatio || 1;

function setup(canvas, h) {{
  const w = canvas.parentElement.clientWidth - 28;
  canvas.style.width  = w + 'px';
  canvas.style.height = h + 'px';
  canvas.width  = w * DPR;
  canvas.height = h * DPR;
  const ctx = canvas.getContext('2d');
  ctx.scale(DPR, DPR);
  return {{ ctx, w, h }};
}}

function draw() {{
  const kcan = document.getElementById('kc');
  const vcan = document.getElementById('vc');
  const tip  = document.getElementById('tip');
  const {{ ctx:kc, w, h:kh }} = setup(kcan, 340);
  const {{ ctx:vc, h:vh }} = setup(vcan, 80);

  const n=DATA.length, PL=10, PR=52, PT=20, PB=30;
  const cw=w-PL-PR, ch=kh-PT-PB;
  const gap=cw/n, bw=Math.max(2,gap-3);

  const UP='#26a641', DN='#f85149', LM='#ffa500', MU='#8b949e', GR='#21262d';

  const pMin = Math.min(...DATA.map(d=>d.low))  * 0.995;
  const pMax = Math.max(...DATA.map(d=>d.high)) * 1.005;
  const pr   = pMax - pMin;
  const py   = v => PT + ch - ((v - pMin) / pr) * ch;

  // grid
  for(let i=0;i<=5;i++) {{
    const p=pMin+(pr/5)*i, y=py(p);
    kc.strokeStyle=GR; kc.lineWidth=1;
    kc.beginPath(); kc.moveTo(PL,y); kc.lineTo(w-PR,y); kc.stroke();
    kc.fillStyle=MU; kc.font='10px SF Mono,monospace'; kc.textAlign='left';
    kc.fillText(p.toFixed(1), w-PR+4, y+4);
  }}

  // date labels
  const step=Math.max(1,Math.floor(n/6));
  DATA.forEach((d,i) => {{
    if(i%step!==0) return;
    const x=PL+i*gap+gap/2;
    kc.fillStyle=MU; kc.font='10px SF Mono,monospace'; kc.textAlign='center';
    kc.fillText(d.date, x, kh-6);
  }});

  // candles
  DATA.forEach((d,i) => {{
    const x=PL+i*gap+gap/2;
    const col=d.limit?LM:(d.close>=d.open?UP:DN);
    kc.strokeStyle=col; kc.lineWidth=1;
    kc.beginPath(); kc.moveTo(x,py(d.high)); kc.lineTo(x,py(d.low)); kc.stroke();
    const y1=py(Math.max(d.open,d.close)), y2=py(Math.min(d.open,d.close));
    kc.fillStyle=col; kc.fillRect(x-bw/2, y1, bw, Math.max(1,y2-y1));
    if(d.limit) {{
      kc.fillStyle=LM; kc.font='bold 11px sans-serif'; kc.textAlign='center';
      kc.fillText('🔥', x, py(d.high)-6);
    }}
  }});

  // volume
  const volMax=Math.max(...DATA.map(d=>d.volume));
  DATA.forEach((d,i) => {{
    const x=PL+i*gap+gap/2;
    const col=d.limit?LM:(d.close>=d.open?UP:DN);
    const bh=(d.volume/volMax)*(vh-10);
    vc.fillStyle=col+'aa';
    vc.fillRect(x-bw/2, vh-bh, bw, bh);
  }});

  // tooltip
  kcan.onmousemove = e => {{
    const r=kcan.getBoundingClientRect();
    const i=Math.round((e.clientX-r.left-PL)/gap-0.5);
    if(i<0||i>=n) {{ tip.style.display='none'; return; }}
    const d=DATA[i];
    const col=d.limit?'#ffa500':(d.close>=d.open?'#26a641':'#f85149');
    const chg=((d.close-d.open)/d.open*100).toFixed(2);
    tip.innerHTML=`<div style="color:#8b949e;margin-bottom:4px">${{d.date}}</div>
      <div>開 <b>${{d.open}}</b></div>
      <div>高 <b>${{d.high}}</b></div>
      <div>低 <b>${{d.low}}</b></div>
      <div>收 <b style="color:${{col}}">${{d.close}}</b> (${{chg>0?'+':''}}${{chg}}%)</div>
      <div>量 <b>${{(d.volume/1000).toFixed(0)}}K</b></div>
      ${{d.limit?'<div style="color:#ffa500;font-weight:700;margin-top:4px">🔥 漲停</div>':''}}`;
    tip.style.display='block';
    const tx=e.clientX-r.left+14;
    tip.style.left=(tx+130>w?tx-150:tx)+'px';
    tip.style.top='24px';
  }};
  kcan.onmouseleave = () => tip.style.display='none';
}}

draw();
window.addEventListener('resize', draw);
</script>
</body>
</html>"""


# ── 掃描主函式 ───────────────────────────────────────────────
def scan(output_dir="charts"):
    os.makedirs(output_dir, exist_ok=True)

    print("[名稱] 正在抓取中文名稱對照表...")
    name_map = fetch_name_map()

    stocks      = get_list()
    today       = datetime.now()
    fetch_start = today - timedelta(days=60)   # 多抓保證涵蓋足夠交易日
    fetch_end   = today
    results     = []
    total       = len(stocks)

    print(f"[掃描] 共 {total} 支，條件：前 3~10 交易日漲停 + 縮量洗盤判定")

    for i, s in enumerate(stocks):
        try:
            if i % 20 == 0 and i > 0:
                print(f"[進度] {i}/{total}，暫停 3 秒...")
                time.sleep(3)

            df = yf.download(s, start=fetch_start, end=fetch_end, progress=False)
            if df.empty or len(df) < 20:
                continue

            # 修正 MultiIndex（新版 yfinance）—— 必須在取欄位之前
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            close  = df['Close'].squeeze()
            volume = df['Volume'].squeeze()
            open_  = df['Open'].squeeze()

            if not isinstance(close, pd.Series):
                continue

            pct          = close.pct_change()
            trading_days = close.index
            n_td         = len(trading_days)

            # ── 第一關：前 3~10 個交易日內有漲停 ──────────────
            lo = max(0, n_td - 10)
            hi = max(0, n_td - 3)
            if lo >= hi:
                continue

            window_dates = set(trading_days[lo:hi].strftime('%Y-%m-%d'))
            all_limit    = pct[pct >= 0.098].index
            limit_days   = all_limit[all_limit.strftime('%Y-%m-%d').isin(window_dates)]

            if limit_days.empty:
                continue

            # 取最後一次漲停日的資料
            last_limit_date = limit_days[-1]
            limit_vol  = float(volume.loc[last_limit_date])
            limit_low  = float(open_.loc[last_limit_date])   # 漲停日開盤 = 起漲點

            curr_price = float(close.iloc[-1])
            curr_vol   = float(volume.iloc[-1])
            ma20       = float(close.rolling(20).mean().iloc[-1])

            # ── 第二關：洗盤三條件 ─────────────────────────────
            shrink    = curr_vol < limit_vol * 0.5   # 縮量：今日量 < 漲停量一半
            hold_low  = curr_price >= limit_low       # 守住起漲點（漲停日開盤價）
            above_ma  = curr_price > ma20             # 站上 20 日均線

            is_washing = shrink and hold_low and above_ma

            vol_ratio_pct = f"{round((curr_vol / limit_vol) * 100)}%"
            days_since    = (today - last_limit_date.to_pydatetime()).days

            code   = s.split('.')[0]
            market = "上市" if s.endswith(".TW") else "上櫃"
            name   = name_map.get(code, "")

            # 產生 K 線圖
            chart_file = os.path.join(output_dir, f"{code}.html")
            wash_info  = {
                "vol_ratio":  vol_ratio_pct,
                "above_ma20": above_ma,
                "hold_low":   hold_low,
            }
            with open(chart_file, "w", encoding="utf-8") as f:
                f.write(generate_chart_html(s, name, df, list(limit_days), is_washing, wash_info))

            dates = [d.strftime('%m/%d') for d in limit_days]
            results.append({
                "_sort": 0 if is_washing else 1,
                "代碼": (
                    f"<a href='{chart_file}' target='_blank' "
                    f"style='color:#58a6ff;font-weight:700;text-decoration:none'>"
                    f"{code} 📊</a>"
                ),
                "名稱":      name,
                "市場":      market,
                "狀態":      "<span style='background:#d93025;color:#fff;padding:3px 9px;border-radius:5px;font-weight:700'>🔥 準備起飛</span>" if is_washing else "<span style='background:#444;color:#ccc;padding:3px 9px;border-radius:5px'>📊 盤整觀察</span>",
                "洗盤量比":   vol_ratio_pct,
                "距漲停天數": days_since,
                "收盤價":    round(curr_price, 2),
                "漲停軌跡":   " / ".join(dates),
            })

        except Exception as e:
            print(f"[{s}] 錯誤：{e}")
            continue

    print(f"[完成] 掃描 {total} 支，命中 {len(results)} 支")
    return pd.DataFrame(results)


# ── 輸出主報表 HTML ──────────────────────────────────────────
def to_html(df, output_file="index.html"):
    t = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

    if not df.empty:
        df_sorted  = df.sort_values(['_sort', '洗盤量比']).drop(columns='_sort')
        table_html = df_sorted.to_html(index=False, escape=False)
        fire_count = (df['_sort'] == 0).sum()
        count_info = (
            f"<p class='count'>共找到 <strong>{len(df)}</strong> 支符合條件"
            f"，其中 <strong style='color:#d93025'>{fire_count} 支</strong> 🔥 準備起飛"
            f"&nbsp;｜&nbsp; 點擊代碼查看 K 線圖</p>"
        )
    else:
        table_html = "<div class='empty'>⚠️ 目前無符合條件標的</div>"
        count_info = ""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>漲停洗盤起飛偵測</title>
  <style>
    :root{{--bg:#0d1117;--panel:#161b22;--border:#30363d;
          --text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--fire:#d93025;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{background:var(--bg);color:var(--text);
         font-family:'SF Mono','Fira Code',monospace;padding:32px 24px;}}
    h1{{font-size:1.6rem;margin-bottom:6px;}}
    h1 span{{color:var(--accent);}}
    .meta{{color:var(--muted);font-size:.78rem;margin-bottom:14px;}}
    .count{{color:var(--muted);font-size:.82rem;margin-bottom:16px;}}
    .count strong{{color:var(--fire);}}
    .hint{{background:var(--panel);border:1px solid var(--border);border-radius:8px;
           padding:16px 20px;margin-bottom:20px;font-size:.8rem;line-height:2;color:var(--muted);}}
    .hint b{{color:var(--text);}}
    table{{width:100%;border-collapse:collapse;background:var(--panel);
           border:1px solid var(--border);border-radius:8px;overflow:hidden;}}
    th{{background:#1c2128;color:var(--muted);font-size:.68rem;
        text-transform:uppercase;letter-spacing:.06em;
        padding:12px 16px;text-align:center;border-bottom:1px solid var(--border);}}
    td{{padding:12px 16px;text-align:center;
        border-bottom:1px solid var(--border);font-size:.88rem;}}
    tr:last-child td{{border-bottom:none;}}
    tr:hover td{{background:#1c2128;}}
    .empty{{padding:40px;text-align:center;color:var(--muted);}}
  </style>
</head>
<body>
  <h1>🚀 漲停縮量 <span>洗盤起飛</span> 偵測系統</h1>
  <p class="meta">台北時間：{t}　｜　選股區間：前 3~10 個交易日</p>
  {count_info}
  <div class="hint">
    <b>💡 選股邏輯</b><br>
    第一關：前 3~10 個交易日內出現漲停（≥9.8%）<br>
    第二關（洗盤三條件同時成立）：<br>
    &nbsp;&nbsp;① 今日成交量 &lt; 漲停日成交量 × 50%（主力縮手鎖碼）<br>
    &nbsp;&nbsp;② 今日股價 ≥ 漲停日開盤價（守住起漲點，不破底）<br>
    &nbsp;&nbsp;③ 今日股價 &gt; 20 日均線（大趨勢向上）<br>
    🔥 三條件全符合 → <b>準備起飛</b>　｜　未全符合 → <b>盤整觀察</b>
  </div>
  {table_html}
</body>
</html>"""

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[輸出] {output_file} 已產生")


# ── 入口 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    df = scan(output_dir="charts")
    to_html(df, output_file="index.html")
