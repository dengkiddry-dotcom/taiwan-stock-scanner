import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import time


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


def scan():
    stocks = get_list()
    end = datetime.now()
    start = end - timedelta(days=30)
    results = []
    total = len(stocks)

    for i, s in enumerate(stocks):
        try:
            # 每 20 支休息一次，避免被限流
            if i % 20 == 0 and i > 0:
                print(f"[進度] {i}/{total}，暫停 3 秒...")
                time.sleep(3)

            df = yf.download(s, start=start, end=end, progress=False)

            if df.empty or len(df) < 2:
                continue

            # squeeze() 自動處理 MultiIndex 或單欄 DataFrame → Series
            close = df['Close'].squeeze()

            if not isinstance(close, pd.Series):
                continue

            pct = close.pct_change()
            # 台股漲停約 +10%，設 9.8% 容差捕捉漲停
            days = pct[pct >= 0.098].index

            if not days.empty:
                dates = [d.strftime('%m/%d') for d in days]
                code = s.split('.')[0]
                market = "上市" if s.endswith(".TW") else "上櫃"
                link = f"https://tw.stock.yahoo.com/quote/{code}/chart"
                results.append({
                    "代碼": f"<a href='{link}' target='_blank' style='color:#1a73e8;font-weight:bold;'>{code} 📈</a>",
                    "市場": market,
                    "漲停次數": len(days),
                    "漲停軌跡": " / ".join(dates),
                    "收盤價": round(float(close.iloc[-1]), 2)
                })

        except Exception as e:
            print(f"[{s}] 錯誤：{e}")
            continue

    print(f"[完成] 共掃描 {total} 支，找到 {len(results)} 支漲停標的")
    return pd.DataFrame(results)


def to_html(df):
    t = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

    if not df.empty:
        df_sorted = df.sort_values('漲停次數', ascending=False)
        table_html = df_sorted.to_html(index=False, escape=False)
        count_info = f"<p>共找到 <strong>{len(df)}</strong> 支漲停標的</p>"
    else:
        table_html = "<h3>⚠️ 近 30 天無漲停標的</h3>"
        count_info = ""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>台股漲停全紀錄</title>
  <style>
    body {{
      font-family: 'Segoe UI', sans-serif;
      padding: 24px;
      background: #f5f7fa;
      color: #333;
    }}
    h1 {{ color: #1a73e8; }}
    p {{ color: #555; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: white;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }}
    th, td {{
      padding: 12px 16px;
      border-bottom: 1px solid #eee;
      text-align: center;
    }}
    th {{
      background: #1a73e8;
      color: white;
      font-weight: 600;
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #f0f4ff; }}
  </style>
</head>
<body>
  <h1>🚀 台股 500 檔漲停全紀錄</h1>
  <p>台北時間：{t}（近 30 天資料）</p>
  {count_info}
  {table_html}
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("[輸出] index.html 已產生")


if __name__ == "__main__":
    to_html(scan())
