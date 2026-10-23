# MxinspireX

**ローカル優先の AI デザインエージェントと無限キャンバス · ひとつの要望から、一連のデザインへ。**

[![Release](https://img.shields.io/github/v/release/ziguishian/MxInspireX?style=flat-square&color=4b8bd8&label=Release)](https://github.com/ziguishian/MxInspireX/releases/latest)
[![Windows x64](https://img.shields.io/badge/Windows-x64-4b8bd8?style=flat-square)](https://github.com/ziguishian/MxInspireX/releases/latest)
[![MIT License](https://img.shields.io/github/license/ziguishian/MxInspireX?style=flat-square&color=608571)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/ziguishian/MxInspireX?style=flat-square&color=c79a49&label=Stars)](https://github.com/ziguishian/MxInspireX/stargazers)

MxinspireX は、灵矩绘境が開発する **AI デザインワークスペース**です。デザイナー、文化・クリエイティブ分野のチーム、商品づくりに携わる方に向けて、要望や参考資料を、修正・比較・書き出しができるデザイン作品へとつなげます。

商品画像、ブランド資料、文書をアップロードし、作りたいものを普段の言葉で伝えてください。エージェントがプロジェクトの文脈に応じてモデルを呼び出し、商品コンセプト、パッケージ、ポスター、キャラクター、シーン画像などをひとつの無限キャンバスにまとめます。対話を続けて修正したり、ノードをつないで前段の文章や画像を次の生成の参考にしたりできます。

> **要望を伝える → 参考資料を追加 → エージェントが生成 → キャンバスで比較・修正 → 書き出し**

プロジェクトとファイルは自分のパソコンに保存されます。クラウドモデルの利用には自分の API キーが必要で、料金はサービス提供元から請求されます。無料の利用クレジットは付属しません。

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md)

[インストーラー](https://github.com/ziguishian/MxInspireX/releases) · [使い方（中国語）](docs/USER_GUIDE.md) · [機能と制約（中国語）](docs/product-facts.md) · [不具合・要望](https://github.com/ziguishian/MxInspireX/issues)

## ワークスペースのプレビュー

<img width="3840" height="1978" alt="MxinspireX のデザインワークスペースとキャンバス 1" src="https://github.com/user-attachments/assets/838a1600-51fa-4382-81ea-13d7e9d9834b" />

<details>
<summary>キャンバスとデザインの例をもっと見る</summary>

<img width="3840" height="1978" alt="MxinspireX のデザインワークスペースとキャンバス 2" src="https://github.com/user-attachments/assets/a53fa767-5d18-4aa2-9ae0-758ecd35e7a2" />
<img width="3840" height="1978" alt="MxinspireX のデザインワークスペースとキャンバス 3" src="https://github.com/user-attachments/assets/005e4846-60de-4e4f-bb43-4ee812f649b7" />

</details>

## 主な機能

- ロゴ、ポスター、商品、パッケージ、キャラクタートイ、空間、文章、HTML の制作。
- 最初の商品画像を後続シーンの参照に使用。画像編集では元の作品を保持します。
- 継続的な対話、画像・文書の参照、キャンバス、バージョン、プレビューとエクスポート。
- 画像・音声・動画生成、外部 3D サービス、ローカルのパラメトリック CAD。利用できる機能は設定したサービスに依存します。
- Token と人民元の料金を表示。確定請求、参考見積もり、照合待ちを区別します。

独立した成果物は並列処理でき、参照画像に依存するシーンはその完成を待ちます。自動の品質レビュー工程はありません。課金結果が不明なリクエストを自動再送しません。

## 起動方法

デスクトップ版は [GitHub Releases](https://github.com/ziguishian/MxInspireX/releases/latest) から Windows x64 インストーラーをダウンロードできます。更新の通知に対応しており、ダウンロードとインストールのための再起動は、ユーザーが承認した場合にのみ行います。[更新・リリース手順（中国語）](docs/desktop-updates.md)も参照してください。ソースコードから起動する場合は、以下の手順に進んでください。

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

## Star History

制作に役立ったら、Star で応援していただけるとうれしいです。使ってみた感想や要望は [Issues](https://github.com/ziguishian/MxInspireX/issues) にお寄せください。

<a href="https://www.star-history.com/?repos=ziguishian%2FMxInspireX&type=date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date" />
    <img width="800" alt="MxinspireX の GitHub Star 数の推移" src="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date" />
  </picture>
</a>

[Star History でインタラクティブなグラフを見る](https://www.star-history.com/?repos=ziguishian%2FMxInspireX&type=date)

## ライセンス・連絡先

コードは [MIT](LICENSE)。依存ライブラリ、フォント、エンジンには各ライセンスが適用されます（`services/api/notices/`）。作品やアップロード内容の権利は各権利者に帰属します。

**灵矩绘境 · MxinspireX** · [ziguishian@foxmail.com](mailto:ziguishian@foxmail.com)
