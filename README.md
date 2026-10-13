<img src="docs/banner.svg" alt="Jev Ultrafast · Browser Use × TypeSafe" width="100%" />

# Jev Ultrafast 中文教程

> English: [README_en.md](README_en.md)

> 本分支相对上游 `browser-use/jev-ultrafast` 的改动：可配置端点、一句话入口、实时观察台、`ENTER` 操作、Windows 编码修复，以及提交前的凭据闸门。

> [!IMPORTANT]
> **The Browser Use Cloud waitlist is open.** Get early access to ultrafast browser agents in the cloud.
> **[Join the waitlist →](https://browser-use.com/ultrafast?utm_source=github&utm_medium=readme&utm_campaign=jev-ultrafast)**

一句话：**把「百度搜索 上海天气」这句话丢给它，它自己开浏览器、自己判断下一步点什么，跑完把结果给你。**

决策由 TypeSafe 的 Jev 模型（`jev-1.13.0`）担，页面快照和操作执行由代码做。需要输入文字时才叫一个小语言模型（文本助手）生成值。截图只给人看，不参与决策。

---

## 目录

1. [它是什么，边界在哪](#1-它是什么边界在哪)
2. [装环境](#2-装环境)
3. [配置两个端点](#3-配置两个端点)
4. [三步跑起来](#4-三步跑起来)
5. [图形界面（观察台）](#5-图形界面观察台)
6. [一句话能怎么写](#6-一句话能怎么写)
7. [命令速查](#7-命令速查)
8. [出问题怎么查](#8-出问题怎么查)
9. [动作集](#9-动作集)
10. [在 Python 里调用](#10-在-python-里调用)
11. [开发与测试](#11-开发与测试)

---

## 1. 它是什么，边界在哪

### 做成一件事的流程

```
一句话  →  本地解析成「起点 URL + 目标」  →  观察页面（元素编号表）
        →  Jev 选「哪个操作 + 哪个元素」  →  代码执行
        →  需要打字时叫文本助手生成内容   →  重复，直到 DONE / BLOCKED / 到上限
```

关键点：**决策只基于结构化的元素表，不看截图**。截图是给观察台显示用的。

### 能做的

| 能力 | 说明 |
| --- | --- |
| 一句话直达 | 从句子推断起点 URL（百度、必应、知乎、GitHub、维基…）与目标 |
| 真实浏览器 | 走 CDP 驱动本机 Chrome，不是无头爬虫，页面真实渲染 |
| 表单交互 | 点击、输入、回车提交、下拉选择 |
| 可观察 | 每一步的候选元素、操作概率、目标概率、实际动作都留痕 |
| 可定位故障 | 环境不对时约 1 秒内报错并给出修复命令，不会挂 30 秒超时 |

### 做不到的（重要）

| 限制 | 表现 |
| --- | --- |
| 验证码过不去 | 百度对全新 profile 必弹「百度安全验证」，模型会**正确报 `blocked`**，不会硬撞 |
| 无图形界面即无截图 | 截图依赖 renderer，繁忙时可能抓不到（不影响任务） |
| 不处理 iframe / shadow DOM / canvas / 文件上传 / 新标签页 | 这些元素不在快照里 |
| 靠「长按 / 组合键 / 悬停菜单」交互的控件 | 动作集里没有 |
| 一个页面元素超过 250 个 | 超出部分被截断 |

---

## 2. 装环境

### 方式一：脚本（推荐）

```bash
cd jev-ultrafast
bash scripts/setup_venv.sh              # Git Bash / macOS / Linux
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_venv.ps1   # PowerShell
```

脚本会建 `.venv`、装依赖、把 `.env.example` 复制成 `.env`（若不存在）、以可编辑模式装本包，最后跑一次 `jev-doctor`。

常用开关：

| 开关（Bash / PowerShell） | 作用 |
| --- | --- |
| 无 / 无 | 装运行 + 开发依赖（含 pytest、ruff） |
| `--no-dev` / `-NoDev` | 只装运行依赖 |
| `--exact` / `-Exact` | 严格按 `requirements.lock.txt` 装，用于复现同一环境 |
| `--recreate` / `-Recreate` | 删掉 `.venv` 重建 |
| `--mirror URL` / `-Mirror URL` | 换 PyPI 镜像 |

> **注意**：`browser-harness==0.1.13` 只在 `pypi.org` 上有，清华源停在 `0.0.1`。
> 用镜像装不上时，加 `--mirror https://pypi.org/simple`。

### 方式二：手动

```bash
python -m venv .venv
source .venv/Scripts/activate          # Git Bash
.venv\Scripts\activate.bat             # cmd
.venv\Scripts\Activate.ps1             # PowerShell
pip install -e .
```

---

## 3. 配置两个端点

所有配置都在项目根目录的 **`.env`** 里（已被 `.gitignore` 忽略，不会进仓库）。优先级：**环境变量 > 服务预设 > 内置默认**。

### 3.1 决策端点：选一个协议

| 协议 | 端点 | 要密钥吗 | 一次决策几个请求 |
| --- | --- | --- | --- |
| `classifier`（默认，推荐起步） | `https://classifier.dev/` | **不要** | 1 个；当选中操作有多个候选元素时 2 个 |
| `typesafe` | `{base}/v1/systemone` | 要 | 1 个，两个 head 一次返回 |

两者是**同一个模型**（classifier.dev 的响应里写着 `"model": "jev-1.13.0"`、`"provider": "typesafe"`），只是线上格式不同。

免密钥起步：

```dotenv
JEV_BACKEND=classifier
CLASSIFIER_URL=https://classifier.dev/
```

> **必须直连**。classifier.dev 的免费额度只认直连流量，走代理会返回
> `{"code":"proxy_requires_payment"}`。所以这个端点**故意忽略 `HTTP_PROXY`/`HTTPS_PROXY`**，
> 除非你显式设 `CLASSIFIER_USE_ENV_PROXY=1`（那需要付费 key）。

> [!WARNING]
> **2026-10-13 实测：classifier.dev 的免密钥路径当前不可用。** 两条都要知道：
> ① 它在 **Jev 不可用时会静默回退到一串 LLM**（看响应里的 `modelsUsed` 才知道），
> 回退后 `scores` 只剩一个 `null`，**概率恒为 1.0**；
> ② 匿名**共享**额度耗尽后，直连返回 `HTTP 402 {"code":"request_spending_limit"}`。
> 端到端实测 0/3。入口是共享池，随时可能被耗尽 —— **不要把它当生产依赖**。
> 生产或内网请走下面两种：`typesafe`（任一起到 `/v1/systemone` 的服务，含自建）
> 或自建 classifier 兼容服务（见 3.4）。

有 TypeSafe key 时：

```dotenv
JEV_BACKEND=typesafe
TYPESAFE_API_KEY=你的key
TYPESAFE_MODEL=jev-latest
# TYPESAFE_BASE_URL=https://api.typesafe.ai
# TYPESAFE_PATH=/v1/systemone
```

### 3.2 文本助手端点

只有需要「输入文字」的步骤才会调用。任何 OpenAI 兼容的 `/chat/completions` 服务都行。

```dotenv
TEXT_MODEL_BASE_URL=https://api.deepseek.com/v1
TEXT_MODEL_API_KEY=sk-xxxx
TEXT_MODEL=deepseek-chat
TEXT_MODEL_REASONING=off          # none | off | low | medium | high | 原始 JSON
TEXT_MODEL_JSON_MODE=auto         # auto | on | off，服务不认 response_format 时设 off
```

内置预设可以直接用 `TEXT_MODEL_PROVIDER`：

`openrouter` `openai` `deepseek` `siliconflow` `dashscope` `moonshot` `zhipu` `ollama` `vllm` `lmstudio`

本地模型（免密钥）：

```dotenv
TEXT_MODEL_PROVIDER=ollama
TEXT_MODEL_BASE_URL=http://127.0.0.1:11434/v1
TEXT_MODEL=qwen2.5:7b
```

### 3.3 验证端点

```bash
jev-doctor          # 看生效配置 + 是否就绪（每个失败项都带修复命令）
jev-doctor --live   # 额外给每个端点发一次最小真实请求
```

**「配置正确」不等于「能用」。** 我们实测遇到过一个网关：`GET /v1/models` 返回 200 正常，但每次对话请求都在 50ms 内返回 `HTTP 500 do_request_failed`。只有 `--live` 能发现这种问题。

---

## 4. 三步跑起来

```bash
# 1. 给它一个能被驱动的浏览器
jev-browser start              # 弹一个专用 profile 的 Chrome 窗口
jev-browser start --headless   # 不想看到窗口就用这个

# 2. 零密钥自证整条链路（不花钱、不碰外部网站）
jev-selftest

# 3. 跑一句真的
jev-run "bing 上海天气"
```

`jev-selftest` 会自己起两个 mock 端点 + 一个本地页面，驱动真实浏览器走完「输入 → 提交 → 完成」。**先跑它，再怀疑你的密钥** —— 9 项全过就说明这台机器上除了外部服务以外都是好的。

想只验决策端点、页面和文本助手仍用本地桩：

```bash
jev-selftest --real-decision
```

### 为什么需要 `jev-browser`

自己 `chrome.exe` 起一个浏览器是没有 CDP 端口的；新版 Chrome 又禁止在默认 profile 上开远程调试。`jev-browser` 用**独立 profile + 独立端口（9333）**启动，并把地址记到 `~/.jev/browser.json`，之后 `jev-run` 自动读取，**你不需要 export 任何变量**。

```bash
jev-browser status    # 是否可达、用哪个二进制、哪个 profile、端口/PID
jev-browser stop
jev-browser restart
```

---

## 5. 图形界面（观察台）

命令行返回 JSON，不适合「看过程」。观察台是本机网页：

```bash
jev-ui --open --launch-browser
```

默认 `http://127.0.0.1:8788`。在输入框里打一句话回车即运行。

![观察台](docs/ui-screenshot.png)

| 面板 | 看什么 |
| --- | --- |
| 解析结果 | 这句话被解析成了什么起点 URL 和什么目标；没点名引擎时的假设也写在这 |
| 当前页面 | 浏览器真实截图，**每个元素按编号框出来**，被选中的目标描绿框 |
| 最近一次决策 | 操作、目标、置信度、耗时，以及「操作概率」和「目标概率」两组条形图 |
| 可操作元素 | 模型实际从中挑选的编号表，每行标注这个元素支持哪些操作 |
| 动作日志 | 每一步：操作 / 目标 / 生成的文本 / 概率 / 累计耗时 |
| 文本模型调用 | 哪个字段生成了什么值、用哪个模型、花了多久 |

其它参数：

```bash
jev-ui --port 8790 --instruction "百度搜索 上海天气"   # 预填输入框
jev-ui --launch-browser --headless                    # 不弹可见窗口
```

安全：只监听回环地址，每次 POST 都要带页面里的进程内令牌，只接受本机请求。

---

## 6. 一句话能怎么写

解析在**本地**做，不消耗模型调用。按下面的顺序尝试匹配：

| 句子长什么样 | 起点 URL |
| --- | --- |
| 句子里含 `http(s)://…` | 用这个 URL，句子剩下的部分当目标 |
| `打开 example.com` / `open example.com` | `https://example.com` |
| `<引擎> <动词> <关键词>`：`百度搜索 上海天气`、`在知乎搜索 咖啡`、`github search llm` | 该引擎的结果页 |
| `<动词> <关键词>`，没点名引擎：`搜索 上海天气` | `JEV_DEFAULT_SEARCH_ENGINE`，默认 baidu |
| `<引擎> <关键词>`：`bing 上海天气`、`google llm benchmarks` | 该引擎的结果页 |
| 以上都不匹配 | 用默认搜索引擎搜整句话 |

支持的引擎别名：`百度` `bing` `必应` `google` `谷歌` `搜狗` `360` `so` `duckduckgo` `知乎` `微博` `bilibili` `淘宝` `京东` `github` `youtube` `wikipedia` `维基`

几点实测行为：

- `百度搜索` 这种**只有引擎没有关键词**的，会直接报错让你补关键词，而不是瞎搜一个字。
- `bing 上海天气` 的关键词是「上海天气」，不会变成「海天气」。
- 没点名引擎时会在 `plan.notes` 里写明「按默认引擎搜整句」，不会偷偷替你选。
- 想看解析结果而不启动浏览器：`jev-run "…" --plan-only`

---

## 7. 命令速查

| 命令 | 用途 |
| --- | --- |
| `jev-run "…"` | 跑一句话 |
| `jev-ui` | 图形观察台（`127.0.0.1:8788`） |
| `jev-browser start\|status\|stop\|restart` | 专用浏览器 |
| `jev-selftest` | 零密钥自检整条链路；`--real-decision` 决策走真实模型 |
| `jev-doctor` | 端点与就绪状态；`--live` 发真实探针 |
| `jev-serve` | 本机 HTTP 接口，给别的语言调（`POST /run`） |

### `jev-run` 常用参数

| 参数 | 作用 |
| --- | --- |
| `--plan-only` | 只打印解析结果，不启浏览器、不调 API |
| `--json` | 输出完整 JSON 结果 |
| `--extract 路径` | 把 JSON 结果写到文件 |
| `--steps N` | 本次动作上限（默认 `JEV_MAX_STEPS` 或 60） |
| `--url` / `--goal` | 手动覆盖起点或目标 |
| `--screenshots` | 循环中抓截图（观察台自动会开） |
| `--keep-open` | 结束后不关标签页 |
| `--launch-browser` | 没有可用浏览器时自动拉起（可配 `--headless`） |
| `--no-preflight` | 跳过开跑前的环境检查（不推荐） |
| `--quiet` | 不打印 stderr 进度 |
| `--env-file` | 指定 `.env` 路径 |

退出码：`0` 成功（`done`/`budget`/`stopped`）、`1` 失败（`error`/`blocked`）、`2` 环境未就绪（`setup-required`）。

### 结果里几个关键字段

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

`status` 取值：`done` 完成 / `blocked` 被拦（验证码等）/ `budget` 到动作上限 / `stopped` 被手动停止 / `setup-required` 环境未就绪 / `error` 出错。

---

## 8. 出问题怎么查

按这个顺序排查最省时间：

```bash
jev-doctor              # 配置和就绪状态，失败项自带修复命令
jev-doctor --live       # 端点是否真的应答
jev-browser status      # 浏览器是否可达
jev-selftest            # 本机这一半是否正常
jev-selftest --real-decision   # 只换决策端点为真实模型
```

### 常见症状

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| `UnicodeDecodeError: 'gbk' codec can't decode…` | 老版本在中文 Windows 下按 cp936 读文件 | 已修（所有读取显式 UTF-8）。若在别的项目复现：读文件一律给 `encoding="utf-8"` |
| `daemon default didn't come up` | 没有可驱动的浏览器 | `jev-browser start` |
| `browser (CDP)` 一直不可达 | 端口被别的进程占用 | 换端口：`jev-browser start --port 9444` |
| 状态 `setup-required` | 缺密钥或浏览器不可用 | 看输出里的 `checks`，每条都带 `fix` |
| classifier.dev 返回 403 `proxy_requires_payment` | 请求走了代理 | 去掉代理；别设 `CLASSIFIER_USE_ENV_PROXY` |
| `HTTP 500 do_request_failed` | 网关自己的上游挂了 | 换端点；`jev-doctor --live` 复检 |
| 百度返回「百度安全验证」 | 百度拦自动化 | 属正常，状态会是 `blocked`。换 bing/google，或用有登录态的 profile |
| Windows 控制台中文乱码 | 控制台代码页 | `chcp 65001` 切到 UTF-8 |
| harness 启动报错、pid 文件残留 | 上次没退干净 | 清空 `~/.config/browser-harness/runtime/` 再 `jev-browser start` |
| `pip install` 报 `ENOSPC` | C 盘空间不足 | 先清缓存：`pip cache purge` |
| `browser-harness` 装不上 0.1.13 | 镜像源滞后 | 加 `--mirror https://pypi.org/simple` |

### 搜索引擎自动化友好度（实测）

| 引擎 | 结果 |
| --- | --- |
| GitHub、必应、维基百科 | 可用，能跑到结果页 |
| 搜狗 | 被拦，2 步后 `blocked` |
| DuckDuckGo | 被拦（同意页） |
| 百度 | 被拦（安全验证） |

---

## 9. 动作集

模型每次只能从这 9 个里挑一个，而且只挑**页面里真实观察到的**元素。

| 操作 | 含义 |
| --- | --- |
| `CLICK` | 点击按钮、链接、菜单项、自动补全建议、日历格子 |
| `TYPE_TEXT` | 往可编辑字段里写内容（值由文本助手从目标里推断） |
| `ENTER` | 在某个字段里按回车，提交它所在的表单 |
| `SELECT` | 选中下拉框里观察到的一个值 |
| `SCROLL_UP` / `SCROLL_DOWN` | 滚动 |
| `WAIT` | 等页面更新 |
| `DONE` | 目标已满足 |
| `BLOCKED` | 所有支持的操作都无法推进 |

### 为什么要单独有 `ENTER`

很多表单**没有可见的提交按钮**。最典型的是必应：它的提交按钮是
`INPUT#sb_form_go`，尺寸 **0×0 不可见**（快照按可见性把它正确过滤掉了），而肉眼看到的放大镜是个 `<label>`。这类表单靠回车提交。

`ENTER` 是**带目标的操作**（回车必须落在某个具体字段上），不是全局动作。执行时会先 `focus()` 该节点、确认 `document.activeElement` 真的落在它上面，再发真实按键序列（`rawKeyDown` → `char("\r")` → `keyUp`）。

> 不能用 `Input.insertText` 代替 —— 它不会触发表单提交。这个坑踩过。

---

## 10. 在 Python 里调用

```python
from jev_ultrafast import task

result = task.run_task("bing 上海天气")
print(result["status"], result["steps"])
for action in result["actions"]:
    print(action["step"], action["operation"], action["action"], action["typed_text"])
```

常用参数：

```python
task.run_task(
    "打开 https://cn.bing.com 用搜索框搜索 上海天气 然后提交",
    url=None,               # 覆盖起点 URL
    goal=None,              # 覆盖目标
    max_actions=20,         # 动作上限
    screenshots=False,      # 循环中抓截图（给界面用）
    keep_open=False,        # 结束后不关标签页
    preflight=True,         # 开跑前查环境，不通过返回 status="setup-required"
    launch_chrome=False,    # 没浏览器时自动拉起
    on_step=None,           # 每步回调，收到完整 agent state
)
```

只想解析、不启动任何东西：

```python
plan = task.parse_instruction("百度搜索 上海天气")
print(plan.url, plan.goal, plan.engine, plan.query)
```

用 `on_step` 做实时观察（观察台就是这么实现的）：

```python
def on_step(state):          # state 是完整 agent state，页面在 state["page"]
    print(state["status"], len(state["history"]), state["page"]["url"])

task.run_task("bing 上海天气", on_step=on_step)
```

提前结束：在 `on_step` 里抛 `task.StopRequested`，结果状态为 `stopped`（不算错误，已有历史仍然返回）。

---

## 11. 开发与测试

```bash
python -m pytest -q                       # 178 项，全离线，无需浏览器和网络
python -m ruff check .
node --check jev_ultrafast/static/app.js
node --check jev_ultrafast/snapshot.js
python -X utf8=0 -c "import jev_ultrafast"   # 模拟 cmd 的 cp936，防编码回归

git config core.hooksPath .githooks       # 启用提交前的凭据闸门（每个克隆做一次）
```

| 测试文件 | 覆盖什么 |
| --- | --- |
| `test_task.py` | 一句话解析与结果契约 |
| `test_config.py` | 端点解析优先级、预设、预检 |
| `test_classifier_backend.py` | classifier.dev 协议适配（含 label 语义、概率归一化） |
| `test_enter_operation.py` | ENTER 动作空间、按键序列、截图容错 |
| `test_ui.py` | 观察台 HTTP 接口、令牌、状态投影 |
| `test_windows_encoding.py` | 用 `-X utf8=0` 子进程复现 cmd 环境 |
| `test_no_secrets.py` | 凭据闸门；其中一个用例会**故意植入密钥**证明扫描器没失效 |
| `test_preflight.py` / `test_chrome.py` / `test_selftest.py` | 预检、浏览器启停、零密钥自检 |

### 凭据闸门

`.env` 里装着真实密钥，它被 `.gitignore` 忽略，**任何时候都不该进仓库**。

```bash
git config core.hooksPath .githooks    # 启用一次即可
python scripts/check_secrets.py        # 手动扫暂存区
python scripts/check_secrets.py --all  # 扫全部已跟踪文件
```

扫描的是**暂存区**内容（这次提交真正会写进去的东西），命中就拒绝提交并指出文件与行号。
确属误报时用 `git commit --no-verify` 跳过，并在提交说明里写清原因。

`scripts/check_secrets.py` 里**不能出现真实密钥** —— 一个装着它所要查找的密钥的扫描器，本身就已经泄漏了。

改代码时请遵守的约定（详见 `AGENTS.md`）：

- 所有端点、密钥、超时**只在 `config.py` 解析**，别在别处硬编码或直接读 `os.environ`
- 读文件一律显式 `encoding="utf-8"`（中文 Windows 默认 cp936）
- 失败必须可操作：`preflight()` 返回 check/ok/detail/fix，绝不允许表现为超时
- 截图只为人服务，抓不到就算了，**不能因为截图失败中断任务**
