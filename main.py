import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
import time

def get_all_taiwan_stock_codes():
    """強化版：從證交所與櫃買中心抓取清單，加入 User-Agent 避免被擋"""
    print("正在獲取全台股清單...")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    stocks = []
    
    # 嘗試多種解析方式
    try:
        # 上市股票 (TWSE)
        res = requests.get("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", headers=headers)
        df_twse = pd.read_html(res.text)[0]
        # 上櫃股票 (TPEX)
        res = requests.get("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", headers=headers)
        df_tpex = pd.read_html(res.text)[0]
        
        combined_df = pd.concat([df_twse, df_tpex])
        
        for item in combined_df[0]:
            if '  ' in str(item):
                code = str(item).split('  ')[0].strip()
                # 確保是 4 位數純數字股票代碼
                if len(code) == 4 and code.isdigit():
                    suffix = ".TW" if item in df_twse[0].values else ".TWO"
                    stocks.append(f"{code}{suffix}")
                    
        # 移除重複項
        stocks = list(set(stocks))
        print(f"成功獲取清單，共 {len(stocks)} 檔。")
    except Exception as e:
        print(f"獲取清單失敗: {e}")
        # 如果爬蟲失敗，提供一組保底清單至少讓程式能跑 (含近期熱門股)
        stocks = ["2330.TW", "2317.TW", "1513.TW", "1519.TW", "1609.TW", "8046.TWO"]
        
    return stocks

def scan_limit_up():
    all_stocks = get_all_taiwan_stock_codes()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    limit_up_list = []
    
    # 為了確保在 GitHub 正常執行，我們一次處理一大批
    # 使用 yfinance 的下載功能優化速度
    print(f"開始下載數據 (此步驟需較長時間)...環境日期: {end_date.strftime('%Y-%m-%d')}")
    
    for i, s in enumerate(all_stocks):
        try:
            # 增加暫停時間，避免被 Yahoo 封鎖
            if i % 40 == 0 and i > 0:
                print(f"已掃描 {i}/{len(all_stocks)} 檔...")
                time.sleep(5) 
                
            df = yf.download(s, start=start_date, end=end_date, progress=False)
            
            if df.empty or len(df) < 2:
                continue
            
            # 處理 MultiIndex 欄位問題
            if isinstance(df.columns, pd.MultiIndex):
                close = df['Close'][s]
            else:
                close = df['Close']

            # 計算漲幅
            pct_change = close.pct_change()
            # 判斷近 30 天是否有任何一天漲幅 > 9.8% (考慮價格跳動)
            limit_days = pct_change[pct_change >= 0.098].index
            
            if not limit_days.empty:
                limit_up_list.append({
                    "股票代碼": s.replace(".TW", "").replace(".TWO", ""),
                    "市場": "上市" if ".TW" in s else "上櫃",
                    "近30日漲停次數": len(limit_days),
                    "最近漲停日期": limit_days[-1].strftime('%Y-%m-%d'),
                    "最新收盤價": round(float(close.iloc[-1]), 2)
                })
                print(f"⚡ 發現漲停股: {s}")
        except:
            continue
            
    return pd.DataFrame(limit_up_list)

def generate_html(df):
    now = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    html_template = f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <title>台股漲停監控</title>
        <style>
            body {{ font-family: "PingFang TC", "Microsoft JhengHei", sans-serif; padding: 30px; background: #f0f2f5; }}
            .container {{ background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            h1 {{ color: #e41e26; border-left: 8px solid #e41e26; padding-left: 15px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th {{ background-color: #333; color: white; padding: 12px; }}
            td {{ padding: 12px; border-bottom: 1px solid #ddd; text-align: center; }}
            tr:hover {{ background-color: #fff9f9; }}
            .date {{ color: #666; font-size: 0.9em; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 台股全市場漲停監控 (近30日)</h1>
            <p class="date">台北更新時間：{now}</p>
            {df.sort_values('近30日漲停次數', ascending=False).to_html(index=False) if not df.empty else "<h3>目前掃描範圍內無符合條件股票，請確認數據源。</h3>"}
        </div>
    </body>
    </html>
    """
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)

if __name__ == "__main__":
    result = scan_limit_up()
    generate_html(result)
