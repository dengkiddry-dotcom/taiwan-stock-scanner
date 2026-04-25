import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import time

def get_mixed_stock_list():
    """建立包含上市與上櫃約 500 檔的精選名單"""
    # 1. 上市權值與熱門 (約 250 檔)
    tw_list = [
        "1101","1102","1216","1301","1303","1402","1503","1504","1513","1514","1519","1605","1608","1609","1611",
        "1722","1773","2002","2006","2301","2303","2308","2313","2317","2324","2327","2330","2337","2344","2352",
        "2353","2356","2357","2360","2367","2368","2371","2376","2377","2379","2382","2383","2385","2395","2408",
        "2409","2412","2449","2451","2454","2458","2474","2498","2542","2603","2606","2609","2610","2615","2618",
        "2880","2881","2882","2883","2884","2885","2886","2887","2890","2891","2892","3005","3008","3017","3019",
        "3023","3034","3035","3037","3044","3045","3231","3406","3443","3481","3576","3653","3661","3702","3711",
        "4904","4915","4919","4938","4958","5269","5871","5880","6239","6278","6414","6415","6505","6669","8046"
    ]
    
    # 2. 上櫃精選與熱門 (OTC 約 250 檔)
    # 包含半導體、生技、遊戲、電機等強勢上櫃板塊
    two_list = [
        "1560","1580","1590","1785","1795","1815","2233","3068","3078","3081","3105","3131","3141","3163","3207",
        "3211","3217","3218","3227","3228","3234","3260","3264","3289","3293","3324","3363","3376","3455","3491",
        "3511","3526","3529","3546","3548","3558","3580","3587","3592","3611","3624","3664","3680","4105","4107",
        "4114","4123","4128","4162","4303","4510","4513","4528","4533","4541","4721","4736","4743","4760","4908",
        "4909","4931","4944","4953","4966","4979","5009","5211","5227","5274","5289","5309","5347","5351","5371",
        "5381","5425","5439","5443","5457","5478","5483","5512","6104","6111","6121","6125","6138","6143","6146",
        "6147","6150","6170","6173","6180","6182","6185","6187","6188","6208","6217","6219","6223","6231","6233",
        "6237","6244","6245","6261","6266","6274","6275","6276","6279","6284","6290","6411","6417","6418","6435",
        "6441","6446","6462","6472","6485","6488","6496","6510","6532","6548","6561","6568","6589","6613","6643",
        "6654","6679","6683","6732","6741","8027","8044","8054","8064","8069","8076","8085","8086","8091","8096",
        "8111","8155","8255","8299","8358","8415","8436","8916","8936","8938"
    ]
    
    # 建立最終清單 (上市標註 .TW, 上櫃標註 .TWO)
    final_list = [f"{c}.TW" for c in tw_list] + [f"{c}.TWO" for c in two_list]
    return list(set(final_list))

def scan():
    test_list = get_mixed_stock_list()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    limit_up_list = []
    
    print(f"🕵️ 正在掃描 {len(test_list)} 檔上市櫃精選標的...")
    
    for i, s in enumerate(test_list):
        try:
            # 500 檔掃描較久，每 50 檔讓伺服器休息一下
            if i % 50 == 0 and i > 0:
                print(f"已完成 {i} 檔，目前掃描中：{s}")
                time.sleep(5)
            
            df = yf.download(s, start=start_date, end=end_date, progress=False)
            if df.empty or len(df) < 2: continue
            
            close = df['Close']
            if isinstance(close, pd.DataFrame): close = close.iloc[:, 0]
            
            pct_change = close.pct_change()
            limit_days = pct_change[pct_change >= 0.098].index
            
            if not limit_days.empty:
                formatted_dates = []
                today = datetime.now()
                for d in limit_days:
                    d_str = d.strftime('%m/%d')
                    # 若為近 3 天則加標籤
                    if (today - d).days <= 3:
                        formatted_dates.append(f"<span class='tag'>{d_str}</span>")
                    else:
                        formatted_dates.append(d_str)
                
                limit_up_list.append({
                    "代碼": s.split('.')[0],
                    "市場": "上市" if ".TW" in s else "上櫃",
                    "近30日次數": len(limit_days),
                    "漲停軌跡": "、".join(formatted_dates),
                    "最新收盤": round(float(close.iloc[-1]), 2)
                })
        except: continue
        
    return pd.DataFrame(limit_up_list)

def to_html(df):
    now = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    html = f"""
    <html><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>上市櫃 500 檔漲停監控</title>
    <style>
        body {{ font-family: "PingFang TC", "Microsoft JhengHei", sans-serif; padding: 15px; background: #f4f7f6; color: #333; }}
        .container {{ max-width: 1000px; margin: auto; background: white; padding: 25px; border-radius: 16px; box-shadow: 0 8px 30px rgba(0,0,0,0.08); }}
        h1 {{ color: #2c3e50; text-align: center; margin-bottom: 5px; letter-spacing: 1px; }}
        .update-time {{ text-align: center; color: #95a5a6; margin-bottom: 25px; font-size: 0.85em; }}
        table {{ width: 100%; border-collapse: collapse; overflow: hidden; border-radius: 8px; }}
        th {{ background: #34495e; color: #ecf0f1; padding: 15px; font-weight: 500; }}
        td {{ padding: 14px; border-bottom: 1px solid #eee; text-align: center; }}
        tr:hover {{ background: #fdfdfd; }}
        .tag {{ background: #e74c3c; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8em; }}
        .market-tw {{ color: #2980b9; font-weight: bold; }}
        .market-two {{ color: #16a085; font-weight: bold; }}
    </style></head><body>
    <div class="container">
        <h1>🚀 上市櫃精選 500 檔漲停監測</h1>
        <p class="update-time">台北更新時間：{now} (UTC+8)</p>
        {df.sort_values(['近30日次數', '最新收盤'], ascending=False).to_html(index=False, escape=False) if not df.empty else "<h3>監控範圍內無漲停紀錄</h3>"}
        <div style="margin-top: 25px; font-size: 0.8em; color: #7f8c8d; border-top: 1px solid #eee; padding-top: 15px;">
            * 標記 <span class="tag">MM/DD</span> 為近 3 天內漲停標的。<br>
            * 市場標註：上市 (.TW) / 上櫃 (.TWO)。
        </div>
    </div>
    </body></html>
    """
    with open("index.html", "w", encoding="utf-8") as f: f.write(html)

if __name__ == "__main__":
    df_result = scan()
    to_html(df_result)
