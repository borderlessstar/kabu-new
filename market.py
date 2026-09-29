# -*- coding: utf-8 -*-
"""
市場の数字を毎日自動で取得して、Claudeが読みやすい表にまとめるスクリプト。
- 株価指数・為替・金利・商品・VIX・業種別の値動き → data/market.md
- data/candidates.csv に記録した候補の「その後の成績」 → data/candidates_perf.md
ニュースではなく数字だけを扱う（解釈はClaudeが行う）。
※ これは情報整理ツールであり、投資助言ではありません。
"""

import csv
import datetime
import io
import os
import urllib.request

import pandas as pd
import yfinance as yf

# ==========================================================
#  ここだけ編集すればOK（行を足す・消すだけ）
# ==========================================================

GROUPS = [
    ("株価指数", [
        ("日経平均", "^N225"),
        ("TOPIX（連動ETF 1306）", "1306.T"),
        ("東証グロース250（連動ETF 2516）", "2516.T"),
        ("S&P500", "^GSPC"),
        ("ナスダック総合", "^IXIC"),
        ("NYダウ", "^DJI"),
        ("ユーロ・ストックス50", "^STOXX50E"),
        ("上海総合", "000001.SS"),
        ("香港ハンセン", "^HSI"),
    ]),
    ("為替", [
        ("ドル円", "JPY=X"),
        ("ユーロ円", "EURJPY=X"),
        ("ユーロドル", "EURUSD=X"),
    ]),
    ("金利", [
        ("米10年国債利回り（%）", "^TNX"),
    ]),
    ("商品", [
        ("WTI原油（ドル）", "CL=F"),
        ("金（ドル）", "GC=F"),
        ("銅（ドル）", "HG=F"),
    ]),
    ("恐怖指数", [
        ("VIX", "^VIX"),
    ]),
]

# 日本の業種（TOPIX-17業種のETF）
JP_SECTORS = [
    ("食品", "1617.T"), ("エネルギー資源", "1618.T"), ("建設・資材", "1619.T"),
    ("素材・化学", "1620.T"), ("医薬品", "1621.T"), ("自動車・輸送機", "1622.T"),
    ("鉄鋼・非鉄", "1623.T"), ("機械", "1624.T"), ("電機・精密", "1625.T"),
    ("情報通信・サービス", "1626.T"), ("電力・ガス", "1627.T"), ("運輸・物流", "1628.T"),
    ("商社・卸売", "1629.T"), ("小売", "1630.T"), ("銀行", "1631.T"),
    ("金融（除く銀行）", "1632.T"), ("不動産", "1633.T"),
]

# 米国の業種（S&P500のセクターETF）
US_SECTORS = [
    ("情報技術", "XLK"), ("通信", "XLC"), ("一般消費財", "XLY"), ("生活必需品", "XLP"),
    ("エネルギー", "XLE"), ("金融", "XLF"), ("ヘルスケア", "XLV"), ("資本財", "XLI"),
    ("素材", "XLB"), ("不動産", "XLRE"), ("公益", "XLU"),
]

# 利回り・指数ポイントなど、「％」ではなく「差」で見るもの
LEVEL_DIFF = {"^TNX", "^VIX"}

# 過熱感を計算する指数（移動平均からの乖離）
TREND_TARGETS = [("日経平均", "^N225"), ("S&P500", "^GSPC")]

# 候補の成績を比べる基準（日本の銘柄はTOPIX、それ以外はS&P500）
BENCH_JP = "1306.T"
BENCH_US = "^GSPC"

# ==========================================================
#  ここから下は基本さわらなくてOK
# ==========================================================

JST = datetime.timezone(datetime.timedelta(hours=9))
DATA_DIR = "data"
MARKET_PATH = os.path.join(DATA_DIR, "market.md")
CAND_PATH = os.path.join(DATA_DIR, "candidates.csv")
PERF_PATH = os.path.join(DATA_DIR, "candidates_perf.md")
MOF_CUR = "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"
MOF_ALL = "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv"


def download(tickers, start=None, period="1y"):
    """終値（配当込み調整後）を {ティッカー: Series} で返す。取れなかったものは入らない。"""
    tickers = sorted(set(tickers))
    out = {}
    try:
        kw = {"start": start} if start else {"period": period}
        df = yf.download(tickers, interval="1d", auto_adjust=True, progress=False,
                         group_by="ticker", threads=True, **kw)
        for t in tickers:
            try:
                s = df[t]["Close"] if len(tickers) > 1 else df["Close"]
                if isinstance(s, pd.DataFrame):
                    s = s.iloc[:, 0]
                s = s.dropna()
                if len(s):
                    out[t] = s
            except Exception:
                pass
    except Exception as e:
        print("まとめ取得に失敗:", e)
    # 取れなかったものは1つずつ再挑戦
    for t in tickers:
        if t in out:
            continue
        try:
            kw = {"start": start} if start else {"period": period}
            s = yf.Ticker(t).history(interval="1d", auto_adjust=True, **kw)["Close"].dropna()
            if len(s):
                out[t] = s
        except Exception as e:
            print(f"{t} の取得に失敗:", e)
    # 日本の銘柄は、その日の終値が日足に反映されるのが翌日になることがあるため、
    # Yahooの「現在値（取引終了後は確定した終値）」で補う
    # （取引時間が決まっている日本の銘柄だけ。為替・先物は24時間動くので対象外）
    topped = []
    for t, s in list(out.items()):
        if not (t.endswith(".T") or t == "^N225"):
            continue
        try:
            tk = yf.Ticker(t)
            tk.history(period="5d", interval="1d")
            meta = tk.history_metadata or {}
            price, ts = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
            if not price or not ts:
                continue
            local = datetime.datetime.fromtimestamp(int(ts), JST)
            now = datetime.datetime.now(JST)
            if local.date() == now.date() and (local.hour, local.minute) < (15, 25):
                continue  # 取引時間中の値は使わない（確定した終値だけを使う）
            day = pd.Timestamp(local.date())
            if s.index.tz is not None:
                day = day.tz_localize(s.index.tz)
            if day > s.index[-1]:
                out[t] = pd.concat([s, pd.Series([float(price)], index=[day])])
                topped.append(t)
        except Exception as e:
            print(f"{t} の当日値の補完に失敗:", e)
    if topped:
        print("当日の終値を補完:", ", ".join(topped))
    return out


def change(s, n, diff=False):
    if len(s) <= n:
        return None
    a, b = float(s.iloc[-1]), float(s.iloc[-1 - n])
    if diff:
        return a - b
    return (a / b - 1) * 100 if b else None


def fmt_chg(v, diff=False):
    if v is None:
        return "—"
    return f"{v:+.2f}" if diff else f"{v:+.1f}%"


def fmt_price(v):
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 10:
        return f"{v:,.2f}"
    return f"{v:,.4f}"


def jgb10():
    """財務省の国債金利CSVから日本10年国債利回りを取る。(日付, 最新値, 前日値)"""
    def read(url):
        with urllib.request.urlopen(url, timeout=30) as r:
            text = r.read().decode("cp932", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
        hi = next(i for i, r in enumerate(rows) if r and r[0].strip() == "基準日")
        col = rows[hi].index("10年")
        data = []
        for r in rows[hi + 1:]:
            if len(r) > col and r[0].strip() and r[col].strip() not in ("", "-"):
                try:
                    data.append((r[0].strip(), float(r[col])))
                except ValueError:
                    pass
        return data
    try:
        data = read(MOF_CUR)
        if len(data) < 2:
            data = read(MOF_ALL)[-2:] + data
            data = data[-2:]
        if not data:
            return None
        prev = data[-2][1] if len(data) >= 2 else None
        d = data[-1][0]
        try:  # 「R8.9.29」（令和）→「09/29」
            _, m, dd = d.split(".")
            d = f"{int(m):02d}/{int(dd):02d}"
        except ValueError:
            pass
        return d, data[-1][1], prev
    except Exception as e:
        print("日本国債利回りの取得に失敗:", e)
        return None


def table_rows(items, prices):
    rows = []
    for name, t in items:
        s = prices.get(t)
        if s is None or not len(s):
            rows.append(f"| {name} | 取得失敗 | — | — | — | — | — |")
            continue
        d = t in LEVEL_DIFF
        rows.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            name, fmt_price(float(s.iloc[-1])),
            fmt_chg(change(s, 1, d), d), fmt_chg(change(s, 5, d), d),
            fmt_chg(change(s, 21, d), d), fmt_chg(change(s, 63, d), d),
            s.index[-1].strftime("%m/%d")))
    return rows


def sector_rows(items, prices):
    data = []
    for name, t in items:
        s = prices.get(t)
        if s is None or len(s) < 64:
            continue
        data.append((name, change(s, 5), change(s, 21), change(s, 63), s.index[-1].strftime("%m/%d")))
    data.sort(key=lambda x: (x[2] is None, -(x[2] or 0)))  # 1か月の強い順
    return [f"| {n} | {fmt_chg(w)} | {fmt_chg(m)} | {fmt_chg(q)} | {d} |" for n, w, m, q, d in data]


def trend_lines(prices):
    out = []
    for name, t in TREND_TARGETS:
        s = prices.get(t)
        if s is None or len(s) < 200:
            continue
        last = float(s.iloc[-1])
        ma25 = float(s.iloc[-25:].mean())
        ma200 = float(s.iloc[-200:].mean())
        hi = float(s.iloc[-250:].max())
        out.append(
            f"- {name}：25日移動平均からの乖離 {((last / ma25) - 1) * 100:+.1f}% ／ "
            f"200日移動平均の{'上' if last >= ma200 else '下'}（乖離 {((last / ma200) - 1) * 100:+.1f}%）／ "
            f"1年高値から {((last / hi) - 1) * 100:+.1f}%")
    return out


def write_market(today, prices):
    L = [f"# 📊 市場データ（{today} 取得）", "",
         "> 自動取得した数字のみ。解釈はしていません。「基準日」はその数字がいつの終値かを示します。",
         "> 前日比・1週・1か月・3か月は営業日ベース（1週=5日、1か月=21日、3か月=63日）。利回りとVIXは「％」ではなく「差」。",
         ""]
    for title, items in GROUPS:
        L += [f"## {title}", "", "| 名前 | 最新 | 前日比 | 1週 | 1か月 | 3か月 | 基準日 |",
              "|---|---|---|---|---|---|---|"]
        L += table_rows(items, prices)
        if title == "金利":
            j = jgb10()
            if j:
                d, v, p = j
                L.append(f"| 日本10年国債利回り（%） | {v:.3f} | {fmt_chg(v - p if p is not None else None, True)} | — | — | — | {d} |")
            else:
                L.append("| 日本10年国債利回り（%） | 取得失敗 | — | — | — | — | — |")
        L.append("")
    L += ["## 過熱感の目安（移動平均からの距離）", ""]
    L += trend_lines(prices) or ["- 取得失敗"]
    L += ["", "> 目安：25日移動平均から+5%以上は短期的な過熱、-5%以下は売られすぎと見られることが多い。", ""]
    L += ["## 日本の業種別（1か月の強い順）", "", "| 業種 | 1週 | 1か月 | 3か月 | 基準日 |", "|---|---|---|---|---|"]
    L += sector_rows(JP_SECTORS, prices) or ["| 取得失敗 | — | — | — | — |"]
    L += ["", "## 米国の業種別（1か月の強い順）", "", "| 業種 | 1週 | 1か月 | 3か月 | 基準日 |", "|---|---|---|---|---|"]
    L += sector_rows(US_SECTORS, prices) or ["| 取得失敗 | — | — | — | — |"]
    L.append("")
    with open(MARKET_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def price_on(s, date_str):
    """記録日当日かそれ以前の、いちばん近い終値"""
    d = pd.Timestamp(date_str)
    idx = s.index.tz_localize(None) if s.index.tz is not None else s.index
    s2 = pd.Series(s.values, index=idx)
    before = s2[s2.index <= d + pd.Timedelta(hours=23)]
    return float(before.iloc[-1]) if len(before) else None


def write_perf(today):
    if not os.path.exists(CAND_PATH):
        return
    with open(CAND_PATH, newline="", encoding="utf-8") as f:
        cands = [r for r in csv.DictReader(f) if r.get("ティッカー", "").strip()]
    if not cands:
        return
    start = min(r["記録日"] for r in cands)
    start = (pd.Timestamp(start) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    tickers = {r["ティッカー"].strip() for r in cands} | {BENCH_JP, BENCH_US}
    prices = download(tickers, start=start)
    L = [f"# 🧾 候補のその後（{today} 更新）", "",
         "> 記録日の終値（配当込み）からの騰落率と、同じ期間の基準（日本株=TOPIX連動ETF、それ以外=S&P500）との差。",
         "> 投資信託は、同じ指数に連動する東証ETFを参考ティッカーとして使っている。", "",
         "| 記録日 | 名前 | 騰落率 | 基準 | 差 | 経過日数 | 出どころ |", "|---|---|---|---|---|---|---|"]
    for r in sorted(cands, key=lambda x: x["記録日"], reverse=True):
        t = r["ティッカー"].strip()
        bench = BENCH_JP if t.endswith(".T") else BENCH_US
        s, b = prices.get(t), prices.get(bench)
        ret = bret = None
        if s is not None and len(s):
            p0 = price_on(s, r["記録日"])
            if p0:
                ret = (float(s.iloc[-1]) / p0 - 1) * 100
        if b is not None and len(b):
            b0 = price_on(b, r["記録日"])
            if b0:
                bret = (float(b.iloc[-1]) / b0 - 1) * 100
        days = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(r["記録日"])).days
        diff = (ret - bret) if (ret is not None and bret is not None) else None
        L.append(f"| {r['記録日']} | {r['名前']}（{t}） | {fmt_chg(ret)} | {fmt_chg(bret)} | {fmt_chg(diff)} | {days}日 | {r.get('出どころ', '')} |")
    L.append("")
    with open(PERF_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    today = datetime.datetime.now(JST).strftime("%Y-%m-%d")
    tickers = [t for _, items in GROUPS for _, t in items] + \
              [t for _, t in JP_SECTORS] + [t for _, t in US_SECTORS]
    prices = download(tickers, period="15mo")
    print(f"{len(prices)}/{len(set(tickers))} 銘柄の価格を取得")
    write_market(today, prices)
    try:
        write_perf(today)
    except Exception as e:
        print("候補の成績計算に失敗:", e)


if __name__ == "__main__":
    main()


def _debug():
    lines = []
    for t in ["^N225", "1306.T", "8306.T"]:
        try:
            tk = yf.Ticker(t)
            d = tk.history(period="5d", interval="1d")
            lines.append(f"{t} daily: " + ", ".join(f"{i}={v:.2f}" for i, v in d["Close"].items()))
            m = tk.history_metadata or {}
            lines.append(f"{t} meta: price={m.get('regularMarketPrice')} time={m.get('regularMarketTime')} "
                         f"({datetime.datetime.fromtimestamp(int(m.get('regularMarketTime') or 0), JST)}) prev={m.get('chartPreviousClose')}")
            i = tk.history(period="2d", interval="5m")["Close"].dropna()
            lines.append(f"{t} 5m last: {i.index[-3:].tolist()} {i.iloc[-3:].tolist()}")
        except Exception as e:
            lines.append(f"{t} error: {e}")
    with open(os.path.join(DATA_DIR, "_debug.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    _debug()
