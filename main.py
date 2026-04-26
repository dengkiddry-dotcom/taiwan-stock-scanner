import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
import time
import os
import json

# ── 台股漲停價計算（含跳動價位）────────────────────────────────
def calc_limit_price(prev_close: float) -> float:
    """依台股跳動價位規則計算漲停價"""
    raw = prev_close * 1.1

    # 依跳動單位無條件捨去
    if raw < 10:
        tick = 0.01
    elif raw < 50:
        tick = 0.05
    elif raw < 100:
        tick = 0.1
    elif raw < 500:
        tick = 0.5
    elif raw < 1000:
        tick = 1.0
    elif raw < 5000:
        tick = 5.0
    else:
        tick = 10.0

    import math
    return math.floor(raw / tick) * tick


# ── 抓取中文名稱對照表 ────────────────────────────────────────
def fetch_name_map() -> dict:
    name_map = {}
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=10)
        for item in r.json():
            name_map[item["Code"]] = item["Name"]
        print(f"[名稱] 上市取得 {len(name_map)} 筆")
    except Exception as e:
        print(f"[名稱] 上市 API 失敗：{e}")
    try:
        r = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=10)
        before = len(name_map)
        for item in r.json():
            name_map[item["SecuritiesCompanyCode"]] = item["CompanyName"]
        print(f"[名稱] 上櫃取得 {len(name_map)-before} 筆")
    except Exception as e:
        print(f"[名稱] 上櫃 API 失敗：{e}")
    return name_map



# ── K 線型態分析 ─────────────────────────────────────────────
def analyze_pattern(df: pd.DataFrame, limit_days: list) -> dict:
    """分析 K 線型態，回傳評分與說明"""
    score  = 0
    notes  = []

    if df.empty or len(df) < 5:
        return {"score": 0, "notes": ["資料不足"], "limit_quality": "未知"}

    close  = df['Close'].squeeze()
    open_  = df['Open'].squeeze()
    high   = df['High'].squeeze()
    low    = df['Low'].squeeze()
    volume = df['Volume'].squeeze()

    # ── 漲停板品質 ────────────────────────────────────────────
    limit_quality = "未知"
    if limit_days:
        last_ld = limit_days[-1]
        try:
            o = float(open_.loc[last_ld])
            h = float(high.loc[last_ld])
            c = float(close.loc[last_ld])
            prev_close = float(close.iloc[list(close.index).index(last_ld) - 1])
            limit_price = calc_limit_price(prev_close)

            if o >= limit_price * 0.999:
                limit_quality = "一字板（最強）"
                score += 30
                notes.append("✅ 一字漲停板，主力意圖最強")
            elif (h - o) / o < 0.02:
                limit_quality = "開盤即拉板（強）"
                score += 20
                notes.append("✅ 開盤快速拉至漲停，籌碼集中")
            else:
                limit_quality = "盤中拉板（普通）"
                score += 10
                notes.append("⚠️ 盤中才拉漲停，主力意圖較弱")
        except Exception:
            limit_quality = "無法判斷"

    # ── 洗盤天數與量能趨勢 ────────────────────────────────────
    if limit_days:
        last_ld  = limit_days[-1]
        try:
            li       = list(close.index).index(last_ld)
            wash_vol = volume.iloc[li+1:]  # 漲停後的量
            wash_days = len(wash_vol)

            if 2 <= wash_days <= 6:
                score += 15
                notes.append(f"✅ 洗盤 {wash_days} 天，天數適中（黃金區間 2~6 天）")
            elif wash_days == 1:
                score += 8
                notes.append("⚠️ 洗盤僅 1 天，可能尚未完成")
            else:
                score += 5
                notes.append(f"⚠️ 洗盤 {wash_days} 天，時間偏長熱度可能已散")

            # 量能是否逐步萎縮
            if len(wash_vol) >= 2:
                is_shrinking = all(
                    wash_vol.iloc[i] >= wash_vol.iloc[i+1]
                    for i in range(len(wash_vol)-1)
                )
                if is_shrinking:
                    score += 15
                    notes.append("✅ 洗盤期量能逐日遞減，主力鎖碼明顯")
                else:
                    notes.append("⚠️ 洗盤期量能不穩定，需觀察")
        except Exception:
            pass

    # ── 近期 K 棒型態（最後 3 根）────────────────────────────
    recent = df.iloc[-3:]
    for idx, row in recent.iterrows():
        o = float(row['Open'])
        h = float(row['High'])
        l = float(row['Low'])
        c = float(row['Close'])
        body    = abs(c - o)
        rng     = h - l if h != l else 0.001
        upper   = h - max(o, c)
        lower   = min(o, c) - l

        # 錘子線（下影線長，實體小，出現在低位）
        if lower > body * 2 and upper < body * 0.5 and rng > 0:
            score += 10
            notes.append(f"✅ {idx.strftime('%m/%d')} 出現錘子線，止跌訊號")

        # 吞噬（今日陽線實體吞掉昨日陰線）
        if len(recent) >= 2:
            prev_idx = recent.index[list(recent.index).index(idx) - 1] if idx != recent.index[0] else None
            if prev_idx is not None:
                po = float(recent.loc[prev_idx, 'Open'])
                pc = float(recent.loc[prev_idx, 'Close'])
                if pc < po and c > o and c > po and o < pc:
                    score += 12
                    notes.append(f"✅ {idx.strftime('%m/%d')} 多頭吞噬，強力止跌")

        # 十字星（實體極小，觀望訊號）
        if body / rng < 0.1:
            notes.append(f"⚠️ {idx.strftime('%m/%d')} 十字星，多空拉鋸中")

    # ── 均線多頭排列 ─────────────────────────────────────────
    ma5  = float(close.rolling(5).mean().iloc[-1])
    ma10 = float(close.rolling(10).mean().iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    curr = float(close.iloc[-1])

    if curr > ma5 > ma10 > ma20:
        score += 15
        notes.append("✅ 均線多頭排列（價 > MA5 > MA10 > MA20）")
    elif curr > ma10 > ma20:
        score += 8
        notes.append("⚠️ 部分均線多頭（價 > MA10 > MA20）")
    else:
        notes.append("❌ 均線排列不佳，趨勢偏弱")

    # ── 洗盤加分（由外部傳入）─────────────────────────────
    # 由 scan() 呼叫後再加分，這裡先佔位

    # ── 評分等級 ────────────────────────────────────────────
    if score >= 70:
        grade = "🔥🔥 極強"
    elif score >= 50:
        grade = "🔥 強"
    elif score >= 30:
        grade = "⚠️ 普通"
    else:
        grade = "❌ 弱"

    return {
        "score":         score,
        "grade":         grade,
        "notes":         notes,
        "limit_quality": limit_quality,
        "ma5":           round(ma5,  2),
        "ma10":          round(ma10, 2),
        "ma20":          round(ma20, 2),
    }


# ── K 線圖 HTML ──────────────────────────────────────────────
def generate_chart_html(symbol, name, df, limit_days, is_washing, wash_info, pattern):
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

    # 計算均線
    closes = [r['close'] for r in records]
    def ma(n):
        result = []
        for i in range(len(closes)):
            if i < n - 1:
                result.append(None)
            else:
                result.append(round(sum(closes[i-n+1:i+1]) / n, 2))
        return result

    ma5_vals  = ma(5)
    ma10_vals = ma(10)
    ma20_vals = ma(20)
    ma60_vals  = ma(60)
    ma240_vals = ma(240)

    # 計算 KD（9日隨機指標）
    highs  = [r['high']  for r in records]
    lows   = [r['low']   for r in records]
    closes = [r['close'] for r in records]
    n_kd   = 9
    k_vals = []
    d_vals = []
    prev_k = 50.0
    prev_d = 50.0
    for j in range(len(records)):
        if j < n_kd - 1:
            k_vals.append(None)
            d_vals.append(None)
        else:
            hh = max(highs[j-n_kd+1:j+1])
            ll = min(lows[j-n_kd+1:j+1])
            rsv = ((closes[j] - ll) / (hh - ll) * 100) if hh != ll else 50.0
            k   = prev_k * 2/3 + rsv * 1/3
            d   = prev_d * 2/3 + k   * 1/3
            k_vals.append(round(k, 1))
            d_vals.append(round(d, 1))
            prev_k = k
            prev_d = d

    for j, r in enumerate(records):
        r['ma5']  = ma5_vals[j]
        r['ma10'] = ma10_vals[j]
        r['ma20'] = ma20_vals[j]
        r['ma60']  = ma60_vals[j]
        r['ma240'] = ma240_vals[j]
        r['k']    = k_vals[j]
        r['d']    = d_vals[j]

    data_json  = json.dumps(records, ensure_ascii=False)
    last_close = records[-1]['close'] if records else 0
    limit_count = len(limit_days)

    status_html = (
        "<span style='background:#d93025;color:#fff;padding:3px 10px;"
        "border-radius:5px;font-weight:700'>🔥 準備起飛</span>"
        if is_washing else
        "<span style='background:#444;color:#ccc;padding:3px 10px;"
        "border-radius:5px'>📊 盤整觀察</span>"
    )

    vol_ratio = wash_info.get('vol_ratio', '-')
    ma20_ok   = "✅ 站上月線" if wash_info.get('above_ma20') else "❌ 跌破月線"
    hold_low  = "✅ 守住起漲點" if wash_info.get('hold_low') else "❌ 跌破起漲點"

    # 型態評分卡
    score      = pattern.get('score', 0)
    grade      = pattern.get('grade', '-')
    p_notes    = pattern.get('notes', [])
    lq         = pattern.get('limit_quality', '-')
    ma5        = pattern.get('ma5',  '-')
    ma10       = pattern.get('ma10', '-')
    ma20_val   = pattern.get('ma20', '-')

    notes_html = "".join(f"<li>{n}</li>" for n in p_notes)
    score_color = "#26a641" if score >= 70 else "#ffa500" if score >= 50 else "#f85149"

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
  .name{{ font-size:1.1rem; font-weight:500; }}
  .tag{{ font-size:.8rem; background:var(--panel); border:1px solid var(--border);
          border-radius:4px; padding:3px 9px; color:var(--muted); }}
  .grid2{{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:14px; }}
  .grid3{{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; margin-bottom:14px; }}
  .card{{ background:var(--panel); border:1px solid var(--border); border-radius:8px; padding:14px 18px; }}
  .s-label{{ font-size:.68rem; color:var(--muted); text-transform:uppercase;
              letter-spacing:.06em; margin-bottom:6px; }}
  .s-val{{ font-size:1rem; font-weight:600; }}
  .wrap{{ background:var(--panel); border:1px solid var(--border);
          border-radius:8px; padding:14px; margin-bottom:12px; position:relative; }}
  .wrap-title{{ font-size:.68rem; color:var(--muted); text-transform:uppercase;
                letter-spacing:.06em; margin-bottom:10px; }}
  canvas{{ display:block; width:100%; cursor:crosshair; }}
  #tip{{ background:var(--panel); border:1px solid var(--border);
         border-radius:6px; padding:10px 16px; font-size:.82rem;
         line-height:1.8; flex-wrap:wrap; display:flex; gap:12px; align-items:center; }}
  .legend{{ display:flex; gap:18px; font-size:.72rem; color:var(--muted); margin-top:8px; margin-bottom:12px; }}
  .dot{{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; }}
  .score-ring{{ font-size:2.5rem; font-weight:700; color:{score_color}; }}
  ul.notes{{ list-style:none; padding:0; font-size:.82rem; line-height:2; }}
  ul.notes li{{ border-bottom:1px solid var(--border); padding:4px 0; }}
  ul.notes li:last-child{{ border-bottom:none; }}
  .ma-row{{ display:flex; gap:16px; font-size:.82rem; margin-top:8px; flex-wrap:wrap; }}
  .ma-item{{ background:#1c2128; border-radius:4px; padding:4px 10px; }}
</style>
</head>
<body>

<div class="header">
  <div class="code">📊 {code}</div>
  <div class="name">{name}</div>
  <div class="tag">{market}</div>
</div>

<!-- 狀態卡 -->
<div class="grid3">
  <div class="card">
    <div class="s-label">最新收盤</div>
    <div class="s-val" style="color:var(--accent)">{last_close}</div>
  </div>
  <div class="card">
    <div class="s-label">洗盤狀態</div>
    <div class="s-val">{status_html}</div>
  </div>
  <div class="card">
    <div class="s-label">漲停板品質</div>
    <div class="s-val" style="font-size:.88rem">{lq}</div>
  </div>
</div>

<!-- 洗盤指標 -->
<div class="card" style="margin-bottom:14px;font-size:.85rem;line-height:2.2">
  <div class="s-label">洗盤指標</div>
  今日量 / 漲停量：<b>{vol_ratio}</b>（&lt;50% 視為縮量）&nbsp;&nbsp;
  {ma20_ok}&nbsp;&nbsp;{hold_low}
  <div class="ma-row">
    <span class="ma-item">MA5：{ma5}</span>
    <span class="ma-item">MA10：{ma10}</span>
    <span class="ma-item">MA20：{ma20_val}</span>
  </div>
</div>

<!-- K 線圖 -->
<div class="wrap">
  <div class="wrap-title">K 線圖（近兩年）</div>
  <canvas id="kc"></canvas>
</div>
<div class="legend">
  <span><span class="dot" style="background:var(--up)"></span>上漲</span>
  <span><span class="dot" style="background:var(--down)"></span>下跌</span>
  <span><span class="dot" style="background:var(--limit)"></span>漲停</span>
  <span><span class="dot" style="background:#f0c040"></span>MA5</span>
  <span><span class="dot" style="background:#e06080"></span>MA10</span>
  <span><span class="dot" style="background:#58a6ff"></span>MA20</span>
  <span><span class="dot" style="background:#bc8cff"></span>MA60</span>
  <span><span class="dot" style="background:#ff8c42"></span>MA240</span>
</div>

<!-- 成交量 -->
<div class="wrap" style="padding:12px 14px;">
  <div class="wrap-title">成交量</div>
  <canvas id="vc"></canvas>
</div>

<!-- KD 指標 -->
<div class="wrap" style="padding:12px 14px;">
  <div class="wrap-title">KD 指標（9日）</div>
  <canvas id="kdc"></canvas>
  <div style="display:flex;gap:18px;font-size:.72rem;color:var(--muted);margin-top:6px;">
    <span><span class="dot" style="background:#f0c040"></span>K 值</span>
    <span><span class="dot" style="background:#58a6ff"></span>D 值</span>
    <span style="color:#8b949e">超買 &gt;80　超賣 &lt;20</span>
  </div>
</div>

<!-- 資訊列（緊接在圖下方） -->
<div id="tip" style="margin-bottom:14px;">
  <span style="color:var(--muted)">← 滑鼠移到 K 線圖查看詳細資訊</span>
</div>


<!-- 型態分析評分卡 -->
<div class="grid2" style="margin-top:12px;">
  <div class="card">
    <div class="s-label">型態評分</div>
    <div class="score-ring">{score} 分</div>
    <div style="font-size:1.1rem;margin-top:6px;">{grade}</div>
    <div style="font-size:.72rem;color:var(--muted);margin-top:4px;">滿分約 87 分</div>
  </div>
  <div class="card">
    <div class="s-label">型態分析說明</div>
    <ul class="notes">{notes_html}</ul>
  </div>
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
  const kdcan= document.getElementById('kdc');
  const tip  = document.getElementById('tip');
  const {{ ctx:kc, w, h:kh }} = setup(kcan, 300);
  const {{ ctx:vc, h:vh }}    = setup(vcan, 70);
  const {{ ctx:kdc,h:kdh }}   = setup(kdcan, 80);

  const n=DATA.length, PL=10, PR=52, PT=16, PB=26;
  const cw=w-PL-PR, ch=kh-PT-PB;
  const gap=cw/n, bw=Math.max(2,gap-3);
  const UP='#26a641',DN='#f85149',LM='#ffa500',MU='#8b949e',GR='#21262d';

  const pMin=Math.min(...DATA.map(d=>d.low))*0.995;
  const pMax=Math.max(...DATA.map(d=>d.high))*1.005;
  const pr=pMax-pMin;
  const py=v=>PT+ch-((v-pMin)/pr)*ch;

  // grid
  for(let i=0;i<=5;i++){{
    const p=pMin+(pr/5)*i,y=py(p);
    kc.strokeStyle=GR; kc.lineWidth=1;
    kc.beginPath(); kc.moveTo(PL,y); kc.lineTo(w-PR,y); kc.stroke();
    kc.fillStyle=MU; kc.font='10px SF Mono,monospace'; kc.textAlign='left';
    kc.fillText(p.toFixed(1),w-PR+4,y+4);
  }}

  // date labels
  const step=Math.max(1,Math.floor(n/6));
  DATA.forEach((d,i)=>{{
    if(i%step!==0)return;
    const x=PL+i*gap+gap/2;
    kc.fillStyle=MU; kc.font='10px SF Mono,monospace'; kc.textAlign='center';
    kc.fillText(d.date,x,kh-6);
  }});

  // candles
  DATA.forEach((d,i)=>{{
    const x=PL+i*gap+gap/2;
    const col=d.limit?LM:(d.close>=d.open?UP:DN);
    kc.strokeStyle=col; kc.lineWidth=1;
    kc.beginPath(); kc.moveTo(x,py(d.high)); kc.lineTo(x,py(d.low)); kc.stroke();
    const y1=py(Math.max(d.open,d.close)),y2=py(Math.min(d.open,d.close));
    kc.fillStyle=col; kc.fillRect(x-bw/2,y1,bw,Math.max(1,y2-y1));
    if(d.limit){{
      kc.fillStyle=LM; kc.font='bold 11px sans-serif'; kc.textAlign='center';
      kc.fillText('🔥',x,py(d.high)-6);
    }}
  }});

  // 均線
  function drawMA(key, color) {{
    kc.strokeStyle = color;
    kc.lineWidth   = 1.2;
    kc.beginPath();
    let started = false;
    DATA.forEach((d, i) => {{
      if (d[key] === null || d[key] === undefined) {{ started = false; return; }}
      const x = PL + i * gap + gap / 2;
      const y = py(d[key]);
      if (!started) {{ kc.moveTo(x, y); started = true; }}
      else kc.lineTo(x, y);
    }});
    kc.stroke();
  }}
  drawMA('ma5',  '#f0c040');
  drawMA('ma10', '#e06080');
  drawMA('ma20', '#58a6ff');
  drawMA('ma60',  '#bc8cff');
  drawMA('ma240', '#ff8c42');

  // volume
  const volMax=Math.max(...DATA.map(d=>d.volume));
  DATA.forEach((d,i)=>{{
    const x=PL+i*gap+gap/2;
    const col=d.limit?LM:(d.close>=d.open?UP:DN);
    vc.fillStyle=col+'aa';
    vc.fillRect(x-bw/2,vh-(d.volume/volMax)*(vh-8),bw,(d.volume/volMax)*(vh-8));
  }});



  // KD 指標繪製
  const kdMU='#8b949e', kdGR='#21262d';
  // 超買超賣參考線
  [20, 50, 80].forEach(lv=>{{
    const y=kdh-(lv/100)*(kdh-4)-2;
    kdc.strokeStyle= lv===50 ? kdGR : (lv===80?'#f8514944':'#26a64144');
    kdc.lineWidth=1; kdc.setLineDash([3,3]);
    kdc.beginPath(); kdc.moveTo(PL,y); kdc.lineTo(w-PR,y); kdc.stroke();
    kdc.setLineDash([]);
    kdc.fillStyle=kdMU; kdc.font='9px SF Mono,monospace'; kdc.textAlign='left';
    kdc.fillText(lv, w-PR+4, y+3);
  }});
  // K 線
  kdc.strokeStyle='#f0c040'; kdc.lineWidth=1.2; kdc.beginPath();
  let kdStarted=false;
  DATA.forEach((d,i)=>{{
    if(d.k===null||d.k===undefined){{kdStarted=false;return;}}
    const x=PL+i*gap+gap/2, y=kdh-(d.k/100)*(kdh-4)-2;
    if(!kdStarted){{kdc.moveTo(x,y);kdStarted=true;}}else kdc.lineTo(x,y);
  }}); kdc.stroke();
  // D 線
  kdc.strokeStyle='#58a6ff'; kdc.lineWidth=1.2; kdc.beginPath();
  kdStarted=false;
  DATA.forEach((d,i)=>{{
    if(d.d===null||d.d===undefined){{kdStarted=false;return;}}
    const x=PL+i*gap+gap/2, y=kdh-(d.d/100)*(kdh-4)-2;
    if(!kdStarted){{kdc.moveTo(x,y);kdStarted=true;}}else kdc.lineTo(x,y);
  }}); kdc.stroke();

  // KD 黃金交叉標記
  for(let i=1;i<DATA.length;i++){{
    const prev=DATA[i-1], cur=DATA[i];
    if(prev.k===null||cur.k===null||prev.d===null||cur.d===null) continue;
    // 黃金交叉：K 從下穿上 D
    if(prev.k<=prev.d && cur.k>cur.d){{
      const x=PL+i*gap+gap/2;
      const y=kdh-(cur.k/100)*(kdh-4)-2;
      kdc.fillStyle='#ffd700';
      kdc.font='bold 10px sans-serif';
      kdc.textAlign='center';
      kdc.fillText('★',x,y-6);  // ★
    }}
    // 死亡交叉：K 從上穿下 D
    if(prev.k>=prev.d && cur.k<cur.d){{
      const x=PL+i*gap+gap/2;
      const y=kdh-(cur.k/100)*(kdh-4)-2;
      kdc.fillStyle='#f85149';
      kdc.font='bold 10px sans-serif';
      kdc.textAlign='center';
      kdc.fillText('★',x,y+12);  // ★
    }}
  }}

  // 游標直線 + 資訊列（固定在圖下方，不遮擋 K 線）
  kcan.onmousemove=e=>{{
    const r=kcan.getBoundingClientRect();
    const mx=e.clientX-r.left;
    const i=Math.round((mx-PL)/gap-0.5);
    if(i<0||i>=n) return;
    const d=DATA[i];
    const col=d.limit?'#ffa500':(d.close>=d.open?'#26a641':'#f85149');
    const chg=((d.close-d.open)/d.open*100).toFixed(2);

    // 游標直線（重繪 K 線後疊加）
    draw();
    const cx=PL+i*gap+gap/2;
    kc.strokeStyle='rgba(255,255,255,0.25)'; kc.lineWidth=1; kc.setLineDash([4,3]);
    kc.beginPath(); kc.moveTo(cx,PT); kc.lineTo(cx,kh-PB); kc.stroke();
    kc.setLineDash([]);

    tip.innerHTML=
      `<span style="color:var(--muted)">${{d.date}}</span>` +
      ` 開<b>${{d.open}}</b>` +
      ` 高<b>${{d.high}}</b>` +
      ` 低<b>${{d.low}}</b>` +
      ` 收<b style="color:${{col}}">${{d.close}}</b><span style="color:${{col}}">(${{chg>0?'+':''}}${{chg}}%)</span>` +
      ` 量<b>${{(d.volume/1000).toFixed(0)}}K</b>` +
      (d.ma5   ? ` <span style="color:#f0c040">MA5 <b>${{d.ma5}}</b></span>` : '') +
      (d.ma10  ? ` <span style="color:#e06080">MA10 <b>${{d.ma10}}</b></span>` : '') +
      (d.ma20  ? ` <span style="color:#58a6ff">MA20 <b>${{d.ma20}}</b></span>` : '') +
      (d.ma60  ? ` <span style="color:#bc8cff">MA60 <b>${{d.ma60}}</b></span>` : '') +
      (d.ma240 ? ` <span style="color:#ff8c42">MA240 <b>${{d.ma240}}</b></span>` : '') +
      (d.k !== null ? ` <span style="color:#f0c040">K<b>${{d.k}}</b></span>` : '') +
      (d.d !== null ? ` <span style="color:#58a6ff">D<b>${{d.d}}</b></span>` : '') +
      (d.limit ? ` <span style="color:#ffa500;font-weight:700">🔥漲停</span>` : '');
  }};
  kcan.onmouseleave=()=>{{
    draw();
    tip.innerHTML='<span style="color:var(--muted)">← 滑鼠移到 K 線圖查看詳細資訊</span>';
  }};
}}

draw();
window.addEventListener('resize',draw);
</script>
</body>
</html>"""




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


# ── 掃描主函式 ───────────────────────────────────────────────
def scan(output_dir="charts", base_url="charts"):
    os.makedirs(output_dir, exist_ok=True)

    print("[名稱] 正在抓取中文名稱對照表...")
    name_map = fetch_name_map()

    stocks      = get_list()
    today       = datetime.now()
    fetch_start = today - timedelta(days=730)  # 抓兩年資料，K 線圖顯示兩年 + 首次漲停回溯
    fetch_end   = today
    results     = []
    total       = len(stocks)

    print(f"[掃描] 共 {total} 支，條件：前 3~10 交易日首次漲停 + 縮量洗盤 + 型態分析")

    for i, s in enumerate(stocks):
        try:
            if i % 20 == 0 and i > 0:
                print(f"[進度] {i}/{total}，暫停 3 秒...")
                time.sleep(3)

            df = yf.download(s, start=fetch_start, end=fetch_end, progress=False)
            if df.empty or len(df) < 20:
                continue

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

            # ── 第一關：前 3~10 個交易日內有「收盤鎖板」漲停 ──
            lo = max(0, n_td - 10)
            hi = max(0, n_td - 3)
            if lo >= hi:
                continue

            # 計算每天的漲停價（前一天收盤 × 1.1，無條件捨去至小數點後2位）
            # 收盤價 >= 漲停價 × 0.999 才算收盤鎖板（容許些微誤差）
            limit_close_days = []
            for idx in trading_days[lo:hi]:
                try:
                    iloc_pos = list(close.index).index(idx)
                    if iloc_pos == 0:
                        continue
                    prev_c = float(close.iloc[iloc_pos - 1])
                    limit_price = calc_limit_price(prev_c)
                    day_close   = float(close.loc[idx])
                    if day_close >= limit_price * 0.999:
                        limit_close_days.append(idx)
                except Exception:
                    continue

            if not limit_close_days:
                continue

            # 同時也計算近三個月所有收盤鎖板日（供首次漲停判斷用）
            all_limit_close = []
            for idx in trading_days:
                try:
                    iloc_pos = list(close.index).index(idx)
                    if iloc_pos == 0:
                        continue
                    prev_c = float(close.iloc[iloc_pos - 1])
                    limit_price = calc_limit_price(prev_c)
                    day_close   = float(close.loc[idx])
                    if day_close >= limit_price * 0.999:
                        all_limit_close.append(idx)
                except Exception:
                    continue

            limit_days = pd.DatetimeIndex(limit_close_days)

            # ── 第一關補充：近三個月首次漲停 ──────────────────
            last_limit_date  = limit_days[-1]
            three_months_ago = last_limit_date - pd.DateOffset(months=3)
            prior_limits = [d for d in all_limit_close
                           if d < last_limit_date and d >= three_months_ago]
            if prior_limits:
                continue  # 前 3 個月內已有漲停，不是首次啟動，跳過

            limit_vol  = float(volume.loc[last_limit_date])
            limit_low  = float(open_.loc[last_limit_date])

            curr_price = float(close.iloc[-1])
            curr_vol   = float(volume.iloc[-1])
            ma20       = float(close.rolling(20).mean().iloc[-1])

            # ── 第二關：洗盤條件 ──────────────────────────────
            shrink     = curr_vol < limit_vol * 0.5
            hold_low   = curr_price >= limit_low
            above_ma   = curr_price > ma20

            is_washing_type = None
            if shrink and hold_low and above_ma:
                is_washing      = True
                is_washing_type = "洗盤型"
            elif above_ma and curr_vol > limit_vol * 0.8 and curr_price > float(close.iloc[-2]):
                is_washing      = True
                is_washing_type = "強勢續攻型"
            else:
                is_washing = False

            if not is_washing:
                continue  # 不符合洗盤或強勢續攻，跳過

            vol_ratio_pct = f"{round((curr_vol / limit_vol) * 100)}%"
            days_since    = len([d for d in trading_days if d > last_limit_date])

            code   = s.split('.')[0]
            market = "上市" if s.endswith(".TW") else "上櫃"
            name   = name_map.get(code, "")

            wash_info = {
                "vol_ratio":    vol_ratio_pct,
                "above_ma20":   above_ma,
                "hold_low":     hold_low,
                "washing_type": is_washing_type,
            }

            # ── 型態分析 ───────────────────────────────────────
            pattern = analyze_pattern(df, list(limit_days))

            # ── 洗盤加分（加入型態評分）───────────────────────
            wash_score_notes = []
            if shrink:
                pattern['score'] += 20
                wash_score_notes.append("✅ 縮量洗盤（今日量 < 漲停量 50%），主力鎖碼")
            else:
                wash_score_notes.append(f"⚠️ 量能未縮（今日量 {vol_ratio_pct}），主力態度未明")
            if hold_low:
                pattern['score'] += 10
                wash_score_notes.append("✅ 守住漲停日起漲點，籌碼穩定")
            else:
                wash_score_notes.append("❌ 跌破起漲點，籌碼鬆動")
            if above_ma:
                pattern['score'] += 5
                wash_score_notes.append("✅ 站上月線，趨勢向上")
            else:
                wash_score_notes.append("❌ 跌破月線，趨勢偏弱")
            pattern['notes'] = wash_score_notes + pattern['notes']

            # ── 新增條件加分 ────────────────────────────────
            extra_notes = []

            # A. 漲停當天量是否放大（>= 前5日均量 1.5 倍）
            try:
                limit_idx = list(close.index).index(last_limit_date)
                if limit_idx >= 5:
                    avg_vol_5 = float(volume.iloc[limit_idx-5:limit_idx].mean())
                    limit_day_vol = float(volume.loc[last_limit_date])
                    if avg_vol_5 > 0 and limit_day_vol >= avg_vol_5 * 1.5:
                        pattern['score'] += 15
                        extra_notes.append(f"✅ 漲停當天量能放大（是前5日均量 {round(limit_day_vol/avg_vol_5, 1)} 倍），主力積極介入")
                    else:
                        extra_notes.append(f"⚠️ 漲停當天量能未明顯放大（{round(limit_day_vol/avg_vol_5, 1) if avg_vol_5 > 0 else '-'} 倍），主力積極度不足")
            except Exception:
                pass

            # B. 洗盤期間是否連續縮量（漲停後每天都 < 漲停量 50%）
            try:
                limit_idx = list(close.index).index(last_limit_date)
                wash_vols = volume.iloc[limit_idx+1:]
                if len(wash_vols) >= 2:
                    all_shrink = all(float(v) < limit_vol * 0.5 for v in wash_vols)
                    if all_shrink:
                        pattern['score'] += 15
                        extra_notes.append(f"✅ 洗盤期間每天量能都 < 漲停量 50%，連續縮量鎖碼")
                    else:
                        extra_notes.append("⚠️ 洗盤期間量能不穩定，非每天縮量")
            except Exception:
                pass

            # C. 股價位置（近一年低檔區啟動 vs 高檔區啟動）
            try:
                year_high = float(close.rolling(min(252, len(close))).max().iloc[-1])
                year_low  = float(close.rolling(min(252, len(close))).min().iloc[-1])
                price_range = year_high - year_low
                if price_range > 0:
                    position = (curr_price - year_low) / price_range
                    if position <= 0.4:
                        pattern['score'] += 15
                        extra_notes.append(f"✅ 股價位於近一年低檔區（位置 {round(position*100)}%），低風險啟動")
                    elif position <= 0.7:
                        pattern['score'] += 5
                        extra_notes.append(f"⚠️ 股價位於近一年中段區（位置 {round(position*100)}%）")
                    else:
                        extra_notes.append(f"❌ 股價位於近一年高檔區（位置 {round(position*100)}%），追高風險高")
            except Exception:
                pass

            # D0. MA60 季線斜率（向上加分）
            try:
                ma60_series = close.rolling(60).mean()
                if len(ma60_series.dropna()) >= 10:
                    ma60_slope = float(ma60_series.iloc[-1]) - float(ma60_series.iloc[-10])
                    if ma60_slope > 0:
                        pattern['score'] += 15
                        extra_notes.append(f"✅ 季線（MA60）向上走勢，趨勢背景良好")
                    elif ma60_slope > -1:
                        extra_notes.append("⚠️ 季線（MA60）走平，趨勢中性")
                    else:
                        pattern['score'] -= 10
                        extra_notes.append("❌ 季線（MA60）向下，趨勢偏弱")
            except Exception:
                pass

            # D. 站上年線（MA240）
            try:
                ma240 = close.rolling(240).mean()
                ma240_today = float(ma240.iloc[-1])
                if not pd.isna(ma240_today):
                    if curr_price > ma240_today:
                        pattern['score'] += 20
                        extra_notes.append(f"✅ 股價站上年線（MA240={ma240_today:.1f}），長線趨勢向上")
                    else:
                        pattern['score'] -= 15
                        extra_notes.append(f"❌ 股價跌破年線（MA240={ma240_today:.1f}），長線趨勢偏弱，風險高")
            except Exception:
                pass

            # E. 漲停日是否突破季線（MA60）
            try:
                ma60 = close.rolling(60).mean()
                limit_idx   = list(close.index).index(last_limit_date)
                ma60_before = float(ma60.iloc[limit_idx - 1]) if limit_idx >= 1 else None
                ma60_at     = float(ma60.iloc[limit_idx])
                close_before = float(close.iloc[limit_idx - 1]) if limit_idx >= 1 else None
                close_at     = float(close.loc[last_limit_date])
                if ma60_before and close_before:
                    if close_before < ma60_before and close_at >= ma60_at:
                        pattern['score'] += 20
                        extra_notes.append(f"✅ 漲停日突破季線（MA60={ma60_at:.1f}），強力突破壓力")
                    elif close_before >= ma60_before:
                        pattern['score'] += 8
                        extra_notes.append(f"⚠️ 漲停前已在季線之上（MA60={ma60_at:.1f}），非突破型態")
                    else:
                        extra_notes.append(f"❌ 漲停日未能突破季線（MA60={ma60_at:.1f}），壓力未解除")
            except Exception:
                pass

            pattern['notes'] = extra_notes + pattern['notes']

            # 重新計算評分等級（滿分約 197 分）
            ps = pattern['score']
            pattern['grade'] = "🔥🔥 極強" if ps >= 140 else "🔥 強" if ps >= 100 else "⚠️ 普通" if ps >= 60 else "❌ 弱"

            # ── 修改4：是否突破洗盤區間 + 突破強度 + 停損參考價 ──
            try:
                limit_idx  = list(close.index).index(last_limit_date)
                wash_highs = df['High'].iloc[limit_idx+1:-1]
                wash_lows  = df['Low'].iloc[limit_idx+1:-1]

                # 修改2：至少2天洗盤才算有效
                if len(wash_highs) >= 2:
                    wash_high   = float(wash_highs.max())
                    wash_low    = float(wash_lows.min())  # 修改4：停損參考價
                    today_close = float(close.iloc[-1])
                    is_breakout = today_close > wash_high
                    if is_breakout:
                        breakout_strength  = round(today_close / wash_high, 3)
                        breakout_vol_ratio = round(curr_vol / limit_vol, 2)
                        if breakout_vol_ratio >= 0.5:
                            breakout_str = f"🔥 突破 {breakout_strength:.2f}x（有量）"
                        else:
                            breakout_str = f"⚠️ 突破 {breakout_strength:.2f}x（量縮試盤）"
                    else:
                        breakout_strength  = 0
                        breakout_vol_ratio = 0
                        breakout_str       = "-"
                else:
                    is_breakout        = False
                    breakout_strength  = 0
                    breakout_vol_ratio = 0
                    breakout_str       = "-"
                    wash_low           = float(close.loc[last_limit_date])
            except Exception:
                is_breakout        = False
                breakout_strength  = 0
                breakout_vol_ratio = 0
                breakout_str       = "-"
                wash_low           = 0


            # ── 產生 K 線圖 ────────────────────────────────────
            chart_file      = os.path.join(output_dir, f"{code}.html")
            chart_link      = f"{base_url}/{code}.html" 
            with open(chart_file, "w", encoding="utf-8") as f:
                f.write(generate_chart_html(
                    s, name, df, list(limit_days),
                    is_washing, wash_info, pattern
                ))

            dates = [d.strftime('%m/%d') for d in limit_days]
            results.append({
                "_score":    pattern['score'],
                "_vol_num":  float(vol_ratio_pct.rstrip('%')),
                "代碼": (
                    f"<a href='{chart_link}' target='_blank' "
                    f"style='color:#58a6ff;font-weight:700;text-decoration:none'>"
                    f"{code} 📊</a>"
                ),
                "名稱":      name,
                "市場":      market,
                "型態評分":   f"<span style='color:{'#26a641' if pattern['score']>=70 else '#ffa500' if pattern['score']>=50 else '#f85149'};font-weight:700'>{pattern['score']} 分 {pattern['grade']}</span>",
                "洗盤量比":   vol_ratio_pct,
                "距漲停天數": days_since,
                "漲停板":     pattern['limit_quality'],
                "收盤價":    round(curr_price, 2),
                "漲停軌跡":   " / ".join(dates),
                "突破洗盤":    breakout_str,
                "進場訊號":    "✅ 進場" if (is_breakout and breakout_vol_ratio >= 0.5 and pattern['score'] >= 100) else "-",
                "停損參考":    round(wash_low, 2) if wash_low else "-",
            })

        except Exception as e:
            print(f"[{s}] 錯誤：{e}")
            continue

    print(f"[完成] 掃描 {total} 支，準備起飛共 {len(results)} 支")
    return pd.DataFrame(results)


# ── 輸出主報表 HTML ──────────────────────────────────────────
def to_html(df, output_file="index.html"):
    t = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

    if not df.empty:
        # 拆成兩區塊：已突破 / 洗盤中
        df_break = df[df['突破洗盤'] != '-'].sort_values(['_score', '_vol_num'], ascending=[False, True]).drop(columns=['_score', '_vol_num'])
        df_watch = df[df['突破洗盤'] == '-'].sort_values(['_score', '_vol_num'], ascending=[False, True]).drop(columns=['_score', '_vol_num'])

        break_html = df_break.to_html(index=False, escape=False) if not df_break.empty else "<p style='color:var(--muted);padding:12px'>目前無突破標的</p>"
        watch_html = df_watch.to_html(index=False, escape=False) if not df_watch.empty else "<p style='color:var(--muted);padding:12px'>目前無洗盤中標的</p>"

        table_html = (
            "<h2 style='color:#ffa500;font-size:1.1rem;margin:20px 0 10px'>"
            "🔥 已突破洗盤區間（可考慮進場）</h2>" +
            break_html +
            "<h2 style='color:#58a6ff;font-size:1.1rem;margin:28px 0 10px'>"
            "📊 洗盤中（持續觀察）</h2>" +
            watch_html
        )
        count_info = (
            f"<p class='count'>"
            f"本次揃描共 <strong style='color:#d93025'>{len(df)}</strong> 支符合條件，"
            f"其中 <strong style='color:#ffa500'>{len(df_break)} 支</strong> 已突破，"
            f"<strong style='color:#58a6ff'>{len(df_watch)} 支</strong> 洗盤中"
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
    第二關（洗盤三條件同時成立）：縮量 &lt; 50% ＋ 守起漲點 ＋ 站上月線<br>
    第三關（型態評分）：一字板、量能遞減、均線排列、K 棒型態綜合評分<br>
    📊 最終輸出：所有符合條件標的，依型態評分由高到低排列
  </div>
  {table_html}
</body>
</html>"""

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[輸出] {output_file} 已產生")


# ── 入口 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    # GitHub Pages 部署時 charts/ 資料夾在同層，相對路徑即可
    df = scan(output_dir="charts", base_url="charts")
    to_html(df, output_file="index.html")
