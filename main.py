import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
import time
import os
import json
import math
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── 設定 ─────────────────────────────────────────────────────
KEEP_DAYS = 30        # 保留幾天的歷史紀錄
MAX_WORKERS = 5       # 多執行緒下載數量（避免被封鎖）

# ── 核心工具函式 ──────────────────────────────────────────────
def calc_limit_price(prev_close: float) -> float:
    """計算台股漲停價，符合台股 Tick 規則"""
    raw = prev_close * 1.1
    if raw < 10: tick = 0.01
    elif raw < 50: tick = 0.05
    elif raw < 100: tick = 0.1
    elif raw < 500: tick = 0.5
    elif raw < 1000: tick = 1.0
    else: tick = 5.0
    return math.floor(raw / tick + 0.0001) * tick

def fetch_name_map() -> dict:
    """抓取台股名稱對照表"""
    name_map = {}
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchange_report/STOCK_DAY_ALL", timeout=10)
        for item in r.json(): name_map[item["Code"]] = item["Name"]
        r2 = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=10)
        for item in r2.json(): name_map[item["SecuritiesCompanyCode"]] = item["CompanyName"]
    except Exception as e:
        print(f"[系統] 名稱抓取失敗: {e}")
    return name_map

def get_list(target=2000):
    """獲取台股上市櫃清單"""
    res = []
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchange_report/STOCK_DAY_ALL", timeout=15)
        res += [f"{i['Code']}.TW" for i in r.json() if len(i['Code']) == 4]
        r2 = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=15)
        res += [f"{i['SecuritiesCompanyCode']}.TWO" for i in r2.json() if len(i['SecuritiesCompanyCode']) == 4]
    except Exception as e:
        print(f"[系統] 清單抓取失敗: {e}")
    return res[:target]

# ── HTML 圖表產生器 ───────────────────────────────────────────
def generate_stock_chart(symbol, name, df, limit_dates, buy_date, ma60_series, ma240_series, k_series, d_series):
    """產生包含日週月線切換、自訂均線、KD副圖的完整HTML"""
    code = symbol.split('.')[0]

    def df_to_ohlcv(d, lim_dates):
        result = []
        for idx, row in d.iterrows():
            result.append({
                "time": idx.strftime('%Y-%m-%d'),
                "open": round(float(row['Open']), 2),
                "high": round(float(row['High']), 2),
                "low": round(float(row['Low']), 2),
                "close": round(float(row['Close']), 2),
                "value": float(row['Volume']),
                "isLimit": idx in lim_dates
            })
        return result

    def calc_kd(d):
        import pandas as pd
        close = d['Close'].astype(float)
        high = d['High'].astype(float)
        low = d['Low'].astype(float)
        win = 9
        rsv = ((close - low.rolling(win).min()) /
               (high.rolling(win).max() - low.rolling(win).min()) * 100).fillna(50)
        k = rsv.ewm(com=2).mean()
        dv = k.ewm(com=2).mean()
        return (
            [{"time": i.strftime('%Y-%m-%d'), "value": round(float(v), 1)} for i, v in k.dropna().items()],
            [{"time": i.strftime('%Y-%m-%d'), "value": round(float(v), 1)} for i, v in dv.dropna().items()]
        )

    def resample_df(d, rule):
        import pandas as pd
        r = d.resample(rule).agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        return r

    # 日線
    daily_data = df_to_ohlcv(df, limit_dates)
    daily_k, daily_d = calc_kd(df)

    # 週線
    df_w = resample_df(df, 'W')
    weekly_data = df_to_ohlcv(df_w, [])
    weekly_k, weekly_d = calc_kd(df_w)

    # 月線
    df_m = resample_df(df, 'ME')
    monthly_data = df_to_ohlcv(df_m, [])
    monthly_k, monthly_d = calc_kd(df_m)

    buy_js = buy_date.strftime('%Y-%m-%d')

    import json
    daily_js = json.dumps(daily_data)
    weekly_js = json.dumps(weekly_data)
    monthly_js = json.dumps(monthly_data)
    daily_k_js = json.dumps(daily_k)
    daily_d_js = json.dumps(daily_d)
    weekly_k_js = json.dumps(weekly_k)
    weekly_d_js = json.dumps(weekly_d)
    monthly_k_js = json.dumps(monthly_k)
    monthly_d_js = json.dumps(monthly_d)

    return f"""
    <!DOCTYPE html><html><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
    <title>{code} {name}</title>
    <script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ background:#0d1117; margin:0; font-family:sans-serif; color:#e6edf3; display:flex; flex-direction:column; height:100vh; overflow:hidden; }}
        #header {{ padding:8px 12px; border-bottom:1px solid #30363d; flex-shrink:0; display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
        #title-row {{ display:flex; align-items:center; gap:8px; width:100%; }}
        #info {{ font-size:12px; color:#8b949e; margin-left:8px; }}
        #controls {{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; width:100%; }}
        .btn {{ background:#1c2128; border:1px solid #30363d; color:#e6edf3; padding:4px 10px; border-radius:4px; cursor:pointer; font-size:13px; }}
        .btn.active {{ background:#58a6ff; border-color:#58a6ff; color:#000; font-weight:bold; }}
        #ma-input {{ background:#1c2128; border:1px solid #30363d; color:#e6edf3; padding:4px 8px; border-radius:4px; font-size:13px; width:160px; }}
        #main-chart {{ flex-grow:1; width:100%; min-height:0; }}
        #kd-chart {{ height:130px; width:100%; border-top:1px solid #30363d; flex-shrink:0; }}
    </style>
    </head><body>
    <div id="header">
        <div id="title-row">
            <a href="../../index.html" style="color:#58a6ff;text-decoration:none;">← 返回</a>
            <strong>{code} {name}</strong>
            <span id="info"></span>
        </div>
        <div id="controls">
            <button class="btn active" onclick="switchPeriod('D',this)">日線</button>
            <button class="btn" onclick="switchPeriod('W',this)">週線</button>
            <button class="btn" onclick="switchPeriod('M',this)">月線</button>
            <input id="ma-input" type="text" value="60,240" placeholder="均線參數，例如 5,10,60,240">
            <button class="btn" onclick="applyMA()">套用均線</button>
        </div>
    </div>
    <div id="main-chart"></div>
    <div id="kd-chart"></div>
    <script>
        // ── 資料 ──
        const allData = {{
            D: {{ ohlcv: {daily_js}, k: {daily_k_js}, d: {daily_d_js} }},
            W: {{ ohlcv: {weekly_js}, k: {weekly_k_js}, d: {weekly_d_js} }},
            M: {{ ohlcv: {monthly_js}, k: {monthly_k_js}, d: {monthly_d_js} }}
        }};
        let currentPeriod = 'D';
        const maColors = ['#f59e0b','#a78bfa','#34d399','#fb7185','#38bdf8','#f97316'];

        // ── 圖表設定 ──
        const chartOptions = {{
            layout:{{ backgroundColor:'#0d1117', textColor:'#d1d4dc' }},
            grid:{{ vertLines:{{color:'#1f2937'}}, horzLines:{{color:'#1f2937'}} }},
            rightPriceScale:{{ borderColor:'#30363d' }},
            timeScale:{{ borderColor:'#30363d', visible:false, barSpacing:8, minBarSpacing:8 }},
            crosshair:{{ mode:1 }},
            handleScale:{{ axisPressedMouseMove:false, mouseWheel:false, pinch:true }},
            handleScroll:{{ mouseWheel:false, pressedMouseMove:true, horzTouchDrag:true, vertTouchDrag:false }}
        }};

        const mainChart = LightweightCharts.createChart(document.getElementById('main-chart'), chartOptions);
        const kdChart = LightweightCharts.createChart(document.getElementById('kd-chart'), {{
            ...chartOptions,
            timeScale:{{ ...chartOptions.timeScale, visible:true }}
        }});

        const candles = mainChart.addCandlestickSeries({{
            upColor:'#ff5252', downColor:'#26a69a',
            borderUpColor:'#ff5252', borderDownColor:'#26a69a',
            wickUpColor:'#ff5252', wickDownColor:'#26a69a'
        }});
        const vols = mainChart.addHistogramSeries({{
            color:'#26a69a', priceFormat:{{type:'volume'}},
            priceScaleId:'', scaleMargins:{{top:0.8, bottom:0}}
        }});
        const kLine = kdChart.addLineSeries({{ color:'#10b981', lineWidth:1.5, title:'K' }});
        const dLine = kdChart.addLineSeries({{ color:'#f97316', lineWidth:1.5, title:'D' }});

        let maSeries = [];

        // ── 計算均線 ──
        function calcMA(data, period) {{
            const result = [];
            for (let i = period - 1; i < data.length; i++) {{
                const sum = data.slice(i - period + 1, i + 1).reduce((a, b) => a + b.close, 0);
                result.push({{ time: data[i].time, value: parseFloat((sum / period).toFixed(2)) }});
            }}
            return result;
        }}

        // ── 套用均線 ──
        function applyMA() {{
            maSeries.forEach(s => mainChart.removeSeries(s));
            maSeries = [];
            const data = allData[currentPeriod].ohlcv;
            const input = document.getElementById('ma-input').value;
            const periods = input.split(',').map(v => parseInt(v.trim())).filter(v => !isNaN(v) && v > 0);
            periods.forEach((p, i) => {{
                const s = mainChart.addLineSeries({{
                    color: maColors[i % maColors.length],
                    lineWidth: 1,
                    title: 'MA' + p,
                    priceLineVisible: false
                }});
                s.setData(calcMA(data, p));
                maSeries.push(s);
            }});
        }}

        // ── 載入資料 ──
        function loadData(period) {{
            const d = allData[period];
            candles.setData(d.ohlcv);
            vols.setData(d.ohlcv.map(x => ({{
                time: x.time, value: x.value,
                color: x.isLimit ? '#eab308' : (x.close >= x.open ? '#ff525288' : '#26a69a88')
            }})));
            kLine.setData(d.k);
            dLine.setData(d.d);

            // BUY 標記只在日線顯示
            if (period === 'D') {{
                candles.setMarkers([{{ time:'{buy_js}', position:'belowBar', color:'#f8d210', shape:'arrowUp', text:'BUY' }}]);
            }} else {{
                candles.setMarkers([]);
            }}

            applyMA();

            // 日線預設顯示最近120根，週月線顯示全部
            const lastIdx = d.ohlcv.length - 1;
            if (period === 'D') {{
                const range = {{ from: d.ohlcv[Math.max(0, lastIdx - 120)].time, to: d.ohlcv[lastIdx].time }};
                mainChart.timeScale().setVisibleRange(range);
                kdChart.timeScale().setVisibleRange(range);
            }} else {{
                mainChart.timeScale().fitContent();
                kdChart.timeScale().fitContent();
            }}
        }}

        // ── 切換週期 ──
        function switchPeriod(period, btn) {{
            currentPeriod = period;
            document.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            loadData(period);
        }}

        // ── 同步滾動 ──
        let isSyncingRange = false;
        mainChart.timeScale().subscribeVisibleTimeRangeChange(range => {{
            if (isSyncingRange) return;
            isSyncingRange = true;
            kdChart.timeScale().setVisibleRange(range);
            isSyncingRange = false;
        }});
        kdChart.timeScale().subscribeVisibleTimeRangeChange(range => {{
            if (isSyncingRange) return;
            isSyncingRange = true;
            mainChart.timeScale().setVisibleRange(range);
            isSyncingRange = false;
        }});

        // ── 同步十字線 ──
        let isSyncingCrosshair = false;
        mainChart.subscribeCrosshairMove(p => {{
            if (isSyncingCrosshair || !p.time) return;
            isSyncingCrosshair = true;
            kdChart.setCrosshairPosition(p.price, p.time, kLine);
            isSyncingCrosshair = false;
            const d = allData[currentPeriod].ohlcv.find(i => i.time === p.time);
            if (d) document.getElementById('info').innerHTML = `開:${{d.open}} 高:${{d.high}} 低:${{d.low}} 收:${{d.close}}`;
        }});
        kdChart.subscribeCrosshairMove(p => {{
            if (isSyncingCrosshair || !p.time) return;
            isSyncingCrosshair = true;
            mainChart.setCrosshairPosition(p.price, p.time, candles);
            isSyncingCrosshair = false;
        }});

        // ── 初始載入 ──
        loadData('D');
    </script></body></html>
    """

# ── 單支股票處理（供多執行緒呼叫）────────────────────────────
def safe_float(val):
    """安全地將 Series 或純數值轉為 float，避免 ambiguous truth value"""
    if isinstance(val, pd.Series):
        return float(val.iloc[0])
    return float(val)

def process_stock(s, fetch_start, today, name_map, twii_bull, output_dir):
    """處理單支股票，回傳 result dict 或 None"""
    try:
        df = yf.download(s, start=fetch_start, end=today, progress=False)
        if len(df) < 240: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 驗證股票代碼未被 yfinance redirect 到其他股票
        expected_code = s.split('.')[0]
        actual_ticker = df.columns.get_level_values(1)[0] if isinstance(df.columns, pd.MultiIndex) else None
        if actual_ticker and actual_ticker != s:
            return None

        # 強制將所有欄位壓成一維 Series，防止多執行緒下 yfinance 回傳 MultiIndex 殘留
        for col in df.columns:
            df[col] = df[col].squeeze()

        close = pd.to_numeric(df['Close'], errors='coerce').dropna()
        volume = pd.to_numeric(df['Volume'], errors='coerce').dropna()
        df = df.loc[close.index]  # 對齊 index
        if len(close) < 240: return None

        ma60 = close.rolling(60).mean()
        ma240 = close.rolling(240).mean()

        recent_close = close.iloc[-90:]
        recent_ma240 = ma240.iloc[-90:]
        broken = (recent_close > recent_ma240) & (recent_close.shift(1) <= recent_ma240.shift(1))
        if not bool(broken.any()): return None

        p_min_90 = float(recent_close.min())
        p_max_90 = float(recent_close.max())
        wave_gain = (p_max_90 - p_min_90) / p_min_90
        if wave_gain < 0.30: return None

        limit_dates = [close.index[j] for j in range(len(close)-30, len(close))
                       if j > 0 and float(close.iloc[j]) >= (calc_limit_price(float(close.iloc[j-1])) - 0.01)]
        if not limit_dates: return None

        last_limit_date = limit_dates[-1]
        limit_vol = safe_float(volume.loc[last_limit_date])   # 修正：避免 Series ambiguous
        limit_low = safe_float(df.loc[last_limit_date, 'Low']) # 修正：避免 Series ambiguous

        curr_c = float(close.iloc[-1])
        curr_ma60 = float(ma60.iloc[-1])
        dist_ma60 = (curr_c - curr_ma60) / curr_ma60
        if abs(dist_ma60) > 0.025: return None

        win_kd = 9
        rsv = ((close - df['Low'].squeeze().rolling(win_kd).min()) /
               (df['High'].squeeze().rolling(win_kd).max() - df['Low'].squeeze().rolling(win_kd).min()) * 100).fillna(50)
        k = rsv.ewm(com=2).mean(); d = k.ewm(com=2).mean()

        win_rate = 45
        if float(ma60.iloc[-1]) > float(ma60.iloc[-5]): win_rate += 10
        else: win_rate -= 15
        if float(volume.iloc[-1]) < limit_vol * 0.4: win_rate += 10
        if float(k.iloc[-1]) > float(d.iloc[-1]) and float(k.iloc[-2]) <= float(d.iloc[-2]): win_rate += 5
        days_since = (today - last_limit_date).days
        if 10 <= days_since <= 30: win_rate += 5
        if twii_bull: win_rate += 5
        win_rate = max(10, min(win_rate, 75))

        diff = p_max_90 - p_min_90
        t1, t2, t3 = p_max_90 + diff*0.382, p_max_90 + diff*0.618, p_max_90 + diff*1.0

        code = s.split('.')[0]
        chart_html = generate_stock_chart(s, name_map.get(code, code), df, limit_dates, close.index[-1], ma60, ma240, k, d)
        with open(f"{output_dir}/{code}.html", "w", encoding="utf-8") as f:
            f.write(chart_html)

        return {
            "win": win_rate, "vol_r": float(volume.iloc[-1]) / limit_vol, "dist": abs(dist_ma60),
            "代碼": f"<a href='./charts/{code}.html' target='_blank'>{code} 📊</a>",
            "名稱": name_map.get(code, code), "勝率": f"{win_rate}%", "進場價": round(curr_c, 2),
            "停損價": round(limit_low, 2), "目標1": round(t1, 2), "目標2": round(t2, 2), "目標3": round(t3, 2),
            "K": round(float(k.iloc[-1]), 1), "D": round(float(d.iloc[-1]), 1)
        }
    except Exception as e:
        import traceback
        print(f"[錯誤] {s}: {e}\n{traceback.format_exc()}")
        return None

# ── 掃描主函式 ───────────────────────────────────────────────
def scan(today_str, output_dir="charts"):
    os.makedirs(output_dir, exist_ok=True)
    name_map = fetch_name_map()
    stocks = get_list()
    today = datetime.now()
    fetch_start = today - timedelta(days=3650)
    results = []

    # 大盤過濾
    try:
        twii_raw = yf.download("^TWII", start=today-timedelta(days=500), end=today, progress=False)
        if isinstance(twii_raw.columns, pd.MultiIndex):
            twii_raw.columns = twii_raw.columns.get_level_values(0)
        twii_bull = float(twii_raw['Close'].iloc[-1]) > float(twii_raw['Close'].rolling(240).mean().iloc[-1])
    except Exception as e:
        print(f"[警告] 大盤資料抓取失敗: {e}")
        twii_bull = True

    # 多執行緒掃描
    print(f"[掃描] 開始，共 {len(stocks)} 支，使用 {MAX_WORKERS} 執行緒...")
    completed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_stock, s, fetch_start, today, name_map, twii_bull, output_dir): s for s in stocks}
        for future in as_completed(futures):
            completed += 1
            if completed % 100 == 0:
                print(f"[進度] {completed}/{len(stocks)}...")
            result = future.result()
            if result:
                results.append(result)

    df_res = pd.DataFrame(results).sort_values(["win", "vol_r", "dist"], ascending=[False, True, True]) if results else pd.DataFrame()
    return df_res.drop(columns=["win", "vol_r", "dist"]) if not df_res.empty else df_res

# ── 歷史導覽列產生 ────────────────────────────────────────────
def build_history_nav(today_str):
    """掃描 history/ 資料夾，產生所有歷史日期的導覽連結"""
    os.makedirs("history", exist_ok=True)
    dates = sorted([
        f.replace(".html", "") for f in os.listdir("history") if f.endswith(".html")
    ], reverse=True)
    
    link_list = []
    for d in dates:
        bold = "font-weight:bold;" if d == today_str else ""
        link_list.append(f"<a href='./history/{d}.html' style='color:#58a6ff;text-decoration:none;{bold}'>{d}</a>")
    links = " | ".join(link_list)
    return f"<div style='margin-bottom:16px;font-size:13px;color:#8b949e;'>📅 歷史紀錄：{links}</div>" if links else ""

# ── 輸出 HTML ─────────────────────────────────────────────────
def to_html(df, today_str, is_history=False):
    """產生 HTML，is_history=True 時為歷史快照（不含導覽列更新）"""
    t = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    nav = build_history_nav(today_str) if not is_history else ""
    
    # 歷史頁的圖表連結要指向對應日期的 charts 資料夾
    table_html = df.to_html(index=False, escape=False) if not df.empty else "<p>今日無符合條件標的</p>"

    html = f"""
    <!DOCTYPE html><html><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>D-Pattern 選股{"（" + today_str + "）" if is_history else ""}</title>
    <style>
        body{{ background:#0d1117; color:#e6edf3; font-family:sans-serif; padding:16px; }}
        .container {{ width:100%; overflow-x:auto; }}
        table{{ width:100%; border-collapse:collapse; background:#161b22; border-radius:8px; }}
        th,td{{ padding:10px; border:1px solid #30363d; text-align:center; min-width:80px; }}
        th{{ background:#1c2128; color:#8b949e; font-size:12px; }} a{{ color:#58a6ff; text-decoration:none; font-weight:bold; }}
    </style>
    </head><body>
    <h1>🚀 D-Pattern 轉機偵測{"（" + today_str + "）" if is_history else ""}</h1>
    <p>更新：{t} (台北)</p>
    {nav}
    <div class="container">{table_html}</div>
    </body></html>
    """
    return html

# ── 自動清理超過 N 天的舊資料 ────────────────────────────────
def cleanup_old_data(today, keep_days=KEEP_DAYS):
    cutoff = today - timedelta(days=keep_days)
    
    # 清理 history/
    if os.path.exists("history"):
        for f in os.listdir("history"):
            if not f.endswith(".html"): continue
            try:
                date = datetime.strptime(f.replace(".html", ""), "%Y-%m-%d")
                if date < cutoff:
                    os.remove(f"history/{f}")
                    print(f"[清理] 刪除歷史頁面: history/{f}")
            except: continue

    # 清理 charts/日期/
    if os.path.exists("charts"):
        for d in os.listdir("charts"):
            dir_path = f"charts/{d}"
            if not os.path.isdir(dir_path): continue
            try:
                date = datetime.strptime(d, "%Y-%m-%d")
                if date < cutoff:
                    shutil.rmtree(dir_path)
                    print(f"[清理] 刪除舊圖表資料夾: {dir_path}")
            except: continue

# ── 主程式 ────────────────────────────────────────────────────
if __name__ == "__main__":
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    chart_dir = f"charts/{today_str}"

    # 1. 掃描（圖表存到 charts/今天日期/）
    df = scan(today_str, output_dir=chart_dir)

    # 2. 修正圖表連結為日期路徑
    if not df.empty:
        df["代碼"] = df["代碼"].str.replace("./charts/", f"./charts/{today_str}/", regex=False)

    # 3. 存歷史快照
    os.makedirs("history", exist_ok=True)
    history_df = df.copy()
    if not history_df.empty:
        history_df["代碼"] = history_df["代碼"].str.replace(f"./charts/{today_str}/", f"../charts/{today_str}/", regex=False)
    with open(f"history/{today_str}.html", "w", encoding="utf-8") as f:
        f.write(to_html(history_df, today_str, is_history=True))
    print(f"[歷史] 已儲存 history/{today_str}.html")

    # 4. 更新主頁（含歷史導覽列）
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(to_html(df, today_str, is_history=False))

    # 5. 清理超過 30 天的舊資料
    cleanup_old_data(today, KEEP_DAYS)

    print("DONE.")
