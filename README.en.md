# MxinspireX

**Local-first AI design agent and infinite canvas · From a brief to a complete set of designs.**

[![Release](https://img.shields.io/github/v/release/ziguishian/MxInspireX?style=flat-square&color=4b8bd8&label=Release)](https://github.com/ziguishian/MxInspireX/releases/latest)
[![Windows x64](https://img.shields.io/badge/Windows-x64-4b8bd8?style=flat-square)](https://github.com/ziguishian/MxInspireX/releases/latest)
[![Non-Commercial License](https://img.shields.io/badge/License-Non--Commercial-c79a49?style=flat-square)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/ziguishian/MxInspireX?style=flat-square&color=c79a49&label=Stars)](https://github.com/ziguishian/MxInspireX/stargazers)

MxinspireX is an **AI design workspace** by 灵矩绘境, built for designers, creative teams across industries, and product creators. It turns briefs and reference materials into work you can refine, compare and export.

Upload product images, brand assets or documents and describe what you need in natural language. The agent uses your project context to call models and brings product concepts, packaging, posters, characters and scene images together on an infinite canvas. Continue the conversation to refine the results, or connect nodes to use upstream text and images as references for the next generation.

> **Describe your brief → Add references → Generate with the agent → Compare and refine on the canvas → Export**

Projects and files stay on your computer. Cloud models require your own API key and are billed by the provider; the app does not include free model credits.

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md)

[Download](https://github.com/ziguishian/MxInspireX/releases) · [User guide (Chinese)](docs/USER_GUIDE.md) · [Product facts and limitations (Chinese)](docs/product-facts.md) · [Report an issue](https://github.com/ziguishian/MxInspireX/issues)

## Workspace preview

<img width="3840" height="1978" alt="MxinspireX design workspace and canvas 1" src="https://github.com/user-attachments/assets/838a1600-51fa-4382-81ea-13d7e9d9834b" />

<details>
<summary>More canvas and design examples</summary>

<img width="3840" height="1978" alt="MxinspireX design workspace and canvas 2" src="https://github.com/user-attachments/assets/a53fa767-5d18-4aa2-9ae0-758ecd35e7a2" />
<img width="3840" height="1978" alt="MxinspireX design workspace and canvas 3" src="https://github.com/user-attachments/assets/005e4846-60de-4e4f-bb43-4ee812f649b7" />

</details>

## Features

- Create logos, posters, product concepts, packaging, character toys, interiors, copy and interactive HTML.
- Reuse the actual first product image in subsequent scenes; preserve originals when editing.
- Persistent project conversations, image/document references, canvas nodes, versions, previews and exports.
- Images, speech, video, a separate external 3D service and local parametric CAD. Availability depends on your configured providers.
- Token usage and CNY billing, separating provider-confirmed charges, estimates and pending reconciliation.

Independent deliverables can run concurrently; dependent scenes wait for their source image. There is no automatic design-quality review stage. Requests with an unknown billing outcome are not automatically resubmitted.

## Quick start

For the desktop app, download the Windows x64 installer from [GitHub Releases](https://github.com/ziguishian/MxInspireX/releases/latest). It checks for updates, but downloads and restarts to install them only with your confirmation. See the [desktop update and release guide (Chinese)](docs/desktop-updates.md). To run from source, follow the steps below.

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

## Star History

If this workspace helps you create, consider giving it a Star or sharing your feedback through [Issues](https://github.com/ziguishian/MxInspireX/issues).

<a href="https://www.star-history.com/?repos=ziguishian%2FMxInspireX&type=date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date" />
    <img width="800" alt="MxinspireX GitHub star growth" src="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date" />
  </picture>
</a>

[View the interactive chart on Star History](https://www.star-history.com/?repos=ziguishian%2FMxInspireX&type=date)

## License and contact

The current source uses the [MxinspireX Non-Commercial License 1.0](LICENSE). Non-commercial learning, research, modification and sharing are permitted. Commercial deployment, paid services, client work and producing designs for commercial projects require prior written permission. This is a source-available license, not an OSI open-source license. Earlier MIT releases, including v0.2.1, and rights already granted remain under their original terms. Third-party components retain their own licenses (`services/api/notices/`); ownership of user materials and outputs is not transferred. Contact the email below for commercial permission.

**灵矩绘境 · MxinspireX** · [ziguishian@foxmail.com](mailto:ziguishian@foxmail.com)
