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


# ── HTML 圖表產生器 ───────────────────────────────────────────
def generate_stock_chart(symbol, name, df, limit_dates, buy_date, ma60_series, ma240_series, k_series, d_series):
    code = symbol.split('.')[0]

    def df_to_ohlcv(d, lim_dates):
        result = []
        for idx, row in d.iterrows():
            try:
                o = round(float(row['Open']), 2)
                h = round(float(row['High']), 2)
                l = round(float(row['Low']), 2)
                c = round(float(row['Close']), 2)
                v = float(row['Volume'])
                # 過濾掉任何 NaN 或無效資料
                if any(x != x for x in [o, h, l, c, v]): continue
                if h < l or h <= 0 or c <= 0: continue
                result.append({
                    "time": idx.strftime('%Y-%m-%d'),
                    "open": o, "high": h, "low": l, "close": c,
                    "value": v, "isLimit": idx in lim_dates
                })
            except: continue
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

    # 漲停日期列表轉 JS
    limit_dates_js = json.dumps([d.strftime('%Y-%m-%d') for d in limit_dates])

    # 如果日線資料是空的，回傳錯誤提示頁面
    if not daily_data:
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1.0">
        <title>{code} {name}</title></head>
        <body style="background:#0d1117;color:#e6edf3;font-family:sans-serif;padding:32px;">
        <a href="../../index.html" style="color:#58a6ff;">← 返回</a>
        <h2 style="margin-top:24px;">{code} {name}</h2>
        <p style="color:#8b949e;">無法取得此股票的 K 線資料，可能原因：yfinance 不支援此代碼，或資料尚未更新。</p>
        </body></html>"""

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
        #ohlc-row {{ font-size:12px; color:#8b949e; width:100%; padding:2px 0; }}
        #ma-row {{ font-size:11px; width:100%; padding:2px 0; display:flex; flex-wrap:wrap; gap:8px; }}
        #kd-row {{ font-size:11px; width:100%; padding:2px 0; display:flex; gap:12px; }}
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
        </div>
        <div id="ohlc-row"></div>
        <div id="ma-row"></div>
        <div id="kd-row"></div>
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
            handleScale:{{ axisPressedMouseMove:false, mouseWheel:true, pinch:true }},
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
        const kLine = kdChart.addLineSeries({{ color:'#10b981', lineWidth:1.5, lastValueVisible:false, crosshairMarkerVisible:false }});
        const dLine = kdChart.addLineSeries({{ color:'#f97316', lineWidth:1.5, lastValueVisible:false, crosshairMarkerVisible:false }});

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
            const maRowEl = document.getElementById('ma-row');
            maRowEl.innerHTML = '';
            periods.forEach((p, i) => {{
                const color = maColors[i % maColors.length];
                const s = mainChart.addLineSeries({{
                    color: color,
                    lineWidth: 1,
                    priceLineVisible: false,
                    lastValueVisible: false,
                    crosshairMarkerVisible: false
                }});
                const maData = calcMA(data, p);
                s.setData(maData);
                maSeries.push(s);
                // 顯示最新值
                const lastVal = maData.length > 0 ? maData[maData.length-1].value : '-';
                const span = document.createElement('span');
                span.id = 'ma-label-' + p;
                span.style.cssText = `color:${{color}};white-space:nowrap;`;
                span.innerHTML = `MA${{p}}: <b>${{lastVal}}</b>`;
                maRowEl.appendChild(span);
            }});
        }}

        // 漲停日標記
        const limitDates = {limit_dates_js};
        const limitMarkers = limitDates.map(d => ({{
            time: d,
            position: 'aboveBar',
            color: '#f8d210',
            shape: 'arrowDown',
            text: '🚀'
        }}));

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
                candles.setMarkers(limitMarkers);
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
        mainChart.timeScale().subscribeVisibleLogicalRangeChange(range => {{
            if (isSyncingRange || !range) return;
            isSyncingRange = true;
            kdChart.timeScale().setVisibleLogicalRange(range);
            isSyncingRange = false;
        }});
        kdChart.timeScale().subscribeVisibleLogicalRangeChange(range => {{
            if (isSyncingRange || !range) return;
            isSyncingRange = true;
            mainChart.timeScale().setVisibleLogicalRange(range);
            isSyncingRange = false;
        }});

        let isSyncingCrosshair = false;
        mainChart.subscribeCrosshairMove(p => {{
            if (isSyncingCrosshair || !p.time) return;
            isSyncingCrosshair = true;
            kdChart.setCrosshairPosition(p.price, p.time, kLine);
            isSyncingCrosshair = false;
            const d = allData[currentPeriod].ohlcv.find(i => i.time === p.time);
            if (d) {{
                const chg = d.close - d.open;
                const chgPct = (chg / d.open * 100).toFixed(2);
                const chgColor = chg >= 0 ? '#ff5252' : '#26a69a';
                document.getElementById('ohlc-row').innerHTML =
                    `${{p.time}} &nbsp; 開:<b>${{d.open}}</b> 高:<b style="color:#ff5252">${{d.high}}</b> 低:<b style="color:#26a69a">${{d.low}}</b> 收:<b style="color:${{chgColor}}">${{d.close}}</b> &nbsp;<span style="color:${{chgColor}}">${{chg>=0?'+':''}}${{chg.toFixed(2)}} (${{chg>=0?'+':''}}${{chgPct}}%)</span>`;
                // 更新均線數值
                maSeries.forEach((s, i) => {{
                    const input = document.getElementById('ma-input').value;
                    const periods = input.split(',').map(v => parseInt(v.trim())).filter(v => !isNaN(v) && v > 0);
                    const period = periods[i];
                    if (!period) return;
                    const maData = calcMA(allData[currentPeriod].ohlcv, period);
                    const found = maData.find(m => m.time === p.time);
                    const el = document.getElementById('ma-label-' + period);
                    if (el && found) el.innerHTML = `MA${{period}}: <b>${{found.value}}</b>`;
                }});
            }}
        }});
        kdChart.subscribeCrosshairMove(p => {{
            if (isSyncingCrosshair || !p.time) return;
            isSyncingCrosshair = true;
            mainChart.setCrosshairPosition(p.price, p.time, candles);
            isSyncingCrosshair = false;
            const kd = allData[currentPeriod];
            const kFound = kd.k.find(i => i.time === p.time);
            const dFound = kd.d.find(i => i.time === p.time);
            if (kFound && dFound) {{
                const kdColor = kFound.value > dFound.value ? '#10b981' : '#f97316';
                document.getElementById('kd-row').innerHTML =
                    `<span style="color:#10b981">K: <b>${{kFound.value}}</b></span>` +
                    `<span style="color:#f97316">D: <b>${{dFound.value}}</b></span>` +
                    `<span style="color:${{kdColor}};font-size:10px;">${{kFound.value > dFound.value ? '▲金叉' : '▼死叉'}}</span>`;
            }}
        }});

        loadData('D');
    </script></body></html>
    """

# ── 單支股票處理（供多執行緒呼叫）────────────────────────────
def safe_float(val):
    if isinstance(val, pd.Series):
        return float(val.iloc[0])
    return float(val)

def process_stock(s, fetch_start, today, name_map, twii_bull, output_dir):
    try:
        import yfinance as _yf
        try:
            df = _yf.download(s, start=fetch_start, end=today, progress=False, threads=False, timeout=15)
        except:
            return None

        if df is None or df.empty: return None

        # 處理 MultiIndex
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 修正欄位名稱大小寫不一致（新版 yfinance 可能回傳小寫）
        df.columns = [c.capitalize() for c in df.columns]

        required = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(c in df.columns for c in required): return None

        # 確保資料是 float 且移除 Close 為 NaN 的列
        df = df[required].astype(float).dropna(subset=['Close'])

        if len(df) < 240: return None

        close = df['Close']
        volume = df['Volume'].fillna(0)

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

        reasons = []  # 選股理由

        # ── 硬性過濾（不符合直接排除）──────────────────────────
        # 1. 型態破壞：收盤跌破漲停日低點 97%
        if curr_c < limit_low * 0.97:
            return None

        # 2. 整理天數：漲停後必須在 5～25 天內
        days_since = (today - last_limit_date).days
        if not (5 <= days_since <= 25):
            return None

        # 3. 位階過高：股價超過年線 180% 直接排除
        curr_ma240 = float(ma240.iloc[-1])
        price_ma240_ratio = curr_c / curr_ma240
        if price_ma240_ratio > 1.8:
            return None

        # ── 勝率評分 ──────────────────────────────────────────
        win_rate = 45

        # A. 季線方向
        if float(ma60.iloc[-1]) > float(ma60.iloc[-5]):
            win_rate += 10
            reasons.append("✅ 季線向上")
        else:
            win_rate -= 15
            reasons.append("⚠️ 季線走平或向下")

        # B. 成交量：近3日均量 vs 漲停爆量
        pullback_vol_ratio = float(volume.iloc[-3:].mean()) / limit_vol
        if pullback_vol_ratio < 0.35:
            win_rate += 15
            reasons.append(f"✅ 窒息量縮（近3日均量僅漲停量{pullback_vol_ratio*100:.0f}%）")
        elif pullback_vol_ratio < 0.5:
            win_rate += 8
            reasons.append(f"✅ 量縮洗盤（近3日均量{pullback_vol_ratio*100:.0f}%）")
        else:
            win_rate -= 10
            reasons.append(f"⚠️ 量未明顯縮（近3日均量{pullback_vol_ratio*100:.0f}%）")

        # C. 位階
        if price_ma240_ratio > 1.4:
            win_rate -= 10
            reasons.append(f"⚠️ 位階偏高（股價為年線{price_ma240_ratio*100:.0f}%）")
        elif 1.05 <= price_ma240_ratio <= 1.35:
            win_rate += 10
            reasons.append(f"✅ 位階理想（股價為年線{price_ma240_ratio*100:.0f}%）")
        else:
            reasons.append(f"📍 位階：股價為年線{price_ma240_ratio*100:.0f}%")

        # D. KD 金叉
        if float(k.iloc[-1]) > float(d.iloc[-1]) and float(k.iloc[-2]) <= float(d.iloc[-2]):
            win_rate += 10
            reasons.append("✅ KD 低檔金叉")
        elif float(k.iloc[-1]) > float(d.iloc[-1]):
            win_rate += 5
            reasons.append("📍 KD K>D 上行中")

        # E. 整理天數最佳區間
        if 7 <= days_since <= 15:
            win_rate += 10
            reasons.append(f"✅ 整理天數理想（{days_since}天）")
        else:
            reasons.append(f"📍 整理天數：{days_since}天")

        # F. 大盤位置分段
        twii_close_val, twii_ma20_val, twii_ma60_val, twii_ma240_val = twii_bull
        if twii_close_val > twii_ma20_val:
            win_rate += 15
            reasons.append("✅ 大盤強勢（站上20MA）")
        elif twii_close_val > twii_ma60_val:
            win_rate += 5
            reasons.append("📍 大盤中性（站上60MA）")
        elif twii_close_val < twii_ma240_val:
            win_rate -= 20
            reasons.append("⚠️ 大盤弱勢（跌破年線）")
        else:
            reasons.append("📍 大盤整理中")

        # G. 第一波強度
        if wave_gain >= 0.5:
            win_rate += 10
            reasons.append(f"✅ 第一波強勁（漲幅{wave_gain*100:.0f}%）")
        else:
            reasons.append(f"📍 第一波漲幅{wave_gain*100:.0f}%")

        win_rate = max(10, min(win_rate, 90))

        # ── 目標價（黃金切割）──────────────────────────────────
        diff = p_max_90 - p_min_90
        t1 = round(p_max_90 + diff*0.382, 2)
        t2 = round(p_max_90 + diff*0.618, 2)
        t3 = round(p_max_90 + diff*1.0, 2)

        # ── 觸發價（突破近期高點）──────────────────────────────
        recent_high = float(df['High'].iloc[-20:].max())
        trigger_price = round(recent_high * 1.01, 2)

        # ── 支撐群掛單區間 ──────────────────────────────────────
        limit_open = safe_float(df.loc[last_limit_date, 'Open'])
        recent_low_support = float(df['Low'].iloc[-20:].min())
        support_candidates = [curr_ma60, limit_open, limit_low, recent_low_support]
        valid_supports = [x for x in support_candidates if x < curr_c and x > 0]
        support_price = max(valid_supports) if valid_supports else curr_ma60
        order_low  = round(support_price * 0.99, 2)
        order_high = round(support_price * 1.01, 2)

        code = s.split('.')[0]
        chart_html = generate_stock_chart(
            s, name_map.get(code, code), df, limit_dates,
            close.index[-1], ma60, ma240, k, d
        )
        with open(f"{output_dir}/{code}.html", "w", encoding="utf-8") as f:
            f.write(chart_html)

        reason_str = "｜".join(reasons)

        return {
            "win": win_rate,
            "vol_r": pullback_vol_ratio,
            "dist": abs(dist_ma60),
            "代碼": f"<a href='./charts/{code}.html' target='_blank'>{code} 📊</a>",
            "名稱": name_map.get(code, code),
            "收盤價": round(curr_c, 2),
            "勝率": f"{win_rate}%",
            "掛單區間": f"{order_low}～{order_high}",
            "觸發價": trigger_price,
            "停損價": round(limit_low, 2),
            "目標①": t1, "目標②": t2, "目標③": t3,
            "K": round(float(k.iloc[-1]), 1),
            "D": round(float(d.iloc[-1]), 1),
            "選股理由": reason_str
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
    fetch_start = datetime(2000, 1, 1)  # 抓全歷史資料
    results = []

    try:
        twii_raw = yf.download("^TWII", start=today-timedelta(days=500), end=today, progress=False)
        if isinstance(twii_raw.columns, pd.MultiIndex):
            twii_raw.columns = twii_raw.columns.get_level_values(0)
        twii_raw.columns = [c.capitalize() for c in twii_raw.columns]
        twii_c = twii_raw['Close']
        twii_bull = (
            float(twii_c.iloc[-1]),
            float(twii_c.rolling(20).mean().iloc[-1]),
            float(twii_c.rolling(60).mean().iloc[-1]),
            float(twii_c.rolling(240).mean().iloc[-1])
        )
    except Exception as e:
        print(f"[警告] 大盤資料抓取失敗: {e}")
        twii_bull = (0, 0, 0, 0)

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

    if not df.empty:
        rows_html = ""
        for _, row in df.iterrows():
            # 勝率
            win_str = str(row.get("勝率", "0%")).replace("%", "")
            try: win_val = int(win_str)
            except: win_val = 0
            if win_val >= 65:
                win_color = "#ff4040"; win_bg = "#3d1a1a"
            elif win_val >= 50:
                win_color = "#ffa500"; win_bg = "#2d2200"
            else:
                win_color = "#26a69a"; win_bg = "#0d2420"

            # KD 金叉/死叉
            try:
                k_val = float(row.get("K", 50))
                d_val = float(row.get("D", 50))
                kd_color = "#ff4040" if k_val > d_val else "#26a69a"
                kd_tag = "▲金叉" if k_val > d_val else "▼死叉"
            except:
                kd_color = "#888"; kd_tag = "-"

            # 收盤價
            close_val = row.get("收盤價", "")
            # 停損距離%
            try:
                stop = float(row.get("停損價", 0))
                close_f = float(close_val)
                stop_pct = round((stop - close_f) / close_f * 100, 1)
                stop_str = f"{stop} <span style='color:#888;font-size:11px;'>({stop_pct}%)</span>"
            except:
                stop_str = str(row.get("停損價", ""))

            trigger = row.get("觸發價", "")
            reason_html = ""
            for r in str(row.get("選股理由","")).split("｜"):
                r = r.strip()
                if not r: continue
                if r.startswith("✅"):
                    c = "#26a69a"
                elif r.startswith("⚠️"):
                    c = "#ffa500"
                else:
                    c = "#666"
                reason_html += f'<span style="color:{c};margin-right:6px;font-size:11px;">{r}</span>'

            rows_html += f"""
            <tr>
                <td style="text-align:left;padding-left:10px;min-width:80px;">{row.get("代碼","")}</td>
                <td style="text-align:left;min-width:70px;color:#ccc;">{row.get("名稱","")}</td>
                <td style="color:#ff4040;font-weight:bold;font-size:15px;min-width:60px;">{close_val}</td>
                <td style="min-width:65px;">
                    <span style="background:{win_bg};color:{win_color};font-weight:bold;padding:4px 8px;border-radius:4px;border:1px solid {win_color};font-size:13px;">{row.get("勝率","")}</span>
                </td>
                <td style="color:#ffd700;font-size:12px;min-width:110px;">{row.get("掛單區間","")}</td>
                <td style="color:#ff9900;font-weight:bold;min-width:65px;">{trigger}</td>
                <td style="color:#26a69a;min-width:100px;">{stop_str}</td>
                <td style="color:#ff8c00;min-width:60px;">{row.get("目標①","")}</td>
                <td style="color:#ff6060;min-width:60px;">{row.get("目標②","")}</td>
                <td style="color:#ff3030;font-weight:bold;min-width:60px;">{row.get("目標③","")}</td>
                <td style="min-width:90px;">
                    <span style="color:{kd_color};font-weight:bold;">{row.get("K","")}</span>
                    <span style="color:#555;">/</span>
                    <span style="color:{kd_color};">{row.get("D","")}</span>
                    <br><span style="color:{kd_color};font-size:10px;">{kd_tag}</span>
                </td>
                <td style="text-align:left;min-width:300px;line-height:1.8;">{reason_html}</td>
            </tr>"""

        table_html = f"""
        <table>
            <thead>
                <tr>
                    <th>代碼 📊</th>
                    <th>名稱</th>
                    <th>收盤價</th>
                    <th>勝率</th>
                    <th>掛單區間</th>
                    <th>觸發價</th>
                    <th>停損價</th>
                    <th>目標①</th>
                    <th>目標②</th>
                    <th>目標③</th>
                    <th>KD</th>
                    <th>選股理由</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>"""
    else:
        table_html = """
        <div style='text-align:center;padding:60px 20px;color:#444;'>
            <div style='font-size:32px;margin-bottom:12px;'>📭</div>
            <div style='font-size:14px;'>今日無符合條件標的</div>
        </div>"""

    count_str = f"共 {len(df)} 檔" if not df.empty else "0 檔"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>D-Pattern 選股{"｜" + today_str if is_history else ""}</title>
    <style>
        * {{ box-sizing:border-box; margin:0; padding:0; }}
        body {{ background:#0d0d0d; color:#e0e0e0; font-family:"Microsoft JhengHei","PingFang TC",sans-serif; font-size:13px; min-height:100vh; }}
        #topbar {{
            background:linear-gradient(135deg,#1a0a0a 0%,#1a1a2e 100%);
            border-bottom:2px solid #ff4040;
            padding:10px 14px;
            display:flex; justify-content:space-between; align-items:center;
            position:sticky; top:0; z-index:100;
        }}
        .topbar-left {{ display:flex; align-items:center; gap:10px; }}
        .topbar-title {{ color:#ff4040; font-size:17px; font-weight:bold; letter-spacing:1px; }}
        .topbar-count {{ background:#2a0a0a; color:#ff6060; border:1px solid #ff4040; padding:2px 8px; border-radius:10px; font-size:11px; }}
        .topbar-meta {{ color:#666; font-size:11px; text-align:right; line-height:1.6; }}
        .nav-bar {{
            background:#111;
            padding:6px 14px;
            border-bottom:1px solid #1e1e1e;
            font-size:11px;
            color:#555;
            overflow-x:auto;
            white-space:nowrap;
        }}
        .nav-bar a {{ color:#58a6ff; text-decoration:none; margin-right:8px; }}
        .container {{ width:100%; overflow-x:auto; padding:8px 4px; }}
        table {{ width:100%; border-collapse:collapse; min-width:720px; }}
        thead tr {{
            background:#1a1a1a;
            border-bottom:2px solid #ff4040;
        }}
        th {{
            padding:10px 8px;
            color:#888;
            font-size:11px;
            text-align:center;
            letter-spacing:0.5px;
            white-space:nowrap;
            font-weight:normal;
        }}
        tbody tr {{
            border-bottom:1px solid #1a1a1a;
            transition:background 0.1s;
        }}
        tbody tr:nth-child(even) {{ background:#0f0f0f; }}
        tbody tr:hover {{ background:#1e1e1e; }}
        td {{
            padding:10px 8px;
            text-align:center;
            white-space:nowrap;
        }}
        a {{ color:#58a6ff; text-decoration:none; font-weight:bold; }}
        a:hover {{ color:#ff4040; }}
        .section-label {{
            padding:6px 14px;
            font-size:11px;
            color:#555;
            border-bottom:1px solid #1a1a1a;
            letter-spacing:1px;
        }}
        .footer {{
            padding:14px;
            text-align:center;
            color:#333;
            font-size:11px;
            border-top:1px solid #1a1a1a;
            margin-top:4px;
        }}
    </style>
    </head><body>
    <div id="topbar">
        <div class="topbar-left">
            <span class="topbar-title">📈 D-Pattern</span>
            <span class="topbar-count">{count_str}</span>
        </div>
        <div class="topbar-meta">
            {"📅 " + today_str + "<br>" if is_history else ""}更新 {t} 台北
        </div>
    </div>
    <div class="nav-bar">{nav if nav else "📅 歷史紀錄：暫無"}</div>
    <div class="section-label">▸ 葛蘭碧轉機｜突破年線 → 回測季線｜依勝率排序</div>
    <div class="container">{table_html}</div>
    <div class="footer">本系統僅供參考，不構成投資建議。投資有風險，操作須謹慎。</div>
    </body></html>"""
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
