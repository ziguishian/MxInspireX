# MxinspireX

**하나의 요청에서 디자인까지.** 灵矩绘境의 로컬 우선 AI 디자인 작업 공간입니다. 대화, 참고 자료, 무한 캔버스를 연결합니다.

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md)

![제품 이미지, 동일 제품의 장면, 배경 편집](docs/images/product-workflow.png)

## 주요 기능

- 로고, 포스터, 제품, 패키지, 캐릭터 토이, 공간 이미지, 문안 및 HTML 제작.
- 첫 제품 이미지를 후속 장면의 실제 참고 이미지로 사용하며 편집 시 원본을 보존합니다.
- 프로젝트 대화, 이미지·문서 참조, 캔버스 노드, 버전, 미리보기 및 내보내기.
- 이미지·음성·영상, 외부 3D 서비스, 로컬 파라메트릭 CAD. 기능은 설정한 서비스에 따라 달라집니다.
- Token과 위안화 요금 표시. 확인된 청구, 참고 견적, 대사 대기 상태를 구분합니다.

독립 결과물은 병렬로 처리하고 원본 이미지가 필요한 장면은 해당 이미지 완성을 기다립니다. 자동 디자인 품질 심사 단계는 없습니다. 과금 결과가 불명확한 요청은 자동 재전송하지 않습니다.

## 빠른 시작

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

## 라이선스 및 문의

코드는 [MIT](LICENSE)를 따릅니다. 의존성, 글꼴, 엔진은 각각의 라이선스를 따릅니다(`services/api/notices/`). 작품과 업로드한 콘텐츠의 권리는 각 권리자에게 있습니다.

**灵矩绘境 · MxinspireX** · [ziguishian@foxmail.com](mailto:ziguishian@foxmail.com)
