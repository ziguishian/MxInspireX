# MxinspireX

**ひとつの要望から、デザインへ。** 灵矩绘境が開発するローカル優先の AI デザインワークスペースです。対話、参考資料、無限キャンバスをつなぎます。

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md)

![商品画像、同一商品のシーン、背景編集](docs/images/product-workflow.png)

## 主な機能

- ロゴ、ポスター、商品、パッケージ、キャラクタートイ、空間、文章、HTML の制作。
- 最初の商品画像を後続シーンの参照に使用。画像編集では元の作品を保持します。
- 継続的な対話、画像・文書の参照、キャンバス、バージョン、プレビューとエクスポート。
- 画像・音声・動画生成、外部 3D サービス、ローカルのパラメトリック CAD。利用できる機能は設定したサービスに依存します。
- Token と人民元の料金を表示。確定請求、参考見積もり、照合待ちを区別します。

独立した成果物は並列処理でき、参照画像に依存するシーンはその完成を待ちます。自動の品質レビュー工程はありません。課金結果が不明なリクエストを自動再送しません。

## 起動方法

**Node.js 22 または 24** と **uv** を用意してください。

```sh
git clone https://github.com/ziguishian/MxInspireX.git
cd MxInspireX
npm run start:portable
```

ロックファイルに従って依存関係をインストールし、uv が Python 3.12 を準備します。表示された URL（通常 `http://127.0.0.1:5173`）を開いてください。ポート使用中の場合は空きポートを選びます。停止は Ctrl+C です。

アバター → **設定（设置）→ モデルと接続（模型与连接）** からサービスと自分の Key を設定し、モデル一覧を同期して選択します。**EvoLink の公式 URL は内蔵されており、Key のみ入力します。** ホームで要望と資料を送信してください。

UI は主に中国語です。README の翻訳は UI の多言語対応を意味しません。Key、利用枠、個人プロジェクトは付属しません。外部 3D 生成には別途設定が必要です。

## ガイド・開発

[画像付きガイド（中国語）](docs/USER_GUIDE.md) · [移行手順](RUN_IN_CODEX.md) · [パッケージ作成](docs/PACKAGING.md) · [開発ガイド](AGENTS.md) · [Agent の流れ](docs/agent-flow.md) · [リリース検証](docs/RELEASE_VALIDATION.md)

```sh
npm run setup:portable
npm run verify:portable   # 空の作業領域で起動確認。モデル呼び出しなし
npm run typecheck
npm test
npm run api:test
npm run build:web
npm run build
```

デスクトップ開発は `node node_modules/electron/install.js` の後に `npm run dev` を実行します。ソース ZIP は依存関係のインストールが必要で、単体起動可能なインストーラーではありません。非公開の事例素材は含まれません。レイアウトテストは実行され、素材一式がない場合のみ素材整合性テスト 2 件をスキップします。

構成は Vue 3 / TypeScript / Vite / Vue Flow、Electron、FastAPI / Python、Node Agent worker です。データは `.local/portable-workspace/` に保存されます。バックアップ前にアプリを停止し、Key、`.env`、データベースをコミットしないでください。クラウドモデルには処理に必要な入力が送信されます。

## ライセンス・連絡先

コードは [MIT](LICENSE)。依存ライブラリ、フォント、エンジンには各ライセンスが適用されます（`services/api/notices/`）。作品やアップロード内容の権利は各権利者に帰属します。

**灵矩绘境 · MxinspireX** · [ziguishian@foxmail.com](mailto:ziguishian@foxmail.com)
