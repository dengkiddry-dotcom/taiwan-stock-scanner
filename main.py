import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import time

def get_mixed_stock_list():
    # 這裡維持 500 檔名單 (為節省空間，此處省略清單內容，請沿用你目前的 500 檔清單)
    tw_list = ["1101","2330","2317","2454","2409","3037","3443"] # ...請填入你原本的清單
    two_list = ["6147","3105","3529"] # ...請填入你原本的清單
    return [f"{c}.TW" for c in tw_list] + [f"{c}.TWO" for c in two_list]

def scan():
    # 這裡可以直接沿用你上一版的 500 檔 get_mixed_stock_list()
    test_list = get_mixed_stock_list() 
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    limit_up_list = []
    
    print(f"正在分析 {len(test_list)} 檔標的之詳細軌跡...")
    
    for i, s in enumerate(test_list):
        try:
            if i % 50 == 0 and i > 0: time.sleep(5)
            df = yf.download(s, start=start_date, end=end_date, progress=False)
            if df.empty or len(df) < 2: continue
            
            close = df['Close']
            if isinstance(close, pd.DataFrame): close = close.iloc[:, 0]
            
            pct_change = close.pct_change()
            limit_days = pct_change[pct_change >= 0.098].index
            
            if not limit_days.empty:
                # 1. 整理所有漲停日期
                all_dates = [d.strftime('%m/%d') for d in limit_days]
                
                # 2. 建立 Yahoo 股市 K 線連結
                pure_code = s.split('.')[0]
                k_link = f"https://tw.stock.yahoo.com/quote/{pure_code}/chart"
                
                limit_up_list.append({
                    "代碼": f"<a href='{k_link}' target='_blank' class='k-link'>{pure_code} 📈</a>",
                    "市場": "上市" if ".TW" in s else "上櫃",
                    "次數": len(limit_days),
                    "所有漲停日期": " / ".join(all_dates),
                    "最新收盤": round(float(close.iloc[-1]), 2)
                })
        except: continue
    return pd.DataFrame(limit_up_list)

def to_html(df):
    now = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    html = f"""
    <html><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>台股強勢股詳細監測</title>
    <style>
        body {{ font-family: sans-serif; padding: 15px; background: #f4f7f6; }}
        .container {{ max-width: 1000px; margin: auto; background: white; padding: 20px; border-radius: 12px; shadow: 0 4px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #2c3e50; text-align: center; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th {{ background: #34495e; color: white; padding: 12px; }}
        td {{ padding: 12px; border-bottom: 1px solid #eee; text-align: center; }}
        .k-link {{ color: #1a73e8; text-decoration: none; font-weight: bold; border: 1px solid #1a73e8; padding: 2px 6px; border-radius: 4px; }}
        .k-link:hover {{ background: #1a73e8; color: white; }}
        .date-list {{ color: #d32f2f; font-weight: bold; letter-spacing: 1px; }}
    </style></head><body>
    <div class="container">
        <h1>🚀 台股漲停全紀錄 & K線連結</h1>
        <p style="text-align:center;">更新時間：{now}</p>
        {df.sort_values('次數', ascending=False).to_html(index=False, escape=False) if not df.empty else "<h3>暫無資料</h3>"}
        <p style="margin-top:20px; font-size:0.9em; color:#666;">* 點擊代碼旁的 📈 圖示可直接開啟 Yahoo 股市 K 線圖。</p>
    </div>
    </body></html>
    """
    with open("index.html", "w", encoding="utf-8") as f: f.write(html)

if __name__ == "__main__":
    df_result = scan()
    to_html(df_result)
