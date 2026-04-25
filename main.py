import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
import time
import os
import json

# ── Gemini API Key（從環境變數讀取，不要寫在程式碼裡）─────────
# 設定方式：在命令提示字元執行 setx GEMINI_API_KEY "你的key"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


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


# ── 爬三大法人資料 ───────────────────────────────────────────
def fetch_institutional(code: str, is_tw: bool, days: int = 10) -> list:
    """
    回傳近 N 天的三大法人資料
    上市用證交所，上櫃用櫃買中心
    """
    results = []
    today   = datetime.now()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*",
        "Referer": "https://www.twse.com.tw/",
    }

    def safe_int(s):
        try:
            return int(str(s).replace(",", "").replace("+", "").strip())
        except Exception:
            return 0

    # 收集近 days 個工作日
    trading_dates = []
    for delta in range(1, days * 3):
        d = today - timedelta(days=delta)
        if d.weekday() < 5:
            trading_dates.append(d)
        if len(trading_dates) >= days:
            break

    for d in reversed(trading_dates):
        date_str   = d.strftime("%Y%m%d")
        date_slash = d.strftime("%Y/%m/%d")
        try:
            if is_tw:
                url = (
                    f"https://www.twse.com.tw/rwd/zh/fund/T86"
                    f"?response=json&date={date_str}&selectType=ALL"
                )
                r = requests.get(url, timeout=10, headers=headers)
                if r.status_code != 200:
                    continue
                data = r.json()
                if data.get("stat") != "OK":
                    continue
                for row in data.get("data", []):
                    if str(row[0]).strip() == code:
                        results.append({
                            "date":    d.strftime("%m/%d"),
                            "foreign": safe_int(row[4]),
                            "trust":   safe_int(row[7]),
                            "dealer":  safe_int(row[10]),
                        })
                        break
            else:
                url = (
                    f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
                    f"3itrade_hedge.php?l=zh-tw&se=EW&t=D"
                    f"&d={date_slash}&s=0,asc&o=json"
                )
                r = requests.get(url, timeout=10, headers=headers)
                if r.status_code != 200:
                    continue
                data = r.json()
                for row in data.get("aaData", []):
                    if str(row[0]).strip() == code:
                        results.append({
                            "date":    d.strftime("%m/%d"),
                            "foreign": safe_int(row[3]),
                            "trust":   safe_int(row[6]),
                            "dealer":  safe_int(row[9]),
                        })
                        break
        except Exception:
            continue
        time.sleep(0.4)

    return results



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
            limit_price = round(prev_close * 1.1, 2)

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
def generate_chart_html(symbol, name, df, limit_days, is_washing, wash_info, inst_data, pattern, ai_analysis=''):
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

    data_json  = json.dumps(records,   ensure_ascii=False)
    inst_json  = json.dumps(inst_data, ensure_ascii=False)
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
  #tip{{ position:absolute; background:#1c2128; border:1px solid var(--border);
         border-radius:6px; padding:10px 14px; font-size:.78rem; pointer-events:none;
         display:none; z-index:10; line-height:1.9; min-width:130px; }}
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
  <div class="wrap-title">K 線圖（近 60 天）</div>
  <canvas id="kc"></canvas>
  <div id="tip"></div>
</div>
<div class="legend">
  <span><span class="dot" style="background:var(--up)"></span>上漲</span>
  <span><span class="dot" style="background:var(--down)"></span>下跌</span>
  <span><span class="dot" style="background:var(--limit)"></span>漲停</span>
</div>

<!-- 成交量 -->
<div class="wrap" style="padding:12px 14px;">
  <div class="wrap-title">成交量</div>
  <canvas id="vc"></canvas>
</div>

<!-- 三大法人 -->
<div class="wrap" style="padding:12px 14px; margin-top:12px;">
  <div class="wrap-title">三大法人買賣超（張）</div>
  <canvas id="ic"></canvas>
  <div style="display:flex;gap:18px;font-size:.72rem;color:var(--muted);margin-top:8px;">
    <span><span class="dot" style="background:#58a6ff"></span>外資</span>
    <span><span class="dot" style="background:#ffa500"></span>投信</span>
    <span><span class="dot" style="background:#bc8cff"></span>自營商</span>
  </div>
</div>

<!-- AI 分析說明 -->
<div class="card" style="margin-top:12px;margin-bottom:12px;">
  <div class="s-label" style="margin-bottom:10px">🤖 Gemini AI 操盤分析</div>
  <div style="font-size:.88rem;line-height:1.9;color:var(--text);white-space:pre-wrap">{ai_analysis}</div>
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
const INST = {inst_json};
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
  const ican = document.getElementById('ic');
  const tip  = document.getElementById('tip');
  const {{ ctx:kc, w, h:kh }} = setup(kcan, 300);
  const {{ ctx:vc, h:vh }}    = setup(vcan, 70);
  const {{ ctx:ic, h:ih }}    = setup(ican, 100);

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

  // volume
  const volMax=Math.max(...DATA.map(d=>d.volume));
  DATA.forEach((d,i)=>{{
    const x=PL+i*gap+gap/2;
    const col=d.limit?LM:(d.close>=d.open?UP:DN);
    vc.fillStyle=col+'aa';
    vc.fillRect(x-bw/2,vh-(d.volume/volMax)*(vh-8),bw,(d.volume/volMax)*(vh-8));
  }});

  // 三大法人圖
  if(INST.length>0){{
    const ig=cw/INST.length, ibw=Math.max(3,ig/4);
    const allVals=INST.flatMap(d=>[d.foreign,d.trust,d.dealer]);
    const iMax=Math.max(...allVals.map(Math.abs),1);
    const mid=ih/2;
    const iscale=v=>(Math.abs(v)/iMax)*(ih/2-8);

    // zero line
    ic.strokeStyle=GR; ic.lineWidth=1;
    ic.beginPath(); ic.moveTo(PL,mid); ic.lineTo(w-PR,mid); ic.stroke();

    INST.forEach((d,i)=>{{
      const x=PL+i*ig+ig/2;
      // 外資
      const fh=iscale(d.foreign);
      ic.fillStyle='#58a6ff88';
      ic.fillRect(x-ibw*1.5,d.foreign>=0?mid-fh:mid,ibw,fh);
      // 投信
      const th=iscale(d.trust);
      ic.fillStyle='#ffa50088';
      ic.fillRect(x-ibw*0.3,d.trust>=0?mid-th:mid,ibw,th);
      // 自營
      const dh=iscale(d.dealer);
      ic.fillStyle='#bc8cff88';
      ic.fillRect(x+ibw*0.9,d.dealer>=0?mid-dh:mid,ibw,dh);

      if(i%Math.max(1,Math.floor(INST.length/5))===0){{
        ic.fillStyle=MU; ic.font='9px SF Mono,monospace'; ic.textAlign='center';
        ic.fillText(d.date,x,ih-4);
      }}
    }});
  }} else {{
    ic.fillStyle=MU; ic.font='12px SF Mono,monospace'; ic.textAlign='center';
    ic.fillText('三大法人資料載入中或暫無資料',w/2,ih/2+4);
  }}

  // tooltip
  kcan.onmousemove=e=>{{
    const r=kcan.getBoundingClientRect();
    const i=Math.round((e.clientX-r.left-PL)/gap-0.5);
    if(i<0||i>=n){{tip.style.display='none';return;}}
    const d=DATA[i];
    const col=d.limit?'#ffa500':(d.close>=d.open?'#26a641':'#f85149');
    const chg=((d.close-d.open)/d.open*100).toFixed(2);
    tip.innerHTML=`<div style="color:#8b949e;margin-bottom:4px">${{d.date}}</div>
      <div>開 <b>${{d.open}}</b></div><div>高 <b>${{d.high}}</b></div>
      <div>低 <b>${{d.low}}</b></div>
      <div>收 <b style="color:${{col}}">${{d.close}}</b> (${{chg>0?'+':''}}${{chg}}%)</div>
      <div>量 <b>${{(d.volume/1000).toFixed(0)}}K</b></div>
      ${{d.limit?'<div style="color:#ffa500;font-weight:700;margin-top:4px">🔥 漲停</div>':''}}`;
    tip.style.display='block';
    const tx=e.clientX-r.left+14;
    tip.style.left=(tx+130>w?tx-150:tx)+'px';
    tip.style.top='20px';
  }};
  kcan.onmouseleave=()=>tip.style.display='none';
}}

draw();
window.addEventListener('resize',draw);
</script>
</body>
</html>"""



# ── Gemini AI 分析說明 ────────────────────────────────────────
def gemini_analysis(code: str, name: str, pattern: dict, wash_info: dict,
                    inst_data: list, days_since: int) -> str:
    """打包資料送給 Gemini Flash，取得操盤手角度的中文分析說明"""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "貼在這裡":
        return "（尚未設定 Gemini API Key，請填入 GEMINI_API_KEY）"

    # 整理三大法人近期方向
    inst_summary = "無資料"
    if inst_data:
        foreign_total = sum(d.get("foreign", 0) for d in inst_data)
        trust_total   = sum(d.get("trust",   0) for d in inst_data)
        dealer_total  = sum(d.get("dealer",  0) for d in inst_data)
        inst_summary  = (
            f"外資近{len(inst_data)}天合計：{'買超' if foreign_total > 0 else '賣超'} {abs(foreign_total)} 張，"
            f"投信：{'買超' if trust_total > 0 else '賣超'} {abs(trust_total)} 張，"
            f"自營商：{'買超' if dealer_total > 0 else '賣超'} {abs(dealer_total)} 張"
        )

    notes_text = "\n".join(pattern.get("notes", []))

    prompt = f"""你是一位經驗豐富的台股操盤手，請根據以下量化資料，用繁體中文寫一段約150~200字的分析說明。
語氣要像在跟投資人簡報，直接、有重點，指出這支股票的優勢與潛在風險。

【股票】{code} {name}
【漲停板品質】{pattern.get("limit_quality", "未知")}
【距漲停天數】{days_since} 天
【洗盤量比】{wash_info.get("vol_ratio", "-")}（低於50%代表主力縮手鎖碼）
【均線狀態】MA5={pattern.get("ma5")} / MA10={pattern.get("ma10")} / MA20={pattern.get("ma20")}
【月線】{"站上" if wash_info.get("above_ma20") else "跌破"}月線
【起漲點】{"守住" if wash_info.get("hold_low") else "跌破"}漲停日起漲點
【型態評分】{pattern.get("score")} 分（{pattern.get("grade")}）
【型態分析細節】
{notes_text}
【三大法人】{inst_summary}

請直接輸出分析內容，不要加標題或編號。"""


    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 400}
    }
    for attempt in range(3):  # 最多重試 3 次
        try:
            r = requests.post(url, json=payload, timeout=20)
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"  [Gemini] 限流，等待 {wait} 秒後重試...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            result = r.json()
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            return text.strip()
        except Exception as e:
            print(f"  [Gemini] 第 {attempt+1} 次失敗：{e}")
            if attempt < 2:
                time.sleep(10)
    return "（AI 分析暫時無法使用）"

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
    fetch_start = today - timedelta(days=130)  # 多抓 ~3 個月，供「首次漲停」回溯用
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

            # ── 第一關補充：近三個月首次漲停（該漲停前 3 個月內不能有其他漲停）──
            last_limit_date = limit_days[-1]
            three_months_ago = last_limit_date - pd.DateOffset(months=3)
            # 找出「漲停日之前」的所有漲停
            prior_limits = all_limit[
                (all_limit < last_limit_date) &
                (all_limit >= three_months_ago)
            ]
            if not prior_limits.empty:
                continue  # 前 3 個月內已有漲停，不是首次啟動，跳過

            limit_vol  = float(volume.loc[last_limit_date])
            limit_low  = float(open_.loc[last_limit_date])

            curr_price = float(close.iloc[-1])
            curr_vol   = float(volume.iloc[-1])
            ma20       = float(close.rolling(20).mean().iloc[-1])

            # ── 第二關：洗盤三條件 ─────────────────────────────
            shrink     = curr_vol < limit_vol * 0.5
            hold_low   = curr_price >= limit_low
            above_ma   = curr_price > ma20
            is_washing = shrink and hold_low and above_ma

            if not is_washing:
                continue  # 只保留準備起飛的標的

            vol_ratio_pct = f"{round((curr_vol / limit_vol) * 100)}%"
            days_since    = (today - last_limit_date.to_pydatetime()).days

            code   = s.split('.')[0]
            market = "上市" if s.endswith(".TW") else "上櫃"
            name   = name_map.get(code, "")
            is_tw  = s.endswith(".TW")

            wash_info = {
                "vol_ratio":  vol_ratio_pct,
                "above_ma20": above_ma,
                "hold_low":   hold_low,
            }

            # ── 型態分析 ───────────────────────────────────────
            pattern = analyze_pattern(df, list(limit_days))

            # ── 爬三大法人 ─────────────────────────────────────
            print(f"  [{code}] 抓三大法人資料...")
            inst_data = fetch_institutional(code, is_tw, days=10)

            # ── Gemini AI 分析 ─────────────────────────────────
            print(f"  [{code}] 呼叫 Gemini 分析...")
            time.sleep(30)  # 避免 429 限流（免費方案每分鐘限制）
            ai_analysis = gemini_analysis(
                code, name, pattern, wash_info, inst_data, days_since
            )

            # ── 產生 K 線圖 ────────────────────────────────────
            chart_file      = os.path.join(output_dir, f"{code}.html")
            chart_link      = f"{base_url}/{code}.html" 
            with open(chart_file, "w", encoding="utf-8") as f:
                f.write(generate_chart_html(
                    s, name, df, list(limit_days),
                    is_washing, wash_info, inst_data, pattern, ai_analysis
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
        # 按型態評分高到低排序，同分再按洗盤量比小優先，全部輸出
        all_sorted = (
            df.sort_values(['_score', '_vol_num'], ascending=[False, True])
            .drop(columns=['_score', '_vol_num'])
        )
        fire_count = len(df)
        table_html = all_sorted.to_html(index=False, escape=False)
        count_info = (
            f"<p class='count'>"
            f"本次掃描「準備起飛」共 <strong style='color:#d93025'>{fire_count} 支</strong>，"
            f"依型態評分由高到低排列"
            f"&nbsp;｜&nbsp; 點擊代碼查看 K 線圖 + 籌碼 + 型態分析</p>"
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
