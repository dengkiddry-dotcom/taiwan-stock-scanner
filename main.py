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
                v = float(row['Volume']) / 1000  # 股數轉張
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

    limit_dates_js = json.dumps([d.strftime('%Y-%m-%d') for d in limit_dates])

    if not daily_data:
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1.0">
        <title>{code} {name}</title></head>
        <body style="background:#0d1117;color:#e6edf3;font-family:sans-serif;padding:32px;">
        <a href="../../index.html" style="color:#58a6ff;">← 返回</a>
        <h2 style="margin-top:24px;">{code} {name}</h2>
        <p style="color:#8b949e;">無法取得此股票的 K 線資料，可能原因：yfinance 不支援此代碼，或資料尚未更新。</p>
        </body></html>"""

    def calc_macd(d, fast=12, slow=26, signal=9):
        close = pd.to_numeric(d['Close'].squeeze(), errors='coerce').dropna()
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        macd = dif.ewm(span=signal, adjust=False).mean()
        osc = dif - macd
        def to_js(s):
            return [{"time": i.strftime('%Y-%m-%d'), "value": round(float(v), 4)} for i, v in s.dropna().items()]
        return to_js(dif), to_js(macd), to_js(osc)

    weekly_dif, weekly_macd, weekly_osc = calc_macd(df_w)

    daily_js = json.dumps(daily_data)
    weekly_js = json.dumps(weekly_data)
    monthly_js = json.dumps(monthly_data)
    daily_k_js = json.dumps(daily_k)
    daily_d_js = json.dumps(daily_d)
    weekly_k_js = json.dumps(weekly_k)
    weekly_d_js = json.dumps(weekly_d)
    monthly_k_js = json.dumps(monthly_k)
    monthly_d_js = json.dumps(monthly_d)
    weekly_dif_js = json.dumps(weekly_dif)
    weekly_macd_js = json.dumps(weekly_macd)
    weekly_osc_js = json.dumps(weekly_osc)

    return f"""
    <!DOCTYPE html><html><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
    <title>{code} {name}</title>
    <script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        * {{ box-sizing:border-box; margin:0; padding:0; }}
        body {{ background:#0d0d0d; color:#e0e0e0; font-family:"Microsoft JhengHei","PingFang TC",sans-serif; display:flex; flex-direction:column; height:100vh; overflow:hidden; }}
        #header {{ background:#111; border-bottom:1px solid #222; flex-shrink:0; padding:4px 8px; }}
        #title-row {{ display:flex; align-items:center; gap:8px; margin-bottom:3px; }}
        #title-row a {{ color:#58a6ff; font-size:12px; text-decoration:none; }}
        #title-row strong {{ font-size:14px; color:#fff; }}
        #controls {{ display:flex; flex-wrap:wrap; gap:4px; align-items:center; }}
        .btn {{ background:#1c1c1c; border:1px solid #333; color:#aaa; padding:3px 8px; border-radius:3px; cursor:pointer; font-size:12px; }}
        .btn.active {{ background:#c0392b; border-color:#c0392b; color:#fff; font-weight:bold; }}
        #ma-input {{ background:#1c1c1c; border:1px solid #333; color:#e0e0e0; padding:3px 6px; border-radius:3px; font-size:12px; width:130px; }}
        .info-bar {{ background:#111; border-bottom:1px solid #1a1a1a; padding:2px 8px; font-size:11px; display:flex; flex-wrap:wrap; gap:6px; align-items:center; flex-shrink:0; min-height:18px; }}
        .chart-label {{ background:#0f0f0f; border-top:1px solid #1a1a1a; padding:2px 8px; font-size:11px; color:#555; flex-shrink:0; display:flex; gap:8px; align-items:center; }}
        .chart-label span.lbl {{ color:#555; }}
        #main-chart {{ flex:6; width:100%; min-height:0; }}
        #vol-chart  {{ flex:2; width:100%; min-height:0; }}
        #sub-chart  {{ flex:2; width:100%; min-height:0; }}
        /* 長按提示 */
        #pin-toast {{
            position:fixed; bottom:60px; left:50%; transform:translateX(-50%);
            background:#222; color:#f59e0b; border:1px solid #f59e0b;
            padding:4px 14px; border-radius:12px; font-size:11px;
            opacity:0; transition:opacity 0.3s; pointer-events:none; z-index:999;
        }}
        #pin-toast.show {{ opacity:1; }}
    </style>
    </head><body>
    <div id="header">
        <div id="title-row">
            <a href="../../index.html">← 返回</a>
            <strong>{code} {name}</strong>
        </div>
        <div id="controls">
            <button class="btn active" id="btn-D" onclick="switchPeriod('D',this)">日</button>
            <button class="btn" id="btn-W" onclick="switchPeriod('W',this)">週</button>
            <button class="btn" id="btn-M" onclick="switchPeriod('M',this)">月</button>
            <input id="ma-input" type="text" value="5,10,20,60,120,240">
            <button class="btn" onclick="applyMA()">均線</button>
        </div>
    </div>
    <div class="info-bar"><span id="ohlc-info" style="color:#666;">← 滑動查看｜長按K棒釘選虛線</span></div>
    <div class="chart-label"><span class="lbl">MA ▶</span><span id="ma-values"></span></div>
    <div id="main-chart"></div>
    <div class="chart-label"><span class="lbl">VOL(張) ▶</span><span id="vol-values"></span></div>
    <div id="vol-chart"></div>
    <div class="chart-label"><span class="lbl" id="sub-label">KD ▶</span><span id="sub-values"></span></div>
    <div id="sub-chart"></div>
    <div id="pin-toast">📌 已釘選</div>

    <script>
        // ── 資料 ──
        const allData = {{
            D: {{ ohlcv:{daily_js},   k:{daily_k_js},    d:{daily_d_js},
                  dif:null, macd:null, osc:null }},
            W: {{ ohlcv:{weekly_js},  k:{weekly_k_js},   d:{weekly_d_js},
                  dif:{weekly_dif_js}, macd:{weekly_macd_js}, osc:{weekly_osc_js} }},
            M: {{ ohlcv:{monthly_js}, k:{monthly_k_js},  d:{monthly_d_js},
                  dif:null, macd:null, osc:null }}
        }};

        const defaultMA = {{ D:'5,10,20,60,120,240', W:'5,10,20', M:'5,60,120' }};
        let currentPeriod = 'D';
        const maColors = ['#f59e0b','#a78bfa','#34d399','#fb7185','#38bdf8','#f97316'];
        const volMAColors = ['#f59e0b','#a78bfa'];

        // ── 圖表基礎設定 ──
        const baseOpts = {{
            layout:{{ background:{{color:'#0d0d0d'}}, textColor:'#666' }},
            grid:{{ vertLines:{{color:'#1a1a1a'}}, horzLines:{{color:'#1a1a1a'}} }},
            rightPriceScale:{{ borderColor:'#222', textColor:'#888' }},
            timeScale:{{ borderColor:'#222', visible:false, barSpacing:8, minBarSpacing:4, fixLeftEdge:true, fixRightEdge:true }},
            crosshair:{{ mode:1, vertLine:{{color:'#444',labelBackgroundColor:'#222'}}, horzLine:{{color:'#444',labelBackgroundColor:'#222'}} }},
            handleScale:{{ axisPressedMouseMove:false, mouseWheel:true, pinch:true }},
            handleScroll:{{ mouseWheel:false, pressedMouseMove:true, horzTouchDrag:true, vertTouchDrag:false }}
        }};

        const mainChart = LightweightCharts.createChart(document.getElementById('main-chart'), baseOpts);
        const volChart  = LightweightCharts.createChart(document.getElementById('vol-chart'),  baseOpts);
        const subChart  = LightweightCharts.createChart(document.getElementById('sub-chart'),  {{
            ...baseOpts, timeScale:{{ ...baseOpts.timeScale, visible:true }}
        }});

        // ── 主圖系列 ──
        const candles = mainChart.addCandlestickSeries({{
            upColor:'#d32f2f', downColor:'#00897b',
            borderUpColor:'#d32f2f', borderDownColor:'#00897b',
            wickUpColor:'#d32f2f', wickDownColor:'#00897b'
        }});

        // ── 成交量系列 ──
        const volSeries = volChart.addHistogramSeries({{
            priceFormat:{{type:'volume'}}, priceScaleId:'right'
        }});
        let volMASeries = [];

        // ── 副圖系列（KD / MACD，動態建立）──
        let subSeries = [];

        // ── 均線系列 ──
        let maSeries = [];
        let maPeriodsCache = [];

        // ── 工具函式 ──
        function calcMA(data, period) {{
            const r = [];
            for (let i = period-1; i < data.length; i++) {{
                const sum = data.slice(i-period+1,i+1).reduce((a,b)=>a+b.close,0);
                r.push({{ time:data[i].time, value:parseFloat((sum/period).toFixed(2)) }});
            }}
            return r;
        }}

        function calcVolMA(data, period) {{
            const r = [];
            for (let i = period-1; i < data.length; i++) {{
                const sum = data.slice(i-period+1,i+1).reduce((a,b)=>a+b.value,0);
                r.push({{ time:data[i].time, value:parseFloat((sum/period).toFixed(0)) }});
            }}
            return r;
        }}

        function fmtVol(v) {{
            if (v >= 100000) return (v/10000).toFixed(1)+'萬張';
            if (v >= 1000) return (v/1000).toFixed(1)+'千張';
            return Math.round(v)+'張';
        }}

        // ── 套用均線 ──
        function applyMA() {{
            maSeries.forEach(s => mainChart.removeSeries(s));
            maSeries = [];
            const data = allData[currentPeriod].ohlcv;
            const input = document.getElementById('ma-input').value;
            maPeriodsCache = input.split(',').map(v=>parseInt(v.trim())).filter(v=>!isNaN(v)&&v>0);
            const el = document.getElementById('ma-values');
            el.innerHTML = '';
            maPeriodsCache.forEach((p,i) => {{
                const color = maColors[i % maColors.length];
                const s = mainChart.addLineSeries({{
                    color, lineWidth:1, priceLineVisible:false,
                    lastValueVisible:false, crosshairMarkerVisible:false
                }});
                const maData = calcMA(data, p);
                s.setData(maData);
                maSeries.push(s);
                const last = maData.length>0 ? maData[maData.length-1].value : '-';
                const span = document.createElement('span');
                span.id = 'ma-lbl-'+p;
                span.style.cssText = `color:${{color}};margin-right:6px;`;
                span.innerHTML = `${{p}}T:<b>${{last}}</b>`;
                el.appendChild(span);
            }});
        }}

        // ── 套用成交量均線 ──
        function applyVolMA(data) {{
            volMASeries.forEach(s => volChart.removeSeries(s));
            volMASeries = [];
            const volData = data.map(x => ({{time:x.time, value:x.value}}));
            [[5, volMAColors[0]], [10, volMAColors[1]]].forEach(([p, color]) => {{
                const s = volChart.addLineSeries({{
                    color, lineWidth:1, priceScaleId:'right',
                    lastValueVisible:false, crosshairMarkerVisible:false, priceLineVisible:false
                }});
                s.setData(calcVolMA(volData, p));
                volMASeries.push(s);
            }});
        }}

        // ── 建立/切換副圖 ──
        function buildSubChart(period) {{
            subSeries.forEach(s => subChart.removeSeries(s));
            subSeries = [];
            const d = allData[period];

            if (period === 'W') {{
                document.getElementById('sub-label').textContent = 'MACD ▶';
                const difS  = subChart.addLineSeries({{ color:'#38bdf8', lineWidth:1.5, lastValueVisible:false, crosshairMarkerVisible:false }});
                const macdS = subChart.addLineSeries({{ color:'#f97316', lineWidth:1.5, lastValueVisible:false, crosshairMarkerVisible:false }});
                const oscS  = subChart.addHistogramSeries({{ lastValueVisible:false, crosshairMarkerVisible:false, priceScaleId:'right' }});
                difS.setData(d.dif);
                macdS.setData(d.macd);
                oscS.setData(d.osc.map(x => ({{
                    time:x.time, value:x.value,
                    color: x.value >= 0 ? '#d32f2f99' : '#00897b99'
                }})));
                subSeries = [difS, macdS, oscS];
                const lastDif  = d.dif.length>0  ? d.dif[d.dif.length-1].value   : '-';
                const lastMacd = d.macd.length>0 ? d.macd[d.macd.length-1].value : '-';
                document.getElementById('sub-values').innerHTML =
                    `<span style="color:#38bdf8">DIF<b>${{lastDif}}</b></span>` +
                    ` <span style="color:#f97316">MACD<b>${{lastMacd}}</b></span>`;
            }} else {{
                document.getElementById('sub-label').textContent = 'KD ▶';
                const kS = subChart.addLineSeries({{ color:'#f59e0b', lineWidth:1.5, lastValueVisible:false, crosshairMarkerVisible:false }});
                const dS = subChart.addLineSeries({{ color:'#a78bfa', lineWidth:1.5, lastValueVisible:false, crosshairMarkerVisible:false }});
                kS.setData(d.k);
                dS.setData(d.d);
                subSeries = [kS, dS];
                const lastK = d.k.length>0 ? d.k[d.k.length-1].value : '-';
                const lastD = d.d.length>0 ? d.d[d.d.length-1].value : '-';
                const kdColor = parseFloat(lastK) > parseFloat(lastD) ? '#f59e0b' : '#a78bfa';
                document.getElementById('sub-values').innerHTML =
                    `<span style="color:#f59e0b">K<b>${{lastK}}</b></span>` +
                    ` <span style="color:#a78bfa">D<b>${{lastD}}</b></span>` +
                    ` <span style="color:${{kdColor}};font-size:10px;">${{parseFloat(lastK)>parseFloat(lastD)?'▲金叉':'▼死叉'}}</span>`;
            }}
        }}

        // 漲停標記
        const limitDates = {limit_dates_js};
        const limitMarkers = limitDates.map(d => ({{
            time:d, position:'aboveBar', color:'#f8d210', shape:'arrowDown', text:'🚀'
        }}));

        // ── 載入資料 ──
        function loadData(period) {{
            const d = allData[period];
            candles.setData(d.ohlcv);
            volSeries.setData(d.ohlcv.map(x => ({{
                time:x.time, value:x.value,
                color: x.isLimit ? '#eab308' : (x.close>=x.open ? '#d32f2f99' : '#00897b99')
            }})));
            applyVolMA(d.ohlcv);
            candles.setMarkers(period==='D' ? limitMarkers : []);
            buildSubChart(period);
            applyMA();
            const lastIdx = d.ohlcv.length-1;
            if (period==='D') {{
                const range = {{ from:d.ohlcv[Math.max(0,lastIdx-120)].time, to:d.ohlcv[lastIdx].time }};
                [mainChart, volChart, subChart].forEach(c => c.timeScale().setVisibleRange(range));
            }} else {{
                [mainChart, volChart, subChart].forEach(c => c.timeScale().fitContent());
            }}
        }}

        function switchPeriod(period, btn) {{
            clearPinnedLines();   // 切換週期時清除釘選虛線
            currentPeriod = period;
            document.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('ma-input').value = defaultMA[period];
            loadData(period);
        }}

        // ── 三圖同步滾動 ──
        let syncingRange = false;
        [mainChart, volChart, subChart].forEach(src => {{
            src.timeScale().subscribeVisibleLogicalRangeChange(range => {{
                if (syncingRange || !range) return;
                syncingRange = true;
                [mainChart, volChart, subChart].filter(c => c !== src)
                    .forEach(c => c.timeScale().setVisibleLogicalRange(range));
                syncingRange = false;
            }});
        }});

        // ── 三圖同步十字線 ──
        let syncingCross = false;
        function bindCross(src, refMap) {{
            src.subscribeCrosshairMove(p => {{
                if (!p.time) return;
                if (syncingCross) return;
                syncingCross = true;
                refMap.forEach(({{chart, series}}) => chart.setCrosshairPosition(p.price, p.time, series));
                syncingCross = false;

                // OHLC 更新
                const ohlcv = allData[currentPeriod].ohlcv;
                const idx = ohlcv.findIndex(x => x.time===p.time);
                const d = idx >= 0 ? ohlcv[idx] : null;
                if (d) {{
                    const prevClose = idx > 0 ? ohlcv[idx-1].close : d.open;
                    const chg = d.close - prevClose;
                    const chgPct = (chg / prevClose * 100).toFixed(2);
                    const cc = chg>=0 ? '#d32f2f' : '#00897b';
                    document.getElementById('ohlc-info').innerHTML =
                        `<span style="color:#555">${{p.time}}</span>` +
                        ` 開<b style="color:#ccc">${{d.open}}</b>` +
                        ` 高<b style="color:#d32f2f">${{d.high}}</b>` +
                        ` 低<b style="color:#00897b">${{d.low}}</b>` +
                        ` 收<b style="color:${{cc}}">${{d.close}}</b>` +
                        ` <span style="color:${{cc}}">${{chg>=0?'+':''}}${{chg.toFixed(2)}}(${{chg>=0?'+':''}}${{chgPct}}%)</span>`;
                    // VOL 更新
                    document.getElementById('vol-values').innerHTML =
                        `<span style="color:${{d.close>=d.open?'#d32f2f':'#00897b'}}">${{fmtVol(d.value)}}</span>`;
                    // MA 數值更新
                    maPeriodsCache.forEach(period => {{
                        const maData = calcMA(allData[currentPeriod].ohlcv, period);
                        const found = maData.find(m => m.time===p.time);
                        const el = document.getElementById('ma-lbl-'+period);
                        if (el && found) el.innerHTML = `${{period}}T:<b>${{found.value}}</b>`;
                    }});
                }}

                // 副圖數值更新
                const cur = allData[currentPeriod];
                if (currentPeriod==='W' && cur.dif) {{
                    const difF  = cur.dif.find(x=>x.time===p.time);
                    const macdF = cur.macd.find(x=>x.time===p.time);
                    const oscF  = cur.osc.find(x=>x.time===p.time);
                    if (difF && macdF) {{
                        const oscColor = oscF && oscF.value>=0 ? '#d32f2f' : '#00897b';
                        document.getElementById('sub-values').innerHTML =
                            `<span style="color:#38bdf8">DIF<b>${{difF.value}}</b></span>` +
                            ` <span style="color:#f97316">MACD<b>${{macdF.value}}</b></span>` +
                            (oscF ? ` <span style="color:${{oscColor}}">OSC<b>${{oscF.value}}</b></span>` : '');
                    }}
                }} else {{
                    const kF = cur.k.find(x=>x.time===p.time);
                    const dF = cur.d.find(x=>x.time===p.time);
                    if (kF && dF) {{
                        const kdColor = kF.value>dF.value ? '#f59e0b' : '#a78bfa';
                        document.getElementById('sub-values').innerHTML =
                            `<span style="color:#f59e0b">K<b>${{kF.value}}</b></span>` +
                            ` <span style="color:#a78bfa">D<b>${{dF.value}}</b></span>` +
                            ` <span style="color:${{kdColor}};font-size:10px;">${{kF.value>dF.value?'▲金叉':'▼死叉'}}</span>`;
                    }}
                }}
            }});
        }}

        bindCross(mainChart, [{{chart:volChart, series:volSeries}}, {{chart:subChart, series:subSeries[0]||volSeries}}]);
        bindCross(volChart,  [{{chart:mainChart, series:candles}}, {{chart:subChart, series:subSeries[0]||candles}}]);
        bindCross(subChart,  [{{chart:mainChart, series:candles}}, {{chart:volChart, series:volSeries}}]);

        loadData('D');

        // ════════════════════════════════════════════════════
        // ── 長按釘選虛線功能 ────────────────────────────────
        // ════════════════════════════════════════════════════
        let pinnedTime    = null;   // 目前釘選的 K 棒時間
        let pinnedLines   = [];     // [{{series, chart}}, ...]
        let longPressTimer = null;
        let touchMoved    = false;

        // 顯示短暫提示 toast
        function showToast(msg) {{
            const el = document.getElementById('pin-toast');
            el.textContent = msg;
            el.classList.add('show');
            clearTimeout(el._timer);
            el._timer = setTimeout(() => el.classList.remove('show'), 1500);
        }}

        // 清除所有釘選虛線
        function clearPinnedLines() {{
            pinnedLines.forEach(item => {{
                try {{ item.chart.removeSeries(item.series); }} catch(e) {{}}
            }});
            pinnedLines = [];
            pinnedTime  = null;
        }}

        // 畫釘選虛線（主圖開高低收 + 成交量圖量能水平線）
        function drawPinnedLines(time) {{
            clearPinnedLines();
            pinnedTime = time;

            const ohlcv = allData[currentPeriod].ohlcv;
            const bar   = ohlcv.find(x => x.time === time);
            if (!bar) return;

            const DASHED = 2;   // LightweightCharts LineStyle: 0=solid, 1=dotted, 2=dashed
            const LW     = 1;
            const allTimes = ohlcv.map(x => x.time);

            // 主圖：開（灰）/ 高（紅）/ 低（綠）/ 收（橙）四條虛線
            const priceLines = [
                {{ value: bar.open,  color: '#aaaaaa', title: `開 ${{bar.open}}`  }},
                {{ value: bar.high,  color: '#e57373', title: `高 ${{bar.high}}`  }},
                {{ value: bar.low,   color: '#4db6ac', title: `低 ${{bar.low}}`   }},
                {{ value: bar.close, color: '#f59e0b', title: `收 ${{bar.close}}` }},
            ];

            priceLines.forEach(pl => {{
                const s = mainChart.addLineSeries({{
                    color: pl.color,
                    lineWidth: LW,
                    lineStyle: DASHED,
                    priceLineVisible: false,
                    lastValueVisible: true,
                    crosshairMarkerVisible: false,
                    title: pl.title,
                }});
                s.setData(allTimes.map(t => ({{ time: t, value: pl.value }})));
                pinnedLines.push({{ series: s, chart: mainChart }});
            }});

            // 成交量圖：量能水平虛線（橙色）
            const volS = volChart.addLineSeries({{
                color: '#f59e0b',
                lineWidth: LW,
                lineStyle: DASHED,
                priceScaleId: 'right',
                priceLineVisible: false,
                lastValueVisible: true,
                crosshairMarkerVisible: false,
                title: `量 ${{Math.round(bar.value)}}`,
            }});
            volS.setData(allTimes.map(t => ({{ time: t, value: bar.value }})));
            pinnedLines.push({{ series: volS, chart: volChart }});
        }}

        // ── 追蹤十字線最後停留的時間 ──
        let lastCrosshairTime = null;
        mainChart.subscribeCrosshairMove(p => {{
            if (p.time) lastCrosshairTime = p.time;
        }});

        // ── 長按觸發邏輯（共用）──
        function onLongPress() {{
            const t = lastCrosshairTime;
            if (!t) return;
            if (pinnedTime === t) {{
                // 再次長按同一根 → 取消釘選
                clearPinnedLines();
                showToast('📌 已取消釘選');
            }} else {{
                // 長按新根 → 釘選（自動取代舊的）
                drawPinnedLines(t);
                showToast('📌 已釘選');
            }}
        }}

        const mainEl = document.getElementById('main-chart');

        // ── Touch 長按（行動端：手指靜止 500ms）──
        mainEl.addEventListener('touchstart', e => {{
            touchMoved = false;
            longPressTimer = setTimeout(() => {{
                if (touchMoved) return;
                onLongPress();
            }}, 500);
        }}, {{ passive: true }});

        mainEl.addEventListener('touchmove', () => {{
            touchMoved = true;
            clearTimeout(longPressTimer);
        }}, {{ passive: true }});

        mainEl.addEventListener('touchend', () => {{
            clearTimeout(longPressTimer);
        }}, {{ passive: true }});

        mainEl.addEventListener('touchcancel', () => {{
            clearTimeout(longPressTimer);
        }}, {{ passive: true }});

        // ── 滑鼠長按（桌面端：按住 500ms，移動或放開取消計時）──
        mainEl.addEventListener('mousedown', () => {{
            longPressTimer = setTimeout(onLongPress, 500);
        }});

        mainEl.addEventListener('mouseup', () => {{
            clearTimeout(longPressTimer);
        }});

        mainEl.addEventListener('mousemove', () => {{
            // 滑鼠移動超過微小距離才取消（避免十字線更新時誤取消）
            clearTimeout(longPressTimer);
        }});

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

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.columns = [c.capitalize() for c in df.columns]

        required = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(c in df.columns for c in required): return None

        df = df[required].astype(float).dropna(subset=['Close'])

        if len(df) < 240: return None

        # ── 修正：squeeze 避免 pandas MultiIndex 問題 ──
        close = df['Close'].squeeze()
        volume = df['Volume'].squeeze().fillna(0)

        ma60 = close.rolling(60).mean()
        ma240 = close.rolling(240).mean()

        recent_close = close.iloc[-90:]
        recent_ma240 = ma240.iloc[-90:]
        broken = (recent_close > recent_ma240) & (recent_close.shift(1) <= recent_ma240.shift(1))
        if not broken.any(axis=None): return None

        p_min_90 = float(recent_close.min())
        p_max_90 = float(recent_close.max())
        wave_gain = (p_max_90 - p_min_90) / p_min_90
        if wave_gain < 0.30: return None

        limit_dates = [close.index[j] for j in range(len(close)-30, len(close))
                       if j > 0 and float(close.iloc[j]) >= (calc_limit_price(float(close.iloc[j-1])) - 0.01)]
        if not limit_dates: return None

        last_limit_date = limit_dates[-1]
        last_limit_idx = close.index.get_loc(last_limit_date)
        limit_vol = safe_float(volume.loc[last_limit_date])
        limit_low = safe_float(df.loc[last_limit_date, 'Low'])

        curr_c = float(close.iloc[-1])
        curr_ma60 = float(ma60.iloc[-1])
        dist_ma60 = (curr_c - curr_ma60) / curr_ma60
        if abs(dist_ma60) > 0.025: return None

        win_kd = 9
        low_s  = df['Low'].squeeze().astype(float)
        high_s = df['High'].squeeze().astype(float)
        rsv = ((close - low_s.rolling(win_kd).min()) /
               (high_s.rolling(win_kd).max() - low_s.rolling(win_kd).min()) * 100).fillna(50)
        k = rsv.ewm(com=2).mean()
        d = k.ewm(com=2).mean()

        reasons = []

        if curr_c < limit_low * 0.97:
            return None

        days_since = (today - last_limit_date).days
        if not (5 <= days_since <= 25):
            return None

        curr_ma240 = float(ma240.iloc[-1])
        price_ma240_ratio = curr_c / curr_ma240
        if price_ma240_ratio > 1.8:
            return None

        # ── 漲停前低波動蓄力篩選 ──
        pre_limit_start = max(0, last_limit_idx - 30)
        pre_limit_close = close.iloc[pre_limit_start:last_limit_idx]
        if len(pre_limit_close) >= 10:
            pre_limit_std_ratio = float(pre_limit_close.std()) / float(pre_limit_close.mean())
        else:
            pre_limit_std_ratio = 1.0

        # ── 漲停日量能啟動倍數 ──
        vol_ma10_before = float(volume.iloc[max(0, last_limit_idx-10):last_limit_idx].mean())
        if vol_ma10_before > 0:
            limit_vol_ratio_activate = limit_vol / vol_ma10_before
        else:
            limit_vol_ratio_activate = 0

        win_rate = 45

        if float(ma60.iloc[-1]) > float(ma60.iloc[-5]):
            win_rate += 10
            reasons.append("✅ 季線向上")
        else:
            win_rate -= 15
            reasons.append("⚠️ 季線走平或向下")

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

        if price_ma240_ratio > 1.4:
            win_rate -= 10
            reasons.append(f"⚠️ 位階偏高（股價為年線{price_ma240_ratio*100:.0f}%）")
        elif 1.05 <= price_ma240_ratio <= 1.35:
            win_rate += 10
            reasons.append(f"✅ 位階理想（股價為年線{price_ma240_ratio*100:.0f}%）")
        else:
            reasons.append(f"📍 位階：股價為年線{price_ma240_ratio*100:.0f}%")

        if float(k.iloc[-1]) > float(d.iloc[-1]) and float(k.iloc[-2]) <= float(d.iloc[-2]):
            win_rate += 10
            reasons.append("✅ KD 低檔金叉")
        elif float(k.iloc[-1]) > float(d.iloc[-1]):
            win_rate += 5
            reasons.append("📍 KD K>D 上行中")

        if 7 <= days_since <= 15:
            win_rate += 10
            reasons.append(f"✅ 整理天數理想（{days_since}天）")
        else:
            reasons.append(f"📍 整理天數：{days_since}天")

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

        if wave_gain >= 0.5:
            win_rate += 10
            reasons.append(f"✅ 第一波強勁（漲幅{wave_gain*100:.0f}%）")
        else:
            reasons.append(f"📍 第一波漲幅{wave_gain*100:.0f}%")

        # ── 蓄力結構評分 ──
        if pre_limit_std_ratio < 0.04:
            win_rate += 15
            reasons.append(f"✅ 漲停前強力蓄力（波動率{pre_limit_std_ratio*100:.1f}%）")
        elif pre_limit_std_ratio < 0.07:
            win_rate += 8
            reasons.append(f"✅ 漲停前低波動蓄力（波動率{pre_limit_std_ratio*100:.1f}%）")
        else:
            reasons.append(f"📍 漲停前波動率{pre_limit_std_ratio*100:.1f}%")

        # ── 量能啟動評分 ──
        if limit_vol_ratio_activate >= 5.0:
            win_rate += 15
            reasons.append(f"✅ 量能爆發啟動（漲停量為前10日均量{limit_vol_ratio_activate:.1f}倍）")
        elif limit_vol_ratio_activate >= 3.0:
            win_rate += 8
            reasons.append(f"✅ 量能明顯放大（{limit_vol_ratio_activate:.1f}倍）")
        else:
            reasons.append(f"📍 量能啟動倍數{limit_vol_ratio_activate:.1f}倍")

        win_rate = max(10, min(win_rate, 90))

        diff = p_max_90 - p_min_90
        t1 = round(p_max_90 + diff*0.382, 2)
        t2 = round(p_max_90 + diff*0.618, 2)
        t3 = round(p_max_90 + diff*1.0, 2)

        recent_high = float(df['High'].iloc[-20:].max())
        trigger_price = round(recent_high * 1.01, 2)

        limit_open = safe_float(df.loc[last_limit_date, 'Open'])
        recent_low_support = float(df['Low'].iloc[-20:].min())
        support_candidates = [curr_ma60, limit_open, limit_low, recent_low_support]
        valid_supports = [x for x in support_candidates if x < curr_c and x > 0]
        support_price = max(valid_supports) if valid_supports else curr_ma60
        order_low  = round(support_price * 0.99, 2)
        order_high = round(support_price * 1.01, 2)

        # 今日成交量（張）
        today_vol_shares = int(volume.iloc[-3:].mean())
        today_vol_張 = round(today_vol_shares / 1000, 0)

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
            "成交量(張)": int(today_vol_張),
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
    fetch_start = datetime(2000, 1, 1)
    results = []

    try:
        twii_raw = yf.download("^TWII", start=today-timedelta(days=500), end=today, progress=False)
        if isinstance(twii_raw.columns, pd.MultiIndex):
            twii_raw.columns = twii_raw.columns.get_level_values(0)
        twii_raw.columns = [c.capitalize() for c in twii_raw.columns]
        twii_c = twii_raw['Close'].squeeze()
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
            win_str = str(row.get("勝率", "0%")).replace("%", "")
            try: win_val = int(win_str)
            except: win_val = 0
            if win_val >= 65:
                win_color = "#ff4040"; win_bg = "#3d1a1a"
            elif win_val >= 50:
                win_color = "#ffa500"; win_bg = "#2d2200"
            else:
                win_color = "#26a69a"; win_bg = "#0d2420"

            try:
                k_val = float(row.get("K", 50))
                d_val = float(row.get("D", 50))
                kd_color = "#ff4040" if k_val > d_val else "#26a69a"
                kd_tag = "▲金叉" if k_val > d_val else "▼死叉"
            except:
                kd_color = "#888"; kd_tag = "-"

            close_val = row.get("收盤價", "")
            try:
                stop = float(row.get("停損價", 0))
                close_f = float(close_val)
                stop_pct = round((stop - close_f) / close_f * 100, 1)
                stop_str = f"{stop} <span style='color:#888;font-size:11px;'>({stop_pct}%)</span>"
            except:
                stop_str = str(row.get("停損價", ""))

            trigger = row.get("觸發價", "")
            vol_val = row.get("成交量(張)", "")

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
                <td style="color:#aaa;font-size:12px;min-width:70px;">{vol_val}</td>
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
                    <th>成交量(張)</th>
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
