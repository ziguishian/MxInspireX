# MxinspireX

**From a brief to a design.** A local-first AI design workspace by 灵矩绘境, connecting conversations, reference materials and an infinite canvas.

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md)

![Product image, consistent scene and background edit](docs/images/product-workflow.png)

## Features

- Create logos, posters, product concepts, packaging, character toys, interiors, copy and interactive HTML.
- Reuse the actual first product image in subsequent scenes; preserve originals when editing.
- Persistent project conversations, image/document references, canvas nodes, versions, previews and exports.
- Images, speech, video, a separate external 3D service and local parametric CAD. Availability depends on your configured providers.
- Token usage and CNY billing, separating provider-confirmed charges, estimates and pending reconciliation.

Independent deliverables can run concurrently; dependent scenes wait for their source image. There is no automatic design-quality review stage. Requests with an unknown billing outcome are not automatically resubmitted.

## Quick start

Install **Node.js 22 or 24** and **uv**, then run:

```sh
git clone https://github.com/ziguishian/MxInspireX.git
cd MxInspireX
npm run start:portable
```

The launcher installs locked dependencies and prepares Python 3.12 through uv. Open the URL printed in the terminal (normally `http://127.0.0.1:5173`); occupied ports are handled automatically. Stop with Ctrl+C.

Open the avatar → **Settings / 设置 → Models and connections / 模型与连接**. Choose a provider, enter your own API key, sync its model catalog and select models. **EvoLink's official endpoint is built in; only the key is required.** Return home, describe a task and optionally attach references.

The app UI is primarily Chinese. These READMEs do not imply a localized interface. No credentials, credits or personal projects are bundled. External 3D generation requires separate configuration.

## Guides and development

[Illustrated guide (Chinese)](docs/USER_GUIDE.md) · [Migration](RUN_IN_CODEX.md) · [Packaging](docs/PACKAGING.md) · [Developer map](AGENTS.md) · [Agent flow](docs/agent-flow.md) · [Release validation](docs/RELEASE_VALIDATION.md)

```sh
npm run setup:portable
npm run verify:portable   # Empty workspace; no model calls
npm run typecheck
npm test
npm run api:test
npm run build:web
npm run build            # Renderer and Electron compilation
```

For desktop development, run `node node_modules/electron/install.js`, then `npm run dev`. Source ZIPs require dependency installation; they are not standalone installers. Private showcase originals are omitted: layout tests still run; two media-integrity checks skip only when their entire dataset is absent.

Stack: Vue 3 / TypeScript / Vite / Vue Flow, Electron, FastAPI / Python and a Node Agent worker. Portable data lives in `.local/portable-workspace/`. Stop the app before backing it up. Never commit keys, `.env` files or databases. Data is stored locally; selected cloud providers receive content required for model requests.

## License and contact

[MIT](LICENSE) for project code; dependencies, fonts and engines retain their own licenses (`services/api/notices/`). Artwork and uploaded content retain their respective owners' rights.

**灵矩绘境 · MxinspireX** · [ziguishian@foxmail.com](mailto:ziguishian@foxmail.com)
