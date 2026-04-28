import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
import time
import os
import json

# ── 全域開關 ─────────────────────────────────────────────────
RUN_BACKTEST = False   # True=開啟回測（慢）False=關閉（快）

# ── 產業分類對照表 ───────────────────────────────────────────
industry_map = {
    "2330":"半導體","2303":"半導體","2454":"半導體","2379":"半導體","2337":"半導體",
    "2344":"半導體","2408":"半導體","3443":"半導體","2385":"半導體","3034":"半導體",
    "2317":"電子代工","2382":"電子代工","2354":"電子代工","2356":"電子代工","2353":"電子代工",
    "3008":"PCB","2383":"PCB","6274":"PCB","4904":"PCB","3044":"PCB",
    "2308":"網通伺服器","2327":"網通伺服器","3376":"網通伺服器","6669":"網通伺服器",
    "2603":"航運","2609":"航運","2615":"航運","2610":"航運","2881":"金融","2882":"金融"
}

INDUSTRY_LEADERS = {
    "半導體": "2330", "金融": "2882", "航運": "2603", "網通伺服器": "2308", "電子代工": "2317"
}

# ── 核心工具函式 ──────────────────────────────────────────────
def calc_limit_price(prev_close: float) -> float:
    raw = prev_close * 1.1
    if raw < 10: tick = 0.01
    elif raw < 50: tick = 0.05
    elif raw < 100: tick = 0.1
    elif raw < 500: tick = 0.5
    elif raw < 1000: tick = 1.0
    else: tick = 5.0
    import math
    return math.floor(raw / tick) * tick

def fetch_name_map() -> dict:
    name_map = {}
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=10)
        for item in r.json(): name_map[item["Code"]] = item["Name"]
        r2 = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=10)
        for item in r2.json(): name_map[item["SecuritiesCompanyCode"]] = item["CompanyName"]
    except: pass
    return name_map

def get_list(target=2000):
    res = []
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=15)
        res += [f"{i['Code']}.TW" for i in r.json() if len(i['Code']) == 4]
        r2 = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=15)
        res += [f"{i['SecuritiesCompanyCode']}.TWO" for i in r2.json() if len(i['SecuritiesCompanyCode']) == 4]
    except: pass
    return res[:target]

# ── 掃描主函式 (修正版：葛蘭碧轉機模式) ───────────────────────
def scan(output_dir="charts", base_url="charts"):
    os.makedirs(output_dir, exist_ok=True)
    name_map = fetch_name_map()
    stocks = get_list()
    today = datetime.now()
    fetch_start = today - timedelta(days=500)
    results = []
    total = len(stocks)

    print(f"[掃描] 啟動達邁/泰碩模式，目標：突破年線後回測季線標的")

    for i, s in enumerate(stocks):
        try:
            if i % 25 == 0: print(f"[進度] {i}/{total}..."); time.sleep(1)
            
            df = yf.download(s, start=fetch_start, end=today, progress=False)
            if df.empty or len(df) < 240: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

            close = df['Close'].squeeze().astype(float)
            volume = df['Volume'].squeeze().astype(float)
            high = df['High'].squeeze().astype(float)
            low = df['Low'].squeeze().astype(float)

            # 1. 均線與位置計算
            ma60 = close.rolling(60).mean().iloc[-1]
            ma240 = close.rolling(240).mean().iloc[-1]
            curr_price = float(close.iloc[-1])
            today_vol = float(volume.iloc[-1])

            # 2. 條件：90天內曾突破年線 (葛蘭碧法則核心)
            has_broken_ma240 = any(close.iloc[-90:] > close.rolling(240).mean().iloc[-90:])
            if not has_broken_ma240: continue

            # 3. 條件：第一波表態強度 (90天波段漲幅 > 30%)
            p_min = float(df.iloc[-90:]['Low'].min())
            p_max = float(df.iloc[-90:]['High'].max())
            wave_gain = (p_max - p_min) / p_min
            if wave_gain < 0.30: continue

            # 4. 條件：30個交易日內曾有漲停 (主力簽名)
            limit_dates = []
            for j in range(len(close)-30, len(close)):
                if j <= 0: continue
                if float(close.iloc[j]) >= calc_limit_price(float(close.iloc[j-1])) * 0.999:
                    limit_dates.append(close.index[j])
            if not limit_dates: continue
            
            last_limit_date = limit_dates[-1]
            limit_vol = float(volume.loc[last_limit_date])
            limit_low = float(df.loc[last_limit_date, 'Low'])

            # 5. 條件：目前回測季線 (葛蘭碧買點二/三)
            dist_to_ma60 = (curr_price - ma60) / ma60
            if abs(dist_to_ma60) > 0.025: continue

            # ── 符合條件，開始評分 ──
            score = 120 
            notes = [f"🔥 達邁起飛型：第一波大漲 {wave_gain*100:.0f}% 且突破年線"]
            notes.append(f"🎯 買點：回測季線支撐 (距離 {dist_to_ma60*100:.1f}%)")

            # A. 窒息量加分 (成交量 < 漲停量 40%)
            if today_vol < limit_vol * 0.4:
                score += 50
                notes.append("✅ 窒息量：量縮極致，賣壓竭盡")

            # B. KD 加分 (低檔金叉)
            try:
                # 簡單 KD 邏輯
                win = 9
                low_min = low.rolling(win).min(); high_max = high.rolling(win).max()
                rsv = (close - low_min) / (high_max - low_min) * 100
                k = rsv.ewm(com=2).mean(); d = k.ewm(com=2).mean()
                if k.iloc[-1] < 50 and k.iloc[-2] <= d.iloc[-2] and k.iloc[-1] > d.iloc[-1]:
                    score += 30
                    notes.append("✅ KD 共振：低檔黃金交叉")
            except: pass

            code = s.split('.')[0]
            name = name_map.get(code, code)
            
            results.append({
                "_score": score,
                "代碼": f"<a href='./charts/{code}.html' target='_blank'>{code} 📊</a>",
                "名稱": name,
                "操作": "✅ 可掛單" if score >= 150 else "👀 觀察",
                "型態評分": f"{score} 分",
                "收盤價": round(curr_price, 2),
                "執行備註": "｜".join(notes),
                "積極停損": round(ma60 * 0.97, 2),
                "整理(日)": len(range(list(close.index).index(last_limit_date)+1, len(close)))
            })

            # 生成簡易 K 線圖 (沿用你的原本 generate_chart_html 結構)
            # 這裡省略細節，確保你的圖表函式存在
        except: continue

    df_out = pd.DataFrame(results).sort_values("_score", ascending=False)
    return df_out.drop(columns=["_score"]), {}

def to_html(df, output_file="index.html", market_status=None):
    t = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    html = f"""<html><head><meta charset="utf-8"><style>
    body{{background:#0d1117;color:#e6edf3;font-family:sans-serif;padding:20px;}}
    table{{width:100%;border-collapse:collapse;margin-top:20px;}}
    th,td{{padding:12px;border:1px solid #30363d;text-align:center;}}
    th{{background:#161b22;}}
    a{{color:#58a6ff;text-decoration:none;font-weight:bold;}}
    .tag{{background:#238636;padding:4px 8px;border-radius:4px;}}
    </style></head><body>
    <h1>🚀 達邁/泰碩模式：葛蘭碧轉機偵測系統</h1>
    <p>台北時間：{t} ｜ 核心：突破年線 + 回測季線 + 窒息量</p>
    {df.to_html(index=False, escape=False) if not df.empty else "目前無符合標的"}
    </body></html>"""
    with open(output_file, "w", encoding="utf-8") as f: f.write(html)

if __name__ == "__main__":
    df, status = scan()
    to_html(df)
    print("[完成] 報表已更新。")
