# MxinspireX

**로컬 우선 AI 디자인 에이전트와 무한 캔버스 · 하나의 요청에서 완성된 디자인 시리즈까지.**

[![Release](https://img.shields.io/github/v/release/ziguishian/MxInspireX?style=flat-square&color=4b8bd8&label=Release)](https://github.com/ziguishian/MxInspireX/releases/latest)
[![Windows x64](https://img.shields.io/badge/Windows-x64-4b8bd8?style=flat-square)](https://github.com/ziguishian/MxInspireX/releases/latest)
[![MIT License](https://img.shields.io/github/license/ziguishian/MxInspireX?style=flat-square&color=608571)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/ziguishian/MxInspireX?style=flat-square&color=c79a49&label=Stars)](https://github.com/ziguishian/MxInspireX/stargazers)

MxinspireX는 灵矩绘境에서 만든 **AI 디자인 작업 공간**입니다. 디자이너, 문화·콘텐츠 제작팀, 제품 기획자가 요구 사항과 참고 자료를 바탕으로 디자인을 만들고, 결과물을 수정·비교·내보낼 수 있도록 돕습니다.

제품 이미지, 브랜드 자료, 문서를 올리고 원하는 작업을 일상적인 말로 설명하세요. 에이전트가 프로젝트의 맥락에 맞춰 모델을 호출하고 제품 콘셉트, 패키지, 포스터, 캐릭터, 연출 이미지 등을 하나의 무한 캔버스에 모읍니다. 대화를 이어 가며 수정하거나 노드를 연결해 앞 단계의 텍스트와 이미지를 다음 생성의 참고 자료로 사용할 수 있습니다.

> **요청 작성 → 참고 자료 추가 → 에이전트 생성 → 캔버스에서 비교·수정 → 내보내기**

프로젝트와 파일은 내 컴퓨터에 저장됩니다. 클라우드 모델을 사용하려면 본인의 API 키가 필요하며, 이용 요금은 서비스 제공업체에서 청구합니다. 무료 모델 크레딧은 포함되지 않습니다.

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md)

[설치 파일 다운로드](https://github.com/ziguishian/MxInspireX/releases) · [사용 가이드(중국어)](docs/USER_GUIDE.md) · [기능 및 제한 사항(중국어)](docs/product-facts.md) · [문제 제보](https://github.com/ziguishian/MxInspireX/issues)

## 작업 공간 미리보기

<img width="3840" height="1978" alt="MxinspireX 디자인 작업 공간과 캔버스 1" src="https://github.com/user-attachments/assets/838a1600-51fa-4382-81ea-13d7e9d9834b" />

<details>
<summary>캔버스와 디자인 예시 더 보기</summary>

<img width="3840" height="1978" alt="MxinspireX 디자인 작업 공간과 캔버스 2" src="https://github.com/user-attachments/assets/a53fa767-5d18-4aa2-9ae0-758ecd35e7a2" />
<img width="3840" height="1978" alt="MxinspireX 디자인 작업 공간과 캔버스 3" src="https://github.com/user-attachments/assets/005e4846-60de-4e4f-bb43-4ee812f649b7" />

</details>

## 주요 기능

- 로고, 포스터, 제품, 패키지, 캐릭터 토이, 공간 이미지, 문안 및 HTML 제작.
- 첫 제품 이미지를 후속 장면의 실제 참고 이미지로 사용하며 편집 시 원본을 보존합니다.
- 프로젝트 대화, 이미지·문서 참조, 캔버스 노드, 버전, 미리보기 및 내보내기.
- 이미지·음성·영상, 외부 3D 서비스, 로컬 파라메트릭 CAD. 기능은 설정한 서비스에 따라 달라집니다.
- Token과 위안화 요금 표시. 확인된 청구, 참고 견적, 대사 대기 상태를 구분합니다.

독립 결과물은 병렬로 처리하고 원본 이미지가 필요한 장면은 해당 이미지 완성을 기다립니다. 자동 디자인 품질 심사 단계는 없습니다. 과금 결과가 불명확한 요청은 자동 재전송하지 않습니다.

## 빠른 시작

데스크톱 앱은 [GitHub Releases](https://github.com/ziguishian/MxInspireX/releases/latest)에서 Windows x64 설치 파일을 다운로드하면 됩니다. 업데이트가 있으면 알려 주며, 사용자가 동의한 경우에만 다운로드하고 설치를 위해 재시작합니다. 자세한 내용은 [업데이트 및 릴리스 가이드(중국어)](docs/desktop-updates.md)를 참고하세요. 소스 코드로 실행하려면 아래 단계를 따르세요.

**Node.js 22 또는 24**와 **uv**를 준비하세요.

```sh
git clone https://github.com/ziguishian/MxInspireX.git
cd MxInspireX
npm run start:portable
```

잠금 파일에 맞춰 의존성을 설치하고 uv가 Python 3.12를 준비합니다. 터미널에 표시되는 주소(기본 `http://127.0.0.1:5173`)를 여세요. 포트가 사용 중이면 빈 포트를 선택합니다. Ctrl+C로 종료합니다.

아바타 → **설정(设置) → 모델 및 연결(模型与连接)**에서 서비스와 본인의 Key를 입력하고 모델 목록을 동기화해 선택하세요. **EvoLink 공식 주소는 내장되어 있어 Key만 입력합니다.** 홈에서 요청을 작성하고 참고 자료를 첨부하세요.

UI는 주로 중국어입니다. README 번역은 UI의 다국어 지원을 의미하지 않습니다. 계정, Key, 사용 크레딧, 개인 프로젝트는 포함되지 않습니다. 외부 3D 생성은 별도 설정이 필요합니다.

## 가이드 및 개발

[스크린샷 가이드(중국어)](docs/USER_GUIDE.md) · [다른 컴퓨터에서 실행](RUN_IN_CODEX.md) · [패키징](docs/PACKAGING.md) · [개발 가이드](AGENTS.md) · [Agent 흐름](docs/agent-flow.md) · [릴리스 검증](docs/RELEASE_VALIDATION.md)

```sh
npm run setup:portable
npm run verify:portable   # 빈 작업 공간에서 확인, 모델 호출 없음
npm run typecheck
npm test
npm run api:test
npm run build:web
npm run build
```

데스크톱 개발은 `node node_modules/electron/install.js` 실행 후 `npm run dev`를 사용합니다. 소스 ZIP은 의존성 설치가 필요하며 독립 실행 설치 프로그램이 아닙니다. 비공개 사례 원본은 제외됩니다. 레이아웃 테스트는 실행하고 자료 전체가 없을 때만 원본 무결성 테스트 2개를 건너뜁니다.

Vue 3 / TypeScript / Vite / Vue Flow, Electron, FastAPI / Python, Node Agent worker로 구성됩니다. 데이터는 `.local/portable-workspace/`에 저장됩니다. 백업 전에 앱을 종료하고 Key, `.env`, 데이터베이스를 커밋하지 마세요. 클라우드 모델에는 작업에 필요한 입력이 전송됩니다.

## Star History

작업에 도움이 되었다면 Star를 남겨 주세요. 사용 후기와 개선 의견은 [Issues](https://github.com/ziguishian/MxInspireX/issues)에서 공유할 수 있습니다.

<a href="https://www.star-history.com/?repos=ziguishian%2FMxInspireX&type=date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date" />
    <img width="800" alt="MxinspireX GitHub Star 증가 추이" src="https://api.star-history.com/svg?repos=ziguishian/MxInspireX&type=Date" />
  </picture>
</a>

[Star History에서 인터랙티브 차트 보기](https://www.star-history.com/?repos=ziguishian%2FMxInspireX&type=date)

## 라이선스 및 문의

코드는 [MIT](LICENSE)를 따릅니다. 의존성, 글꼴, 엔진은 각각의 라이선스를 따릅니다(`services/api/notices/`). 작품과 업로드한 콘텐츠의 권리는 각 권리자에게 있습니다.

**灵矩绘境 · MxinspireX** · [ziguishian@foxmail.com](mailto:ziguishian@foxmail.com)
