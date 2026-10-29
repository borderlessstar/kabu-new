# -*- coding: utf-8 -*-
"""
IMF（国際通貨基金）の経済見通し（World Economic Outlook）の数字を自動で取得して、
Claudeが読みやすい表にまとめるスクリプト。
- IMFの公式データAPI（api.imf.org、無料・登録不要）から、成長率・物価・失業率などの予測値を取る
  ※ www.imf.org の DataMapper は GitHub の実行環境からは 403 で断られるため使わない
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

# 追う指標（IMFの指標コード, 表示名, 単位）
INDICATORS = [
    ("NGDP_RPCH", "実質GDP成長率", "%"),
    ("PCPIPCH", "物価上昇率（消費者物価）", "%"),
    ("LUR", "失業率", "%"),
    ("BCA_NGDPD", "経常収支（GDP比）", "%"),
    ("GGXWDG_NGDP", "政府債務（GDP比）", "%"),
]

# 追う国・地域（表示名, IMFのコードの候補, 英語名の候補）
#   コードが分からなくても、英語名が一致すれば拾う
AREAS = [
    ("世界", ["G001", "WEOWORLD", "001"], ["World"]),
    ("先進国", ["GX110", "ADVEC", "110"], ["Advanced Economies"]),
    ("新興国・途上国", ["GX200", "OEMDC", "200"], ["Emerging Market and Developing Economies"]),
    ("日本", ["JPN"], ["Japan"]),
    ("米国", ["USA"], ["United States"]),
    ("ユーロ圏", ["G163", "EURO", "163"], ["Euro area"]),
    ("中国", ["CHN"], ["China", "China, People's Republic of"]),
    ("インド", ["IND"], ["India"]),
]

# ==========================================================
#  ここから下は基本さわらなくてOK
# ==========================================================

BASE = "https://api.imf.org/external/sdmx/2.1/data/IMF.RES,WEO"
JST = datetime.timezone(datetime.timedelta(hours=9))
DATA_DIR = "data"
MD_PATH = os.path.join(DATA_DIR, "imf.md")
SNAP_PATH = os.path.join(DATA_DIR, "imf_snapshot.csv")
PREV_PATH = os.path.join(DATA_DIR, "imf_prev.csv")
FIELDS = ["indicator", "area", "year", "value", "version", "fetched"]
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
STATUS_PATH = os.path.join(DATA_DIR, "imf_status.txt")
LOG = []


def log(msg):
    print(msg)
    LOG.append(msg)


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_values(years):
    """{(指標, 表示名, 年): 値} と、版の目印（数字の更新日など）を返す"""
    out, version = {}, ""
    for code, label, _ in INDICATORS:
        url = f"{BASE}/.{code}.A?startPeriod={years[0]}&endPeriod={years[-1]}"
        try:
            data = get_json(url)
        except Exception as e:
            log(f"取得失敗 {label}: {e}")
            continue
        try:
            st = data.get("structure") or data["data"]["structures"][0]
            dims = st["dimensions"]["series"]
            times = [v["id"] for v in st["dimensions"]["observation"][0]["values"]]
            pos = {d["id"]: i for i, d in enumerate(dims)}
            c_vals = dims[pos["COUNTRY"]]["values"]
            series = (data.get("dataSets") or data["data"]["dataSets"])[0]["series"]
        except Exception as e:
            log(f"形式が想定外 {label}: {e}")
            continue
        # 表示したい国・地域と、APIの並び順（番号）の対応を作る
        index_of = {}
        for name, codes, en_names in AREAS:
            for i, v in enumerate(c_vals):
                if v.get("id") in codes or (v.get("name") or "").strip().lower() in [n.lower() for n in en_names]:
                    index_of[i] = name
                    break
        if code == INDICATORS[0][0]:
            found = [n for n in index_of.values()]
            missing = [n for n, _, _ in AREAS if n not in found]
            if missing:
                groups = [f"{v.get('id')}={v.get('name')}" for v in c_vals if len(v.get("id", "")) != 3][:40]
                log(f"見つからない地域: {missing} / 地域コード例: {groups}")
        for key, ser in series.items():
            c_idx = int(key.split(":")[pos["COUNTRY"]])
            if c_idx not in index_of:
                continue
            for t_idx, obs in (ser.get("observations") or {}).items():
                try:
                    out[(code, index_of[c_idx], int(times[int(t_idx)]))] = round(float(obs[0]), 2)
                except (TypeError, ValueError, IndexError):
                    continue
        m = __import__("re").search(r"Dataflow=IMF\.RES:WEO\(([\d.]+)\)", json.dumps(data))
        if m and not version:
            version = f"WEOデータ v{m.group(1)}"
    return out, version


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

    new, version = fetch_values(years)
    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        f.write(f"{today} 取得数 {len(new)} 版 {version}\n" + "\n".join(LOG[:20]) + "\n")
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
        f"> 版：{version or snap_ver or '不明'}　｜　この数字を最初に取得した日：{detected}（数字が変わったら新しい版として扱う）",
        f"> 比較している前の版：{prev_ver or '（まだ記録なし。次の改定から比較できます）'}",
        "> 出典：IMF World Economic Outlook データベース（api.imf.org） https://data.imf.org/",
        "",
    ]
    for code, label, unit in INDICATORS:
        y0, y1, y2 = years
        lines.append(f"## {label}（{unit}）")
        lines.append("")
        lines.append(f"| 国・地域 | {y0}年 | {y1}年 | {y2}年 | 前の版から（{y1}年） | 前の版から（{y2}年） |")
        lines.append("|---|---|---|---|---|---|")
        for name, _, _ in AREAS:
            v = [new.get((code, name, y)) for y in years]
            if all(x is None for x in v):
                continue
            p1, p2 = prev.get((code, name, y1)), prev.get((code, name, y2))
            lines.append(f"| {name} | {fmt(v[0])} | {fmt(v[1])} | {fmt(v[2])} | {diff(v[1], p1)} | {diff(v[2], p2)} |")
        lines.append("")
    lines.append("※「前の版から」は、IMFが前回出した見通しとの差（＋は上方修正、－は下方修正）。単位はポイント。")

    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{today}: IMFの数字 {len(new)} 個を保存（版: {version}、改定検知: {changed}）")


if __name__ == "__main__":
    main()
