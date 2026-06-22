# -*- coding: utf-8 -*-
"""
毎朝、株式ニュースを自動収集して保存するスクリプト。
- Google ニュースのRSSから、決めたテーマ・会社名で記事を集める
- 同じ記事は2回保存しない（重複除外）
- ANTHROPIC_API_KEY があればAIが要約とスコアを付ける（なくても動く）
- data/articles.csv に蓄積、data/digest.md に「今朝のまとめ」を出力
※ これは情報整理ツールであり、投資助言ではありません。最終判断はご自身で。
"""

import csv
import os
import datetime
import urllib.parse
import feedparser

# ==========================================================
#  ここだけ編集すればOK（コードの知識は不要・文字を書き換えるだけ）
# ==========================================================

# 1) 追いたいテーマ・キーワード（行を増やしても減らしてもOK）
THEMES = [
    "日本株 注目 銘柄",
    "決算 上方修正",
    "半導体 関連株",
    "AI 関連 日本株",
    "新高値 銘柄",
    "増配 自社株買い",
    "好決算 株価",
]

# 2) 個別に追いたい会社名・銘柄（任意。空のままでもOK）
WATCHLIST = [
    # "トヨタ自動車",
    # "ソニーグループ",
    # "NVIDIA",
]

# 3) 1テーマあたり取得する最大件数
MAX_PER_QUERY = 8

# ==========================================================
#  ここから下は基本さわらなくてOK
# ==========================================================

JST = datetime.timezone(datetime.timedelta(hours=9))
DATA_DIR = "data"
CSV_PATH = os.path.join(DATA_DIR, "articles.csv")
DIGEST_PATH = os.path.join(DATA_DIR, "digest.md")
FIELDS = ["date", "theme", "source", "title", "link", "summary", "score", "comment"]


def gnews_url(query):
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"


def load_seen():
    seen = set()
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                seen.add(row.get("link", ""))
    return seen


def fetch():
    queries = [(t, t) for t in THEMES] + [(w, w) for w in WATCHLIST]
    items = []
    for label, q in queries:
        feed = feedparser.parse(gnews_url(q))
        for e in feed.entries[:MAX_PER_QUERY]:
            link = e.get("link", "")
            if not link:
                continue
            source = ""
            src = e.get("source")
            if src is not None and hasattr(src, "title"):
                source = src.title
            items.append({
                "theme": label,
                "source": source,
                "title": e.get("title", ""),
                "link": link,
                "raw_summary": e.get("summary", ""),
            })
    return items


def ai_enrich(items):
    """ANTHROPIC_API_KEY があればAIで要約＋スコア付け。なければ空欄で返す。"""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        for it in items:
            it["summary"] = ""
            it["score"] = ""
            it["comment"] = ""
        return items

    import json
    import anthropic
    client = anthropic.Anthropic(api_key=key)

    for it in items:
        prompt = (
            "あなたは株式ニュースの整理アシスタントです。投資助言ではなく、参考用の要約と評価のみ行います。\n"
            "次のニュースについて、日本語で下のJSONだけを返してください（前置き・コードブロックは禁止）:\n"
            '{"summary":"1〜2文の要約","company":"対象企業や銘柄が分かれば。なければ空","score":中期的な注目度を0〜5の整数,"comment":"なぜ注目か一言(20字程度)"}\n\n'
            f"タイトル: {it['title']}\n"
            f"補足: {it['raw_summary'][:500]}\n"
        )
        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in msg.content if b.type == "text").strip()
            text = text.replace("```json", "").replace("```", "").strip()
            data = json.loads(text)
            it["summary"] = str(data.get("summary", ""))
            it["score"] = data.get("score", "")
            comp = str(data.get("company", "")).strip()
            it["comment"] = (f"[{comp}] " if comp else "") + str(data.get("comment", ""))
        except Exception:
            it["summary"] = ""
            it["score"] = ""
            it["comment"] = "(AI処理スキップ)"
    return items


def score_key(it):
    try:
        return int(it.get("score"))
    except (TypeError, ValueError):
        return -1


def write_digest(today, items):
    ranked = sorted(items, key=score_key, reverse=True)
    lines = [
        f"# 📈 今朝の株ニュース（{today}）",
        "",
        "> ⚠️ これは情報整理であり投資助言ではありません。最終判断はご自身で。",
        "",
    ]
    top = [it for it in ranked if score_key(it) >= 4][:3]
    if top:
        lines.append("## ⭐ 今朝の注目（参考・AIスコア上位）")
        lines.append("")
        for it in top:
            lines.append(f"- **{it['title']}** （スコア{it.get('score')}） {it.get('comment','')}")
            lines.append(f"  {it['link']}")
        lines.append("")
    lines.append("## 🆕 すべての新着")
    lines.append("")
    if not items:
        lines.append("_新着なし_")
    for it in ranked:
        s = it.get("score")
        badge = f"`{s}` " if s not in ("", None) else ""
        summ = f"  \n  {it['summary']}" if it.get("summary") else ""
        src = f" _({it.get('source','')})_" if it.get("source") else ""
        lines.append(f"- {badge}**{it['title']}**{src}{summ}")
        lines.append(f"  {it['link']}")
    with open(DIGEST_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    seen = load_seen()
    today = datetime.datetime.now(JST).strftime("%Y-%m-%d")

    fetched = fetch()

    # 既存＆今回分の重複を除外
    uniq = {}
    for it in fetched:
        if it["link"] in seen or it["link"] in uniq:
            continue
        uniq[it["link"]] = it
    new_items = list(uniq.values())

    new_items = ai_enrich(new_items)

    write_header = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            w.writeheader()
        for it in new_items:
            w.writerow({
                "date": today,
                "theme": it["theme"],
                "source": it.get("source", ""),
                "title": it["title"],
                "link": it["link"],
                "summary": it.get("summary", ""),
                "score": it.get("score", ""),
                "comment": it.get("comment", ""),
            })

    write_digest(today, new_items)
    print(f"{today}: {len(new_items)} 件の新着を保存しました")


if __name__ == "__main__":
    main()
