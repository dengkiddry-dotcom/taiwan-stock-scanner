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
    # 半導體
    "2330":"半導體","2303":"半導體","2454":"半導體","2379":"半導體",
    "2337":"半導體","2344":"半導體","2408":"半導體","3443":"半導體",
    "2385":"半導體","3034":"半導體","6415":"半導體","3711":"半導體",
    "2449":"半導體","2351":"半導體","3006":"半導體","2367":"半導體",
    "2364":"半導體","3037":"半導體","3019":"半導體","6274":"半導體",
    "2360":"半導體","2369":"半導體","3529":"半導體","4967":"半導體",
    # 電子代工／ODM
    "2317":"電子代工","2382":"電子代工","2354":"電子代工","2356":"電子代工",
    "2353":"電子代工","2324":"電子代工","2357":"電子代工","2313":"電子代工",
    "3231":"電子代工","2395":"電子代工",
    # PCB／電路板
    "3008":"PCB","2383":"PCB","6274":"PCB","4904":"PCB",
    "3044":"PCB","3045":"PCB","8046":"PCB","6239":"PCB",
    "3005":"PCB","2301":"PCB","3017":"PCB","3023":"PCB",
    # 網通／伺服器
    "2308":"網通伺服器","2327":"網通伺服器","3376":"網通伺服器",
    "6669":"網通伺服器","3293":"網通伺服器","4977":"網通伺服器",
    "3260":"網通伺服器","6285":"網通伺服器","3702":"網通伺服器",
    # 面板／顯示
    "3481":"面板","2409":"面板","3006":"面板",
    # 電源／被動元件
    "2409":"被動元件","2458":"被動元件","2474":"被動元件",
    "6278":"被動元件","2376":"被動元件","2377":"被動元件",
    "3035":"被動元件","2371":"被動元件","2368":"被動元件",
    # 光學／相機
    "3576":"光學","2351":"光學","3406":"光學","2498":"光學",
    "3653":"光學","5269":"光學",
    # 金融／銀行
    "2880":"金融","2881":"金融","2882":"金融","2883":"金融",
    "2884":"金融","2885":"金融","2886":"金融","2887":"金融",
    "2890":"金融","2891":"金融","2892":"金融","5871":"金融",
    "5880":"金融","2801":"金融","2812":"金融","2820":"金融",
    # 航運
    "2603":"航運","2609":"航運","2615":"航運","2610":"航運",
    "2606":"航運","2618":"航運","5608":"航運","2605":"航運",
    # 鋼鐵／原物料
    "2002":"鋼鐵","2006":"鋼鐵","2007":"鋼鐵","2008":"鋼鐵",
    "2015":"鋼鐵","2023":"鋼鐵","2027":"鋼鐵",
    # 石化
    "1301":"石化","1303":"石化","6505":"石化","1326":"石化",
    "1312":"石化","1313":"石化",
    # 傳產／食品
    "1216":"食品","1101":"水泥","1102":"水泥","1722":"化工",
    "1773":"化工","1402":"紡織","2542":"建設",
    # 電信
    "4904":"電信","4915":"電信","4919":"電信","3045":"電信",
    # 生技醫療
    "4938":"生技","4958":"生技","6414":"生技","1799":"生技",
    "4162":"生技","4960":"生技","6547":"生技","4168":"生技",
    # 電機／馬達
    "1503":"電機","1504":"電機","1513":"電機","1514":"電機",
    "1519":"電機","1605":"電機","1608":"電機","1609":"電機",
    "1611":"電機",
    # 上櫃半導體
    "3661":"半導體","3163":"半導體","6146":"半導體","6150":"半導體",
    "3227":"半導體","6185":"半導體","3264":"半導體","3324":"半導體",
    "6208":"半導體","6217":"半導體","6223":"半導體","6231":"半導體",
    # 上櫃網通
    "6138":"網通伺服器","6143":"網通伺服器","6147":"網通伺服器",
    "3680":"網通伺服器","3558":"網通伺服器","6170":"網通伺服器",
    # 上櫃生技
    "4107":"生技","4105":"生技","4114":"生技","4123":"生技",
    "4128":"生技","6180":"生技","6182":"生技","6187":"生技",
    "6188":"生技",
    # 上櫃電子
    "3078":"電子代工","3081":"電子代工","3105":"電子代工",
    "3131":"電子代工","3141":"電子代工","3207":"電子代工",
    "3211":"電子代工","3217":"電子代工","3218":"電子代工",
    "3228":"電子代工","3234":"電子代工","3289":"電子代工",
}


# ── 龍頭股對照表（FIX-20）────────────────────────────────────
INDUSTRY_LEADERS = {
    "半導體":    "2330",
    "金融":      "2882",
    "航運":      "2603",
    "鋼鐵":      "2002",
    "石化":      "6505",
    "網通伺服器": "2308",
    "電子代工":   "2317",
}


# ── 產業位階判斷（FIX-17~21 強化版）─────────────────────────
def get_industry_stage(industry_dfs: list, industry_name: str = "") -> str:
    """
    FIX-17：樣本 < 5 回傳「樣本不足」
    FIX-18：加入廣度斜率（速度）判斷
    FIX-19：r20 > 0.85 視為「高檔過熱」
    FIX-20：龍頭股跌破 MA20 強制降一級
    FIX-21：門檻依產業樣本數動態調整
    """
    if not industry_dfs:
        return "未知"

    # FIX-17：樣本不足直接回傳
    if len(industry_dfs) < 5:
        return "樣本不足"

    above_ma20 = above_ma60 = above_ma240 = 0
    above_ma20_prev = 0   # FIX-18：10日前的廣度
    valid60 = valid240 = valid_prev = 0

    for df in industry_dfs:
        try:
            close = df["Close"].squeeze()
            if not isinstance(close, pd.Series) or len(close) < 60:
                continue

            curr  = float(close.iloc[-1])
            ma20  = float(close.rolling(20).mean().iloc[-1])
            ma60  = float(close.rolling(60).mean().iloc[-1])

            valid60 += 1
            if curr > ma20: above_ma20 += 1
            if curr > ma60: above_ma60 += 1

            # FIX-18：10日前收盤 vs 當時MA20
            if len(close) >= 30:
                prev_close = float(close.iloc[-11])
                prev_ma20  = float(close.rolling(20).mean().iloc[-11])
                valid_prev += 1
                if prev_close > prev_ma20: above_ma20_prev += 1

            if len(close) >= 240:
                ma240 = float(close.rolling(240).mean().iloc[-1])
                valid240 += 1
                if curr > ma240: above_ma240 += 1
        except Exception:
            continue

    if valid60 == 0:
        return "未知"

    r20  = above_ma20 / valid60
    r60  = above_ma60 / valid60
    r240 = above_ma240 / valid240 if valid240 > 0 else None

    # FIX-18：廣度斜率
    r20_prev = above_ma20_prev / valid_prev if valid_prev > 0 else r20
    slope    = r20 - r20_prev   # 正 = 改善中，負 = 惡化中

    # FIX-21：動態門檻（依樣本數）
    n = valid60
    if n >= 20:
        t_hi, t_mid, t_lo = 0.65, 0.55, 0.45
    elif n >= 10:
        t_hi, t_mid, t_lo = 0.60, 0.50, 0.40
    else:
        t_hi, t_mid, t_lo = 0.55, 0.45, 0.35

    # FIX-19：超買過熱判斷（優先）
    if r20 > 0.85:
        stage = "高檔過熱"

    # 正常廣度判斷
    elif r20 >= t_hi and r60 >= t_hi and (r240 is None or r240 >= t_mid):
        stage = "成長中期"
    elif r20 >= t_hi and r60 >= t_mid and (r240 is None or r240 < t_mid):
        stage = "復甦初期"
    elif r20 < 0.50 and r60 >= t_mid:
        stage = "高檔成熟"
    elif r20 < t_lo and r60 < t_lo:
        stage = "衰退期"
    else:
        stage = "盤整過渡"

    # FIX-18：斜率修正（快速惡化降一級、快速復甦升一級）
    stage_order = ["衰退期", "盤整過渡", "高檔成熟", "復甦初期", "成長中期", "高檔過熱"]
    if slope < -0.15 and stage in stage_order:
        idx = stage_order.index(stage)
        if idx > 0:
            stage = stage_order[idx - 1]
    elif slope > 0.15 and stage in stage_order:
        idx = stage_order.index(stage)
        # 最多升到「成長中期」，不自動升到「高檔過熱」
        if idx < stage_order.index("成長中期"):
            stage = stage_order[idx + 1]

    return stage


# ── 官方產業分類抓取 ─────────────────────────────────────────
def normalize_industry_name(raw: str) -> str:
    if not raw:
        return ""

    name = str(raw).strip()
    name = name.replace("業", "").replace("類", "").replace("股票", "")

    mapping_keywords = [
        ("半導體", "半導體"),
        ("電子零組件", "電子零組件"),
        ("電腦及週邊", "電腦週邊"),
        ("通信網路", "網通伺服器"),
        ("光電", "光電"),
        ("電子通路", "電子通路"),
        ("資訊服務", "資訊服務"),
        ("其他電子", "其他電子"),
        ("金融保險", "金融"),
        ("航運", "航運"),
        ("鋼鐵", "鋼鐵"),
        ("塑膠", "石化"),
        ("油電燃氣", "油電燃氣"),
        ("化學", "化工"),
        ("生技醫療", "生技"),
        ("電機機械", "電機"),
        ("建材營造", "建設"),
        ("食品", "食品"),
        ("水泥", "水泥"),
        ("紡織", "紡織"),
        ("汽車", "汽車"),
        ("觀光餐旅", "觀光"),
        ("貿易百貨", "貿易百貨"),
    ]
    for key, value in mapping_keywords:
        if key in name:
            return value

    return name or "其他"


def fetch_official_industry_map() -> dict:
    result = {}

    sources = [
        ("上市", "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"),
        ("上櫃", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"),
    ]

    for label, url in sources:
        try:
            r = requests.get(url, timeout=15)
            data = r.json()
            added = 0

            for item in data:
                if not isinstance(item, dict):
                    continue

                code = (
                    item.get("公司代號")
                    or item.get("股票代號")
                    or item.get("SecuritiesCompanyCode")
                    or item.get("Code")
                    or ""
                )
                code = str(code).strip()

                industry = (
                    item.get("產業別")
                    or item.get("產業類別")
                    or item.get("Industry")
                    or item.get("IndustryType")
                    or ""
                )

                if not industry:
                    for k, v in item.items():
                        if "產業" in str(k) or "Industry" in str(k):
                            industry = v
                            break

                if code.isdigit() and len(code) == 4 and industry:
                    result[code] = normalize_industry_name(industry)
                    added += 1

            print(f"[產業] 官方{label}產業別取得 {added} 筆")
        except Exception as e:
            print(f"[產業] 官方{label}產業別 API 失敗：{e}")

    return result


# ── 產業位階查詢（FIX-09：移除單股 fallback，找不到直接回「未知」）──
def resolve_industry_stage(code: str, df: pd.DataFrame, industry_lookup: dict, industry_stage_cache: dict) -> tuple:
    industry = industry_lookup.get(code, "未分類")
    stage    = industry_stage_cache.get(industry, "未知")
    return industry, stage


# ── 台股漲停價計算（含跳動價位）────────────────────────────────
def calc_limit_price(prev_close: float) -> float:
    raw = prev_close * 1.1

    if raw < 10:
        tick = 0.01
    elif raw < 50:
        tick = 0.05
    elif raw < 100:
        tick = 0.1
    elif raw < 500:
        tick = 0.5
    elif raw < 1000:
        tick = 1.0
    elif raw < 5000:
        tick = 5.0
    else:
        tick = 10.0

    import math
    return math.floor(raw / tick) * tick


# ── 簡易回測模組 ─────────────────────────────────────────────
def _fmt_pct(value):
    if value is None or pd.isna(value):
        return "-"
    return f"{value * 100:.1f}%"


def _forward_return_and_drawdown(close: pd.Series, signal_pos: int, horizon: int) -> tuple:
    # FIX-05：進場點改成訊號後第1天（模擬隔天買進），不用當天收盤
    entry_iloc = signal_pos + 1
    if entry_iloc + horizon >= len(close):
        return None, None

    entry_price = float(close.iloc[entry_iloc])
    if entry_price <= 0:
        return None, None

    future_window = close.iloc[entry_iloc + 1: entry_iloc + horizon + 1].astype(float)
    if future_window.empty:
        return None, None

    end_return    = float(close.iloc[entry_iloc + horizon]) / entry_price - 1
    max_drawdown  = float(future_window.min()) / entry_price - 1
    return end_return, max_drawdown


def backtest_strategy(df: pd.DataFrame, horizons=(5, 10, 20)) -> dict:
    """
    FIX-12：回測改成隔日掛單模擬。
    掛單價 = 整理期最高收盤 × 1.005
    隔天 low ≤ 掛單價 ≤ 隔天 high → 視為成交
    未觸及掛單價的訊號不計入回測，更貼近實際操作。
    """
    empty = {
        "samples": 0,
        "win_5": None, "avg_5": None,
        "win_10": None, "avg_10": None, "mdd_10": None,
        "win_20": None, "avg_20": None,
    }

    try:
        if df.empty or len(df) < 90:
            return empty

        close  = df["Close"].squeeze().astype(float)
        volume = df["Volume"].squeeze().astype(float)
        high   = df["High"].squeeze().astype(float)
        low    = df["Low"].squeeze().astype(float)

        if not isinstance(close, pd.Series) or len(close) < 90:
            return empty

        signal_positions = []   # (signal_i, entry_price)
        max_horizon      = max(horizons)
        rolling_ma20     = close.rolling(20).mean()

        for cur_i in range(70, len(close) - max_horizon - 1):
            lo = max(1, cur_i - 10)
            hi = max(1, cur_i - 2)
            if lo >= hi:
                continue

            # 找首次漲停
            limit_candidates = []
            for j in range(lo, hi):
                try:
                    lp = calc_limit_price(float(close.iloc[j - 1]))
                    if float(close.iloc[j]) >= lp * 0.999:
                        limit_candidates.append(j)
                except Exception:
                    continue

            if not limit_candidates:
                continue

            last_limit_i = limit_candidates[-1]

            # 近63交易日首次漲停
            start_check = max(1, last_limit_i - 63)
            prior_limit = any(
                calc_limit_price(float(close.iloc[j-1])) * 0.999 <= float(close.iloc[j])
                for j in range(start_check, last_limit_i)
                if j > 0
            )
            if prior_limit:
                continue

            limit_vol  = float(volume.iloc[last_limit_i])
            limit_low  = float(low.iloc[last_limit_i])      # FIX-03：用最低價
            curr_price = float(close.iloc[cur_i])
            curr_vol   = float(volume.iloc[cur_i])
            ma20_val   = float(rolling_ma20.iloc[cur_i])

            if limit_vol <= 0 or pd.isna(ma20_val):
                continue

            # FIX-01：洗盤三條件
            shrink   = curr_vol < limit_vol * 0.5
            hold_low = curr_price >= limit_low
            above_ma = curr_price > ma20_val
            if not (shrink and hold_low and above_ma):
                continue

            # FIX-06：訊號去重
            if signal_positions and cur_i - signal_positions[-1][0] < 10:
                continue

            # FIX-12：計算掛單價，判斷隔天是否成交
            wash_closes_bt = [float(close.iloc[j]) for j in range(last_limit_i + 1, cur_i + 1)]
            wash_high_c    = max(wash_closes_bt) if wash_closes_bt else curr_price
            entry_price    = round(wash_high_c * 1.005, 2)

            next_i     = cur_i + 1
            next_low   = float(low.iloc[next_i])
            next_high  = float(high.iloc[next_i])

            if not (next_low <= entry_price <= next_high):
                continue   # 掛單未成交，不計入

            signal_positions.append((cur_i, entry_price))

        if not signal_positions:
            return empty

        result = {"samples": len(signal_positions)}

        for h in horizons:
            returns   = []
            drawdowns = []
            for (pos, ep) in signal_positions:
                end_i = pos + 1 + h   # 進場隔天算起 h 天後
                if end_i >= len(close):
                    continue
                if ep <= 0:
                    continue
                future = close.iloc[pos + 2: end_i + 1].astype(float)
                if future.empty:
                    continue
                ret = float(close.iloc[end_i]) / ep - 1
                mdd = float(future.min()) / ep - 1
                returns.append(ret)
                drawdowns.append(mdd)

            if returns:
                result[f"win_{h}"] = sum(1 for r in returns if r > 0) / len(returns)
                result[f"avg_{h}"] = sum(returns) / len(returns)
            else:
                result[f"win_{h}"] = None
                result[f"avg_{h}"] = None

            if h == 10:
                result["mdd_10"] = min(drawdowns) if drawdowns else None

        return {**empty, **result}

    except Exception:
        return empty


# ── 抓取中文名稱對照表 ────────────────────────────────────────
def fetch_name_map() -> dict:
    name_map = {}
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=10)
        for item in r.json():
            name_map[item["Code"]] = item["Name"]
        print(f"[名稱] 上市取得 {len(name_map)} 筆")
    except Exception as e:
        print(f"[名稱] 上市 API 失敗：{e}")
    try:
        r = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=10)
        before = len(name_map)
        for item in r.json():
            name_map[item["SecuritiesCompanyCode"]] = item["CompanyName"]
        print(f"[名稱] 上櫃取得 {len(name_map)-before} 筆")
    except Exception as e:
        print(f"[名稱] 上櫃 API 失敗：{e}")
    return name_map


# ── K 線型態分析 ─────────────────────────────────────────────
def analyze_pattern(df: pd.DataFrame, limit_days: list) -> dict:
    score  = 0
    notes  = []

    if df.empty or len(df) < 5:
        return {"score": 0, "notes": ["資料不足"], "limit_quality": "未知"}

    close  = df['Close'].squeeze()
    open_  = df['Open'].squeeze()
    high   = df['High'].squeeze()
    low    = df['Low'].squeeze()
    volume = df['Volume'].squeeze()

    limit_quality = "未知"
    if limit_days:
        last_ld = limit_days[-1]
        try:
            o = float(open_.loc[last_ld])
            h = float(high.loc[last_ld])
            c = float(close.loc[last_ld])
            prev_close = float(close.iloc[list(close.index).index(last_ld) - 1])
            limit_price = calc_limit_price(prev_close)

            if o >= limit_price * 0.999:
                limit_quality = "一字板（最強）"
                score += 30
                notes.append("✅ 一字漲停板，主力意圖最強")
            elif (h - o) / o < 0.02:
                limit_quality = "開盤即拉板（強）"
                score += 20
                notes.append("✅ 開盤快速拉至漲停，籌碼集中")
            else:
                limit_quality = "盤中拉板（普通）"
                score += 10
                notes.append("⚠️ 盤中才拉漲停，主力意圖較弱")
        except Exception:
            limit_quality = "無法判斷"

    if limit_days:
        last_ld  = limit_days[-1]
        try:
            li       = list(close.index).index(last_ld)
            wash_vol = volume.iloc[li+1:]
            wash_days = len(wash_vol)

            if 2 <= wash_days <= 6:
                score += 15
                notes.append(f"✅ 洗盤 {wash_days} 個交易日，天數適中（黃金區間 2~6 交易日）")
            elif wash_days == 1:
                score += 8
                notes.append("⚠️ 洗盤僅 1 個交易日，可能尚未完成")
            else:
                score += 5
                notes.append(f"⚠️ 洗盤 {wash_days} 個交易日，時間偏長熱度可能已散")

            if len(wash_vol) >= 2:
                is_shrinking = all(
                    wash_vol.iloc[i] >= wash_vol.iloc[i+1]
                    for i in range(len(wash_vol)-1)
                )
                if is_shrinking:
                    score += 15
                    notes.append("✅ 洗盤期量能逐日遞減，主力鎖碼明顯")
                else:
                    notes.append("⚠️ 洗盤期量能不穩定，需觀察")
        except Exception:
            pass

    recent = df.iloc[-3:]
    for idx, row in recent.iterrows():
        o = float(row['Open'])
        h = float(row['High'])
        l = float(row['Low'])
        c = float(row['Close'])
        body    = abs(c - o)
        rng     = h - l if h != l else 0.001
        upper   = h - max(o, c)
        lower   = min(o, c) - l

        if lower > body * 2 and upper < body * 0.5 and rng > 0:
            score += 10
            notes.append(f"✅ {idx.strftime('%m/%d')} 出現錘子線，止跌訊號")

        if len(recent) >= 2:
            prev_idx = recent.index[list(recent.index).index(idx) - 1] if idx != recent.index[0] else None
            if prev_idx is not None:
                po = float(recent.loc[prev_idx, 'Open'])
                pc = float(recent.loc[prev_idx, 'Close'])
                if pc < po and c > o and c > po and o < pc:
                    score += 12
                    notes.append(f"✅ {idx.strftime('%m/%d')} 多頭吞噬，強力止跌")

        if body / rng < 0.1:
            notes.append(f"⚠️ {idx.strftime('%m/%d')} 十字星，多空拉鋸中")

    ma5  = float(close.rolling(5).mean().iloc[-1])
    ma10 = float(close.rolling(10).mean().iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    curr = float(close.iloc[-1])

    if curr > ma5 > ma10 > ma20:
        score += 15
        notes.append("✅ 均線多頭排列（價 > MA5 > MA10 > MA20）")
    elif curr > ma10 > ma20:
        score += 8
        notes.append("⚠️ 部分均線多頭（價 > MA10 > MA20）")
    else:
        notes.append("❌ 均線排列不佳，趨勢偏弱")

    if score >= 70:
        grade = "🔥🔥 極強"
    elif score >= 50:
        grade = "🔥 強"
    elif score >= 30:
        grade = "⚠️ 普通"
    else:
        grade = "❌ 弱"

    return {
        "score":         score,
        "grade":         grade,
        "notes":         notes,
        "limit_quality": limit_quality,
        "ma5":           round(ma5,  2),
        "ma10":          round(ma10, 2),
        "ma20":          round(ma20, 2),
    }


# ── K 線圖 HTML（含縮放區間功能）───────────────────────────────
def generate_chart_html(symbol, name, df, limit_days, is_washing, wash_info, pattern, wash_low_val=0, target_val=0, entry_val=0, industry='', industry_stage=''):
    code   = symbol.split('.')[0]
    market = "上市" if symbol.endswith(".TW") else "上櫃"

    records = []
    limit_set = {d.strftime('%Y-%m-%d') for d in limit_days}
    for idx, row in df.iterrows():
        records.append({
            "date":   idx.strftime('%m/%d'),
            "open":   round(float(row['Open']),  2),
            "high":   round(float(row['High']),  2),
            "low":    round(float(row['Low']),   2),
            "close":  round(float(row['Close']), 2),
            "volume": int(row['Volume']),
            "limit":  idx.strftime('%Y-%m-%d') in limit_set,
        })

    closes = [r['close'] for r in records]
    def ma(n):
        result = []
        for i in range(len(closes)):
            if i < n - 1:
                result.append(None)
            else:
                result.append(round(sum(closes[i-n+1:i+1]) / n, 2))
        return result

    ma5_vals   = ma(5)
    ma10_vals  = ma(10)
    ma20_vals  = ma(20)
    ma60_vals  = ma(60)
    ma240_vals = ma(240)

    for j, r in enumerate(records):
        r['ma5']   = ma5_vals[j]
        r['ma10']  = ma10_vals[j]
        r['ma20']  = ma20_vals[j]
        r['ma60']  = ma60_vals[j]
        r['ma240'] = ma240_vals[j]

    data_json = json.dumps(records, ensure_ascii=False)
    ref_lines = json.dumps({
        "entry":     round(entry_val,    2) if entry_val    else 0,
        "stop_loss": round(wash_low_val, 2) if wash_low_val else 0,
        "target":    round(target_val,   2) if target_val   else 0,
    })
    last_close  = records[-1]['close'] if records else 0
    limit_count = len(limit_days)

    status_html = (
        "<span style='background:#d93025;color:#fff;padding:3px 10px;"
        "border-radius:5px;font-weight:700'>🔥 準備起飛</span>"
        if is_washing else
        "<span style='background:#444;color:#ccc;padding:3px 10px;"
        "border-radius:5px'>📊 盤整觀察</span>"
    )

    vol_ratio = wash_info.get('vol_ratio', '-')
    ma20_ok   = "✅ 站上月線" if wash_info.get('above_ma20') else "❌ 跌破月線"
    hold_low  = "✅ 守住起漲點" if wash_info.get('hold_low') else "❌ 跌破起漲點"

    score      = pattern.get('score', 0)
    grade      = pattern.get('grade', '-')
    p_notes    = pattern.get('notes', [])
    lq         = pattern.get('limit_quality', '-')
    ma5        = pattern.get('ma5',  '-')
    ma10       = pattern.get('ma10', '-')
    ma20_val   = pattern.get('ma20', '-')

    notes_html  = "".join(f"<li>{n}</li>" for n in p_notes)
    score_color = "#26a641" if score >= 70 else "#ffa500" if score >= 50 else "#f85149"

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{code} {name} K線圖</title>
<style>
  :root {{
    --bg:#0d1117; --panel:#161b22; --border:#30363d;
    --text:#e6edf3; --muted:#8b949e;
    --up:#26a641; --down:#f85149; --limit:#ffa500; --accent:#58a6ff;
  }}
  *{{ box-sizing:border-box; margin:0; padding:0; }}
  body{{ background:var(--bg); color:var(--text);
         font-family:'SF Mono','Fira Code',monospace; padding:24px; }}
  .header{{ display:flex; align-items:baseline; gap:14px; margin-bottom:18px; flex-wrap:wrap; }}
  .code{{ font-size:2rem; font-weight:700; color:var(--accent); }}
  .name{{ font-size:1.1rem; font-weight:500; }}
  .tag{{ font-size:.8rem; background:var(--panel); border:1px solid var(--border);
          border-radius:4px; padding:3px 9px; color:var(--muted); }}
  .grid2{{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:14px; }}
  .grid3{{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; margin-bottom:14px; }}
  .card{{ background:var(--panel); border:1px solid var(--border); border-radius:8px; padding:14px 18px; }}
  .s-label{{ font-size:.68rem; color:var(--muted); text-transform:uppercase;
              letter-spacing:.06em; margin-bottom:6px; }}
  .s-val{{ font-size:1rem; font-weight:600; }}
  .wrap{{ background:var(--panel); border:1px solid var(--border);
          border-radius:8px; padding:14px; margin-bottom:12px; position:relative; }}
  .wrap-title{{ font-size:.68rem; color:var(--muted); text-transform:uppercase;
                letter-spacing:.06em; margin-bottom:10px; }}
  canvas{{ display:block; width:100%; cursor:crosshair; }}
  #tip{{ background:var(--panel); border:1px solid var(--border);
         border-radius:6px; padding:10px 16px; font-size:.82rem;
         line-height:1.8; flex-wrap:wrap; display:flex; gap:12px; align-items:center; }}
  .legend{{ display:flex; gap:18px; font-size:.72rem; color:var(--muted); margin-top:8px; margin-bottom:12px; flex-wrap:wrap; }}
  .dot{{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; }}
  .score-ring{{ font-size:2.5rem; font-weight:700; color:{score_color}; }}
  ul.notes{{ list-style:none; padding:0; font-size:.82rem; line-height:2; }}
  ul.notes li{{ border-bottom:1px solid var(--border); padding:4px 0; }}
  ul.notes li:last-child{{ border-bottom:none; }}
  .ma-row{{ display:flex; gap:16px; font-size:.82rem; margin-top:8px; flex-wrap:wrap; }}
  .ma-item{{ background:#1c2128; border-radius:4px; padding:4px 10px; }}
  /* 區間按鈕 */
  .range-bar{{ display:flex; gap:6px; margin-bottom:10px; align-items:center; flex-wrap:wrap; }}
  .rbtn{{
    background:transparent; color:var(--muted);
    border:1px solid var(--border); border-radius:4px;
    padding:3px 12px; font-size:.75rem; font-family:inherit;
    cursor:pointer; transition:border-color .15s, color .15s;
  }}
  .rbtn:hover{{ border-color:var(--accent); color:var(--accent); }}
  .rbtn.active{{ border-color:var(--accent); color:var(--accent); font-weight:700; }}
  /* 縮略導航 */
  #nc{{ cursor:col-resize; }}
</style>
</head>
<body>

<div class="header">
  <div class="code">📊 {code}</div>
  <div class="name">{name}</div>
  <div class="tag">{market}</div>
  <div class="tag">{industry}</div>
  <div class="tag" style="color:{'#26a641' if industry_stage in ['復甦初期','成長中期'] else '#f85149' if industry_stage=='衰退期' else '#ffa500'}">{industry_stage}</div>
</div>

<!-- 狀態卡 -->
<div class="grid3">
  <div class="card">
    <div class="s-label">最新收盤</div>
    <div class="s-val" style="color:var(--accent)">{last_close}</div>
  </div>
  <div class="card">
    <div class="s-label">洗盤狀態</div>
    <div class="s-val">{status_html}</div>
  </div>
  <div class="card">
    <div class="s-label">漲停板品質</div>
    <div class="s-val" style="font-size:.88rem">{lq}</div>
  </div>
</div>

<!-- 洗盤指標 -->
<div class="card" style="margin-bottom:14px;font-size:.85rem;line-height:2.2">
  <div class="s-label">洗盤指標</div>
  最後交易日量 / 漲停量：<b>{vol_ratio}</b>（&lt;50% 視為縮量）&nbsp;&nbsp;
  {ma20_ok}&nbsp;&nbsp;{hold_low}
  <div class="ma-row">
    <span class="ma-item">MA5：{ma5}</span>
    <span class="ma-item">MA10：{ma10}</span>
    <span class="ma-item">MA20：{ma20_val}</span>
  </div>
</div>

<!-- 快速區間切換列 -->
<div class="range-bar">
  <span style="font-size:.72rem;color:var(--muted);margin-right:4px;">區間：</span>
  <button class="rbtn" id="rb-20"  onclick="setRange(20)">1M</button>
  <button class="rbtn" id="rb-60"  onclick="setRange(60)">3M</button>
  <button class="rbtn" id="rb-120" onclick="setRange(120)">6M</button>
  <button class="rbtn" id="rb-250" onclick="setRange(250)">1Y</button>
  <button class="rbtn" id="rb-all" onclick="setRange(-1)">All</button>
  <span style="font-size:.72rem;color:var(--muted);margin-left:8px;">｜ 滾輪縮放 ｜ 底部拖拉</span>
</div>

<!-- 游標資訊列 -->
<div id="tip" style="margin-bottom:8px;font-size:.82rem;">
  <span style="color:var(--muted)">← 滑鼠移到 K 線圖查看詳細資訊</span>
</div>

<!-- K 線圖 -->
<div class="wrap">
  <div class="wrap-title">K 線圖</div>
  <canvas id="kc"></canvas>
</div>
<div class="legend">
  <span><span class="dot" style="background:var(--up)"></span>上漲</span>
  <span><span class="dot" style="background:var(--down)"></span>下跌</span>
  <span><span class="dot" style="background:var(--limit)"></span>漲停</span>
  <span><span class="dot" style="background:#f0c040"></span>MA5</span>
  <span><span class="dot" style="background:#e06080"></span>MA10</span>
  <span><span class="dot" style="background:#58a6ff"></span>MA20</span>
  <span><span class="dot" style="background:#bc8cff"></span>MA60</span>
  <span><span class="dot" style="background:#ff8c42"></span>MA240</span>
</div>

<!-- 成交量 -->
<div class="wrap" style="padding:12px 14px;">
  <div class="wrap-title">成交量</div>
  <canvas id="vc"></canvas>
</div>

<!-- KD 指標 -->
<div class="wrap" style="padding:12px 14px;">
  <div class="wrap-title">KD 指標（9日）</div>
  <canvas id="kdc"></canvas>
  <div style="display:flex;gap:18px;font-size:.72rem;color:var(--muted);margin-top:6px;">
    <span><span class="dot" style="background:#f0c040"></span>K 值</span>
    <span><span class="dot" style="background:#58a6ff"></span>D 值</span>
    <span style="color:#8b949e">超買 &gt;80　超賣 &lt;20</span>
  </div>
</div>

<!-- 縮略圖導航（拖拉選區間）-->
<div class="wrap" style="padding:10px 14px;margin-bottom:16px;">
  <div class="wrap-title">區間選取（拖拉邊界縮放 ／ 拖拉中間平移）</div>
  <canvas id="nc"></canvas>
</div>

<!-- 型態分析評分卡 -->
<div class="grid2" style="margin-top:4px;">
  <div class="card">
    <div class="s-label">型態評分</div>
    <div class="score-ring">{score} 分</div>
    <div style="font-size:1.1rem;margin-top:6px;">{grade}</div>
    <div style="font-size:.72rem;color:var(--muted);margin-top:4px;">滿分約 87 分</div>
  </div>
  <div class="card">
    <div class="s-label">型態分析說明</div>
    <ul class="notes">{notes_html}</ul>
  </div>
</div>

<script>
const DATA      = {data_json};
const REF_LINES = {ref_lines};
const DPR       = window.devicePixelRatio || 1;
const N         = DATA.length;

// ── 縮放狀態 ──────────────────────────────────────────────────
let viewStart = Math.max(0, N - 120);
let viewEnd   = N;

// ── 拖拉狀態（縮略圖）────────────────────────────────────────
let _isDragging   = false;
let _navMode      = null;   // 'left' | 'right' | 'move'
let _navDragX     = 0;
let _navViewStart = 0;
let _navViewEnd   = 0;

// ── canvas 初始化 ─────────────────────────────────────────────
function setup(canvas, h) {{
  const w = canvas.parentElement.clientWidth - 28;
  canvas.style.width  = w + 'px';
  canvas.style.height = h + 'px';
  canvas.width  = Math.floor(w * DPR);
  canvas.height = Math.floor(h * DPR);
  const ctx = canvas.getContext('2d');
  ctx.scale(DPR, DPR);
  return {{ ctx, w, h }};
}}

// ── KD 計算（對任意資料切片）─────────────────────────────────
function calcKD(slice) {{
  const ks = [], ds = [];
  let pk = 50, pd = 50;
  for (let j = 0; j < slice.length; j++) {{
    if (j < 8) {{ ks.push(null); ds.push(null); continue; }}
    const win  = slice.slice(j - 8, j + 1);
    const hh   = Math.max(...win.map(d => d.high));
    const ll   = Math.min(...win.map(d => d.low));
    const rsv  = hh !== ll ? (slice[j].close - ll) / (hh - ll) * 100 : 50;
    const k    = pk * 2/3 + rsv * 1/3;
    const d    = pd * 2/3 + k   * 1/3;
    ks.push(parseFloat(k.toFixed(1)));
    ds.push(parseFloat(d.toFixed(1)));
    pk = k; pd = d;
  }}
  return {{ ks, ds }};
}}

// ── 主繪圖函式 ────────────────────────────────────────────────
function draw() {{
  const kcan  = document.getElementById('kc');
  const vcan  = document.getElementById('vc');
  const kdcan = document.getElementById('kdc');
  const ncan  = document.getElementById('nc');

  const {{ ctx:kc,  w, h:kh  }} = setup(kcan,  300);
  const {{ ctx:vc,     h:vh  }} = setup(vcan,   70);
  const {{ ctx:kdc,    h:kdh }} = setup(kdcan,  80);
  const {{ ctx:nc,     h:nh  }} = setup(ncan,   44);

  const slice = DATA.slice(viewStart, viewEnd);
  const sn    = slice.length;
  if (sn === 0) return;

  const PL = 10, PR = 56, PT = 16, PB = 26;
  const cw = w - PL - PR, ch = kh - PT - PB;
  const gap = cw / sn;
  const bw  = Math.max(2, Math.min(14, gap - 2));

  const UP = '#26a641', DN = '#f85149', LM = '#ffa500', MU = '#8b949e', GR = '#21262d';

  // ── K 線圖 ──────────────────────────────────────────────────
  kc.clearRect(0, 0, w, kh);

  const pMin = Math.min(...slice.map(d => d.low))  * 0.995;
  const pMax = Math.max(...slice.map(d => d.high)) * 1.005;
  const pr   = pMax - pMin || 1;
  const py   = v => PT + ch - ((v - pMin) / pr) * ch;

  // 水平格線
  for (let i = 0; i <= 5; i++) {{
    const p = pMin + (pr / 5) * i, y = py(p);
    kc.strokeStyle = GR; kc.lineWidth = 1;
    kc.beginPath(); kc.moveTo(PL, y); kc.lineTo(w - PR, y); kc.stroke();
    kc.fillStyle = MU; kc.font = '10px SF Mono,monospace'; kc.textAlign = 'left';
    kc.fillText(p.toFixed(1), w - PR + 4, y + 4);
  }}

  // 日期標籤
  const step = Math.max(1, Math.floor(sn / 6));
  slice.forEach((d, i) => {{
    if (i % step !== 0) return;
    const x = PL + i * gap + gap / 2;
    kc.fillStyle = MU; kc.font = '10px SF Mono,monospace'; kc.textAlign = 'center';
    kc.fillText(d.date, x, kh - 6);
  }});

  // K 棒
  slice.forEach((d, i) => {{
    const x   = PL + i * gap + gap / 2;
    const col = d.limit ? LM : (d.close >= d.open ? UP : DN);
    kc.strokeStyle = col; kc.lineWidth = 1;
    kc.beginPath(); kc.moveTo(x, py(d.high)); kc.lineTo(x, py(d.low)); kc.stroke();
    const y1 = py(Math.max(d.open, d.close)), y2 = py(Math.min(d.open, d.close));
    kc.fillStyle = col;
    kc.fillRect(x - bw / 2, y1, bw, Math.max(1, y2 - y1));
    if (d.limit) {{
      kc.fillStyle = LM; kc.font = 'bold 11px sans-serif'; kc.textAlign = 'center';
      kc.fillText('🔥', x, py(d.high) - 6);
    }}
  }});

  // 均線
  function drawMA(key, color) {{
    kc.strokeStyle = color; kc.lineWidth = 1.2; kc.beginPath();
    let started = false;
    slice.forEach((d, i) => {{
      if (d[key] === null || d[key] === undefined) {{ started = false; return; }}
      const x = PL + i * gap + gap / 2, y = py(d[key]);
      if (!started) {{ kc.moveTo(x, y); started = true; }} else kc.lineTo(x, y);
    }});
    kc.stroke();
  }}
  drawMA('ma5',  '#f0c040');
  drawMA('ma10', '#e06080');
  drawMA('ma20', '#58a6ff');
  drawMA('ma60',  '#bc8cff');
  drawMA('ma240', '#ff8c42');

  // 參考線（掛單 / 停損 / 目標）
  function drawRefLine(val, color, label) {{
    if (!val || val <= 0) return;
    const y = py(val);
    kc.strokeStyle = color + '88'; kc.lineWidth = 1.5; kc.setLineDash([6, 3]);
    kc.beginPath(); kc.moveTo(PL, y); kc.lineTo(w - PR, y); kc.stroke();
    kc.setLineDash([]);
    kc.fillStyle = color; kc.font = 'bold 10px SF Mono,monospace'; kc.textAlign = 'left';
    kc.fillText(`${{label}} ${{val}}`, w - PR + 4, y - 3);
  }}
  drawRefLine(REF_LINES.entry,     '#58a6ff', '掛單');
  drawRefLine(REF_LINES.stop_loss, '#f85149', '停損');
  drawRefLine(REF_LINES.target,    '#26a641', '目標');

  // ── 成交量 ──────────────────────────────────────────────────
  vc.clearRect(0, 0, w, vh);
  const volMax = Math.max(...slice.map(d => d.volume)) || 1;
  slice.forEach((d, i) => {{
    const x   = PL + i * gap + gap / 2;
    const col = d.limit ? LM : (d.close >= d.open ? UP : DN);
    vc.fillStyle = col + 'aa';
    const barH = (d.volume / volMax) * (vh - 8);
    vc.fillRect(x - bw / 2, vh - barH, bw, barH);
  }});

  // ── KD 指標 ─────────────────────────────────────────────────
  kdc.clearRect(0, 0, w, kdh);
  const {{ ks: k_vals, ds: d_vals }} = calcKD(slice);

  [20, 50, 80].forEach(lv => {{
    const y = kdh - (lv / 100) * (kdh - 4) - 2;
    kdc.strokeStyle = lv === 50 ? GR : (lv === 80 ? '#f8514944' : '#26a64144');
    kdc.lineWidth = 1; kdc.setLineDash([3, 3]);
    kdc.beginPath(); kdc.moveTo(PL, y); kdc.lineTo(w - PR, y); kdc.stroke();
    kdc.setLineDash([]);
    kdc.fillStyle = MU; kdc.font = '9px SF Mono,monospace'; kdc.textAlign = 'left';
    kdc.fillText(lv, w - PR + 4, y + 3);
  }});

  function drawKDLine(vals, color) {{
    kdc.strokeStyle = color; kdc.lineWidth = 1.2; kdc.beginPath();
    let started = false;
    vals.forEach((v, i) => {{
      if (v === null) {{ started = false; return; }}
      const x = PL + i * gap + gap / 2;
      const y = kdh - (v / 100) * (kdh - 4) - 2;
      if (!started) {{ kdc.moveTo(x, y); started = true; }} else kdc.lineTo(x, y);
    }});
    kdc.stroke();
  }}
  drawKDLine(k_vals, '#f0c040');
  drawKDLine(d_vals, '#58a6ff');

  // KD 黃金／死亡交叉標記
  for (let i = 1; i < slice.length; i++) {{
    const pk = k_vals[i-1], pd = d_vals[i-1], ck = k_vals[i], cd = d_vals[i];
    if (pk === null || pd === null || ck === null || cd === null) continue;
    const x = PL + i * gap + gap / 2;
    const y = kdh - (ck / 100) * (kdh - 4) - 2;
    if (pk <= pd && ck > cd) {{
      kdc.fillStyle = '#ffd700'; kdc.font = 'bold 10px sans-serif'; kdc.textAlign = 'center';
      kdc.fillText('★', x, y - 6);
    }}
    if (pk >= pd && ck < cd) {{
      kdc.fillStyle = '#f85149'; kdc.font = 'bold 10px sans-serif'; kdc.textAlign = 'center';
      kdc.fillText('★', x, y + 12);
    }}
  }}

  // ── 縮略圖導航 ───────────────────────────────────────────────
  nc.clearRect(0, 0, w, nh);
  const npMin = Math.min(...DATA.map(d => d.low));
  const npMax = Math.max(...DATA.map(d => d.high));
  const npr   = npMax - npMin || 1;
  const nGap  = w / N;

  // 遮罩：非選取區灰暗
  nc.fillStyle = 'rgba(0,0,0,0.35)';
  nc.fillRect(0, 0, viewStart * nGap, nh);
  nc.fillRect(viewEnd * nGap, 0, w - viewEnd * nGap, nh);

  // 收盤線
  nc.strokeStyle = '#58a6ff66'; nc.lineWidth = 1; nc.beginPath();
  DATA.forEach((d, i) => {{
    const x = i * nGap + nGap / 2;
    const y = nh - ((d.close - npMin) / npr) * (nh - 4) - 2;
    i === 0 ? nc.moveTo(x, y) : nc.lineTo(x, y);
  }});
  nc.stroke();

  // 選取框
  const nx1 = viewStart * nGap, nx2 = viewEnd * nGap;
  nc.strokeStyle = '#58a6ff'; nc.lineWidth = 1.5;
  nc.strokeRect(nx1, 0, nx2 - nx1, nh);

  // 拖拉把手
  nc.fillStyle = '#58a6ff';
  [nx1, nx2].forEach(hx => {{ nc.fillRect(hx - 2, 4, 4, nh - 8); }});

  // ── 游標互動（K 線圖）────────────────────────────────────────
  kcan.onmousemove = e => {{
    const r  = kcan.getBoundingClientRect();
    const mx = e.clientX - r.left;
    const i  = Math.round((mx - PL) / gap - 0.5);
    if (i < 0 || i >= sn) return;
    const d   = slice[i];
    const col = d.limit ? '#ffa500' : (d.close >= d.open ? '#26a641' : '#f85149');
    const chg = ((d.close - d.open) / d.open * 100).toFixed(2);

    // 同步游標線（重繪後疊加）
    draw();
    const cx = PL + i * gap + gap / 2;
    [{{ ctx:kc, h:kh }}, {{ ctx:vc, h:vh }}, {{ ctx:kdc, h:kdh }}].forEach(c => {{
      c.ctx.strokeStyle = 'rgba(255,255,255,0.2)'; c.ctx.lineWidth = 1; c.ctx.setLineDash([4, 3]);
      c.ctx.beginPath(); c.ctx.moveTo(cx, 0); c.ctx.lineTo(cx, c.h); c.ctx.stroke();
      c.ctx.setLineDash([]);
    }});

    document.getElementById('tip').innerHTML =
      `<span style="color:var(--muted)">${{d.date}}</span>` +
      ` 開<b>${{d.open}}</b> 高<b>${{d.high}}</b> 低<b>${{d.low}}</b>` +
      ` 收<b style="color:${{col}}">${{d.close}}</b><span style="color:${{col}}">(${{chg > 0 ? '+' : ''}}${{chg}}%)</span>` +
      ` 量<b>${{(d.volume / 1000).toFixed(0)}}K</b>` +
      (d.ma5   ? ` <span style="color:#f0c040">MA5 <b>${{d.ma5}}</b></span>`   : '') +
      (d.ma10  ? ` <span style="color:#e06080">MA10 <b>${{d.ma10}}</b></span>` : '') +
      (d.ma20  ? ` <span style="color:#58a6ff">MA20 <b>${{d.ma20}}</b></span>` : '') +
      (d.ma60  ? ` <span style="color:#bc8cff">MA60 <b>${{d.ma60}}</b></span>` : '') +
      (d.ma240 ? ` <span style="color:#ff8c42">MA240 <b>${{d.ma240}}</b></span>` : '') +
      (k_vals[i] !== null ? ` <span style="color:#f0c040">K<b>${{k_vals[i]}}</b></span>` : '') +
      (d_vals[i] !== null ? ` <span style="color:#58a6ff">D<b>${{d_vals[i]}}</b></span>` : '') +
      (d.limit ? ` <span style="color:#ffa500;font-weight:700">🔥漲停</span>` : '');
  }};
  kcan.onmouseleave = () => {{
    draw();
    document.getElementById('tip').innerHTML =
      '<span style="color:var(--muted)">← 滑鼠移到 K 線圖查看詳細資訊</span>';
  }};
}}

// ── 快速區間按鈕 ───────────────────────────────────────────────
function setRange(days) {{
  if (days === -1) {{ viewStart = 0; viewEnd = N; }}
  else {{ viewEnd = N; viewStart = Math.max(0, N - days); }}
  document.querySelectorAll('.rbtn').forEach(b => b.classList.remove('active'));
  const el = document.getElementById('rb-' + (days === -1 ? 'all' : days));
  if (el) el.classList.add('active');
  draw();
}}

// ── 滾輪縮放（K 線圖上）──────────────────────────────────────
document.getElementById('kc').addEventListener('wheel', e => {{
  e.preventDefault();
  const sn    = viewEnd - viewStart;
  const delta = e.deltaY > 0 ? 1 : -1;
  const zoom  = Math.max(1, Math.floor(sn * 0.1));
  const mid   = Math.floor((viewStart + viewEnd) / 2);
  const newSn = Math.max(20, Math.min(N, sn + delta * zoom));
  let ns = mid - Math.floor(newSn / 2);
  let ne = ns + newSn;
  if (ns < 0) {{ ns = 0; ne = newSn; }}
  if (ne > N) {{ ne = N; ns = Math.max(0, N - newSn); }}
  viewStart = ns; viewEnd = ne;
  draw();
}}, {{ passive: false }});

// ── 縮略圖拖拉（滑鼠）────────────────────────────────────────
const ncan = document.getElementById('nc');

function getNavMode(mx) {{
  const nw = ncan.getBoundingClientRect().width;
  const x1 = viewStart / N * nw;
  const x2 = viewEnd   / N * nw;
  if (Math.abs(mx - x1) < 10) return 'left';
  if (Math.abs(mx - x2) < 10) return 'right';
  if (mx > x1 && mx < x2)     return 'move';
  return null;
}}

ncan.addEventListener('mousedown', e => {{
  const r  = ncan.getBoundingClientRect();
  const mx = e.clientX - r.left;
  _navMode = getNavMode(mx);
  if (_navMode) {{
    _isDragging   = true;
    _navDragX     = mx;
    _navViewStart = viewStart;
    _navViewEnd   = viewEnd;
  }}
}});

window.addEventListener('mousemove', e => {{
  if (!_isDragging || !_navMode) return;
  const r   = ncan.getBoundingClientRect();
  const mx  = e.clientX - r.left;
  const dx  = Math.round((mx - _navDragX) / r.width * N);
  if (_navMode === 'left') {{
    viewStart = Math.max(0, Math.min(_navViewStart + dx, viewEnd - 20));
  }} else if (_navMode === 'right') {{
    viewEnd = Math.max(viewStart + 20, Math.min(N, _navViewEnd + dx));
  }} else if (_navMode === 'move') {{
    const span = _navViewEnd - _navViewStart;
    let ns = _navViewStart + dx, ne = _navViewEnd + dx;
    if (ns < 0) {{ ns = 0; ne = span; }}
    if (ne > N) {{ ne = N; ns = N - span; }}
    viewStart = ns; viewEnd = ne;
  }}
  draw();
}});

window.addEventListener('mouseup', () => {{
  _isDragging = false;
  _navMode    = null;
}});

// 游標樣式
ncan.addEventListener('mousemove', e => {{
  const r  = ncan.getBoundingClientRect();
  const mx = e.clientX - r.left;
  const m  = getNavMode(mx);
  ncan.style.cursor = (m === 'left' || m === 'right') ? 'ew-resize' : (m === 'move' ? 'grab' : 'default');
}});

// ── 縮略圖拖拉（觸控）────────────────────────────────────────
ncan.addEventListener('touchstart', e => {{
  const r  = ncan.getBoundingClientRect();
  const mx = e.touches[0].clientX - r.left;
  _navMode = getNavMode(mx);
  if (_navMode) {{
    _isDragging   = true;
    _navDragX     = mx;
    _navViewStart = viewStart;
    _navViewEnd   = viewEnd;
  }}
}}, {{ passive: true }});

ncan.addEventListener('touchmove', e => {{
  if (!_isDragging || !_navMode) return;
  const r  = ncan.getBoundingClientRect();
  const mx = e.touches[0].clientX - r.left;
  const dx = Math.round((mx - _navDragX) / r.width * N);
  if (_navMode === 'left') {{
    viewStart = Math.max(0, Math.min(_navViewStart + dx, viewEnd - 20));
  }} else if (_navMode === 'right') {{
    viewEnd = Math.max(viewStart + 20, Math.min(N, _navViewEnd + dx));
  }} else if (_navMode === 'move') {{
    const span = _navViewEnd - _navViewStart;
    let ns = _navViewStart + dx, ne = _navViewEnd + dx;
    if (ns < 0) {{ ns = 0; ne = span; }}
    if (ne > N) {{ ne = N; ns = N - span; }}
    viewStart = ns; viewEnd = ne;
  }}
  draw();
}}, {{ passive: true }});

ncan.addEventListener('touchend', () => {{
  _isDragging = false;
  _navMode    = null;
}});

// ── 初始化 ───────────────────────────────────────────────────
window.addEventListener('resize', draw);
setRange(120);   // 預設顯示近 6 個月
</script>
</body>
</html>"""


# ── 股票清單 ─────────────────────────────────────────────────
def get_list(target=1200):
    tw_codes  = []
    two_codes = []

    try:
        r = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
            timeout=15)
        for item in r.json():
            code = item.get("Code", "")
            if code.isdigit() and len(code) == 4:
                tw_codes.append(code)
        print(f"[清單] 上市取得 {len(tw_codes)} 支")
    except Exception as e:
        print(f"[清單] 上市 API 失敗：{e}")

    try:
        r = requests.get(
            "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes",
            timeout=15)
        for item in r.json():
            code = item.get("SecuritiesCompanyCode", "")
            if code.isdigit() and len(code) == 4:
                two_codes.append(code)
        print(f"[清單] 上櫃取得 {len(two_codes)} 支")
    except Exception as e:
        print(f"[清單] 上櫃 API 失敗：{e}")

    # FIX-25：target 參數實際控制數量（上市60%、上櫃40%）
    tw_n      = int(target * 0.6)
    two_n     = target - tw_n
    tw_codes  = tw_codes[:tw_n]
    two_codes = two_codes[:two_n]

    result = [f"{c}.TW"  for c in tw_codes] + \
             [f"{c}.TWO" for c in two_codes]

    print(f"[清單] 合計 {len(result)} 支納入掃描")
    return result


# ── 掃描主函式 ───────────────────────────────────────────────
def scan(output_dir="charts", base_url="charts"):
    os.makedirs(output_dir, exist_ok=True)

    print("[名稱] 正在抓取中文名稱對照表...")
    name_map = fetch_name_map()

    official_industry_map = fetch_official_industry_map()
    # FIX-08：手動先、官方覆蓋 → 官方資料優先
    industry_lookup = industry_map.copy()
    industry_lookup.update(official_industry_map)
    print(f"[產業] 產業分類對照表合計 {len(industry_lookup)} 筆（官方優先）")

    stocks      = get_list()
    today       = datetime.now()
    fetch_start = today - timedelta(days=730)
    fetch_end   = today
    results     = []
    total       = len(stocks)
    price_cache = {}

    print("[產業] 建立產業資料池...")
    industry_data = {}
    for s in stocks:
        code = s.split('.')[0]
        ind  = industry_lookup.get(code)
        if not ind:
            continue
        try:
            if s not in price_cache:
                price_cache[s] = yf.download(s, start=fetch_start, end=fetch_end, progress=False)
            df_ind = price_cache[s]
            if df_ind.empty or len(df_ind) < 60:
                continue
            if isinstance(df_ind.columns, pd.MultiIndex):
                df_ind = df_ind.copy()
                df_ind.columns = df_ind.columns.get_level_values(0)
                price_cache[s] = df_ind
            industry_data.setdefault(ind, []).append(df_ind)
        except Exception:
            continue
    print(f"[產業] 完成，涵蓋 {len(industry_data)} 個產業")

    industry_stage_cache = {
        ind: get_industry_stage(dfs, industry_name=ind)
        for ind, dfs in industry_data.items()
    }

    # FIX-20：龍頭股狀態加權 — 龍頭跌破 MA20 → 產業強制降一級
    _stage_order = ["衰退期", "盤整過渡", "高檔成熟", "復甦初期", "成長中期", "高檔過熱"]
    for ind, leader_code in INDUSTRY_LEADERS.items():
        if ind not in industry_stage_cache:
            continue
        leader_sym = f"{leader_code}.TW"
        try:
            _ldf = price_cache.get(leader_sym)
            if _ldf is None or _ldf.empty:
                continue
            if isinstance(_ldf.columns, pd.MultiIndex):
                _ldf = _ldf.copy(); _ldf.columns = _ldf.columns.get_level_values(0)
            _lc   = _ldf["Close"].squeeze().astype(float)
            _curr = float(_lc.iloc[-1])
            _ma20 = float(_lc.rolling(20).mean().iloc[-1])
            if _curr < _ma20:   # 龍頭跌破月線 → 降一級
                cur_stage = industry_stage_cache[ind]
                if cur_stage in _stage_order:
                    idx = _stage_order.index(cur_stage)
                    if idx > 0:
                        industry_stage_cache[ind] = _stage_order[idx - 1]
                        print(f"[產業] FIX-20 {ind} 龍頭{leader_code}跌破MA20，位階降級：{cur_stage}→{industry_stage_cache[ind]}")
        except Exception:
            continue

    print("[產業] 位階快取：" + ", ".join(f"{k}={v}" for k, v in sorted(industry_stage_cache.items())))

    # ── 基準日：用最後一筆交易日，支援週末／假日執行 ──────────
    # 先抓一支主力股確認最後交易日
    _ref_last_day = None
    try:
        _ref_df = yf.download("^TWII", start=today - timedelta(days=10), end=today + timedelta(days=1), progress=False)
        if not _ref_df.empty:
            if isinstance(_ref_df.columns, pd.MultiIndex):
                _ref_df.columns = _ref_df.columns.get_level_values(0)
            _ref_last_day = _ref_df.index[-1]
    except Exception:
        pass

    if _ref_last_day is not None:
        weekday_name = _ref_last_day.strftime('%A')
        print(f"[基準日] 最後交易日：{_ref_last_day.strftime('%Y-%m-%d')} ({weekday_name})")
    else:
        print("[基準日] 無法確認最後交易日，以各股最後一筆為準")

    # ── NEW-01：大盤濾網（BUG-08：^TPEX yfinance抓不到，只用^TWII）──
    market_status = {"twii_ok": None, "twii_close": None, "twii_ma20": None}
    try:
        _mdf = yf.download("^TWII", start=today - timedelta(days=60),
                           end=today + timedelta(days=1), progress=False)
        if not _mdf.empty:
            if isinstance(_mdf.columns, pd.MultiIndex):
                _mdf.columns = _mdf.columns.get_level_values(0)
            _mc   = _mdf["Close"].squeeze().astype(float)
            _last = float(_mc.iloc[-1])
            _ma20 = float(_mc.rolling(20).mean().iloc[-1])
            market_status["twii_close"] = round(_last, 2)
            market_status["twii_ma20"]  = round(_ma20, 2)
            market_status["twii_ok"]    = _last >= _ma20
    except Exception:
        pass

    twii_ok = market_status.get("twii_ok")
    if twii_ok is True:
        market_warn = 0
        print(f"[大盤] ✅ 加權指數 {market_status['twii_close']} 站上MA20({market_status['twii_ma20']})，正常掃描")
    elif twii_ok is False:
        market_warn = 1
        print(f"[大盤] ⚠️ 加權指數 {market_status['twii_close']} 跌破MA20({market_status['twii_ma20']})，名單A評分 -20")
    else:
        market_warn = 0
        print("[大盤] ❓ 大盤狀態無法確認，不調整評分")

    print(f"[掃描] 共 {total} 支，雙名單：A觀察名單（1~10交易日整理）+ B二波確認（今日再漲停）")

    for i, s in enumerate(stocks):
        try:
            if i % 20 == 0 and i > 0:
                print(f"[進度] {i}/{total}，暫停 3 秒...")
                time.sleep(3)

            if s not in price_cache:
                price_cache[s] = yf.download(s, start=fetch_start, end=fetch_end, progress=False)
            df = price_cache[s]
            if df.empty or len(df) < 20:
                continue

            if isinstance(df.columns, pd.MultiIndex):
                df = df.copy()
                df.columns = df.columns.get_level_values(0)
                price_cache[s] = df

            close  = df['Close'].squeeze()
            volume = df['Volume'].squeeze()
            open_  = df['Open'].squeeze()
            high_  = df['High'].squeeze()

            if not isinstance(close, pd.Series):
                continue

            trading_days = close.index
            n_td         = len(trading_days)

            if n_td < 20:
                continue

            # ── 先建立全資料漲停日清單 ─────────────────────────────
            all_limit_close = []
            for idx in trading_days:
                try:
                    iloc_pos = list(close.index).index(idx)
                    if iloc_pos == 0:
                        continue
                    prev_c      = float(close.iloc[iloc_pos - 1])
                    limit_price = calc_limit_price(prev_c)
                    day_close   = float(close.loc[idx])
                    if day_close >= limit_price * 0.999:
                        all_limit_close.append(idx)
                except Exception:
                    continue

            # ════════════════════════════════════════════════════════
            # 名單A：明日觀察名單（主力名單）
            #   首漲停 → 整理 2~10 天 → 量縮守位 → 今日尚未二波
            # 名單B：二波確認名單（事後確認）
            #   首漲停 → 整理 2~6 天 → 今日再度漲停
            # ════════════════════════════════════════════════════════
            today_idx   = trading_days[-1]
            today_iloc  = n_td - 1
            if today_iloc == 0:
                continue

            today_close = float(close.iloc[today_iloc])   # = 最後交易日收盤
            today_vol   = float(volume.iloc[today_iloc])    # FIX-15：最後交易日量（非 calendar today）

            # ── 今日是否再度漲停（用於名單B判斷）────────────────────
            try:
                prev_c_today       = float(close.iloc[today_iloc - 1])
                limit_price_today  = calc_limit_price(prev_c_today)
                today_is_limit     = today_close >= limit_price_today * 0.999
            except Exception:
                today_is_limit = False

            # ── 找首次漲停 ────────────────────────────────────────────
            # 名單A：首漲停在第 3~12 根前（整理 2~10 天）
            # 名單B：首漲停在第 3~8 根前（整理 2~6 天）
            first_limit_date      = None
            first_limit_iloc      = None
            first_limit_price_val = None
            first_limit_close_val = None

            search_range = range(2, 13)   # BUG-07：從2開始，支援整理1天（週末邊界）
            for offset in search_range:
                candidate_iloc = today_iloc - offset
                if candidate_iloc <= 0:
                    break
                try:
                    prev_c_cand      = float(close.iloc[candidate_iloc - 1])
                    limit_price_cand = calc_limit_price(prev_c_cand)
                    cand_close       = float(close.iloc[candidate_iloc])
                    if cand_close >= limit_price_cand * 0.999:
                        first_limit_date      = trading_days[candidate_iloc]
                        first_limit_iloc      = candidate_iloc
                        first_limit_price_val = limit_price_cand
                        first_limit_close_val = cand_close
                        break
                except Exception:
                    continue

            if first_limit_date is None:
                continue

            # ── 近三個月內首次漲停（63 個交易日）────────────────────
            # 用 iloc 往前找 63 個交易日，不用 calendar DateOffset
            first_limit_iloc_in_all = first_limit_iloc   # 已是 trading_days 的 iloc
            lookback_start_iloc = max(0, first_limit_iloc - 63)
            prior_limits = [d for d in all_limit_close
                            if trading_days[lookback_start_iloc] <= d < first_limit_date]
            if prior_limits:
                continue

            # ── 整理天數（首漲停後到今日前，不含今日）───────────────
            # BUG-07：下限改成 1，週末執行時最後交易日可能整理僅1天
            wash_idxs       = list(range(first_limit_iloc + 1, today_iloc))
            wash_days_count = len(wash_idxs)

            if wash_days_count < 1:
                continue   # 至少整理1天（首漲停當天不算）

            # ── 判斷名單類型 ──────────────────────────────────────────
            is_list_b = today_is_limit and wash_days_count <= 6
            is_list_a = not today_is_limit and wash_days_count <= 10

            if not is_list_a and not is_list_b:
                continue

            # ══════════════════════════════════════════════════════════
            # 共用基礎變數
            # ══════════════════════════════════════════════════════════
            limit_vol      = float(volume.iloc[first_limit_iloc])
            limit_low      = float(df['Low'].iloc[first_limit_iloc])    # BUG-03修正：用最低價
            wash_vols      = [float(volume.iloc[wi]) for wi in wash_idxs]
            wash_closes    = [float(close.iloc[wi]) for wi in wash_idxs]
            wash_highs_day = [float(df['High'].iloc[wi]) for wi in wash_idxs]
            wash_lows_day  = [float(df['Low'].iloc[wi]) for wi in wash_idxs]

            wash_high_close  = max(wash_closes) if wash_closes else today_close
            wash_period_high = max(wash_highs_day) if wash_highs_day else today_close
            wash_period_low  = min(wash_lows_day) if wash_lows_day else limit_low

            ma5   = float(close.rolling(5).mean().iloc[-1])
            ma10  = float(close.rolling(10).mean().iloc[-1])
            ma20  = float(close.rolling(20).mean().iloc[-1])
            above_ma   = today_close > ma20
            ma_bullish = today_close > ma5 > ma10 > ma20

            # FIX-11：整理期破底兩層判斷
            #   第一層：盤中最多容忍跌破 3%（超過代表籌碼鬆動）
            if wash_lows_day and wash_period_low < limit_low * 0.97:
                continue
            #   第二層：整理期每天收盤不能跌破首漲停最低價
            if wash_closes and any(wc < limit_low for wc in wash_closes):
                continue
            if today_close < limit_low:
                continue

            # FIX-03：整理震盪幅度 > 15% 代表主力未控盤，淘汰
            if wash_highs_day and wash_lows_day and limit_low > 0:
                volatility = (wash_period_high - wash_period_low) / limit_low
                if volatility > 0.15:
                    continue

            # FIX-13：流動性濾網（冷門股跳過，隔天進出困難）
            avg20_vol    = float(close.rolling(20).count().iloc[-1])   # placeholder先用count
            try:
                _vol_s  = volume.astype(float)
                _cls_s  = close.astype(float)
                avg20_vol    = float(_vol_s.rolling(20).mean().iloc[-1])
                avg20_amount = float((_cls_s * _vol_s).rolling(20).mean().iloc[-1])
                if avg20_vol < 300_000:
                    continue   # FIX-22：日均量 < 30萬股，流動性不足
                if avg20_amount < 20_000_000:
                    continue   # FIX-22：日均成交額 < 2000萬，流動性不足
            except Exception:
                continue   # FIX-23：資料有問題直接跳過，不讓問題股通過

            # ── 連續縮量（評分用）────────────────────────────────────
            shrink_breaks = sum(
                1 for k in range(len(wash_vols) - 1)
                if wash_vols[k] < wash_vols[k + 1]
            )
            is_continuous_shrink = shrink_breaks <= 1

            # ── 最後交易日量能比 ────────────────────────────────────────────
            today_vol_ratio = today_vol / limit_vol if limit_vol > 0 else 1
            today_vol_heavy = today_vol_ratio >= 0.8   # 今日量 >= 首波80% 視為偏大

            # ══════════════════════════════════════════════════════════
            # 名單A：明日觀察名單 — 尚未二波，等待發動
            # ══════════════════════════════════════════════════════════
            if is_list_a:
                # A1：整理期收盤在漲停價 ±8% 以內（放寬）
                band_lo_a = first_limit_price_val * 0.92
                band_hi_a = first_limit_price_val * 1.08
                if wash_closes and not all(band_lo_a <= wc <= band_hi_a for wc in wash_closes):
                    continue

                # A2：今日收盤距漲停收盤不超過 -12%
                if today_close < first_limit_close_val * 0.88:
                    continue

                # A3：BUG-01修正 — 整理期平均量 < 首波70%（放寬，不逐天卡死）
                #     wash_closes 為空（整理1天且今日就是整理日）時跳過此條
                avg_wash_vol = sum(wash_vols) / len(wash_vols) if wash_vols else 0
                if avg_wash_vol > 0 and avg_wash_vol >= limit_vol * 0.70:
                    continue

                # A4：BUG-03修正 — 整理期收盤不破首漲停日最低價
                if wash_closes and not all(wc >= limit_low for wc in wash_closes):
                    continue
                if today_close < limit_low:
                    continue

                # FIX-10：硬條件只保留站上 MA20
                if not above_ma:
                    continue   # 跌破月線才淘汰
                # MA5 已移出硬條件，改為評分加分項（見 wash_score_notes）

                # A6：整理期間無第二根漲停（確保尚未發動）
                wash_second_limit = False
                for wi in wash_idxs:
                    try:
                        pc = float(close.iloc[wi - 1])
                        lp = calc_limit_price(pc)
                        if float(close.iloc[wi]) >= lp * 0.999:
                            wash_second_limit = True
                            break
                    except Exception:
                        continue
                if wash_second_limit:
                    continue

                # ── 三層分級（名單A）────────────────────────────────
                is_confirmed  = today_close > wash_high_close
                near_breakout = today_close >= wash_high_close * 0.97

                if is_confirmed:
                    tier     = "🟢 靠近突破"
                    tier_key = 1
                elif near_breakout:
                    tier     = "🔴 卡位觀察"
                    tier_key = 2
                else:
                    tier     = "🟡 整理中"
                    tier_key = 3

                list_type      = "A"
                hold_limit_low = today_close >= limit_low

                # NEW-02：觀察名單 A+/A/B 內部分級
                avg_wash_vol_for_grade = sum(wash_vols) / len(wash_vols) if wash_vols else limit_vol
                if (ma_bullish
                        and avg_wash_vol_for_grade < limit_vol * 0.50
                        and industry_stage in ("成長中期", "復甦初期")):
                    list_a_grade = "A+"
                elif (above_ma
                        and avg_wash_vol_for_grade < limit_vol * 0.70):
                    list_a_grade = "A"
                else:
                    list_a_grade = "B"

            # ══════════════════════════════════════════════════════════
            # 名單B：二波確認名單 — 今日再度漲停
            # ══════════════════════════════════════════════════════════
            else:  # is_list_b
                # B1：整理期收盤在漲停價 ±5% 以內
                band_lo_b = first_limit_price_val * 0.95
                band_hi_b = first_limit_price_val * 1.05
                if wash_closes and not all(band_lo_b <= wc <= band_hi_b for wc in wash_closes):
                    continue

                # B2：整理期收盤不破首漲停日最低價
                if wash_closes and not all(wc >= limit_low for wc in wash_closes):
                    continue

                tier       = "🔥 二波確認"
                tier_key   = 0   # 最優先
                list_type  = "B"
                list_a_grade  = "-"
                hold_limit_low = True

            # ── 通過！────────────────────────────────────────────────
            curr_price  = today_close
            curr_vol    = today_vol
            vol_ratio_pct = f"{round((today_vol / limit_vol) * 100)}%" if limit_vol > 0 else "-"
            days_since    = wash_days_count

            code   = s.split('.')[0]
            market = "上市" if s.endswith(".TW") else "上櫃"
            name   = name_map.get(code, "")

            limit_days = pd.DatetimeIndex([first_limit_date, today_idx])

            industry, industry_stage = resolve_industry_stage(code, df, industry_lookup, industry_stage_cache)

            vol_expand      = today_vol >= limit_vol * 0.5
            is_washing      = True
            is_washing_type = tier

            wash_info = {
                "vol_ratio":    vol_ratio_pct,
                "above_ma20":   above_ma,
                "hold_low":     hold_limit_low,
                "washing_type": is_washing_type,
            }

            pattern = analyze_pattern(df, list(limit_days))

            # ── 評分邏輯 ──────────────────────────────────────────────
            wash_score_notes = []

            if list_type == "B":
                pattern['score'] += 35
                wash_score_notes.append("🔥 二波漲停確認發動，最強訊號")
            else:
                # 名單A 三層加分
                if tier_key == 1:
                    pattern['score'] += 25
                    wash_score_notes.append("🟢 最後交易日收盤突破整理高點，明日可能發動")
                elif tier_key == 2:
                    pattern['score'] += 15
                    wash_score_notes.append("🔴 靠近突破位（≥97%），可小量卡位")
                else:
                    wash_score_notes.append("🟡 整理中，等待靠近突破位再動")

            # ── 整理天數加分 ──────────────────────────────────────────
            if wash_days_count <= 1:
                pattern['score'] += 30
                wash_score_notes.append(f"✅ 整理僅 {wash_days_count} 個交易日，超急洗型，主力強力鎖碼")
            elif wash_days_count <= 3:
                pattern['score'] += 25
                wash_score_notes.append(f"✅ 整理 {wash_days_count} 個交易日，急洗急噴型，控盤力強")
            elif wash_days_count <= 5:
                pattern['score'] += 15
                wash_score_notes.append(f"✅ 整理 {wash_days_count} 個交易日，節奏標準")
            else:
                pattern['score'] += 5
                wash_score_notes.append(f"⚠️ 整理 {wash_days_count} 個交易日，熱度略散")

            # ── 連續縮量加分 ──────────────────────────────────────────
            if is_continuous_shrink:
                pattern['score'] += 20
                wash_score_notes.append("✅ 整理期連續縮量（允許1天例外），籌碼高度鎖定")
            else:
                wash_score_notes.append("⚠️ 整理期量能不穩，有出貨嫌疑")

            # ── 最後交易日量能 ──────────────────────────────────────────────
            vol_pct_of_limit = round(today_vol / limit_vol * 100) if limit_vol > 0 else 0
            if not today_vol_heavy:
                pattern['score'] += 10
                wash_score_notes.append(f"✅ 最後交易日縮量（首波 {vol_pct_of_limit}%），無出貨跡象")
            else:
                wash_score_notes.append(f"⚠️ 最後交易日量偏大（首波 {vol_pct_of_limit}%），需觀察是否出貨")

            # ── 整理均價與漲停價偏離度（越貼越強）───────────────────
            avg_wash_close = sum(wash_close_list) / len(wash_close_list)
            deviation_pct  = abs(avg_wash_close - first_limit_price_val) / first_limit_price_val * 100
            if deviation_pct <= 1.5:
                pattern['score'] += 20
                wash_score_notes.append(f"✅ 整理均價緊貼漲停價（偏離 {deviation_pct:.1f}%），主力高度鎖碼")
            elif deviation_pct <= 3.0:
                pattern['score'] += 12
                wash_score_notes.append(f"✅ 整理均價靠近漲停價（偏離 {deviation_pct:.1f}%），鎖碼尚佳")
            else:
                pattern['score'] += 3
                wash_score_notes.append(f"⚠️ 整理均價偏離漲停價 {deviation_pct:.1f}%，整理位置偏低")

            # ── 均線多頭排列（MA5 改為加分項，非硬條件）────────────
            if ma_bullish:
                pattern['score'] += 15
                wash_score_notes.append("✅ 均線完整多頭排列（價>MA5>MA10>MA20），趨勢強")
            elif today_close > ma5:
                pattern['score'] += 8
                wash_score_notes.append("✅ 最後交易日站上MA5，短線偏多")
            elif above_ma:
                pattern['score'] += 3
                wash_score_notes.append("⚠️ 站上月線但低於MA5，整理中")

            pattern['notes'] = wash_score_notes + pattern['notes']

            extra_notes = []

            # A. 首漲停當天量能是否放大（vs 前5日均量）
            try:
                if first_limit_iloc >= 5:
                    avg_vol_5     = float(volume.iloc[first_limit_iloc-5:first_limit_iloc].mean())
                    first_day_vol = float(volume.iloc[first_limit_iloc])
                    if avg_vol_5 > 0 and first_day_vol >= avg_vol_5 * 1.5:
                        pattern['score'] += 15
                        extra_notes.append(f"✅ 首漲停量能放大（是前5日均量 {round(first_day_vol/avg_vol_5, 1)} 倍），主力強力介入")
                    else:
                        extra_notes.append(f"⚠️ 首漲停量能未明顯放大（{round(first_day_vol/avg_vol_5, 1) if avg_vol_5>0 else '-'} 倍）")
            except Exception:
                pass

            # B. 整理期量能是否逐日萎縮（縮量整理最佳）
            try:
                wash_vol_list = [float(volume.iloc[wi]) for wi in wash_idxs]
                if len(wash_vol_list) >= 2:
                    all_shrink_wash = all(
                        wash_vol_list[k] >= wash_vol_list[k+1]
                        for k in range(len(wash_vol_list)-1)
                    )
                    avg_wash_vol = sum(wash_vol_list) / len(wash_vol_list)
                    if all_shrink_wash:
                        pattern['score'] += 15
                        extra_notes.append("✅ 整理期量能逐日遞減，縮量蓄勢明顯")
                    elif avg_wash_vol < limit_vol * 0.6:
                        pattern['score'] += 8
                        extra_notes.append("⚠️ 整理期量能偏小但不規則，籌碼尚穩")
                    else:
                        extra_notes.append("⚠️ 整理期量能偏大，主力控盤力度有限")
            except Exception:
                pass

            try:
                year_high = float(close.rolling(min(252, len(close))).max().iloc[-1])
                year_low  = float(close.rolling(min(252, len(close))).min().iloc[-1])
                price_range = year_high - year_low
                if price_range > 0:
                    position = (curr_price - year_low) / price_range
                    if position <= 0.4:
                        pattern['score'] += 15
                        extra_notes.append(f"✅ 股價位於近一年低檔區（位置 {round(position*100)}%），低風險啟動")
                    elif position <= 0.7:
                        pattern['score'] += 5
                        extra_notes.append(f"⚠️ 股價位於近一年中段區（位置 {round(position*100)}%）")
                    else:
                        extra_notes.append(f"❌ 股價位於近一年高檔區（位置 {round(position*100)}%），追高風險高")
            except Exception:
                pass

            try:
                ma60_series = close.rolling(60).mean()
                if len(ma60_series.dropna()) >= 10:
                    ma60_slope = float(ma60_series.iloc[-1]) - float(ma60_series.iloc[-10])
                    if ma60_slope > 0:
                        pattern['score'] += 15
                        extra_notes.append(f"✅ 季線（MA60）向上走勢，趨勢背景良好")
                    elif ma60_slope > -1:
                        extra_notes.append("⚠️ 季線（MA60）走平，趨勢中性")
                    else:
                        pattern['score'] -= 10
                        extra_notes.append("❌ 季線（MA60）向下，趨勢偏弱")
            except Exception:
                pass

            try:
                ma240 = close.rolling(240).mean()
                ma240_today = float(ma240.iloc[-1])
                if not pd.isna(ma240_today):
                    if curr_price > ma240_today:
                        pattern['score'] += 20
                        extra_notes.append(f"✅ 股價站上年線（MA240={ma240_today:.1f}），長線趨勢向上")
                    else:
                        pattern['score'] -= 15
                        extra_notes.append(f"❌ 股價跌破年線（MA240={ma240_today:.1f}），長線趨勢偏弱，風險高")
            except Exception:
                pass

            try:
                ma60 = close.rolling(60).mean()
                ma60_before  = float(ma60.iloc[first_limit_iloc - 1]) if first_limit_iloc >= 1 else None
                ma60_at      = float(ma60.iloc[first_limit_iloc])
                close_before = float(close.iloc[first_limit_iloc - 1]) if first_limit_iloc >= 1 else None
                close_at     = float(close.iloc[first_limit_iloc])
                if ma60_before and close_before:
                    if close_before < ma60_before and close_at >= ma60_at:
                        pattern['score'] += 20
                        extra_notes.append(f"✅ 首漲停日突破季線（MA60={ma60_at:.1f}），強力突破壓力")
                    elif close_before >= ma60_before:
                        pattern['score'] += 8
                        extra_notes.append(f"⚠️ 首漲停前已在季線之上（MA60={ma60_at:.1f}），非突破型態")
                    else:
                        extra_notes.append(f"❌ 首漲停日未能突破季線（MA60={ma60_at:.1f}），壓力未解除")
            except Exception:
                pass

            pattern['notes'] = extra_notes + pattern['notes']

            stage_bonus = {"復甦初期": 20, "成長中期": 10, "盤整過渡": 0, "高檔過熱": -10, "高檔成熟": -10, "衰退期": -10, "樣本不足": 0, "未知": 0}.get(industry_stage, 0)
            if stage_bonus != 0:
                pattern['score'] += stage_bonus
                stage_emoji = "✅" if stage_bonus > 0 else "❌"
                pattern['notes'].insert(0, f"{stage_emoji} 產業位階：{industry_stage}（{'+' if stage_bonus>0 else ''}{stage_bonus} 分）")

            ps = pattern['score']

            # NEW-01：大盤濾網加減分
            market_adj = {0: 0, 1: -20, 2: -40}.get(market_warn, 0)
            if list_type == "A" and market_adj != 0:
                pattern['score'] += market_adj
                pattern['notes'].insert(0,
                    f"{'⚠️' if market_warn==1 else '❌'} 大盤{'一指數' if market_warn==1 else '雙指數'}跌破MA20（評分{market_adj}分）")

            ps = pattern['score']
            pattern['grade'] = "🔥🔥 極強" if ps >= 140 else "🔥 強" if ps >= 100 else "⚠️ 普通" if ps >= 60 else "❌ 弱"

            # ── 整理區間參考價 ───────────────────────────────────────
            wash_high = wash_period_high
            wash_low  = wash_period_low
            breakout_str = tier

            try:
                kd_series = []
                prev_k2, prev_d2 = 50.0, 50.0
                for j in range(len(close)):
                    if j < 8:
                        kd_series.append((None, None))
                        continue
                    hh = float(df['High'].iloc[j-8:j+1].max())
                    ll = float(df['Low'].iloc[j-8:j+1].min())
                    rsv = ((float(close.iloc[j]) - ll) / (hh - ll) * 100) if hh != ll else 50.0
                    k2  = prev_k2 * 2/3 + rsv * 1/3
                    d2  = prev_d2 * 2/3 + k2  * 1/3
                    kd_series.append((round(k2, 1), round(d2, 1)))
                    prev_k2, prev_d2 = k2, d2
                if len(kd_series) >= 2:
                    pk, pd_v = kd_series[-2]
                    ck, cd   = kd_series[-1]
                    kd_golden = (pk is not None and pd_v is not None and
                                 ck is not None and cd  is not None and
                                 pk <= pd_v and ck > cd)
                else:
                    kd_golden = False
            except Exception:
                kd_golden = False

            # ── 隔日策略：二波漲停後建議等回測，勿追漲停 ────────────
            stop_loss_ref = round(wash_low, 2) if wash_low else "-"
            entry_ref     = round(wash_high, 2) if wash_high else "-"

            if isinstance(entry_ref, (int, float)) and isinstance(stop_loss_ref, (int, float)):
                risk         = entry_ref - stop_loss_ref
                risk_pct     = risk / entry_ref if entry_ref > 0 else None
                target_price = round(entry_ref + risk * 2, 2) if risk > 0 else "-"
            else:
                risk         = None
                risk_pct     = None
                target_price = "-"

            # ── NEW-03：雙停損 ──────────────────────────────────────
            stop_loss_aggressive = round(wash_period_low, 2) if wash_period_low else "-"  # 積極：整理低點
            stop_loss_defensive  = round(limit_low, 2) if limit_low else "-"              # 防守：首漲停最低價

            # ── NEW-04：隔日掛單策略 ─────────────────────────────────
            today_vs_high = today_close / wash_high_close if wash_high_close else 1
            # FIX-14：量警示區分「量大未突破（出貨疑慮）」vs「放量突破（可觀察）」
            if today_vol_ratio > 0.9 and today_close < wash_high_close:
                vol_warning = "⚠️ 量大未突破，注意出貨 "
            elif today_vol_ratio > 0.9 and today_close >= wash_high_close:
                vol_warning = "📈 放量突破，觀察是否續強 "
            else:
                vol_warning = ""

            if list_type == "B":
                order_type    = "二波確認"
                order_display = round(wash_high_close, 2) if wash_high_close else entry_ref
                order_note    = f"{vol_warning}最後交易日二波漲停；明日勿追，等回測整理高點不破再進場"
            elif tier_key == 1:   # 靠近突破
                order_type    = "突破掛單"
                order_display = round(wash_high_close * 1.005, 2) if wash_high_close else entry_ref
                if today_vs_high >= 0.97:
                    order_note = f"{vol_warning}平盤±1% 可試單，量縮優先；開太高不追"
                else:
                    order_note = f"{vol_warning}等開盤站上整理高點再追，勿搶進"
            elif tier_key == 2:   # 卡位觀察
                order_type    = "卡位試單"
                order_display = round(wash_high_close * 1.005, 2) if wash_high_close else entry_ref
                order_note    = f"{vol_warning}靠近突破位；可小量卡位，突破確認後加碼"
            else:                 # 整理中
                order_type    = "持續觀察"
                order_display = round(wash_high_close * 1.005, 2) if wash_high_close else entry_ref
                order_note    = f"{vol_warning}整理中，若開盤跌破整理低點直接放棄"

            if kd_golden:
                order_note += "｜KD黃金交叉共振"

            dates = [d.strftime('%m/%d') for d in limit_days]
            stage_color = '#26a641' if industry_stage in ['復甦初期', '成長中期'] else '#f85149' if industry_stage == '衰退期' else '#ffa500'

            # 回測開關（RUN_BACKTEST=False 時跳過，大幅加速）
            if RUN_BACKTEST:
                bt = backtest_strategy(df)
            else:
                bt = {"samples": 0, "win_5": None, "avg_5": None,
                      "win_10": None, "avg_10": None, "mdd_10": None,
                      "win_20": None, "avg_20": None}
            bt_samples = bt.get("samples", 0)

            chart_file = os.path.join(output_dir, f"{code}.html")
            chart_link = f"{base_url}/{code}.html"
            with open(chart_file, "w", encoding="utf-8") as f:
                f.write(generate_chart_html(
                    s, name, df, list(limit_days),
                    is_washing, wash_info, pattern,
                    wash_low_val=wash_low if wash_low else 0,
                    target_val=target_price if isinstance(target_price, (int, float)) else 0,
                    entry_val=entry_ref if isinstance(entry_ref, (int, float)) else 0,
                    industry=industry,
                    industry_stage=industry_stage
                ))

            results.append({
                "_score":    pattern['score'],
                "_tier_key": tier_key,
                "_vol_num":  float(vol_ratio_pct.rstrip('%')) if vol_ratio_pct != '-' else 0,
                "代碼": (
                    f"<a href='{chart_link}' target='_blank' "
                    f"style='color:#58a6ff;font-weight:700;text-decoration:none'>"
                    f"{code} 📊</a>"
                ),
                "名稱":       name,
                "市場":       market,
                "名單":       "🔥二波確認" if list_type=="B" else "📋觀察名單",
                "分級":       list_a_grade,
                "產業":       industry,
                "產業位階":    f"<span style='color:{stage_color}'>{industry_stage}</span>",
                "型態評分":    f"<span style='color:{'#26a641' if pattern['score']>=140 else '#ffa500' if pattern['score']>=100 else '#f85149'};font-weight:700'>{pattern['score']} {pattern['grade']}</span>",
                "狀態分層":    breakout_str,
                "整理(交易日)": days_since,
                "今日量/首波":  vol_ratio_pct,
                "收盤價":     round(curr_price, 2),
                "首漲停板":    pattern['limit_quality'],
                "漲停軌跡":    " / ".join(dates),
                "隔日策略":    order_type,
                "進場參考價":  order_display,
                "積極停損":    stop_loss_aggressive,
                "防守停損":    stop_loss_defensive,
                "2R目標價":   target_price,
                "單筆風險":    _fmt_pct(risk_pct),
                "執行備註":    order_note,
                "回測樣本":    f"⚠️樣本不足({bt_samples})" if bt_samples < 10 else bt_samples,
                "5日勝率":     _fmt_pct(bt.get("win_5")),
                "10日勝率":    _fmt_pct(bt.get("win_10")),
                "10日均報酬":  _fmt_pct(bt.get("avg_10")),
                "10日最大回撤": _fmt_pct(bt.get("mdd_10")),
                "20日勝率":    _fmt_pct(bt.get("win_20")),
            })

        except Exception as e:
            print(f"[{s}] 錯誤：{e}")
            continue

    print(f"[完成] 掃描 {total} 支，符合條件共 {len(results)} 支")
    return pd.DataFrame(results), market_status  # BUG-09：帶回 market_status 供 to_html 使用


# ── 輸出主報表 HTML ──────────────────────────────────────────
def to_html(df, output_file="index.html", market_status=None):
    # BUG-09：market_status 從 scan() 傳入，不再讀取區域變數
    if market_status is None:
        market_status = {}
    t = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

    if not df.empty:
        sort_cols = ['_tier_key', '_score', '_vol_num']
        sort_asc  = [True, False, True]
        drop_cols = ['_score', '_tier_key', '_vol_num']

        df_fire   = df[df['狀態分層'].str.startswith('🔥')].sort_values(sort_cols, ascending=sort_asc).drop(columns=drop_cols)
        df_green  = df[df['狀態分層'].str.startswith('🟢')].sort_values(sort_cols, ascending=sort_asc).drop(columns=drop_cols)
        df_red    = df[df['狀態分層'].str.startswith('🔴')].sort_values(sort_cols, ascending=sort_asc).drop(columns=drop_cols)
        df_yellow = df[df['狀態分層'].str.startswith('🟡')].sort_values(sort_cols, ascending=sort_asc).drop(columns=drop_cols)

        def tbl(d): return d.to_html(index=False, escape=False) if not d.empty else "<p style='color:var(--muted);padding:12px'>目前無符合標的</p>"

        table_html = (
            "<h2 style='color:#d93025;font-size:1.1rem;margin:20px 0 10px'>"
            "🔥 二波確認名單（今日再度漲停，明日回測不破進場）</h2>" + tbl(df_fire) +
            "<h2 style='color:#26a641;font-size:1.1rem;margin:28px 0 10px'>"
            "🟢 靠近突破（整理高點附近，明日可突破掛單）</h2>" + tbl(df_green) +
            "<h2 style='color:#ffa500;font-size:1.1rem;margin:28px 0 10px'>"
            "🔴 卡位觀察（量縮守位，靠近 97% 可試單）</h2>" + tbl(df_red) +
            "<h2 style='color:#8b949e;font-size:1.1rem;margin:28px 0 10px'>"
            "🟡 整理中（等待靠近突破位再動）</h2>" + tbl(df_yellow)
        )
        count_info = (
            f"<p class='count'>"
            f"本次掃描共 <strong style='color:#d93025'>{len(df)}</strong> 支符合條件｜"
            f"<strong style='color:#d93025'>🔥 二波確認 {len(df_fire)} 支</strong>・"
            f"<strong style='color:#26a641'>🟢 靠近突破 {len(df_green)} 支</strong>・"
            f"<strong style='color:#ffa500'>🔴 卡位 {len(df_red)} 支</strong>・"
            f"<strong style='color:#8b949e'>🟡 整理 {len(df_yellow)} 支</strong>"
            f"&nbsp;｜&nbsp; 點擊代碼查看 K 線圖</p>"
        )
    else:
        table_html = "<div class='empty'>⚠️ 目前無符合條件標的</div>"
        count_info = ""

    # 大盤狀態 HTML
    def _mkt_badge(ok, label, close_val, ma20_val):
        if ok is None:
            return f"<span style='color:#8b949e'>{label} ❓</span>"
        color = "#26a641" if ok else "#f85149"
        icon  = "✅" if ok else "❌"
        return (f"<span style='color:{color}'>{icon} {label} "
                f"{close_val}（MA20:{ma20_val}）</span>")

    twii_badge = _mkt_badge(market_status.get("twii_ok"),
                            "加權", market_status.get("twii_close","?"),
                            market_status.get("twii_ma20","?"))
    # BUG-08：移除 tpex_badge（^TPEX 抓不到）
    # BUG-09：market_warn 從傳入的 market_status 推導
    _twii_ok = market_status.get("twii_ok")
    market_warn = 1 if _twii_ok is False else 0
    mkt_warn_color = "#26a641" if market_warn == 0 else "#ffa500"
    mkt_warn_text  = "✅ 大盤多頭，正常操作" if market_warn == 0 else "⚠️ 加權指數跌破MA20，降低部位"

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>漲停洗盤起飛偵測</title>
  <style>
    :root{{--bg:#0d1117;--panel:#161b22;--border:#30363d;
          --text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--fire:#d93025;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{background:var(--bg);color:var(--text);
         font-family:'SF Mono','Fira Code',monospace;padding:32px 24px;}}
    h1{{font-size:1.6rem;margin-bottom:6px;}}
    h1 span{{color:var(--accent);}}
    .meta{{color:var(--muted);font-size:.78rem;margin-bottom:14px;}}
    .count{{color:var(--muted);font-size:.82rem;margin-bottom:16px;}}
    .hint{{background:var(--panel);border:1px solid var(--border);border-radius:8px;
           padding:16px 20px;margin-bottom:20px;font-size:.8rem;line-height:2;color:var(--muted);}}
    .hint b{{color:var(--text);}}
    table{{width:100%;border-collapse:collapse;background:var(--panel);
           border:1px solid var(--border);border-radius:8px;overflow:hidden;}}
    th{{background:#1c2128;color:var(--muted);font-size:.68rem;
        text-transform:uppercase;letter-spacing:.06em;
        padding:12px 16px;text-align:center;border-bottom:1px solid var(--border);}}
    td{{padding:12px 16px;text-align:center;
        border-bottom:1px solid var(--border);font-size:.88rem;}}
    tr:last-child td{{border-bottom:none;}}
    tr:hover td{{background:#1c2128;}}
    .empty{{padding:40px;text-align:center;color:var(--muted);}}
  </style>
</head>
<body>
  <h1>🚀 漲停縮量 <span>洗盤起飛</span> 偵測系統</h1>
  <p class="meta">台北時間：{t}　｜　選股區間：1~10 個交易日整理</p>
  <div style="background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:10px 18px;margin-bottom:14px;font-size:.82rem;display:flex;gap:24px;flex-wrap:wrap;align-items:center;">
    <span style="color:{mkt_warn_color};font-weight:700">{mkt_warn_text}</span>
    {twii_badge}
  </div>
  {count_info}
  <div class="hint">
    <b>💡 選股邏輯（兩張名單）</b><br>
    📋 <b>觀察名單</b>：首漲停後整理 1~10 個交易日，收盤在漲停價 ±8% 內，整理均量 &lt; 首波70%，守住漲停日最低價，尚未二波（MA5 為加分項）<br>
    🔥 <b>二波確認</b>：首漲停後整理 1~6 個交易日，收盤在漲停價 ±5% 內，最後交易日再度漲停（事後確認）<br>
    四層輸出：🔥 二波確認 ／ 🟢 靠近突破 ／ 🔴 卡位觀察 ／ 🟡 整理中<br>
    分級：A+ 量縮嚴格＋多頭排列＋成長產業 ／ A 量縮守位 ／ B 基本通過<br>
    雙停損：積極停損=整理低點 ／ 防守停損=首漲停最低價<br>
    ⚡ 操作：🔥回測不破進 ／ 🟢突破掛單 ／ 🔴卡位試單 ／ 🟡繼續等
  </div>
  {table_html}
</body>
</html>"""

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[輸出] {output_file} 已產生")


# ── 入口 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    df, market_status = scan(output_dir="charts", base_url="./charts")
    to_html(df, output_file="index.html", market_status=market_status)
