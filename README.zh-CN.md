# Kang AI-AutoCut

**Local-first Agentic AI Video Production System**

本地优先的 Agentic AI 视频生产系统

**Languages:** [English](README.md) | 简体中文 | [日本語](README.ja.md) | [한국어](README.ko.md) | [Bahasa Indonesia](README.id.md) | [Deutsch](README.de.md) | [Español](README.es.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3-3776AB)](README.md#installation)
[![FFmpeg](https://img.shields.io/badge/ffmpeg-required-007808)](README.md#installation)
[![Local-first](https://img.shields.io/badge/local--first-yes-4c1)](docs/decisions/ADR-0007-local-first.md)
[![Agent-oriented](https://img.shields.io/badge/agent--oriented-yes-8957e5)](README.md#use-with-an-ai-agent)
[![Tests](https://img.shields.io/badge/tests-1062%20passing-brightgreen)](README.md#installation)
[![macOS](https://img.shields.io/badge/macOS-tested-000000)](README.md#installation)
[![Baseline](https://img.shields.io/badge/baseline-pre--third--SKU-orange)](README.md#frozen-baseline)

*徽章为静态徽章，描述的是冻结基线。本仓库不运行任何 CI 工作流，徽章上的数字并非实时状态。*

Kang AI-AutoCut 是一套面向 Agent 的视频生产系统，而不是一个 FFmpeg 拼接脚本。它接收已获授权的原始素材与明确表述的创作目标，并推动工作贯穿**八个生产阶段** —— 素材理解、剪辑智能、叙事规划、时间线构建、画面完成、文字排版、音频、母版制作、审阅与修复 —— 其中**人工批准是一道显式的门禁**。

它运行在你自己的机器上。生产控制路径与媒体处理都是本地优先的；经批准的外部 AI 服务商只能接收已获批准的智能分析或生成任务所明确需要的输入。每一个创作决策都会被记录，系统拒绝汇报它无法度量的成功。

> **商业优先，按设计可扩展。** 商业广告是第一个经过生产验证的工作流。该架构的构建目标就是扩展到更广泛的创作者与媒体工作流。

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

## 为什么选择 Kang AI-AutoCut

大多数 AI 视频工具是在聊天窗口里**一次性产出一个视频**。重新运行会得到另一个不同的视频，而且整个过程无从审查。

Kang AI-AutoCut 把视频生产视为一条**工程流水线**：

| 普通 AI 视频产出 | Kang AI-AutoCut |
|---|---|
| 一次性结果，难以重复 | 一条可以再次运行的可复用工作流 |
| 决策散落在聊天记录里 | 每一个决策都是被记录的产出物 |
| 失败就意味着从头再来 | 任务从中断的那个阶段继续 |
| 唯一的检查是“看起来做完了” | 产出物被度量：帧数、黑帧、冻结帧、响度、真峰值、母版哈希 |
| 模型可能悄悄跳过某个步骤 | 一个阶段**若不指明它所运行的能力，就无法通过** |
| 人的判断无处可见 | 人工输入发生在具名的门禁处，并被记录在案 |
| 你的素材被上传到服务商 | 处理过程本地优先；服务商只接收任务所需的输入 |

---

## 你可以构建什么

**目前已通过生产验证：**

- **商业广告与电商产品视频** —— 第一个端到端跑通的工作流，包含交付母版校验。
- **社交媒体短视频产品内容** —— 竖屏、短时长的商业剪辑，使用同样的八个阶段。

**架构设计上要扩展进入的方向** —— *尚未通过生产验证*：

- 创作者与自媒体视频
- 产品演示与讲解类内容
- 品牌与营销活动内容
- 其他结构化的视频生产工作流

目前的系统是商业优先的。本文档不声称所有视频品类都已支持，也尚不存在任何内容模式（content-mode）框架。

---

## 工作原理

### 你需要做的事

1. **放入原始素材** —— 把系统指向存放源视频的目录。
2. **说明目标** —— 产品、平台、语言、目标时长，以及这支视频必须声明什么、不得声明什么。
3. **让 Agent 运行流水线** —— 它会依次推进各个阶段，并在需要你介入时停下来。
4. **回应门禁** —— 批准文案、提供缺失的产出物，或做出创作判断。
5. **批准最终视频** —— 由具名的自然人放行母版。这次放行是与审阅相互独立的一次决策，并且会指明它所批准的确切母版。

### 系统做的事

生产控制路径执行**八个语义阶段**：

| # | 阶段 | 发生什么 |
|---|---|---|
| 1 | **PREPARE** | 源素材清点，并为每个文件生成不可变摘要 |
| 2 | **UNDERSTAND SHOTS** | 对媒体进行分析；把实测时间戳映射到 CFR 分析网格上，以找出真实的视觉片段 |
| 3 | **PLAN THE EDIT** | 时间线区间会对照可观察的动作进行校验 —— 错过动作起点或结果点的剪辑会被拒绝 |
| 4 | **FINISH THE PICTURE** | 通过时基不变量抽取源区间并加以度量，然后对每个镜头做出 KEEP / REVIEW / CORRECT（保留 / 待复核 / 需修正）决策 |
| 5 | **PLAN THE WORDS** | 在任何付费配音工作**之前**先检查旁白覆盖度；随后渲染屏幕文案 |
| 6 | **BUILD THE AUDIO** | 分别判定 FIT / SYNC / RHYTHM；然后构建混音并对其**进行度量** |
| 7 | **ASSEMBLE & MASTER** | 产出交付母版，然后对照文件本身进行校验 |
| 8 | **REVIEW & REPAIR** | 逐一判定所有审阅维度；推导出结论；进入人工放行门禁 |

### 两种视图如何对应

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

### 阶段会刻意停下来

当缺少必需输入时，运行会**停下来，并指明必须由谁采取行动**：

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

**Producer Gate（生产者门：系统按设计主动停止，等待被声明的生产者提供或批准某个产出物）不是失败。** 它意味着系统拒绝凭空编造一个创作决策，也拒绝声称自己完成了并未做的工作。有些阶段是自动化的；另一些则确实需要 Agent、服务商适配器或人来完成。本 README 中“生成或准备”“由 Agent 提供”“按需由任务产出（job-authored when required）”这些措辞都是刻意贯穿使用的。

---

## 当前能力

### 当前可用且已验证

| 能力 | 说明 |
|---|---|
| 源素材导入与不可变清点 | 逐文件 SHA-256，在使用前重新校验 |
| VFR 安全的媒体理解 | 把实测时间戳映射到 CFR 分析网格 |
| 视觉分段 | 在引擎实际解码所用的网格上运行 |
| 时间线区间校验 | 拒绝错过可观察动作的剪辑 |
| 源区间抽取 | 每一个区间都由实测时间戳解析得出 |
| 画面执行 | 产出真实的视频产出物，并在之后重新度量 |
| 旁白覆盖度 | 在任何付费语音生成之前运行 |
| 文字排版渲染 | 用任务自身的版式与字体产出真实结果 |
| 音频混音与母版制作 | 真实的混音，并度量响度、真峰值与削波 |
| 打包与最终母版 | `final/master.mp4`，外加经过度量的技术质检 |
| 审阅契约与放行结论 | 每个维度只判定一次；结论是推导出来的，而不是断言的 |
| 定向修复规划 | 作用范围锁定在受影响的层 |
| 人工放行门禁 | 一次独立的决策，并指明它所批准的母版 |
| 干预台账 | 每当门禁中止运行时自动写入 |
| 续跑与失效处理 | 从第一个未完成的阶段继续；使某个阶段失效会重新打开其下游的全部内容 |
| 母版完整性校验 | 重新计算摘要；被删除或被改动的母版无法通过校验 |

### 受门禁约束 / 由任务产出

这些能力会运行，但它们所消费的产出物是按任务提供的 —— 由 Agent、适配器或人提供：

| 能力 | 仍然需要提供的部分 |
|---|---|
| 只读画面测量 | 本仓库不附带任何测量工具 |
| 产品真实性保护 | 同上；其容差校验尚未在真实数据上运行过 |
| KEEP / REVIEW / CORRECT 决策 | 决策会运行；但本仓库中没有任何组件会依据 `CORRECT` 采取动作 |
| 音频节目校验（FIT / SYNC / RHYTHM） | 它所消费的语音落点（voice placement） |
| 语音 / 音乐生成 | 由服务商适配器提供；**非内置** |

### 计划中 / 可扩展

尚未实现，也未作任何声称：自动化商业审阅器、通用后端编译器、产出物注册表、任务队列、无人值守的单命令运行器，以及更广泛的内容模式工作流。

---

## 与 AI Agent 配合使用

Kang AI-AutoCut 的设计目标是**由 Agent 来操作** —— 这里的 Agent 指能够对你的文件系统和 shell 采取行动的模型，而不是只能聊天的模型。

它**不绑定任何单一的 Agent 产品**。兼容性以能力为依据：

| Agent 需要能够…… | 原因 |
|---|---|
| 读取仓库文件 | 遵循 `README.md`、`PROJECT_IDENTITY.md`、`AGENTS.md` |
| 运行 shell 命令 | FFmpeg、FFprobe、Python、测试套件 |
| 读写本地文件 | 任务状态、产出物、媒体暂存 |
| 执行 Python 与 FFmpeg 工作流 | 每个阶段都是本地的、确定性的 |
| 理解结构化 JSON 产出物 | 任务、审阅、证据、清单 |
| **在 Producer Gate 处停下** | 并向你询问，而不是自行猜测 |
| 遵守仓库的边界 | 媒体不进入 Git、不出现密钥、不使用与机器绑定的路径 |

具备相应能力的 Agent 示例包括 Codex、DeepSeek Harness、Claude Code，以及其他编码类或计算机操作类 Agent。**这些只是示例，并非要求，也不代表获得背书的集成。**

**只能聊天的模型无法操作本系统。** 没有文件系统和 shell 访问权限，它无法运行这条流水线，只能停留在讨论层面。

### 内部治理与对外兼容性

这是两件不同的事，而且两者都成立：

- **在内部**，经过验证的生产工作流使用 **Codex 作为顶层 Supervisor（监督者）**。创作决策权归属于此，系统的构建方式确保没有任何确定性组件去决定一支视频应当表达什么。
- **在对外层面**，只要架构允许，本仓库都力求保持 **Agent 无关（Agent-agnostic）**。控制路径中没有任何部分被硬性锁定到某一家厂商的 Agent。

---

## Agent 快速开始

把仓库地址和类似下面这样的提示词交给一个具备相应能力的编码 Agent：

```text
请按照仓库中的说明，在本机安装 Kang AI-AutoCut。

仓库地址：https://github.com/KanG-ciyuan/Kang-AI-AutoCut

在改动任何内容之前：
1. 阅读 README.md、PROJECT_IDENTITY.md 和 AGENTS.md。
2. 检查环境：Python、FFmpeg/FFprobe，以及代码实际导入的那些 Python 包。
3. 报告缺失的内容。未经我批准，不要安装任何东西。

然后：
4. 只使用逻辑角色和环境变量来配置本地工作区与媒体根目录。让媒体文件留在 Git 之外。
5. 绝不把 API key、token 或凭据写入任何被跟踪的文件、日志或提交中。
6. 在创建我的第一个视频任务之前，先运行仓库的自检。

当我们开始一个任务时：
7. 运行生产控制路径，并在每一个 Producer Gate 处停下。
8. 当某个门禁需要人工决策或创作批准时，向我询问。
9. 不要替我编造文案、艺术方向或声明。
```

**Agent 仍然需要手动完成的部分。** 目前的安装*并非*完全自动化：没有安装器，没有打包清单，也没有声明式的依赖锁定文件。Agent 必须检查环境、安装你已批准的前置依赖，并配置本地路径。本 README 的后续部分会准确列出哪些内容经过验证，而本仓库中并不存在 `pyproject.toml` 或 `requirements.txt` —— 这是已知的文档缺口，而不是某个隐藏步骤。

---

## 安装

### 已验证的前置条件

| 要求 | 状态 |
|---|---|
| **Python 3** | 已在 3.11.15 上验证。仓库未声明最低版本 —— 请把这一点视为缺口。 |
| **FFmpeg 与 FFprobe** | 必需。已在 ffmpeg/ffprobe 9.0.1 上验证。 |
| **`numpy`** | 媒体理解模块所需 |
| **`Pillow`** | 文字排版执行适配器所需 |
| **macOS** | 已在 macOS arm64 上验证。Windows 与 Linux **未**验证。 |

本仓库不存在 `pyproject.toml`、`setup.py` 或 `requirements.txt`，因此这里不声称任何版本锁定。请直接阅读代码的 import，而不要相信一个并不存在的锁定文件。

### 环境配置

```sh
git clone https://github.com/KanG-ciyuan/Kang-AI-AutoCut.git
cd AI-AutoCut

# Local configuration: resolves environment variables, never machine paths
cp config/examples/autocut.env.example .env.local
# edit .env.local: set AUTOCUT_MEDIA_ROOT and AUTOCUT_WORKSPACE
```

### 验证安装

```sh
# Full offline regression — no network, no media required
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests

# End-to-end execution proof — builds its own media, produces a real master
python3 scripts/run_pre_exam_proof.py --job-root /tmp/pre-exam-proof
```

这段验证程序刻意设计为两个阶段：它会停在人工放行门禁处，写入指明**已验证**母版的放行记录，然后继续执行直到完成。如果母版被删除或被改动，它会失败。

### 你的第一个任务

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

它会在第一个 Producer Gate 处停下，并告诉你接下来需要什么。

完整说明：[`docs/audit/execution-runbook.md`](docs/audit/execution-runbook.md)。

---

## Agent 与 LLM 兼容性

有四个不同的层次很容易被混为一谈。系统刻意把它们区分开来：

| 层次 | 它是什么 | 在本项目中 |
|---|---|---|
| **LLM** | 一个推理模型 | 可替换 —— 在确实用到模型的地方 |
| **Agent** | 一个模型**加上工具**，能够对本仓库采取行动 | 操作本系统所必需 |
| **Provider（服务商）** | 可选的、用于生成或智能分析的外部服务 | 可插拔；**非内置** |
| **执行引擎** | 确定性的本地 Python/FFmpeg 流水线 | 唯一被信任来报告某个步骤已成功的组件 |

**按设计不锁定厂商。** 控制路径调用的是确定性的本地模块。在涉及模型或服务商的地方，它只是一个通过已声明契约提供产出物的生产者 —— 因此更换模型或服务商不会改变这条流水线。

**但兼容性是能力问题，而不是品牌问题。** 一个无法读写文件、无法运行 shell 命令、或不遵守门禁的模型，无论推理能力多强，都无法操作本系统。

---

## 音频与 AI 服务商架构

当前仓库对任务所提供的音频素材执行**本地混音与母版制作**。它刻意**不**调用任何语音、音乐或音效服务商。音频合成在这里并未实现。

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

**今天已有的部分：** `BUILD THE AUDIO` 阶段消费任务本地的音频素材，依据任务自身的目标用 FFmpeg 对它们进行混音，并对结果加以度量。它会拒绝任何采样峰值达到满刻度的混音。

**不存在的部分：** 任何内置的服务商集成。这里没有一键语音生成，本仓库也不包含任何服务商客户端。

**历史背景，如实标注。** 在早前经过验证的生产工作中，旁白是通过 **MiniMax `speech-2.8-hd`** 产出的，另有一份前身任务清单记录了 **Doubao Seed Audio 1.0**。两者都是**历史上评估过的实验**，记录在 [`docs/providers/audio-provider.md`](docs/providers/audio-provider.md) 中 —— 它们不是当前内置的生产集成。它们的结论影响了音频策略；它们的客户端并不属于本仓库。

本仓库中任何位置都不出现密钥、token 或凭据的值。凭据仅通过环境变量名被引用。

---

## 商业与生产价值

价值在于架构本身，而不在于对结果的承诺：

- **可复用的工作流，而不是一次性的产出。** 面对下一个产品时，运行同一套生产流程，而不是新开一段对话。
- **可重复的生产。** 同样的阶段、契约与门禁适用于每一个任务，因此流程知识会不断积累，而不是转瞬即逝。
- **可审计的创作决策。** 每一个选择都是有证据的产出物，因此审阅可以追问*为什么*，而不只是*是什么*。
- **可续跑的任务。** 因门禁或失败而中止的任务，会从中断的那个阶段继续，而不是从头开始。
- **确定性的执行。** 渲染、抽取与度量都是本地的、可复现的；模型的声称从来不是证据。
- **源素材可复用。** 优质镜头可以支撑多个版本，而无需重新拍摄。
- **结构化的审阅与修复。** 修复针对受影响的层进行，而不是整体重新生成 —— 因此已获批准的剪辑不会被悄悄替换掉。
- **可度量的产出物校验。** 帧数、黑帧、冻结帧、响度、真峰值与母版摘要都是从文件本身度量得出的。
- **人工干预是可见的。** 系统会记录门禁何时开启、由谁处理、何时解决。
- **本地媒体所有权。** 源媒体不会被自动上传到云端流水线；控制路径与媒体处理都留在你的机器上，而经批准的外部服务商只接收任务明确需要的输入。
- **服务商灵活性。** 生成能力位于一道边界之后，因此服务商的选择是可替换的。

本文档**不**声称：质量有保证、转化率或收入结果有保证，也不声称剪辑时间一定会减少。这些都不是本仓库中任何内容所能证实的。

---

## 架构

| 文档 | 内容 |
|---|---|
| [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md) | 交互模型、生产控制路径、成熟度 |
| [`docs/architecture/supervisor-authority.md`](docs/architecture/supervisor-authority.md) | Codex Supervisor 的边界 |
| [`docs/architecture/backend-neutral-timeline.md`](docs/architecture/backend-neutral-timeline.md) | 一条时间线，三种后端 |
| [`docs/architecture/operations.md`](docs/architecture/operations.md) | 路径角色、ASCII 暂存、校验规则 |
| [`docs/contracts/`](docs/contracts/) | 冻结的契约 |
| [`docs/policies/`](docs/policies/) | 剪辑、镜头、排版、音频与审阅策略 |
| [`docs/decisions/`](docs/decisions/) | 架构决策记录 |
| [`docs/audit/production-chain-manifest.md`](docs/audit/production-chain-manifest.md) | 逐项能力的接线与就绪度 |
| [`docs/audit/execution-runbook.md`](docs/audit/execution-runbook.md) | 如何运行每一处边界 |
| [`docs/audit/gate-g0-history.md`](docs/audit/gate-g0-history.md) | 冻结基线是如何达成的 |

### 仓库结构

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

## 本地优先设计

本地优先是一项硬性要求，而不是一个临时状态。生产控制路径与全部媒体处理都在本机运行，使用 Python、FFmpeg/FFprobe 与本地文件系统，并以确定性的方式编排。经批准的外部 AI API 可用于选定的智能分析或生成任务；它们永远不是控制路径。云基础设施 —— 对象存储、服务器平台、分布式 worker、仪表盘、用户账号 —— 被刻意排除在外。参见 [ADR-0007](docs/decisions/ADR-0007-local-first.md)。

本仓库中不出现任何与机器绑定的绝对路径。每一个运行时位置都是一个逻辑角色，由环境变量解析得出；参见 [`docs/architecture/operations.md`](docs/architecture/operations.md) 与 [`config/examples/autocut.env.example`](config/examples/autocut.env.example)。

---

## 当前状态

| | |
|---|---|
| 冻结基线 | `pre-third-sku-blind-v1` → `b65a73b53040bd1ff5defe25e624a28f623b6847` |
| 冻结状态 | `CLOSED_AND_FROZEN` |
| 考核有效性 | `PASS_WITH_EXPLICIT_PRODUCER_GATES` |
| 下一个计划中的生产阶段 | Third-SKU 盲测 —— **尚未开始** |

一条可用的**带门禁的生产控制路径**已经存在，并已产出真实的、经过独立验证的交付母版。它不是无人值守的一键剪辑器，也从未声称自己是。

---

## 已知限制

- **不是无人值守的单命令剪辑器。** Producer Gate 会按设计中止运行，其中一些需要人或 Agent 介入。
- **没有自动化的商业审阅器。** 审阅契约记录判断，但它本身不产生判断。
- **画面测量与产品保护由任务产出。** 本仓库不附带测量工具，而且保护容差校验尚未在真实数据上运行过 —— 已被证明的是这道门禁会拒绝，而不是会评估。
- **`CORRECT` 画面分支从未在生产运行中触发过。**
- **没有内置的音频服务商。** 合成并未实现；流水线消费任务本地的素材。
- **文字排版证明的是执行，而不是艺术方向。** 没有屏幕文案层级规划器，也没有产品遮挡校验；版式由任务自行提供。
- **执行验证使用的是本地生成的音频。** 它证明的是混音与母版制作路径，而不是真实的人声演绎。
- **没有产出物注册表，也没有任务队列。** 大量的暂存数据需要手工清理。
- **没有通用后端编译器。** `compile_for_backend` 对每一个后端都会抛出异常；执行改为通过任务作用域的适配器完成。
- **没有声明式的依赖清单。** 不存在 `pyproject.toml` 或锁定文件。
- **仅在 macOS 上验证过。** Windows 与 Linux 尚未测试。
- **已跟踪、尚未解决：** 运行感知的视觉分段（C-01）与自动化的选定区间校验（"needs vision"）。

---

## 路线图

1. **针对 `pre-third-sku-blind-v1` 运行 Third-SKU 盲测。**
2. 度量最终质量、Producer Gate 的出现频率，以及人工干预情况。
3. 用盲测得到的证据来决定：接下来值得自动化的剩余任务产出型能力有哪些。

冻结基线就是要**以冻结状态**接受考察：在盲测之前不安排任何考前自动化工作，因此这次考核度量的是那个已被接受的系统，而不是一个在它脚下仍在变动的系统。

---

## 冻结基线

```
tag             pre-third-sku-blind-v1
target commit   b65a73b53040bd1ff5defe25e624a28f623b6847
```

**这里“冻结”的含义：** 存在一个可复现的考前基线。被打上标签的那个提交，就是当时经过审计并被接受的精确系统，因此下一次考核运行可以对照一个已知状态来比较，而不是对照对它的记忆。

**它不意味着：** 产品已经完工、每项能力都已自动化，或者系统已经生产完备。文档类提交可能在打标签之后落到 `main` 上；标签本身不会移动。

---

## 许可证

**Apache-2.0。** 完整许可证文本见 [LICENSE](LICENSE)。许可证选型理由、不提供 `NOTICE` 的决定，以及仍留待后续阶段处理的事项，记录在 [LICENSE_DECISION_PENDING.md](LICENSE_DECISION_PENDING.md)。

---

## 规范身份信息

- 项目 ID：`ai-autocut`
- 默认分支：`main`
- 运行时数据根目录：逻辑角色 `AUTOCUT_WORKSPACE`
- 媒体根目录：逻辑角色 `AUTOCUT_MEDIA_ROOT`

机器可读的身份记录见 [PROJECT_IDENTITY.md](PROJECT_IDENTITY.md)。Agent 入口规则见 [AGENTS.md](AGENTS.md)。
