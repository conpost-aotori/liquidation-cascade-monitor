# Liquidation Cascade Monitor

BTC 清算カスケード・マップのジェネレーター。Hyperliquid Perps の大口建玉から
清算価格を集計し、特定価格帯のクラスター（「ここを抜けると連鎖清算」）を
ビジュアル化して X / Discord に配信することを目指すプロジェクト。

```
①データ取得(HL公式API) → ②クラスター集計 → ③画像生成 → ④配信(X / Discord)
                                          ▲ 今ここ（このセッション）
```

## このセッションのスコープ：③画像生成

`LiquidationMap`（データ構造）を入力に、添付モックアップ相当の PNG を
HTML/CSS + ヘッドレス Chromium で生成します。データ取得・配信はまだ未実装で、
`liqmap/sample_data.py` の **illustrative なサンプル**で見た目を作り込みます。
このデータ構造は将来 ①の出力と一致させる前提なので、実データ接続時に
レンダラーは変更不要です。

## セットアップ

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

## 使い方

```powershell
# サンプルを 2x (3200x1800) で out/ に生成
.\.venv\Scripts\python.exe scripts\generate.py

# 等倍 (1600x900)
.\.venv\Scripts\python.exe scripts\generate.py --scale 1

# 出力先指定 + デバッグ用に HTML も書き出す
.\.venv\Scripts\python.exe scripts\generate.py -o out\card.png --html
```

出力サイズは 16:9（1600×900 ベース）で、X 画像・Discord 添付どちらにも適した比率です。

## 構成

```
src/liqmap/
  models.py          # Band / KeyLevel / Scenario / LiquidationMap（データ構造）
  sample_data.py     # モックアップ相当の illustrative サンプル
  render.py          # レイアウト計算 + HTML生成 + Playwright スクリーンショット
  templates/
    map.html.j2      # カードの HTML/CSS テンプレート
scripts/
  generate.py        # CLI: サンプル → PNG
out/                 # 生成物（git 管理外）
```

## データ構造（将来の①と共通）

- `Band(price, long_notional, short_notional)` — 価格帯ごとの清算想定額（USD）。
  ロングは下落で、ショートは上昇で発火。
- `KeyLevel(price, label, notional, side)` — チャート注記＋右パネルの主要レベル表。
- `Scenario(title, direction, body)` — 右パネルのシナリオ文（編集テキスト）。
- `LiquidationMap` — 上記＋現在値・地合いチップ・著者・日付などをまとめた描画ペイロード。

## 実装状況：①〜④すべて稼働（実データ）

- **①データ取得** `src/liqmap/sources/hyperliquid.py` — リーダーボードを母集団に
  `clearinghouseState` を並列取得（全37,525件 ≈ 16分）、BTC建玉の清算価格を抽出。
- **②クラスター集計** `src/liqmap/clusters.py` — 清算価格を価格帯に集計し、
  一次トリガー / 最大クラスター / 上値の壁を導出＋シナリオ文を自動生成。
- **③画像生成** `src/liqmap/render.py` + `templates/map.html.j2`
- **④配信** `src/liqmap/distribute.py` — X (API v2 / tweepy) と Discord (Webhook)。
  **既定は dry-run**、`live=True`（=`--post-*`）明示時のみ送信。

```powershell
# 実データで生成（全件クロール）
.\.venv\Scripts\python.exe scripts\generate.py --source live --max-addresses 0
# キャッシュから再描画して X 投稿（明示時のみ）
.\.venv\Scripts\python.exe scripts\post_live.py --post-x
```

## 自動運用（GitHub Actions）

`.github/workflows/post.yml` が **12時間毎（07:00 / 19:00 JST = UTC 22:00 / 10:00）** に
全件クロール → 画像生成 → X 投稿を自動実行します。

- 認証情報は **GitHub Secrets**（`X_API_KEY` / `X_API_SECRET` / `X_ACCESS_TOKEN` / `X_ACCESS_SECRET`）。`.env` はコミットしません。
- 手動実行：Actions → "post-liquidation-map" → Run workflow。`post=false`（既定）で**ドライラン（投稿せず画像のみ）**、`post=true` で実投稿。
- 生成画像は各実行の Artifact から確認できます。

> ⚠️ 数値は清算予測であり投資助言ではありません。
