# Kang AI-AutoCut

**Local-first Agentic AI Video Production System**

**로컬 우선 Agentic AI 영상 제작 시스템**

**Languages:** [English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | 한국어 | [Bahasa Indonesia](README.id.md) | [Deutsch](README.de.md) | [Español](README.es.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3-3776AB)](README.md#installation)
[![FFmpeg](https://img.shields.io/badge/ffmpeg-required-007808)](README.md#installation)
[![Local-first](https://img.shields.io/badge/local--first-yes-4c1)](docs/decisions/ADR-0007-local-first.md)
[![Agent-oriented](https://img.shields.io/badge/agent--oriented-yes-8957e5)](README.md#use-with-an-ai-agent)
[![Tests](https://img.shields.io/badge/tests-1062%20passing-brightgreen)](README.md#installation)
[![macOS](https://img.shields.io/badge/macOS-tested-000000)](README.md#installation)
[![Baseline](https://img.shields.io/badge/baseline-pre--third--SKU-orange)](README.md#frozen-baseline)

*배지는 정적이며 동결된 기준선(frozen baseline)을 설명합니다. 이 저장소는 CI
워크플로를 실행하지 않으며, 배지의 숫자는 실시간 상태가 아닙니다.*

Kang AI-AutoCut은 FFmpeg 이어 붙이기 스크립트가 아니라 Agent 지향(Agent-oriented)
영상 제작 시스템입니다. 권한이 확보된 원본 소재와 명시된 창작 목표를 입력으로 받아,
**여덟 개의 제작 스테이지** — 소재 이해, 편집 지능, 내러티브 설계, 타임라인 구성,
화면 마감, 타이포그래피, 오디오, 마스터링, 리뷰와 수정 — 를 통해 작업을 진행하며,
**사람의 승인을 명시적인 게이트로** 둡니다.

이 시스템은 사용자의 컴퓨터에서 실행됩니다. 프로덕션 제어 경로와 미디어 처리는 로컬
우선이며, 외부 AI 제공자는 승인된 지능(intelligence) 또는 생성(generation) 작업에
명시적으로 필요한 입력만 전달받을 수 있습니다. 모든 창작 결정은 기록되며, 시스템은
측정할 수 없는 성공을 보고하지 않습니다.

> **상업용 우선(Commercial-first), 설계부터 확장 가능.** 상업 광고는 최초의
> 프로덕션 검증 완료 워크플로입니다. 이 아키텍처는 더 넓은 크리에이터·미디어
> 워크플로로 확장되도록 설계되었습니다.

```
Raw Footage
    ↓
Understand  →  Plan  →  Edit
    ↓
Picture  ·  Typography  ·  Audio
    ↓
Assemble & Master
    ↓
Review  →  Repair  →  Human Approval
    ↓
Final Video
```

---

## 왜 Kang AI-AutoCut인가

대부분의 AI 영상 도구는 채팅 창 안에서 **영상 한 편을 한 번** 만들어 냅니다. 다시
실행하면 다른 영상이 나오고, 그 과정은 들여다볼 수 없습니다.

Kang AI-AutoCut은 영상 제작을 **엔지니어링 파이프라인**으로 다룹니다:

| 일반적인 AI 영상 출력 | Kang AI-AutoCut |
|---|---|
| 일회성 결과물이라 반복하기 어려움 | 다시 실행할 수 있는 재사용 가능한 워크플로 |
| 결정이 채팅 로그에만 남음 | 모든 결정이 기록된 산출물로 남음 |
| 실패하면 처음부터 다시 시작 | 잡(job)은 멈춘 스테이지부터 재개 |
| "다 된 것 같다"가 유일한 확인 수단 | 출력을 측정: 프레임, 블랙 프레임, 정지 프레임, 라우드니스, 트루 피크, 마스터 해시 |
| 모델이 단계를 조용히 건너뛸 수 있음 | 스테이지는 **자신이 실행한 역량(capability)을 명시하지 않고는 통과할 수 없음** |
| 사람의 판단이 드러나지 않음 | 사람의 입력은 이름이 붙은 게이트에서 이루어지고 기록됨 |
| 촬영 소재가 제공자에게 업로드됨 | 처리는 로컬 우선이며, 제공자는 해당 작업에 필요한 입력만 받음 |

---

## 무엇을 만들 수 있는가

**현재 프로덕션 검증 완료:**

- **상업 광고 및 이커머스 제품 영상** — 납품용 마스터 검증까지 포함해 처음부터 끝까지
  수행한 최초의 워크플로입니다.
- **소셜 미디어 숏폼 제품 콘텐츠** — 동일한 여덟 스테이지를 사용하는 세로형·단편 상업
  편집입니다.

**아키텍처가 확장을 목표로 설계된 방향** — *아직 프로덕션 검증되지 않음*:

- 크리에이터 및 셀프 미디어 영상
- 제품 시연 및 설명(explainer) 콘텐츠
- 브랜드 및 캠페인 콘텐츠
- 기타 구조화된 영상 제작 워크플로

이 시스템은 현재 상업용 우선(commercial-first)입니다. 여기서 모든 영상 카테고리가
이미 지원된다고 주장하지 않으며, 콘텐츠 모드 프레임워크도 아직 존재하지 않습니다.

---

## 동작 방식

### 사용자가 하는 일

1. **원본 소재 추가** — 소스 영상이 있는 디렉터리를 시스템에 지정합니다.
2. **목표 명시** — 제품, 플랫폼, 언어, 목표 길이, 그리고 영상이 반드시 말해야 할 것과
   말해서는 안 될 것을 정합니다.
3. **Agent가 파이프라인을 실행하도록 함** — Agent는 스테이지를 진행하고, 사용자가
   필요할 때 멈춥니다.
4. **게이트에 응답** — 카피를 승인하고, 누락된 산출물을 제공하고, 창작 판단을 내립니다.
5. **최종 영상 승인** — 이름이 지정된 사람이 마스터를 릴리스합니다. 이 릴리스는 리뷰와는
   별개의 결정이며, 승인하는 정확한 마스터를 명시합니다.

### 시스템이 하는 일

프로덕션 제어 경로는 **여덟 개의 의미론적 스테이지**를 실행합니다:

| # | 스테이지 | 수행 내용 |
|---|---|---|
| 1 | **PREPARE** | 파일별 변경 불가 다이제스트를 포함한 소스 인벤토리 생성 |
| 2 | **UNDERSTAND SHOTS** | 미디어를 분석하고, 측정된 타임스탬프를 CFR 분석 그리드에 매핑해 실제 시각 세그먼트를 찾음 |
| 3 | **PLAN THE EDIT** | 타임라인 구간을 관측 가능한 동작과 대조해 검증 — 온셋(onset)이나 결과를 놓친 컷은 거부됨 |
| 4 | **FINISH THE PICTURE** | 타임베이스 불변식을 통해 소스 구간을 추출하고 측정한 뒤, 샷별로 KEEP / REVIEW / CORRECT 결정을 내림 |
| 5 | **PLAN THE WORDS** | 유료 음성 작업 **이전에** 나레이션 커버리지를 확인한 다음, 화면 카피를 렌더링 |
| 6 | **BUILD THE AUDIO** | FIT / SYNC / RHYTHM을 각각 판정한 뒤 믹스를 만들고 **측정** |
| 7 | **ASSEMBLE & MASTER** | 납품 마스터를 생성한 뒤 파일 자체와 대조해 검증 |
| 8 | **REVIEW & REPAIR** | 모든 리뷰 차원을 판정하고, 판정(verdict)을 도출한 뒤 사람의 릴리스 게이트를 수행 |

### 두 관점의 대응 관계

```
USER VIEW                          SYSTEM VIEW (8 stages)
─────────────────────────────      ──────────────────────────────────────
1  add raw footage            →    PREPARE
2  state the goal             →    (job manifest + brief)
3  understand the material    →    UNDERSTAND SHOTS
4  build the editing strategy →    PLAN THE EDIT
5  construct the timeline     →    PLAN THE EDIT
6  finish the picture         →    FINISH THE PICTURE
7  titles / copy / typography →    PLAN THE WORDS
8  voice / music / audio      →    BUILD THE AUDIO
9  assemble and master        →    ASSEMBLE & MASTER
10 review and repair          →    REVIEW & REPAIR
11 human approval             →    REVIEW & REPAIR (human release gate)
12 final video                →    delivered master
```

### 스테이지는 의도적으로 멈춥니다

필수 입력이 누락되면 실행은 **멈추고 누가 조치해야 하는지 명시합니다**:

```
   Stage ──▶ [ PRODUCER GATE ] ──▶ Stage
                 │
                 ├─ which artifact is missing
                 ├─ which producer is responsible (AUTO / CODEX / HUMAN / ADAPTER)
                 ├─ the input and output contract
                 ├─ the procedure to follow
                 ├─ the evidence required
                 └─ what must become true to resume
```

**Producer Gate(프로듀서 게이트: 선언된 프로듀서가 산출물을 제공하거나 승인할 때까지
시스템이 의도적으로 멈추는 지점)는 실패가 아닙니다.** 그것은 창작 결정을 지어내거나,
하지 않은 작업을 했다고 주장하기를 시스템이 거부하는 것입니다. 일부 스테이지는
자동화되어 있고, 다른 스테이지는 Agent나 제공자 어댑터, 또는 사람이 정당하게 필요합니다.
이 README 전반에서 "생성 또는 준비(generate or prepare)", "Agent가 제공(Agent
supplies)", "필요할 때 잡에서 작성(job-authored when required)"이라는 표현을 의도적으로
사용합니다.

---

## 현재 역량

### 현재 사용 가능하며 검증된 항목

| 역량 | 비고 |
|---|---|
| 소스 수집 및 변경 불가 인벤토리 | 파일별 SHA-256, 사용 전 재검증 |
| VFR 안전 미디어 이해 | 측정된 타임스탬프를 CFR 분석 그리드에 매핑 |
| 시각 세그먼테이션 | 엔진이 실제로 디코딩하는 그리드 위에서 실행 |
| 타임라인 구간 검증 | 관측 가능한 동작을 놓친 컷을 거부 |
| 소스 구간 추출 | 모든 구간을 측정된 타임스탬프에서 해석 |
| 화면 실행(picture execution) | 실제 영상 산출물을 생성하고 이후 다시 측정 |
| 나레이션 커버리지 | 유료 음성 생성 이전에 실행 |
| 타이포그래피 렌더링 | 잡 자체의 레이아웃과 폰트로 실제 출력 생성 |
| 오디오 믹싱 및 마스터링 | 실제 믹스와 측정된 라우드니스·트루 피크·클리핑 |
| 패키징 및 최종 마스터 | `final/master.mp4`와 측정된 기술 QA |
| 리뷰 계약과 릴리스 판정 | 모든 차원을 한 번씩 판정하고, 판정은 주장이 아니라 도출 |
| 표적 수정(targeted repair) 계획 | 영향받은 레이어로 범위를 고정 |
| 사람의 릴리스 게이트 | 승인하는 마스터를 명시하는 별도의 결정 |
| 개입 원장(intervention ledger) | 게이트가 실행을 정지시킬 때마다 자동 기록 |
| 재개 및 무효화 | 첫 번째 미완료 스테이지에서 재개하며, 한 스테이지를 무효화하면 하위 전체가 다시 열림 |
| 마스터 무결성 검증 | 다이제스트를 재계산하며, 삭제되거나 변경된 마스터는 검증 실패 |

### 게이트 적용 / 잡(job)에서 작성되는 항목

이들은 실행되지만, 소비하는 산출물은 잡마다 Agent나 어댑터, 또는 사람이 제공합니다:

| 역량 | 아직 제공이 필요한 것 |
|---|---|
| 읽기 전용 화면 측정 | 이 저장소에는 측정 도구가 포함되어 있지 않음 |
| 제품 진위(authenticity) 보호 | 마찬가지이며, 허용 오차 검사는 실제 데이터에서 아직 실행되지 않음 |
| KEEP / REVIEW / CORRECT 결정 | 결정은 실행되지만, `CORRECT`에 대해 조치하는 것은 이 저장소에 없음 |
| 오디오 프로그램 검증(FIT / SYNC / RHYTHM) | 이것이 소비하는 음성 배치 |
| 음성 / 음악 생성 | 제공자 어댑터가 제공하며, **내장되어 있지 않음** |

### 계획됨 / 확장 가능

구현되지 않았고 주장하지도 않습니다: 자동화된 광고 리뷰어, 범용 백엔드 컴파일러,
산출물 레지스트리, 잡 큐, 무인 원커맨드 러너, 그리고 더 넓은 콘텐츠 모드 워크플로.

---

## AI Agent와 함께 사용하기

Kang AI-AutoCut은 **Agent와 함께 운영되도록** 설계되었습니다. 여기서 Agent는 채팅 전용
모델이 아니라, 사용자의 파일 시스템과 셸에서 실제로 동작할 수 있는 모델을 뜻합니다.

**특정 Agent 제품에 묶여 있지 않습니다.** 호환성은 역량(capability) 기준입니다:

| Agent에게 필요한 능력 | 이유 |
|---|---|
| 저장소 파일 읽기 | `README.md`, `PROJECT_IDENTITY.md`, `AGENTS.md`를 따르기 위해 |
| 셸 명령 실행 | FFmpeg, FFprobe, Python, 테스트 스위트 |
| 로컬 파일 읽기와 쓰기 | 잡 상태, 산출물, 미디어 스테이징 |
| Python 및 FFmpeg 워크플로 실행 | 모든 스테이지가 로컬이고 결정적이므로 |
| 구조화된 JSON 산출물 이해 | 잡, 리뷰, 증거, 매니페스트 |
| **Producer Gate에서 멈추기** | 추측하는 대신 사용자에게 묻기 위해 |
| 저장소의 경계 준수 | Git 외부의 미디어, 시크릿 금지, 머신 종속 경로 금지 |

역량을 갖춘 Agent의 예로는 Codex, DeepSeek Harness, Claude Code, 그리고 기타 코딩
Agent나 컴퓨터 사용(computer-use) Agent가 있습니다. **이는 예시일 뿐이며, 요구 사항이나
공식 지원 통합이 아닙니다.**

**채팅 전용 모델은 이 시스템을 운영할 수 없습니다.** 파일 시스템과 셸 접근 권한이 없으면
파이프라인을 실행할 수 없고, 논의만 할 수 있습니다.

### 내부 거버넌스와 공개 호환성

이 둘은 서로 다른 것이며, 두 가지 모두 사실입니다:

- **내부적으로는** 검증된 프로덕션 워크플로가 **Codex를 최상위 Supervisor로** 사용합니다.
  창작 권한이 그곳에 있으며, 어떤 결정적 구성 요소도 영상이 무엇을 말해야 하는지 결정하지
  않도록 시스템이 설계되었습니다.
- **공개적으로는** 저장소가 아키텍처가 허용하는 범위에서 **Agent 중립(Agent-agnostic)** 을
  유지하는 것을 목표로 합니다. 제어 경로의 어떤 부분도 특정 벤더의 Agent에 하드락되어
  있지 않습니다.

---

## Agent 빠른 시작

역량을 갖춘 코딩 Agent에게 저장소 URL과 다음과 같은 프롬프트를 전달하세요:

```text
저장소의 안내에 따라 이 컴퓨터에 Kang AI-AutoCut을 설치해 주세요.

저장소: https://github.com/KanG-ciyuan/AI-AutoCut

무엇이든 변경하기 전에:
1. README.md, PROJECT_IDENTITY.md, AGENTS.md를 읽어 주세요.
2. 환경을 확인해 주세요: Python, FFmpeg/FFprobe, 그리고 코드가 실제로 임포트하는
   Python 패키지.
3. 누락된 항목을 보고해 주세요. 제가 승인하지 않은 것은 아무것도 설치하지 마세요.

그다음:
4. 논리적 역할과 환경 변수만 사용해 로컬 워크스페이스와 미디어 루트를 구성해
   주세요. 미디어는 Git 외부에 두세요.
5. API 키, 토큰, 자격 증명을 추적 대상 파일, 로그, 커밋에 절대 기록하지 마세요.
6. 제 첫 영상 잡을 만들기 전에 저장소 자체 테스트를 실행해 주세요.

잡을 시작할 때:
7. 프로덕션 제어 경로를 실행하고 모든 Producer Gate에서 멈춰 주세요.
8. 게이트에 사람의 결정이나 창작 승인이 필요하면 저에게 물어봐 주세요.
9. 제 대신 카피, 아트 디렉션, 주장을 지어내지 마세요.
```

**Agent가 여전히 직접 해야 하는 일.** 설치가 오늘 완전히 자동화되어 있지는 *않습니다*:
설치 프로그램도, 패키징 매니페스트도, 선언된 의존성 잠금 파일(lockfile)도 없습니다.
Agent는 환경을 점검하고, 사용자가 승인한 사전 요구 사항을 설치하고, 로컬 경로를 구성해야
합니다. 아래 README는 검증된 항목을 정확히 나열하며, 이 저장소에는 `pyproject.toml`이나
`requirements.txt`가 존재하지 않습니다 — 이는 숨겨진 단계가 아니라 알려진 문서 공백입니다.

---

## 설치

### 검증된 사전 요구 사항

| 요구 사항 | 상태 |
|---|---|
| **Python 3** | 3.11.15에서 검증됨. 저장소는 최소 버전을 선언하지 않음 — 이는 공백으로 간주해야 함. |
| **FFmpeg 및 FFprobe** | 필수. ffmpeg/ffprobe 9.0.1에서 검증됨. |
| **`numpy`** | 미디어 이해 모듈이 요구 |
| **`Pillow`** | 타이포그래피 실행 어댑터가 요구 |
| **macOS** | macOS arm64에서 검증됨. Windows와 Linux는 **검증되지 않음**. |

`pyproject.toml`, `setup.py`, `requirements.txt`가 존재하지 않으므로 여기서 어떤 버전
고정도 주장하지 않습니다. 존재하지 않는 잠금 파일을 신뢰하지 말고 임포트 구문을 직접
확인하세요.

### 설정

```sh
git clone https://github.com/KanG-ciyuan/AI-AutoCut.git
cd AI-AutoCut

# Local configuration: resolves environment variables, never machine paths
cp config/examples/autocut.env.example .env.local
# edit .env.local: set AUTOCUT_MEDIA_ROOT and AUTOCUT_WORKSPACE
```

### 설치 검증

```sh
# Full offline regression — no network, no media required
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests

# End-to-end execution proof — builds its own media, produces a real master
python3 scripts/run_pre_exam_proof.py --job-root /tmp/pre-exam-proof
```

이 검증(proof)은 의도적으로 두 단계로 구성됩니다. 사람의 릴리스 게이트에서 멈추고,
**검증된** 마스터를 명시하는 릴리스를 기록한 뒤, 완료까지 재개합니다. 마스터가
삭제되거나 변경되면 실패합니다.

### 첫 번째 잡

```sh
# 1. Initialize a job (generic: any product, any source count)
python3 -m src.ai_autocut.job_foundation \
    --job-id my-first-job \
    --product-name 'My Product' \
    --source-root /path/to/footage \
    --workspace /path/to/job-workspace

# 2. Run the production control path
python3 -m src.ai_autocut.fast_path --job-root /path/to/job-workspace
```

첫 번째 Producer Gate에서 멈추고, 다음에 무엇이 필요한지 알려줍니다.

전체 안내: [`docs/audit/execution-runbook.md`](docs/audit/execution-runbook.md).

---

## Agent 및 LLM 호환성

서로 다른 네 계층은 혼동하기 쉽습니다. 이 시스템은 이들을 의도적으로 분리합니다:

| 계층 | 정의 | 이 프로젝트에서 |
|---|---|---|
| **LLM** | 추론 모델 | 모델이 사용되는 곳에서는 교체 가능 |
| **Agent** | 이 저장소에 작용할 수 있는 **도구를 갖춘** 모델 | 시스템 운영에 필수 |
| **Provider** | 생성 또는 지능 작업을 위한 선택적 외부 서비스 | 플러그 가능하며, **내장되어 있지 않음** |
| **Execution engine** | 결정적 로컬 Python/FFmpeg 파이프라인 | 특정 단계가 성공했다고 보고하도록 신뢰받는 유일한 구성 요소 |

**설계상 벤더 종속이 없습니다.** 제어 경로는 결정적 로컬 모듈을 호출합니다. 모델이나
제공자가 관여하는 경우에도 그것은 선언된 계약을 통해 산출물을 제공하는 프로듀서이므로,
모델이나 제공자를 교체해도 파이프라인은 바뀌지 않습니다.

**그러나 호환성은 브랜드가 아니라 역량의 문제입니다.** 파일을 읽고 쓸 수 없거나, 셸
명령을 실행할 수 없거나, 게이트를 존중할 수 없는 모델은 추론 능력이 아무리 뛰어나도 이
시스템을 운영할 수 없습니다.

---

## 오디오 및 AI 제공자 아키텍처

현재 저장소는 잡이 제공하는 오디오 자산에 대해 **로컬 믹싱과 마스터링**을 수행합니다.
음성, 음악, 효과음 제공자를 의도적으로 호출하지 **않습니다**. 오디오 합성은 여기서
구현되어 있지 않습니다.

```
External Audio Provider   (future Adapter layer — NOT built in)
        ↓
  generated VO / BGM / SFX assets
        ↓
  job-local audio assets
        ↓
  Audio Program  →  local Mix  →  local Master
                     (measured: loudness, true peak, clipping)
```

**오늘 존재하는 것:** `BUILD THE AUDIO` 스테이지는 잡 로컬 오디오 자산을 소비하고, 잡
자체의 목표치에 맞춰 FFmpeg로 믹싱하고, 그 결과를 측정합니다. 샘플 피크가 풀
스케일(full scale)에 도달하는 믹스는 거부합니다.

**존재하지 않는 것:** 내장된 제공자 통합은 없습니다. 원클릭 음성 생성은 없으며, 이
저장소에는 제공자 클라이언트가 포함되어 있지 않습니다.

**역사적 맥락, 정확한 표기.** 보이스오버는 이전의 검증된 프로덕션 작업 중
**MiniMax `speech-2.8-hd`** 를 통해 제작되었고, 이전 잡 매니페스트에는 **Doubao Seed
Audio 1.0**이 기록되어 있습니다. 두 가지 모두
[`docs/providers/audio-provider.md`](docs/providers/audio-provider.md)에 기록된 **과거에
평가된 실험**이며, 현재 이 저장소에 포함된 프로덕션 통합이 아닙니다. 그 발견들은 오디오
정책을 형성했지만, 해당 클라이언트는 이 저장소의 일부가 아닙니다.

키, 토큰, 자격 증명 값은 이 저장소 어디에도 나타나지 않습니다. 자격 증명은 환경 변수
이름으로만 참조됩니다.

---

## 상업적·프로덕션 가치

가치는 결과에 대한 약속이 아니라 아키텍처에 있습니다:

- **일회성 결과물이 아니라 재사용 가능한 워크플로.** 다음 제품에도 같은 제작 과정을
  실행할 수 있습니다. 새 대화를 시작할 필요가 없습니다.
- **반복 가능한 제작.** 동일한 스테이지, 계약, 게이트가 모든 잡에 적용되므로 프로세스
  지식이 사라지지 않고 축적됩니다.
- **감사 가능한 창작 결정.** 모든 선택이 증거를 가진 산출물로 남으므로, 리뷰에서 *무엇을*
  했는지만이 아니라 *왜* 그렇게 했는지 물을 수 있습니다.
- **재개 가능한 잡.** 게이트나 실패로 멈춘 잡은 처음이 아니라 멈춘 스테이지부터
  이어집니다.
- **결정적 실행.** 렌더링, 추출, 측정은 로컬에서 재현 가능하며, 모델의 주장은 결코
  증거가 되지 않습니다.
- **소스 소재의 재사용.** 좋은 촬영본은 재촬영 없이 여러 버전에 활용할 수 있습니다.
- **구조화된 리뷰와 수정.** 수정은 전체 재생성이 아니라 영향받은 레이어에 국한되므로,
  승인된 편집이 조용히 교체되지 않습니다.
- **측정 가능한 출력 검증.** 프레임 수, 블랙 프레임, 정지 프레임, 라우드니스, 트루 피크,
  마스터 다이제스트를 파일에서 직접 측정합니다.
- **사람의 개입이 드러남.** 시스템은 게이트가 언제 열렸고, 누가 조치했고, 언제
  해소되었는지를 기록합니다.
- **로컬 미디어 소유권.** 소스 미디어는 클라우드 파이프라인으로 자동 업로드되지
  않습니다. 제어 경로와 미디어 처리는 사용자의 컴퓨터에 남고, 승인된 외부 제공자는
  작업이 명시적으로 요구하는 입력만 받습니다.
- **제공자 유연성.** 생성은 경계 뒤에 있으므로 제공자 선택은 교체 가능합니다.

이것이 **주장하지 않는** 것: 품질 보장, 전환율이나 매출 결과 보장, 편집 시간 단축 보장.
이는 이 저장소의 어떤 것으로도 입증되지 않습니다.

---

## 아키텍처

| 문서 | 내용 |
|---|---|
| [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md) | 상호작용 모델, 프로덕션 제어 경로, 성숙도 |
| [`docs/architecture/supervisor-authority.md`](docs/architecture/supervisor-authority.md) | Codex Supervisor 경계 |
| [`docs/architecture/backend-neutral-timeline.md`](docs/architecture/backend-neutral-timeline.md) | 하나의 타임라인, 세 개의 백엔드 |
| [`docs/architecture/operations.md`](docs/architecture/operations.md) | 경로 역할, ASCII 스테이징, 검증 규칙 |
| [`docs/contracts/`](docs/contracts/) | 동결된 계약 |
| [`docs/policies/`](docs/policies/) | 편집, 샷, 타이포그래피, 오디오, 리뷰 정책 |
| [`docs/decisions/`](docs/decisions/) | 아키텍처 결정 기록 |
| [`docs/audit/production-chain-manifest.md`](docs/audit/production-chain-manifest.md) | 역량별 연결 상태와 준비도 |
| [`docs/audit/execution-runbook.md`](docs/audit/execution-runbook.md) | 모든 경계를 실행하는 방법 |
| [`docs/audit/gate-g0-history.md`](docs/audit/gate-g0-history.md) | 동결 기준선에 도달한 과정 |

### 저장소 구조

```
src/ai_autocut/          production code
  fast_path.py             the eight-stage control path
  producer_registry.py     every required artifact and its producer
  execution_contracts.py   the four execution boundaries
  execution_adapters.py    job-scoped picture / typography / audio / packaging
  timebase_adapter.py      the source-timestamp invariant
  media_probe.py           measured facts about a real media file
  ...                      contracts, policies, validators

tests/                   offline regression suite
schemas/                 frozen contracts and the Gold manifest
docs/                    architecture, contracts, policies, decisions, audits
scripts/                 the execution proof and the local-env wrapper
examples/                example job shape
config/examples/         configuration template
```

---

## 로컬 우선 설계

로컬 우선은 일시적 상태가 아니라 요구 사항입니다. 프로덕션 제어 경로와 모든 미디어 처리는
Python, FFmpeg/FFprobe, 로컬 파일 시스템을 사용해 결정적 오케스트레이션으로 로컬
머신에서 실행됩니다. 승인된 외부 AI API는 선택된 지능 또는 생성 작업에 사용될 수 있지만,
결코 제어 경로가 아닙니다. 클라우드 인프라 — 객체 스토리지, 서버 플랫폼, 분산 워커,
대시보드, 사용자 계정 — 는 의도적으로 존재하지 않습니다.
[ADR-0007](docs/decisions/ADR-0007-local-first.md)을 참조하세요.

이 저장소에는 머신에 종속된 절대 경로가 없습니다. 모든 런타임 위치는 환경 변수에서
해석되는 논리적 역할입니다.
[`docs/architecture/operations.md`](docs/architecture/operations.md)와
[`config/examples/autocut.env.example`](config/examples/autocut.env.example)를 참조하세요.

---

## 현재 상태

| | |
|---|---|
| 동결 기준선 | `pre-third-sku-blind-v1` → `b65a73b53040bd1ff5defe25e624a28f623b6847` |
| 동결 상태 | `CLOSED_AND_FROZEN` |
| 시험 유효성 | `PASS_WITH_EXPLICIT_PRODUCER_GATES` |
| 다음 계획된 프로덕션 단계 | Third-SKU 블라인드 시험 — **시작되지 않음** |

작동하는 **게이트 기반 프로덕션 제어 경로**가 존재하며, 실제로 독립 검증된 납품
마스터를 산출했습니다. 그것은 무인 원클릭 편집기가 아니며, 그렇게 주장하지도 않습니다.

---

## 알려진 한계

- **무인 원커맨드 편집기가 아닙니다.** Producer Gate는 설계상 실행을 멈추며, 일부는
  사람이나 Agent가 필요합니다.
- **자동화된 광고 리뷰어가 없습니다.** 리뷰 계약은 판단을 기록할 뿐, 판단을 생성하지
  않습니다.
- **화면 측정과 제품 보호는 잡에서 제공됩니다.** 이 저장소에는 측정 도구가 포함되어 있지
  않으며, 보호 허용 오차 검사는 실제 데이터에서 아직 실행되지 않았습니다 — 게이트는
  평가가 아니라 거부를 입증한 상태입니다.
- **`CORRECT` 화면 분기는 프로덕션 실행에서 한 번도 발동한 적이 없습니다.**
- **내장 오디오 제공자가 없습니다.** 합성은 구현되어 있지 않으며, 파이프라인은 잡 로컬
  자산을 소비합니다.
- **타이포그래피는 실행을 입증할 뿐, 아트 디렉션을 입증하지 않습니다.** 화면 카피 위계
  planner도, 제품 가림(obstruction) 검증도 없으며, 잡이 자체 레이아웃을 제공합니다.
- **실행 검증(execution proof)은 생성된 로컬 오디오를 사용합니다.** 이는 믹싱과 마스터링
  경로를 입증할 뿐, 실제 음성 퍼포먼스를 입증하지는 않습니다.
- **산출물 레지스트리와 잡 큐가 없습니다.** 대용량 스테이징 데이터는 수작업으로
  정리합니다.
- **범용 백엔드 컴파일러가 없습니다.** `compile_for_backend`는 모든 백엔드에 대해 예외를
  발생시키며, 실행은 대신 잡 범위 어댑터를 통해 이루어집니다.
- **선언된 의존성 매니페스트가 없습니다.** `pyproject.toml`이나 잠금 파일이 존재하지
  않습니다.
- **macOS에서만 검증되었습니다.** Windows와 Linux는 테스트되지 않았습니다.
- **추적 중이며 미해결:** 실행 인지(run-aware) 시각 세그먼테이션(C-01)과 자동 선택 구간
  검증(저장소에서는 "needs vision"으로 표기).

---

## 로드맵

1. **`pre-third-sku-blind-v1`에 대해 Third-SKU 블라인드 시험을 실행합니다.**
2. 최종 품질, Producer Gate 발생 빈도, 사람의 개입을 측정합니다.
3. 블라인드 실행 증거를 바탕으로, 남은 잡 제공 역량 중 다음에 자동화할 가치가 있는 항목을
   결정합니다.

동결 기준선은 **동결된 그대로** 검토되어야 합니다: 시험 이전에 사전 시험 자동화 작업을
예정하지 않았으므로, 이 시험은 그 아래에서 계속 움직이는 시스템이 아니라 승인된 시스템을
측정합니다.

---

## 동결 기준선

```
tag             pre-third-sku-blind-v1
target commit   b65a73b53040bd1ff5defe25e624a28f623b6847
```

**여기서 "frozen"이 뜻하는 것:** 재현 가능한 사전 시험 기준선이 존재합니다. 태그된
커밋은 감사와 승인을 거친 정확한 시스템이므로, 다음 시험 실행은 기억이 아니라 알려진
상태와 비교될 수 있습니다.

**뜻하지 않는 것:** 제품이 완성되었다거나, 모든 역량이 자동화되었다거나, 시스템이
프로덕션 수준으로 완결되었다는 뜻이 아닙니다. 문서 커밋은 태그 이후 `main`에 추가될 수
있으며, 태그 자체는 이동하지 않습니다.

---

## 라이선스

**Apache-2.0.** 전체 라이선스 전문은 [LICENSE](LICENSE)에 있습니다. 근거, `NOTICE`
미포함 결정, 그리고 이후 단계에서 다룰 미결 항목은
[LICENSE_DECISION_PENDING.md](LICENSE_DECISION_PENDING.md)에 기록되어 있습니다.

---

## 표준 식별 정보

- 프로젝트 ID: `ai-autocut`
- 기본 브랜치: `main`
- 런타임 데이터 루트: 논리적 역할 `AUTOCUT_WORKSPACE`
- 미디어 루트: 논리적 역할 `AUTOCUT_MEDIA_ROOT`

기계 판독 가능한 식별 기록은 [PROJECT_IDENTITY.md](PROJECT_IDENTITY.md)에 있습니다.
Agent 진입 규칙은 [AGENTS.md](AGENTS.md)에 있습니다.
