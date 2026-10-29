# -*- coding: utf-8 -*-
"""
IMF（国際通貨基金）の経済見通し（World Economic Outlook）の数字を自動で取得して、
Claudeが読みやすい表にまとめるスクリプト。
- IMF DataMapper API（無料・登録不要）から、成長率・物価・失業率などの予測値を取る
- IMFが見通しを改定したら、前の版の数字と並べて「上方修正／下方修正」が分かるようにする
- 結果は data/imf.md（読む用）、data/imf_snapshot.csv と data/imf_prev.csv（比較用）
ニュースではなく数字だけを扱う（解釈はClaudeが行う）。
※ これは情報整理ツールであり、投資助言ではありません。
"""

import csv
import datetime
import json
import os
import urllib.request

# ==========================================================
#  ここだけ編集すればOK（行を足す・消すだけ）
# ==========================================================

# 追う指標（IMF DataMapper の指標コード, 表示名, 単位）
INDICATORS = [
    ("NGDP_RPCH", "実質GDP成長率", "%"),
    ("PCPIPCH", "物価上昇率（消費者物価）", "%"),
    ("LUR", "失業率", "%"),
    ("BCA_NGDPD", "経常収支（GDP比）", "%"),
    ("GGXWDG_NGDP", "政府債務（GDP比）", "%"),
]

# 追う国・地域（IMF DataMapper のコード, 表示名）
AREAS = [
    ("WEOWORLD", "世界"),
    ("ADVEC", "先進国"),
    ("OEMDC", "新興国・途上国"),
    ("JPN", "日本"),
    ("USA", "米国"),
    ("EURO", "ユーロ圏"),
    ("CHN", "中国"),
    ("IND", "インド"),
]

# ==========================================================
#  ここから下は基本さわらなくてOK
# ==========================================================

BASE = "https://www.imf.org/external/datamapper/api/v1"
JST = datetime.timezone(datetime.timedelta(hours=9))
DATA_DIR = "data"
MD_PATH = os.path.join(DATA_DIR, "imf.md")
SNAP_PATH = os.path.join(DATA_DIR, "imf_snapshot.csv")
PREV_PATH = os.path.join(DATA_DIR, "imf_prev.csv")
FIELDS = ["indicator", "area", "year", "value", "version", "fetched"]
UA = {"User-Agent": "Mozilla/5.0 (kabu-new imf collector)"}


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_version():
    """WEOの版の名前（例: World Economic Outlook (October 2026)）を取る"""
    try:
        meta = get_json(f"{BASE}/indicators").get("indicators", {})
        return (meta.get(INDICATORS[0][0], {}) or {}).get("source", "") or ""
    except Exception as e:
        print(f"版の取得に失敗: {e}")
        return ""


def fetch_values(years):
    """{(指標, 地域, 年): 値} を返す"""
    out = {}
    areas = "/".join(code for code, _ in AREAS)
    periods = ",".join(str(y) for y in years)
    for code, label, _ in INDICATORS:
        try:
            data = get_json(f"{BASE}/{code}/{areas}?periods={periods}")
        except Exception as e:
            print(f"取得失敗 {label}: {e}")
            continue
        for area, series in (data.get("values", {}).get(code, {}) or {}).items():
            for year, value in (series or {}).items():
                if value is None:
                    continue
                out[(code, area, int(year))] = round(float(value), 2)
    return out


def load(path):
    if not os.path.exists(path):
        return {}, "", ""
    vals, version, fetched = {}, "", ""
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            vals[(r["indicator"], r["area"], int(r["year"]))] = float(r["value"])
            version, fetched = r.get("version", ""), r.get("fetched", "")
    return vals, version, fetched


def save(path, vals, version, fetched):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for (ind, area, year), v in sorted(vals.items()):
            w.writerow({"indicator": ind, "area": area, "year": year, "value": v,
                        "version": version, "fetched": fetched})


def fmt(v):
    return "—" if v is None else f"{v:.1f}"


def diff(new, old):
    if new is None or old is None:
        return "—"
    d = round(new - old, 1)
    return "±0.0" if d == 0 else f"{d:+.1f}"


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    today = datetime.datetime.now(JST).strftime("%Y-%m-%d")
    this_year = datetime.datetime.now(JST).year
    years = [this_year - 1, this_year, this_year + 1]

    version = fetch_version()
    new = fetch_values(years)
    if not new:
        print("IMFの数字を1つも取れなかったので、前回のファイルをそのまま残します")
        return

    snap, snap_ver, snap_date = load(SNAP_PATH)
    # 版の名前が変わった、または数字が変わった → 新しい見通しが出たとみなす
    changed = bool(snap) and (
        (version and snap_ver and version != snap_ver)
        or any(abs(new[k] - snap[k]) >= 0.05 for k in new if k in snap)
    )
    if changed:
        save(PREV_PATH, snap, snap_ver, snap_date)
        detected = today
    else:
        detected = snap_date if snap else today
    save(SNAP_PATH, new, version or snap_ver, detected)

    prev, prev_ver, _ = load(PREV_PATH)

    lines = [
        f"# 🌐 IMFの経済見通し（{today} 取得）",
        "",
        "> IMF（国際通貨基金）が年4回（4月・10月に本改定、1月・7月に部分改定）出す世界経済見通しの数字。自動取得した数字のみで、解釈はしていません。",
        f"> 版：{version or snap_ver or '不明'}　｜　この版を最初に取得した日：{detected}",
        f"> 比較している前の版：{prev_ver or '（まだ記録なし。次の改定から比較できます）'}",
        "> 出典：IMF DataMapper https://www.imf.org/external/datamapper/",
        "",
    ]
    for code, label, unit in INDICATORS:
        y0, y1, y2 = years
        lines.append(f"## {label}（{unit}）")
        lines.append("")
        lines.append(f"| 国・地域 | {y0}年 | {y1}年 | {y2}年 | 前の版から（{y1}年） | 前の版から（{y2}年） |")
        lines.append("|---|---|---|---|---|---|")
        for area, name in AREAS:
            v = [new.get((code, area, y)) for y in years]
            if all(x is None for x in v):
                continue
            p1, p2 = prev.get((code, area, y1)), prev.get((code, area, y2))
            lines.append(f"| {name} | {fmt(v[0])} | {fmt(v[1])} | {fmt(v[2])} | {diff(v[1], p1)} | {diff(v[2], p2)} |")
        lines.append("")
    lines.append("※「前の版から」は、IMFが前回出した見通しとの差（＋は上方修正、－は下方修正）。単位はポイント。")

    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{today}: IMFの数字 {len(new)} 個を保存（版: {version}、改定検知: {changed}）")


if __name__ == "__main__":
    main()
