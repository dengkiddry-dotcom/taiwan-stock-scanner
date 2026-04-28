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
KEEP_DAYS = 30
MAX_WORKERS = 5
INSTITUTIONAL_MONTHS = 3  # 三大法人抓幾個月

# ── 核心工具函式 ──────────────────────────────────────────────
def calc_limit_price(prev_close: float) -> float:
    raw = prev_close * 1.1
    if raw < 10: tick = 0.01
    elif raw < 50: tick = 0.05
    elif raw < 100: tick = 0.1
    elif raw < 500: tick = 0.5
    elif raw < 1000: tick = 1.0
    else: tick = 5.0
    return math.floor(raw / tick + 0.0001) * tick

def fetch_name_map() -> dict:
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
    res = []
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchange_report/STOCK_DAY_ALL", timeout=15)
        res += [f"{i['Code']}.TW" for i in r.json() if len(i['Code']) == 4]
        r2 = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=15)
        res += [f"{i['SecuritiesCompanyCode']}.TWO" for i in r2.json() if len(i['SecuritiesCompanyCode']) == 4]
    except Exception as e:
        print(f"[系統] 清單抓取失敗: {e}")
    return res[:target]

# ── 三大法人資料抓取 ──────────────────────────────────────────
def fetch_institutional_daily(code: str, months: int = 3) -> list:
    """
    抓取單支股票每日三大法人買賣超。
    T86 API 以月份查詢，每次回傳該月所有交易日的全市場資料。
    欄位索引（已驗證）：
      0: 證券代號, 4: 外資買賣超, 7: 投信買賣超, 8: 自營商買賣超
    """
    result = []
    today = datetime.now()

    def parse_num(s):
        try: return int(str(s).replace(',', '').replace('+', '').strip())
        except: return 0

    # 產生過去 N 個月的查詢日期（每月1號）
    month_list = []
    for m in range(months):
        d = today.replace(day=1) - timedelta(days=30 * m)
        month_list.append(d.strftime('%Y%m01'))

    for date_str in month_list:
        try:
            url = (f"https://www.twse.com.tw/rwd/zh/fund/T86"
                   f"?date={date_str}&selectType=ALLBUT0999&response=json")
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            data = r.json()
            if data.get('stat') != 'OK':
                continue

            rows = data.get('data', [])
            date_label = data.get('date', date_str[:6])  # API 有時會回傳查詢日期

            for row in rows:
                if len(row) < 9: continue
                row_code = str(row[0]).strip()
                if row_code != code: continue

                # 解析民國年日期，例如 "113/04/28" → "2024-04-28"
                raw_date = str(row[0] if len(row) == 1 else date_label)
                try:
                    # T86 當日報表沒有逐日欄位，用查詢月份標記
                    year = int(date_str[:4])
                    month = int(date_str[4:6])
                    display_date = f"{year}/{month:02d}"
                except:
                    display_date = date_str[:6]

                result.append({
                    "date": display_date,
                    "foreign": parse_num(row[4]),   # 外資買賣超股數
                    "invest":  parse_num(row[7]),   # 投信買賣超股數
                    "dealer":  parse_num(row[8]),   # 自營商買賣超股數
                })
                break  # 找到該股票就跳出

            time.sleep(0.5)
        except Exception as e:
            continue

    return list(reversed(result))

# ── HTML 圖表產生器 ───────────────────────────────────────────
def generate_stock_chart(symbol, name, df, limit_dates, buy_date, ma60_series, ma240_series, k_series, d_series, institutional_data=None):
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
        close = pd.to_numeric(d['Close'].squeeze(), errors='coerce').dropna()
        high = pd.to_numeric(d['High'].squeeze(), errors='coerce').reindex(close.index).fillna(close)
        low = pd.to_numeric(d['Low'].squeeze(), errors='coerce').reindex(close.index).fillna(close)
        win = 9
        denom = high.rolling(win).max() - low.rolling(win).min()
        denom = denom.replace(0, 1)
        rsv = ((close - low.rolling(win).min()) / denom * 100).fillna(50)
        k = rsv.ewm(com=2).mean()
        dv = k.ewm(com=2).mean()
        return (
            [{"time": i.strftime('%Y-%m-%d'), "value": round(float(v), 1)} for i, v in k.dropna().items()],
            [{"time": i.strftime('%Y-%m-%d'), "value": round(float(v), 1)} for i, v in dv.dropna().items()]
        )

    def resample_df(d, rule):
        r = d.resample(rule).agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        return r

    daily_data = df_to_ohlcv(df, limit_dates)
    daily_k, daily_d = calc_kd(df)
    df_w = resample_df(df, 'W')
    weekly_data = df_to_ohlcv(df_w, [])
    weekly_k, weekly_d = calc_kd(df_w)
    df_m = resample_df(df, 'ME')
    monthly_data = df_to_ohlcv(df_m, [])
    monthly_k, monthly_d = calc_kd(df_m)

    buy_js = buy_date.strftime('%Y-%m-%d')

    daily_js = json.dumps(daily_data)
    weekly_js = json.dumps(weekly_data)
    monthly_js = json.dumps(monthly_data)
    daily_k_js = json.dumps(daily_k)
    daily_d_js = json.dumps(daily_d)
    weekly_k_js = json.dumps(weekly_k)
    weekly_d_js = json.dumps(weekly_d)
    monthly_k_js = json.dumps(monthly_k)
    monthly_d_js = json.dumps(monthly_d)

    # 三大法人資料
    inst_js = json.dumps(institutional_data or [])
    has_inst = bool(institutional_data)
    inst_section = """
    <div id="inst-chart" style="width:100%;border-top:1px solid #30363d;flex-shrink:0;padding:8px 12px;">
        <div style="font-size:11px;color:#8b949e;margin-bottom:4px;">📊 三大法人買賣超（近3個月，單位：張）</div>
        <canvas id="instCanvas" style="width:100%;height:120px;"></canvas>
    </div>
    """ if has_inst else ""

    inst_script = f"""
    // ── 三大法人柱狀圖 ──
    const instData = {inst_js};
    if (instData.length > 0) {{
        const canvas = document.getElementById('instCanvas');
        const ctx = canvas.getContext('2d');
        canvas.width = canvas.offsetWidth;
        canvas.height = 120;
        const W = canvas.width, H = canvas.height;
        const n = instData.length;
        const barW = Math.floor(W / (n * 3 + n + 1));
        const gap = Math.floor(barW * 0.3);
        const maxVal = Math.max(...instData.flatMap(d => [Math.abs(d.foreign), Math.abs(d.invest), Math.abs(d.dealer)])) || 1;
        const midY = H * 0.5;
        const scale = midY / maxVal * 0.9;

        instData.forEach((d, i) => {{
            const x0 = gap + i * (barW * 3 + gap * 2);
            [['foreign','#38bdf8'],['invest','#f59e0b'],['dealer','#a78bfa']].forEach(([key, color], j) => {{
                const val = d[key];
                const bh = Math.abs(val) * scale;
                const x = x0 + j * (barW + 1);
                const y = val >= 0 ? midY - bh : midY;
                ctx.fillStyle = val >= 0 ? color : color + '88';
                ctx.fillRect(x, y, barW, bh || 1);
            }});
            ctx.fillStyle = '#8b949e';
            ctx.font = '9px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(d.date, x0 + barW * 1.5, H - 2);
        }});

        // 圖例
        ctx.font = '10px sans-serif';
        [['外資','#38bdf8',0],['投信','#f59e0b',50],['自營','#a78bfa',100]].forEach(([label, color, ox]) => {{
            ctx.fillStyle = color;
            ctx.fillRect(ox, 2, 10, 10);
            ctx.fillStyle = '#e6edf3';
            ctx.fillText(label, ox + 14, 11);
        }});

        // 零軸線
        ctx.strokeStyle = '#30363d';
        ctx.beginPath();
        ctx.moveTo(0, midY);
        ctx.lineTo(W, midY);
        ctx.stroke();
    }}
    """ if has_inst else ""

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
            <input id="ma-input" type="text" value="5,10,20,60,240" placeholder="均線參數，例如 5,10,20,60,240">
            <button class="btn" onclick="applyMA()">套用均線</button>
        </div>
    </div>
    <div id="main-chart"></div>
    <div id="kd-chart"></div>
    {inst_section}
    <script>
        const allData = {{
            D: {{ ohlcv: {daily_js}, k: {daily_k_js}, d: {daily_d_js} }},
            W: {{ ohlcv: {weekly_js}, k: {weekly_k_js}, d: {weekly_d_js} }},
            M: {{ ohlcv: {monthly_js}, k: {monthly_k_js}, d: {monthly_d_js} }}
        }};
        let currentPeriod = 'D';
        const maColors = ['#f59e0b','#a78bfa','#34d399','#fb7185','#38bdf8','#f97316'];

        const chartOptions = {{
            layout:{{ backgroundColor:'#0d1117', textColor:'#d1d4dc' }},
            grid:{{ vertLines:{{color:'#1f2937'}}, horzLines:{{color:'#1f2937'}} }},
            rightPriceScale:{{ borderColor:'#30363d' }},
            timeScale:{{ borderColor:'#30363d', visible:false, barSpacing:8, minBarSpacing:8, fixLeftEdge:true, fixRightEdge:true }},
            crosshair:{{ mode:1 }},
            handleScale:{{ axisPressedMouseMove:false, mouseWheel:false, pinch:true }},
            handleScroll:{{ mouseWheel:false, pressedMouseMove:true, horzTouchDrag:true, vertTouchDrag:false }}
        }};

        const mainChart = LightweightCharts.createChart(document.getElementById('main-chart'), chartOptions);
        const kdChart = LightweightCharts.createChart(document.getElementById('kd-chart'), {{
            ...chartOptions,
            timeScale:{{ ...chartOptions.timeScale, visible:true, fixLeftEdge:true, fixRightEdge:true }}
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

        function calcMA(data, period) {{
            const result = [];
            for (let i = period - 1; i < data.length; i++) {{
                const sum = data.slice(i - period + 1, i + 1).reduce((a, b) => a + b.close, 0);
                result.push({{ time: data[i].time, value: parseFloat((sum / period).toFixed(2)) }});
            }}
            return result;
        }}

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

        function loadData(period) {{
            const d = allData[period];
            candles.setData(d.ohlcv);
            vols.setData(d.ohlcv.map(x => ({{
                time: x.time, value: x.value,
                color: x.isLimit ? '#eab308' : (x.close >= x.open ? '#ff525288' : '#26a69a88')
            }})));
            kLine.setData(d.k);
            dLine.setData(d.d);
            if (period === 'D') {{
                candles.setMarkers([{{ time:'{buy_js}', position:'belowBar', color:'#f8d210', shape:'arrowUp', text:'BUY' }}]);
            }} else {{
                candles.setMarkers([]);
            }}
            applyMA();
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

        function switchPeriod(period, btn) {{
            currentPeriod = period;
            document.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            loadData(period);
        }}

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

        loadData('D');
        {inst_script}
    </script></body></html>
    """

# ── 單支股票處理（供多執行緒呼叫）────────────────────────────
def safe_float(val):
    if isinstance(val, pd.Series):
        return float(val.iloc[0])
    return float(val)

def process_stock(s, fetch_start, today, name_map, twii_bull, output_dir):
    try:
        # 用 session 隔離避免多執行緒資料污染
        import yfinance as _yf
        df = _yf.download(s, start=fetch_start, end=today, progress=False, threads=False)
        if df is None or df.empty or len(df) < 240: return None

        # 處理 MultiIndex
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 確認欄位存在
        required = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(c in df.columns for c in required): return None
        df = df[required].copy()

        # 強制每個欄位都是一維
        for col in df.columns:
            df[col] = pd.to_numeric(df[col].squeeze(), errors='coerce')

        close = df['Close'].dropna()
        volume = df['Volume'].dropna()
        df = df.loc[close.index]
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
        limit_vol = safe_float(volume.loc[last_limit_date])
        limit_low = safe_float(df.loc[last_limit_date, 'Low'])

        curr_c = float(close.iloc[-1])
        curr_ma60 = float(ma60.iloc[-1])
        dist_ma60 = (curr_c - curr_ma60) / curr_ma60
        if abs(dist_ma60) > 0.025: return None

        win_kd = 9
        rsv = ((close - df['Low'].squeeze().rolling(win_kd).min()) /
               (df['High'].squeeze().rolling(win_kd).max() - df['Low'].squeeze().rolling(win_kd).min()) * 100).fillna(50)
        k = rsv.ewm(com=2).mean()
        d = k.ewm(com=2).mean()

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

        # 抓三大法人（只對上市股票，上櫃暫不支援）
        inst_data = []
        if s.endswith('.TW'):
            try:
                inst_data = fetch_institutional_daily(code, INSTITUTIONAL_MONTHS)
            except:
                inst_data = []

        chart_html = generate_stock_chart(
            s, name_map.get(code, code), df, limit_dates,
            close.index[-1], ma60, ma240, k, d,
            institutional_data=inst_data
        )
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

    try:
        twii_raw = yf.download("^TWII", start=today-timedelta(days=500), end=today, progress=False)
        if isinstance(twii_raw.columns, pd.MultiIndex):
            twii_raw.columns = twii_raw.columns.get_level_values(0)
        twii_bull = float(twii_raw['Close'].iloc[-1]) > float(twii_raw['Close'].rolling(240).mean().iloc[-1])
    except Exception as e:
        print(f"[警告] 大盤資料抓取失敗: {e}")
        twii_bull = True

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

# ── 歷史導覽列 ────────────────────────────────────────────────
def build_history_nav(today_str):
    os.makedirs("history", exist_ok=True)
    dates = sorted([f.replace(".html", "") for f in os.listdir("history") if f.endswith(".html")], reverse=True)
    link_list = []
    for d in dates:
        bold = "font-weight:bold;" if d == today_str else ""
        link_list.append(f"<a href='./history/{d}.html' style='color:#58a6ff;text-decoration:none;{bold}'>{d}</a>")
    links = " | ".join(link_list)
    return f"<div style='margin-bottom:16px;font-size:13px;color:#8b949e;'>📅 歷史紀錄：{links}</div>" if links else ""

# ── 輸出 HTML ─────────────────────────────────────────────────
def to_html(df, today_str, is_history=False):
    t = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    nav = build_history_nav(today_str) if not is_history else ""
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
        th{{ background:#1c2128; color:#8b949e; font-size:12px; }}
        a{{ color:#58a6ff; text-decoration:none; font-weight:bold; }}
    </style>
    </head><body>
    <h1>🚀 D-Pattern 轉機偵測{"（" + today_str + "）" if is_history else ""}</h1>
    <p>更新：{t} (台北)</p>
    {nav}
    <div class="container">{table_html}</div>
    </body></html>
    """
    return html

# ── 自動清理 ──────────────────────────────────────────────────
def cleanup_old_data(today, keep_days=KEEP_DAYS):
    cutoff = today - timedelta(days=keep_days)
    if os.path.exists("history"):
        for f in os.listdir("history"):
            if not f.endswith(".html"): continue
            try:
                date = datetime.strptime(f.replace(".html", ""), "%Y-%m-%d")
                if date < cutoff:
                    os.remove(f"history/{f}")
                    print(f"[清理] 刪除歷史頁面: history/{f}")
            except: continue
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

    df = scan(today_str, output_dir=chart_dir)

    if not df.empty:
        df["代碼"] = df["代碼"].str.replace("./charts/", f"./charts/{today_str}/", regex=False)

    os.makedirs("history", exist_ok=True)
    history_df = df.copy()
    if not history_df.empty:
        history_df["代碼"] = history_df["代碼"].str.replace(f"./charts/{today_str}/", f"../charts/{today_str}/", regex=False)
    with open(f"history/{today_str}.html", "w", encoding="utf-8") as f:
        f.write(to_html(history_df, today_str, is_history=True))
    print(f"[歷史] 已儲存 history/{today_str}.html")

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(to_html(df, today_str, is_history=False))

    cleanup_old_data(today, KEEP_DAYS)
    print("DONE.")
