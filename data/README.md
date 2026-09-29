# data フォルダの中身

投資判断の材料を自動で集めている場所。Claudeは「今買うなら何がいい？」と聞かれたら、次の順に読む。

| ファイル | 中身 | 更新 |
|---|---|---|
| `market.md` | 株価指数・為替・金利・商品・VIX・業種別の数字と、過熱感の目安 | 毎日 00:17 JST ごろ（土曜は 06:17 にも） |
| `weekly.md` | 週1のまとめ（市場の温度・お金の流れ・プロの動き・候補・答え合わせ・来週の予定） | 毎週土曜の朝 |
| `candidates_perf.md` | これまでに出した候補の、その後の成績（TOPIX／S&P500との差） | 毎日 |
| `pro_holdings.md` | 追っているプロ（日本株アクティブ投信3本・米国の投資家3人）の最新の保有銘柄 | 新しい月次レポート・13Fが出たとき |
| `candidates.csv` | 候補の記録（記録日・名前・ティッカー・根拠の出どころ・見送りの目安） | 週1のまとめが追記 |
| `digest.md` | 日本株ニュースの見出し一覧（Googleニュース経由） | 毎日 |
| `articles.csv` | 見出しの蓄積 | 毎日 |

読むときは curl で raw.githubusercontent.com から取る（WebFetchはキャッシュで古い版を返すことがある）。

```
curl -s https://raw.githubusercontent.com/borderlessstar/kabu-new/main/data/market.md
```

※ 情報整理のための仕組みで、売買の推奨ではない。
