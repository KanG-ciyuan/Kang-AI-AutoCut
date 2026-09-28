![Kang AI-AutoCut 概念视觉：原始素材、剪辑时间线与审片成片](assets/showcase/kang-ai-autocut-production-hero-v2.png)

# Kang AI-AutoCut

**真实素材 → 可追溯的生产过程 → 人工验收的成片**

Kang AI-AutoCut 是由 Agent 统筹、本地优先的商业视频生产系统：产品事实、创作决策、
画面、声音、字幕、技术检查与人工放行，都有可追溯的任务记录。

<table>
  <tr>
    <td width="72%" valign="top">
      <strong>真实 SKU 生产 · HUMAN FINAL REVIEW：PASS</strong><br><br>
      <strong>气垫粉扑 / Indonesia TikTok Commerce</strong><br>
      24 秒竖屏视频 · 1080 × 1920 · 30 fps · 12 个剪辑片段<br><br>
      卖家确认的产品事实 → 获批商业文案 → 固定 Creator Reference Voice 与选定 VO → 画面剪辑 → 标题和口播字幕 → 最终渲染。<br><br>
      <a href="docs/audit/cushion-puff-production-state.md">查看生产记录与证据边界</a>
    </td>
    <td align="center">
      <img src="assets/showcase/cushion-puff-human-pass-frame.jpg" width="185" alt="Human PASS 气垫粉扑成片的真实画面，展示产品和印尼语标题、字幕">
    </td>
  </tr>
</table>

*横幅是系统概念视觉；上方产品画面取自获批的真实成片。*

**原素材说明：** 这条视频使用已获授权复用、画面质量参差的现成素材，因此成片画面与剪辑选择受到原素材制约；拍摄质量更好的素材能为后续剪辑提供更好的基础。

**Languages:** [English](README.md) | 简体中文 | [日本語](README.ja.md) | [한국어](README.ko.md) | [Bahasa Indonesia](README.id.md) | [Deutsch](README.de.md) | [Español](README.es.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3-3776AB)](README.md#installation)
[![FFmpeg](https://img.shields.io/badge/ffmpeg-required-007808)](README.md#installation)
[![Local-first](https://img.shields.io/badge/local--first-yes-4c1)](docs/decisions/ADR-0007-local-first.md)
[![Agent-oriented](https://img.shields.io/badge/agent--oriented-yes-8957e5)](README.md#use-with-an-ai-agent)
[![Tests](https://img.shields.io/badge/tests-1933%20passing-brightgreen)](README.md#installation)
[![macOS](https://img.shields.io/badge/macOS-tested-000000)](README.md#installation)
[![Baseline](https://img.shields.io/badge/baseline-pre--third--SKU-orange)](README.md#frozen-baseline)

*徽章为静态徽章，描述的是冻结基线。本仓库不运行任何 CI 工作流，徽章上的数字并非实时状态。*

商业广告是第一个经过生产验证的工作流。系统接收已获授权的素材和创作目标，
按任务推进素材理解、剪辑、排版、音频、母版制作与审阅；人工批准仍是明确的门禁。
本地控制路径与媒体处理不会把未完成的步骤报告为成功。

---

## 项目定位

**把一整个原始素材文件夹和一份 Producer Brief 交给 Kang AI-AutoCut。**

这条有人监督、本地优先的工作流可以理解素材、规划并完成剪辑、协调任务内编写的
商业文案与外部服务商提供的音频、渲染排版、审阅实测结果，再把视频交给人批准。
多版本规划只是其中一项可选能力。

它不是全自动视频工厂。工作流有**两道主要人工审批门禁（Human approval gates）**：

- **Creative Copy Approval（创意文案审批）**
- **Producer 终审**

这并不表示整条流程只有两处会停下。八阶段 Fast Path 在缺少必要的决策或产出物时，
还会触发具名的 `HUMAN`、`CODEX` 或 `ADAPTER` Producer Gate。

---

## 真实 SKU 生产证据

**气垫粉扑 / Indonesia TikTok Commerce（SKU #2）：Human Final Review PASS。**
这条 24 秒竖屏视频完成了 Product Truth 与 Seller Confirmation、视觉证据与
宣称边界审阅、经批准的 Commercial Copy、固定 Creator Reference Voice 与选定
VO、画面规划和剪辑、标题与口播字幕、最终渲染，并通过 **Human Final Review：PASS**。
人工批准绑定的是精确的最终成片，不代表普遍的质量保证。详见
[生产状态与证据边界](docs/audit/cushion-puff-production-state.md)。

母版与原始素材仍保存在 Git 之外的生产工作区；本仓库不发布视频预览或母版。
这一里程碑证明的是有人参与决策的真实 SKU 生产流程，不代表无人值守运行，
也不声称正式八阶段 Fast Path 的每一道门禁都已通过。

更早的**水龙头过滤器（SKU #1）**已有[Filter Gold v1](docs/gold/filter-gold-v1.md)
记录的 Gold 生产结果。气垫粉扑是较新的人工批准成片，并非第一个真实 SKU。
`pre-third-sku-blind-v1` 是在前两个 SKU 历史之后冻结的第三 SKU 考核基线；
标签名称不改变前两个产品的编号。

---

## 真实生产流程：八阶段 Fast Path

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

## Producer 参与环节

工作流围绕真实的人类决策设计，而不是围绕消除它们。

```
Producer Brief → 八阶段 Fast Path → 具名 Producer Gate → 人工放行
```

目前有**两个主要 Human approval gates**，分别承担创意与放行决定：

| 门禁 | Producer 决定什么 |
|---|---|
| **Creative Copy Approval（创意文案审批）** | 文案内容，以及视频被允许做出的宣称 |
| **Producer 终审** | 作品是否发布 |

它们并非仅有的停点。八阶段 Fast Path 还可能因缺少必要的决策或产出物，
触发 `HUMAN`、`CODEX` 或 `ADAPTER` Producer Gate。素材理解、剪辑规划、
画面、排版、音频、母版、QA 与修复都在这些明确合约下推进。
这是 **Producer-in-the-loop**，不是无人值守的自动化。
## 为什么重要

大多数 AI 视频工具是在聊天窗口里**一次性产出一个视频**。重新运行会得到另一个不同的视频，而且整个过程无从审查。

价值在于可复用、可追溯的生产记录：Agent 负责创作判断，本地工具执行和度量媒体，
人批准宣称与最终成片。项目不承诺仅凭自动化就能提高转化率或成片质量。

Kang AI-AutoCut 把视频生产视为一条**可审计的工程工作流**：

| 普通 AI 视频产出 | Kang AI-AutoCut |
|---|---|
| 一次性结果，难以重复 | 一条可以再次运行的可复用工作流 |
| 决策散落在聊天记录里 | 每一个决策都是被记录的产出物 |
| 失败就意味着从头再来 | 任务从中断的那个阶段继续 |
| 唯一的检查是“看起来做完了” | 产出物被度量：帧数、黑帧、冻结帧、响度、真峰值、母版哈希 |
| 模型可能悄悄跳过某个步骤 | 一个阶段**若不指明它所运行的能力，就无法通过** |
| 人的判断无处可见 | 人工输入发生在具名的门禁处，并被记录在案 |
| 媒体和服务商输入去向可能难以追溯 | 处理过程本地优先；获批准的服务商只接收任务所需的输入 |

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

## 当前能力与接线状态

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
| 文字排版渲染 | 任务产出的标题及可选、与最终 VO 对齐的口播字幕；两者已用于气垫粉扑成片 |
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

Commercial Strategy v1、Commercial Intelligence v1 与 Commercial Copy v1 仍为
**`CONTRACT_ONLY / NOT_WIRED`**：已有 schema、校验器、样例与测试，但生产路径中
没有注册的 Producer 自动生成这些内容。真实气垫粉扑生产中，Agent 在任务内编写了商业策略和
本地化文案，由人工批准最终文案与宣称边界。这一任务级实践已经用于生产，
并不意味着正式 v1 Commercial 合约已接入自动生成路径。

### 计划中 / 可扩展

尚未实现，也未作任何声称：自动化商业审阅器、通用后端编译器、产出物注册表、任务队列、无人值守的单命令运行器，以及更广泛的内容模式工作流。

---

## 多版本生产

同一个素材池可以产出**多个商业上彼此区分的版本**。每个版本都独立重新考虑整个素材池，而不是继承上一个版本的时间线：

- 重新考虑**每一个**候选片段，不机械继承上一个版本的时间线
- 在商业上成立时，**可以**复用表现优秀的素材
- 以往的使用情况作为**软性多样性信号**，而不是禁止条件
- 候选质量相当时，优先选择使用较少的素材
- **绝不**仅仅为了提高去重率而牺牲商业质量

> **有商业意义的差异，优先于人为的最大化差异。**

版本之间可以在 Hook、叙事角度、镜头选择、镜头顺序、镜头边界、节奏、配音、排版文案、BGM、音效与商业强调点上形成差异。这不是"一份时间线渲染出多个版本"。

![Kang AI-AutoCut 早期概念图：从原始素材到多个营销版本的预期生产流程](assets/showcase/kang-ai-autocut-hero.png)

*这是项目早期的概念视觉，展示预期工作流；它不是实际生产成果，也不代表图中每项能力都已接入。*

---

## 剪辑智能

```
候选窗口
    ↓  内部视觉切点检测
视觉片段
    ↓  语义 / 动作分组
时间线镜头
```

**候选边界 ≠ 时间线边界**，并且**先理解，后切割**：素材先被理解，然后才被剪。素材决定它能支撑多长的叙事 —— 目标时长不会反过来强迫素材填满时间线。

> **内容驱动的时长。** 这里刻意不存在通用的固定最短镜头时长。

完整契约见 [`docs/policies/editing-intelligence.md`](docs/policies/editing-intelligence.md)。

---

## 音频智能

每一层音频回答不同的问题：

| 层 | 作用 |
|---|---|
| 画面 | 证据 |
| 标题 | 卖点总结 |
| 配音 | 营销解释 + 销售叙事 |
| BGM | 情绪 + 节奏 |
| 音效 / 环境声 | 真实感 + 动作强调 |

声音按以下方式设计：

```
视觉事件  →  声音事件  →  时间  →  混音
```

> **声音必须具备画面或叙事上的依据。**

不会因为场景是浴室就自动铺上水声。画面上出现真实的流水或冲洗，才可以有对应的水声；看到真实的湿搓动作，才可能有克制的搓洗质感；而没有任何水源在画面中的产品 Hero 展示，不应自动加入明显的水声。

混音优先级为 **人声 > 证据声 > 音乐**。

完整策略见 [`docs/policies/audio-intelligence.md`](docs/policies/audio-intelligence.md)。

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

**当前生产服务商。** 生产音频由 **Doubao / Seed Audio** 生成，已验证模型为 **`seed-audio-1.0`**，用于印尼语配音、BGM 以及生成的音效 / 环境声。该服务商客户端位于本仓库之外；本仓库只对任务本地素材做本地混音与母版制作，不附带合成客户端。

气垫粉扑的生产流程固定了 Creator Reference Voice，按任务获批文案生成多条 VO Take，
由**人工实际试听并选定最终 Take**。这是已执行的生产实践，并非仓库内置的语音生成或
试听选择客户端。仓库消费选中的任务本地音频进行混音与母版制作；见
[Voice Profile](docs/providers/indonesia-beauty-creator-voice-v1.md)。

**历史背景，如实标注。** 在早前经过验证的生产工作中，旁白是通过 **MiniMax `speech-2.8-hd`** 产出的。那是**过去**的评估，记录在 [`docs/providers/audio-provider.md`](docs/providers/audio-provider.md) 中；MiniMax **不是**当前的生产服务商。macOS `say` 同样不是生产服务商。

本仓库中任何位置都不出现密钥、token 或凭据的值。凭据仅通过环境变量名被引用。

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
| **FFmpeg 与 FFprobe** | 必需。生产路径最低 4.4.2；完整离线测试套件需 5.1.2 或更新版本。端到端已在 5.1.2、6.1.2、9.0.1 上验证。 |
| **`numpy`** | 媒体理解模块所需 |
| **`Pillow`** | 文字排版执行适配器所需 |
| **macOS** | 已在 macOS arm64 上验证。Windows 与 Linux **未**验证。 |

本仓库不存在 `pyproject.toml`、`setup.py` 或 `requirements.txt`，因此这里不声称任何版本锁定。请直接阅读代码的 import，而不要相信一个并不存在的锁定文件。

**两种 FFmpeg 门槛各有实测依据。** 4.4.x 的 `frame=pts_time` 可能全部为空值，
时间戳读取器会回退到已核对一致的 `best_effort_timestamp_time`；低于 4.4 的版本会被拒绝。
测试用 VFR 素材所需的 `-fps_mode` 在 4.4.2 和 5.0.1 中不存在、从 5.1.2 起可用，
因此较旧工具链可运行生产路径，但相关测试会注明原因后跳过。详见
[`tests/test_tool_version_gate.py`](tests/test_tool_version_gate.py)。

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

以下命令是仓库支持的任务初始化与八阶段控制路径入口。仓库另有一次启动的编排器，
但它仍会在 Producer Gate 处暂停，并依赖任务内编写的输入；见
[执行说明](docs/audit/execution-runbook.md)。

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

## 当前状态

| | |
|---|---|
| 冻结基线 | `pre-third-sku-blind-v1` → `b65a73b53040bd1ff5defe25e624a28f623b6847` |
| 冻结状态 | `CLOSED_AND_FROZEN` |
| 考核有效性 | `PASS_WITH_EXPLICIT_PRODUCER_GATES` |
| 已通过生产验证的范围 | 商业广告 / 电商视频 |
| 回归测试套件 | 2026-09-28 共 1,933 项通过，离线运行，无需网络 |

一条可用的**带门禁的生产控制路径**已经存在，并已产出真实的、经过独立验证的交付母版。它仍然不是无人值守的一键剪辑器，也从未声称自己是 —— Producer 决策按设计仍是流程的一部分。

更早的**水龙头过滤器（SKU #1）** Gold 与获人工批准的**气垫粉扑（SKU #2）**
是两段不同的生产历史。上方标签标记的是第三 SKU 盲测前冻结的工程基线，
不是第一个生产里程碑。气垫粉扑验证的是该次有人参与的成片，不会让
合约阶段的 Commercial 模块变成已接入的生成器。

---

## 已知限制

- **不是无人值守的剪辑器。** 一次启动现在可以端到端驱动一个任务，但 Producer Gate 仍会按设计中止运行。
- **没有自动化的商业审阅器。** 审阅契约记录判断，但它本身不产生判断。
- **画面测量与产品保护由任务产出。** 本仓库不附带测量工具，而且保护容差校验尚未在真实数据上运行过 —— 已被证明的是这道门禁会拒绝，而不是会评估。文字排版位置所需的遮挡证据同样由任务产出。
- **`CORRECT` 画面分支从未在生产运行中触发过。**
- **本仓库不附带音频服务商客户端。** 生产音频由外部服务商生成（见下）；本仓库的流水线消费任务本地的素材。
- **文字排版的艺术方向锁定在单一基线上。** `Typography Art Direction A v1` 定义了设计语言、封闭的区域集合与审阅器；任务选择它，而不是自行发明视觉风格。位置证据由任务产出 —— 系统消费遮挡证据，但本身不测量遮挡。
- **执行验证使用的是本地生成的音频。** 它证明的是混音与母版制作路径，而不是真实的人声演绎。
- **没有产出物注册表，也没有任务队列。** 大量的暂存数据需要手工清理。
- **没有通用后端编译器。** `compile_for_backend` 对每一个后端都会抛出异常；执行改为通过任务作用域的适配器完成。
- **没有声明式的依赖清单。** 不存在 `pyproject.toml` 或锁定文件。
- **仅在 macOS 上验证过。** Windows 与 Linux 尚未测试。
- **已跟踪、尚未解决：** 运行感知的视觉分段（C-01）与自动化的选定区间校验（"needs vision"）。
- **Editing Intelligence vNext 仍在 shadow 路径。** `candidate_evidence.v1/v2` 与
  `hook_decision.v1` 可以在影子流程中生成；`planning_evidence.v1` 仍只是经过校验和测试的
  contract-only 文档。它们都没有接入正式生产路径或产出镜头序列，详见
  [`docs/contracts/`](docs/contracts/)。
- **候选分析与 Hook 决策的证据边界。** `VNEXT_SHADOW` 能从实测素材构建候选、校验
  窗口并生成结构化证据。可选的实时多模态分析脚本不属于离线测试；一次开发期间的
  模型运行未在本仓库保存可独立核验的产出物，不能把它宣传为已验证的生产结果。
  `candidate_evidence.v2` 记录 `NO_ACTION`、`PROBLEM_STATE_VISIBLE` 等视觉观察，
  但像素统计不能证明语义或商业宣称，后者仍受 Product Facts 约束。
- **Hook 选择不等于自动写广告。** 模型单次调用对 2–5 个不同假设排序，确定性门禁
  只否决不符合声明事实、候选与证据约束的选项，不自行重新排名。若多个角度都合格，
  `selected_hook_id` 保持待定，由负责人选择；它不生成镜头顺序、时间线、配音、字幕
  或最终 CTA。

---

## 路线图

1. **补齐仍由任务产出的证据。** 文字位置与画面遮挡的证据目前由任务提供；合约能够承载，但尚无 Producer 自动测量。
2. **在证据支持的范围内减少人工介入**，同时保留真正需要人决策的 Producer Gate。
3. **扩展已验证范围**，在商业视频工作流稳定后再考虑其他内容类型。

冻结基线仍然按冻结时的状态接受考察；它记录的是当时经过审计的精确系统，
不自动代表当前 `main` 上后续工作的完成状态。

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
