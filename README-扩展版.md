<img src="docs/banner.svg" alt="Jev Ultrafast · Browser Use × TypeSafe" width="100%" />

# Jev Ultrafast 技术方案与使用说明

> 本文档为 `README.md` 的扩展版，用于方案分享与评审。在原文基础上补充三部分内容：
> 自然语言输入后的自动化决策闭环、决策模型的本地方案、以及后续演进方向。
> 原版见 [README.md](README.md)，英文版见 [README_en.md](README_en.md)。

> 本分支相对上游 `browser-use/jev-ultrafast` 的变更：端点与模型可配置、自然语言任务入口、
> 运行观察台、`ENTER` 操作、Windows 编码修复，以及提交前凭据校验。

## 方案定位

以自然语言描述任务目标，由系统自主完成页面导航、元素定位、操作执行与结果判定，**全过程无需人工指定页面元素或操作步骤**。

决策由 TypeSafe 的 Jev 模型（`jev-1.13.0`）承担；页面感知与操作执行由确定性代码完成；仅当任务需要输入文本时，才调用一个辅助语言模型生成字段值。截图仅用于运行观测，不参与决策。

## 自然语言输入后的自动化决策闭环

**自接收自然语言指令至输出运行结果，全过程无需人工介入。** 该特性与同源项目 browser-use 一致；二者差异不在于是否需要人工参与，而在于决策所依据的页面表征。

自动化决策分为三个层面：

| 层面 | 决策方 | 决策内容 |
| --- | --- | --- |
| **任务入口** | 本地解析（正则实现，不消耗模型调用） | 由指令确定起始 URL 与任务目标 |
| **每一步** | 决策模型 + 确定性校验 | 从 9 个操作中选择一个，并从页面快照的数十个元素中确定目标；随后执行**新鲜度校验**（页面状态变化即重新决策）与**几何命中校验**（目标被遮挡即拒绝执行） |
| **终止判定** | 决策模型 + 确定性校验 | `DONE`（模型判定目标达成）/ `BLOCKED`（无可用操作推进）/ 预算耗尽 / 连续 3 步页面状态未变化 |

即：**指令给定后，无需人工指定任何页面元素或操作步骤。** 这是本方案与传统脚本自动化（硬编码 selector、固定步骤）的本质区别，也是其与 browser-use 共有的能力。

### 与 browser-use 的差异：决策所依据的页面表征

两条路线均为全程自动化，差异在于**可见范围**：

| | browser-use | jev-ultrafast |
| --- | --- | --- |
| 页面输入 | 编号化 DOM 快照 **+ 截图** | 仅 DOM 文本 |
| 决策模型 | 多模态 LLM（`use_vision` 默认 `True`） | 专用分类模型（Jev） |
| 单步成本 | 图像编码 + 多模态推理 | 一次轻量分类（150 ms ~ 2.2 s） |
| canvas / 图表 / 纯图形元素 | 可感知 | 不可感知 |

**建议按流程特征分流**：常规表单、表格、列表、菜单类操作使用 jev-ultrafast（延迟与成本优势显著）；
canvas、图表、富文本编辑器等 DOM 中不存在的内容，使用 browser-use。

### 人工介入点

| 环节 | 人工职责 |
| --- | --- |
| 运行前 | 编写任务描述：明确操作对象、目标终态、可观察的成功特征 |
| 运行中 | **无需介入**；仅当出现验证码（`blocked`）时需要人工处理 |
| 运行后 | 核验业务结果 —— `DONE` 是模型判定，不代表业务成立；断言必须落在最终页面状态上 |

---

## 目录

1. [能力范围与边界](#1-能力范围与边界)
2. [环境准备](#2-环境准备)
3. [端点配置](#3-端点配置)
4. [运行验证](#4-运行验证)
5. [运行观察台](#5-运行观察台)
6. [指令句式](#6-指令句式)
7. [命令参考](#7-命令参考)
8. [故障排查](#8-故障排查)
9. [动作空间](#9-动作空间)
10. [编程接口](#10-编程接口)
11. [工程规范与测试](#11-工程规范与测试)
12. [后续演进方向](#12-后续演进方向)

---

## 1. 能力范围与边界

### 执行流程

```
自然语言指令  →  本地解析为「起始 URL + 任务目标」  →  页面感知（编号元素表）
             →  Jev 决策「操作 + 目标元素」          →  确定性执行
             →  需要文本时调用辅助模型生成           →  循环，直至 DONE / BLOCKED / 预算上限
```

关键约束：**决策仅基于结构化元素表，不使用截图**。截图仅服务于运行观测。

### 能力范围

| 能力 | 说明 |
| --- | --- |
| 自然语言任务入口 | 由指令解析起始 URL（百度、必应、知乎、GitHub、维基等）与任务目标 |
| 真实浏览器执行 | 通过 CDP 驱动本机 Chrome，页面完整渲染，非无头爬虫 |
| 表单交互 | 点击、输入、回车提交、下拉选择 |
| 过程可观测 | 每步的候选元素、操作概率、目标概率与实际动作均有记录 |
| 故障可定位 | 环境异常约 1 秒内报错并给出修复命令，不表现为超时 |

### 边界与限制

| 限制 | 表现 |
| --- | --- |
| 验证码无法绕过 | 百度对全新 profile 必然返回安全验证页，模型**正确判定 `blocked`**，不会误操作 |
| 截图非决策依据 | 截图依赖渲染进程，繁忙时可能获取失败（不影响任务） |
| 不支持 iframe / shadow DOM / canvas / 文件上传 / 新标签页 | 上述元素不在快照范围内 |
| 长按 / 组合键 / 悬停菜单类交互 | 不在动作空间内 |
| 单页元素超过 250 个 | 超出部分被截断 |

---

## 2. 环境准备

### 方式一：脚本安装（推荐）

```bash
cd jev-ultrafast
bash scripts/setup_venv.sh              # Git Bash / macOS / Linux
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_venv.ps1   # PowerShell
```

脚本依次完成：创建 `.venv`、安装依赖、复制 `.env.example` 为 `.env`（若不存在）、以可编辑模式安装本包，最后执行 `jev-doctor`。

| 开关（Bash / PowerShell） | 作用 |
| --- | --- |
| 无 | 安装运行 + 开发依赖（含 pytest、ruff） |
| `--no-dev` / `-NoDev` | 仅安装运行依赖 |
| `--exact` / `-Exact` | 严格按 `requirements.lock.txt` 安装，用于环境复现 |
| `--recreate` / `-Recreate` | 删除 `.venv` 并重建 |
| `--mirror URL` / `-Mirror URL` | 指定 PyPI 镜像 |

> **注意**：`browser-harness==0.1.13` 仅存在于 `pypi.org`，清华镜像源停留在 `0.0.1`。
> 若镜像安装失败，请追加 `--mirror https://pypi.org/simple`。

### 方式二：手动安装

```bash
python -m venv .venv
source .venv/Scripts/activate          # Git Bash
.venv\Scripts\activate.bat             # cmd
.venv\Scripts\Activate.ps1             # PowerShell
pip install -e .
```

---

## 3. 端点配置

全部配置位于项目根目录 **`.env`**（已被 `.gitignore` 忽略，不会进入仓库）。解析优先级：**显式环境变量 > 服务预设 > 内置默认值**。

### 3.1 决策端点：协议选择

| 协议 | 端点 | 是否需要密钥 | 单次决策请求数 |
| --- | --- | --- | --- |
| `classifier`（默认，推荐起步） | `https://classifier.dev/` | **否** | 1 次；当选中操作存在多个候选元素时 2 次 |
| `typesafe` | `{base}/v1/systemone` | 是 | 1 次，操作与目标两个 head 同时返回 |

两者背后是**同一模型**（classifier.dev 响应中标注 `"model": "jev-1.13.0"`、`"provider": "typesafe"`），仅线上格式不同。

免密钥接入：

```dotenv
JEV_BACKEND=classifier
CLASSIFIER_URL=https://classifier.dev/
```

> **必须直连**。classifier.dev 的匿名额度仅接受直连流量，经代理访问会返回
> `{"code":"proxy_requires_payment"}`。因此该端点**主动忽略 `HTTP_PROXY`/`HTTPS_PROXY`**，
> 除非显式设置 `CLASSIFIER_USE_ENV_PROXY=1`（该模式需要付费密钥）。

使用 TypeSafe 密钥时：

```dotenv
JEV_BACKEND=typesafe
TYPESAFE_API_KEY=你的key
TYPESAFE_MODEL=jev-latest
# TYPESAFE_BASE_URL=https://api.typesafe.ai
# TYPESAFE_PATH=/v1/systemone
```

### 3.2 文本辅助模型端点

仅在任务需要「输入文本」的步骤调用。任何 OpenAI 兼容的 `/chat/completions` 服务均可。

```dotenv
TEXT_MODEL_BASE_URL=https://api.deepseek.com/v1
TEXT_MODEL_API_KEY=sk-xxxx
TEXT_MODEL=deepseek-chat
TEXT_MODEL_REASONING=off          # none | off | low | medium | high | 原始 JSON
TEXT_MODEL_JSON_MODE=auto         # auto | on | off；服务不支持 response_format 时设为 off
```

也可通过 `TEXT_MODEL_PROVIDER` 直接使用内置预设：

`openrouter` `openai` `deepseek` `siliconflow` `dashscope` `moonshot` `zhipu` `ollama` `vllm` `lmstudio`

本地模型（免密钥）：

```dotenv
TEXT_MODEL_PROVIDER=ollama
TEXT_MODEL_BASE_URL=http://127.0.0.1:11434/v1
TEXT_MODEL=qwen2.5:7b
```

### 3.3 端点验证

```bash
jev-doctor          # 输出生效配置与就绪状态（每个失败项附带修复命令）
jev-doctor --live   # 额外向每个端点发送一次最小真实请求
```

**配置生效不代表端点可用。** 实测案例：某网关 `GET /v1/models` 返回 200，但所有对话请求均在 50 ms 内返回 `HTTP 500 do_request_failed` —— 只有 `--live` 能暴露此类问题。

### 3.4 将决策模型替换为本地服务（内网 / 离线）

决策已抽象为一个窄契约，任何本地服务实现该形状即可替换 Jev，**循环、动作空间与校验逻辑均无需改动**：

```jsonc
POST {CLASSIFIER_URL}
  { "input": "<页面 + 元素表 + 目标 + 问题>", "labels": ["操作或元素编号..."] }
→ { "results": [{ "label": "...", "scores": {...} }] }
```

```dotenv
JEV_BACKEND=classifier
CLASSIFIER_URL=http://127.0.0.1:8000/classify
TEXT_MODEL_BASE_URL=http://127.0.0.1:8000/v1
TEXT_MODEL=本地模型名
```

`scripts/mock_provider.py` 为最小实现样例，参照其编写适配器约需 100 行。
替换前应先建立**回放集**：将每次运行的 `page` 导出、人工标注正确的 `(operation, target)`，
对比新旧后端的**逐步准确率** —— 仅看端到端成功率无法区分"模型选错"与"页面状态变化"。

---

## 4. 运行验证

```bash
# 1. 准备可驱动的浏览器
jev-browser start              # 启动专用 profile 的 Chrome 窗口
jev-browser start --headless   # 无窗口模式

# 2. 零密钥端到端验证（不产生费用、不访问外部站点）
jev-selftest

# 3. 执行一条真实任务
jev-run "bing 上海天气"
```

`jev-selftest` 自动启动两个 mock 端点与一个本地页面，驱动真实浏览器完成「输入 → 提交 → 完成」。
**建议先执行自检再排查配置** —— 9 项全部通过，即证明本机链路（除外部服务外）均正常。

若仅需验证决策端点，页面与文本辅助仍使用本地桩：

```bash
jev-selftest --real-decision
```

### 专用浏览器的必要性

常规方式启动的 Chrome 不暴露 CDP 端口，且新版 Chrome 禁止在默认 profile 上开启远程调试。`jev-browser` 以**独立 profile + 独立端口（9333）**启动，并将地址记录至 `~/.jev/browser.json`，后续 `jev-run` 自动读取，**无需导出任何环境变量**。

```bash
jev-browser status    # 可达性、浏览器二进制、profile、端口/PID
jev-browser stop
jev-browser restart
```

---

## 5. 运行观察台

命令行输出为 JSON，不便于过程观测。观察台提供本机 Web 界面：

```bash
jev-ui --open --launch-browser
```

默认地址 `http://127.0.0.1:8788`，在输入框输入指令回车即运行。

![运行观察台](docs/ui-screenshot.png)

| 面板 | 内容 |
| --- | --- |
| 解析结果 | 指令解析出的起始 URL 与任务目标；未显式指定引擎时的假设同样记录于此 |
| 当前页面 | 浏览器实际截图，**每个元素按编号框出**，选中的目标以绿色框标注 |
| 最近一次决策 | 操作、目标、置信度、耗时，以及操作概率与目标概率两组分布图 |
| 可操作元素 | 模型实际从中选择的编号表，每行标注该元素支持的操作 |
| 动作日志 | 每步的操作 / 目标 / 生成文本 / 概率 / 累计耗时 |
| 文本模型调用 | 字段名、生成的值、所用模型、耗时 |

其他参数：

```bash
jev-ui --port 8790 --instruction "百度搜索 上海天气"   # 预填指令输入框
jev-ui --launch-browser --headless                    # 无可见窗口
```

安全机制：仅监听回环地址，每次 POST 请求必须携带页面内的进程级令牌，仅接受本机请求。

---

## 6. 指令句式

指令解析在**本地**完成，不消耗模型调用。按以下顺序匹配：

| 句式模式 | 起始 URL |
| --- | --- |
| 指令中包含 `http(s)://…` | 使用该 URL，剩余部分作为任务目标 |
| `打开 example.com` / `open example.com` | `https://example.com` |
| `<引擎> <动词> <关键词>`：`百度搜索 上海天气`、`在知乎搜索 咖啡`、`github search llm` | 对应引擎的结果页 |
| `<动词> <关键词>`，未指定引擎：`搜索 上海天气` | `JEV_DEFAULT_SEARCH_ENGINE`，默认 baidu |
| `<引擎> <关键词>`：`bing 上海天气`、`google llm benchmarks` | 对应引擎的结果页 |
| 以上均不匹配 | 以默认搜索引擎检索整句 |

支持的引擎别名：`百度` `bing` `必应` `google` `谷歌` `搜狗` `360` `so` `duckduckgo` `知乎` `微博` `bilibili` `淘宝` `京东` `github` `youtube` `wikipedia` `维基`

已验证的解析行为：

- 仅有引擎而无关键词（如 `百度搜索`）时直接报错并提示补充关键词，不会以截断后的词执行检索。
- `bing 上海天气` 的关键词为「上海天气」，不会被句式后缀截断为「海天气」。
- 未指定引擎时，`plan.notes` 会记录「按默认引擎检索整句」的假设，不会静默替代用户选择。
- 仅查看解析结果而不启动浏览器：`jev-run "…" --plan-only`

---

## 7. 命令参考

| 命令 | 用途 |
| --- | --- |
| `jev-run "…"` | 执行一条任务指令 |
| `jev-ui` | 运行观察台（`127.0.0.1:8788`） |
| `jev-browser start\|status\|stop\|restart` | 专用浏览器管理 |
| `jev-selftest` | 零密钥端到端自检；`--real-decision` 使决策走真实模型 |
| `jev-doctor` | 端点与就绪状态；`--live` 发送真实探针 |
| `jev-serve` | 本机 HTTP 接口，供其他语言集成调用（`POST /run`） |

### `jev-run` 常用参数

| 参数 | 作用 |
| --- | --- |
| `--plan-only` | 仅输出解析结果，不启动浏览器、不调用 API |
| `--json` | 输出完整 JSON 结果 |
| `--extract 路径` | 将 JSON 结果写入文件 |
| `--steps N` | 本次动作上限（默认 `JEV_MAX_STEPS` 或 60） |
| `--url` / `--goal` | 显式指定起始 URL 或任务目标 |
| `--screenshots` | 循环中抓取截图（观察台自动启用） |
| `--keep-open` | 结束后保留标签页 |
| `--launch-browser` | 无可用浏览器时自动启动（可配 `--headless`） |
| `--no-preflight` | 跳过运行前环境检查（不推荐） |
| `--quiet` | 抑制 stderr 进度输出 |
| `--env-file` | 指定 `.env` 路径 |

退出码：`0` 成功（`done`/`budget`/`stopped`）、`1` 失败（`error`/`blocked`）、`2` 环境未就绪（`setup-required`）。

### 结果关键字段

```json
{
  "status": "done",
  "steps": 2,
  "actions": [
    {"step": 1, "operation": "TYPE_TEXT", "action": "输入搜索词", "typed_text": "上海天气",
     "probability": 1.0, "decided_by": "jev-1.13.0"}
  ],
  "text_calls": [{"field": "输入搜索词", "value": "上海天气", "model": "deepseek-v4-flash"}],
  "page": {"url": "…", "title": "上海天气 - 搜索", "text": "…"}
}
```

`status` 取值：`done` 完成 / `blocked` 受阻（验证码等）/ `budget` 达到动作上限 / `stopped` 手动停止 / `setup-required` 环境未就绪 / `error` 运行异常。

---

## 8. 故障排查

建议按以下顺序排查：

```bash
jev-doctor              # 配置与就绪状态，失败项附带修复命令
jev-doctor --live       # 端点是否真实应答
jev-browser status      # 浏览器是否可达
jev-selftest            # 本机链路是否正常
jev-selftest --real-decision   # 仅替换决策端点为真实模型
```

### 常见症状

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| `UnicodeDecodeError: 'gbk' codec can't decode…` | 旧版本在中文 Windows 下以 cp936 读取文件 | 已修复（全部读取显式 UTF-8）。其他项目中复现时：读文件须显式指定 `encoding="utf-8"` |
| `daemon default didn't come up` | 无可驱动的浏览器 | `jev-browser start` |
| `browser (CDP)` 持续不可达 | 端口被其他进程占用 | 更换端口：`jev-browser start --port 9444` |
| 状态为 `setup-required` | 缺少密钥或浏览器不可用 | 查看输出中的 `checks`，每项均附带 `fix` |
| classifier.dev 返回 403 `proxy_requires_payment` | 请求经过代理 | 移除代理；不要设置 `CLASSIFIER_USE_ENV_PROXY` |
| `HTTP 500 do_request_failed` | 网关自身上游故障 | 更换端点；`jev-doctor --live` 复检 |
| 百度返回「百度安全验证」 | 百度对自动化请求的拦截 | 属正常行为，状态为 `blocked`。改用 bing/google，或使用已有登录态的 profile |
| Windows 控制台中文乱码 | 控制台代码页 | `chcp 65001` 切换至 UTF-8 |
| harness 启动异常、pid 文件残留 | 上次进程未正常退出 | 清空 `~/.config/browser-harness/runtime/` 后重新 `jev-browser start` |
| `pip install` 报 `ENOSPC` | 系统盘空间不足 | 先清理缓存：`pip cache purge` |
| `browser-harness` 无法安装 0.1.13 | 镜像源版本滞后 | 追加 `--mirror https://pypi.org/simple` |

### 搜索引擎自动化兼容性（实测）

| 引擎 | 结果 |
| --- | --- |
| GitHub、必应、维基百科 | 可用，可到达结果页 |
| 搜狗 | 被拦截，2 步后 `blocked` |
| DuckDuckGo | 被拦截（同意页） |
| 百度 | 被拦截（安全验证） |

---

## 9. 动作空间

模型每次仅从以下 9 个操作中选择一个，且目标限定为快照中**实际观察到的**元素。

| 操作 | 语义 |
| --- | --- |
| `CLICK` | 点击按钮、链接、菜单项、自动补全建议、日历单元格 |
| `TYPE_TEXT` | 向可编辑字段写入内容（值由文本辅助模型依据任务目标推断） |
| `ENTER` | 在指定字段内按回车，提交其所属表单 |
| `SELECT` | 选中下拉框中已观察到的一个选项 |
| `SCROLL_UP` / `SCROLL_DOWN` | 页面滚动 |
| `WAIT` | 等待页面更新 |
| `DONE` | 判定任务目标已达成 |
| `BLOCKED` | 所有支持的操作均无法推进 |

### `ENTER` 操作的设计动因

大量表单**不存在可见的提交控件**。典型实例为必应：其提交按钮
`INPUT#sb_form_go` 尺寸为 **0×0 不可见**（快照按可见性规则正确过滤），而界面上可见的放大镜实为 `<label>` 元素。此类表单依赖回车提交。

`ENTER` 是**带目标的操作**（回车必须落在某个具体字段上），而非全局动作。执行时先 `focus()` 目标节点并确认 `document.activeElement` 已正确聚焦，再发送真实按键序列（`rawKeyDown` → `char("\r")` → `keyUp`）。

> 经验证，`Input.insertText` 不能替代按键事件 —— 它不会触发表单提交。

---

## 10. 编程接口

```python
from jev_ultrafast import task

result = task.run_task("bing 上海天气")
print(result["status"], result["steps"])
for action in result["actions"]:
    print(action["step"], action["operation"], action["action"], action["typed_text"])
```

完整参数：

```python
task.run_task(
    "打开 https://cn.bing.com 用搜索框搜索 上海天气 然后提交",
    url=None,               # 覆盖起始 URL
    goal=None,              # 覆盖任务目标
    max_actions=20,         # 动作上限
    screenshots=False,      # 循环中抓取截图（供观察台使用）
    keep_open=False,        # 结束后保留标签页
    preflight=True,         # 运行前校验环境，不通过返回 status="setup-required"
    launch_chrome=False,    # 无可用浏览器时自动启动
    on_step=None,           # 每步回调，接收完整 agent state
)
```

仅解析指令：

```python
plan = task.parse_instruction("百度搜索 上海天气")
print(plan.url, plan.goal, plan.engine, plan.query)
```

通过 `on_step` 实现实时观测（观察台即基于此实现）：

```python
def on_step(state):          # state 为完整 agent state，页面位于 state["page"]
    print(state["status"], len(state["history"]), state["page"]["url"])

task.run_task("bing 上海天气", on_step=on_step)
```

提前终止：在 `on_step` 中抛出 `task.StopRequested`，结果状态为 `stopped`（不计为错误，已执行的历史仍会返回）。

---

## 11. 工程规范与测试

```bash
python -m pytest -q                       # 178 项，全部离线，无需浏览器与网络
python -m ruff check .
node --check jev_ultrafast/static/app.js
node --check jev_ultrafast/snapshot.js
python -X utf8=0 -c "import jev_ultrafast"   # 模拟 cmd 的 cp936 代码页，防编码回归

git config core.hooksPath .githooks       # 启用提交前凭据校验（每个克隆执行一次）
```

| 测试文件 | 覆盖范围 |
| --- | --- |
| `test_task.py` | 指令解析与结果契约 |
| `test_config.py` | 端点解析优先级、服务预设、预检 |
| `test_classifier_backend.py` | classifier.dev 协议适配（含 label 语义、概率归一化） |
| `test_enter_operation.py` | ENTER 动作空间、按键序列、截图容错 |
| `test_ui.py` | 观察台 HTTP 接口、令牌、状态投影 |
| `test_windows_encoding.py` | 以 `-X utf8=0` 子进程复现 cmd 环境 |
| `test_no_secrets.py` | 凭据校验；其中一个用例**故意植入密钥**以证明扫描器有效 |
| `test_preflight.py` / `test_chrome.py` / `test_selftest.py` | 预检、浏览器启停、零密钥自检 |

### 凭据校验

`.env` 中包含真实密钥，已被 `.gitignore` 忽略，**任何情况下不得进入仓库**。

```bash
git config core.hooksPath .githooks    # 启用一次即可
python scripts/check_secrets.py        # 手动扫描暂存区
python scripts/check_secrets.py --all  # 扫描全部已跟踪文件
```

扫描对象为**暂存区**内容（即本次提交实际写入的内容），命中即拒绝提交并指出文件与行号。
确属误报时可使用 `git commit --no-verify` 显式跳过，并在提交说明中说明原因。

`scripts/check_secrets.py` 中**不得出现真实密钥** —— 包含其自身所要查找的密钥的扫描器，本身即已构成泄漏。

代码约定（详见 `AGENTS.md`）：

- 所有端点、密钥、超时**仅在 `config.py` 中解析**，避免在其他模块硬编码或直接读取 `os.environ`
- 文件读取一律显式指定 `encoding="utf-8"`（中文 Windows 默认代码页为 cp936）
- 失败必须可操作：`preflight()` 返回 check/ok/detail/fix，不得表现为超时
- 截图仅供人工观测，获取失败不视为运行失败

---

## 12. 后续演进方向

| 改造项 | 解决的问题 |
| --- | --- |
| **`EXTRACT` 操作** | 目前缺少结构化答案输出：查询类任务（"查看节点 node-07 的 CPU 使用率，并返回数值"）模型可正确导航并判定完成，但答案包含在 `page.text` 中，需自行解析。增加一个 head，使模型在 `DONE` 之前将与目标相关的值抽取为 JSON 并写入 `result["extracted"]`，循环与执行器无需改动 |
| **iframe / shadow DOM 穿透** | 企业内部系统常见多层 iframe 与组件库 shadow root，当前选择器仅覆盖主文档 |
| **视口可配置** | 当前固定为 1120×780；内部系统常见 1440/1920 宽度，调大可单次容纳更多元素 |
| **动作空间扩展** | 尚不支持 hover、右键、拖拽、文件上传、组合键、多标签页 |

---

*本文档中的命令与数据均来自本机实测；browser-use 的感知相关参数引自其官方文档。*
