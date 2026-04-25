import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
import time

def get_all_taiwan_stock_codes():
    """自動從證交所抓取所有上市櫃代碼"""
    print("正在下載最新上市櫃清單...")
    url_twse = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2" # 上市
    url_tpex = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4" # 上櫃
    
    stocks = []
    for url in [url_twse, url_tpex]:
        res = requests.get(url)
        df = pd.read_html(res.text)[0]
        df = df[df[0].str.contains('  ')] 
        for item in df[0]:
            code = item.split('  ')[0]
            if len(code) == 4: # 只抓一般股票
                suffix = ".TW" if url == url_twse else ".TWO"
                stocks.append(f"{code}{suffix}")
    return stocks

def scan():
    all_stocks = get_all_taiwan_stock_codes()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    limit_up_list = []
    
    print(f"開始掃描 {len(all_stocks)} 檔股票...")
    for i, s in enumerate(all_stocks):
        try:
            # 分流處理，避免被 Yahoo 封鎖
            if i % 100 == 0 and i > 0:
                print(f"進度: {i}/{len(all_stocks)}")
                time.sleep(3)
            
            df = yf.download(s, start=start_date, end=end_date, progress=False)
            if df.empty or len(df) < 2: continue
            
            close = df['Close']
            if isinstance(close, pd.DataFrame): close = close.iloc[:, 0]
            
            # 計算漲幅判定
            pct_change = close.pct_change()
            limit_up_days = pct_change[pct_change >= 0.099].index
            
            if not limit_up_days.empty:
                limit_up_list.append({
                    "代碼": s,
                    "近1個月漲停次數": len(limit_up_days),
                    "最後漲停日期": limit_up_days[-1].strftime('%Y-%m-%d'),
                    "最新收盤價": round(close.iloc[-1], 2)
                })
        except: continue
    return pd.DataFrame(limit_up_list)

def to_html(df):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = f"""
    <html><head><meta charset="UTF-8"><title>台股漲停報告</title>
    <style>
        body {{ font-family: sans-serif; padding: 20px; background: #f5f5f5; }}
        table {{ width: 100%; border-collapse: collapse; background: white; }}
        th, td {{ border: 1px solid #ddd; padding: 10px; text-align: center; }}
        th {{ background: #333; color: white; }}
        tr:nth-child(even) {{ background: #f9f9f9; }}
    </style></head><body>
    <h1>🚀 台股全市場漲停監控 (近30日)</h1>
    <p>更新時間：{now}</p>
    {df.sort_values('近1個月漲停次數', ascending=False).to_html(index=False) if not df.empty else "今日無符合條件股票"}
    </body></html>
    """
    with open("index.html", "w", encoding="utf-8") as f: f.write(html)

if __name__ == "__main__":
    df_result = scan()
    to_html(df_result)
