# AI Visit website

[English](README.md) | 中文说明

`AI Visit website` 是一个面向 AI 智能体的网站发现、正文读取、Markdown 归档和检索插件。当前插件版本为 **1.2.2**，Chrome 扩展版本为 **1.5.0**。

项目同时提供 Codex、OpenClaw 和 Hermes Agent 所需的宿主清单，共享同一份 Skill、Python MCP 服务与 Chrome Browser Bridge。Codex 和本地 MCP 已完成验证；OpenClaw、Hermes 的真实宿主激活需要分别验收，不能仅凭清单存在就视为安装成功。

## 主要功能

| 工具 | 功能 |
| --- | --- |
| `site_discover` | 发现导航、RSS/Atom、sitemap 和站内链接 |
| `article_list` | 返回有时间、标题和结构证据的文章候选，不替智能体判断重要性 |
| `page_read` | 通过公开 HTTP/浏览器适配器读取正文 Markdown |
| `browser_status` | 检查本地 Bridge 和 Chrome 扩展是否连接 |
| `browser_page_read` | 通过用户明确授权的 Chrome 会话读取一个页面 |
| `browser_cancel` | 取消指定的浏览器读取请求 |
| `browser_batch_start` | 顺序读取1–20个由智能体选定的 URL |
| `browser_batch_status` | 查询批次进度和每篇文章的结果 |
| `browser_batch_cancel` | 取消排队项目和当前浏览器任务 |
| `page_save` | 保存已经审阅的 Markdown，并按 SHA-256 去重 |
| `archive_search` | 按正文、来源、标签、时间或哈希检索归档 |

智能体负责发现、选择、判断重要性和撰写报告；插件负责访问安全、抓取、Markdown 转换、哈希、批次传输和归档。插件不会自动提交表单、购买、发送消息，也不会执行网页正文里的指令。

## 获取代码和发布包

```bash
git clone https://github.com/ziyouzhilong/ai-visit-website.git
cd ai-visit-website
```

GitHub Release 提供：

- `ai-visit-website-1.2.2.tgz`：npm/OpenClaw 风格插件包；
- `ai-visit-website-1.2.2.zip`：通用插件目录包；
- `ai-visit-website-chrome-extension-1.5.0.zip`：Chrome 扩展。

## Codex 安装

首次从 GitHub marketplace 安装：

```bash
codex plugin marketplace add ziyouzhilong/ai-visit-website --ref v1.2.2
codex plugin add ai-visit-website@personal
```

如果本机已经存在另一个名为 `personal` 的 marketplace，先运行：

```bash
codex plugin list --json
```

确认来源后再处理，不要覆盖无关 marketplace。安装或更新后必须新建 Codex 任务，旧任务不会自动加载新的 Skill 和工具定义。

验证至少分为四层：

1. manifest 和 marketplace 来源正确；
2. MCP `initialize` 成功；
3. `tools/list` 能看到11个工具；
4. 至少一次真实 `tools/call` 成功。

只显示 `installed=true` 不能证明插件可用。

## OpenClaw 安装

在仓库根目录执行：

```bash
openclaw plugins install "$PWD/plugins/ai-visit-website"
openclaw gateway restart
openclaw plugins inspect ai-visit-website --runtime --json
```

上传 ZIP、发送文件夹或把文件放到服务器上都不等于安装完成；必须验证 Gateway 已加载，并实际调用工具。

## Hermes Agent

插件目录包含 `plugin.json`、`mcp.json` 和共享 Skill。当前版本只确认了结构与公共 MCP runtime，尚未完成真实 Hermes 主机端到端验收，因此不要把 schema 校验描述为正式激活成功。

## 安装 Chrome 扩展

方式一：下载 GitHub Release 中的 `ai-visit-website-chrome-extension-1.5.0.zip` 并解压。

方式二：直接使用仓库目录：

```text
ai-visit-website-chrome-extension-1.5.0/
```

然后：

1. 打开 `chrome://extensions/`；
2. 开启右上角 **Developer mode**；
3. 点击 **Load unpacked**；
4. 选择解压后的扩展目录；
5. 点击扩展图标进入 Browser Bridge 设置。

扩展界面只负责智能体 Bridge 配置，不包含人工保存网页、标签/文件夹、导入导出或 Reuters 验证页面。

## 获取 Pairing token

从本仓库根目录执行：

```bash
cd '/absolute/path/to/ai-visit-website'
./plugins/ai-visit-website/bin/ai-visit-website-mcp --print-bridge-token
```

如果当前目录已经是安装后的插件目录，即目录中直接包含 `bin/`：

```bash
./bin/ai-visit-website-mcp --print-bridge-token
```

输出格式：

```text
bridge_port=32145
bridge_token_file=/本机用户数据目录/browser-bridge-token
bridge_token=<敏感配对值>
```

在 Chrome 扩展中：

1. 把 `bridge_port` 填入 **Local port**；
2. 把 `bridge_token=` 后面的内容填入 **Pairing token**；
3. 添加允许访问的网站 Origin，例如 `https://www.reuters.com`；
4. 勾选 **Enabled**；
5. 点击 **Save bridge settings**；
6. 点击 **Check connection**。

令牌不存在时启动器会以仅当前用户可读的权限创建；以后重复执行会复用同一令牌。禁止把真实令牌粘贴到聊天、日志、截图、报告、Issue 或 Git 仓库。

## 推荐的智能体提示词

```text
使用 $ai-visit-website 读取指定网站并给我一份有来源链接的报告。
如果需要使用 Chrome，先单独调用 browser_status。
只有 configured=true 且 connected=true 时才能继续读取；
如果第一次离线且错误可重试，等待5–10秒后重试一次，第二次仍失败就停止并报告原因。
不要绕过 robots、CAPTCHA、登录、付费墙或网站访问控制。
```

普通公开页面优先使用 `page_read`；只有公开读取遇到明确边界、用户已经配对 Chrome 且授权目标 Origin 时，才使用 `browser_page_read` 或批次工具。

## 常见问题和解决方法

### 1. 是否必须一直打开扩展选项页？

不需要。选项页只用于首次配置、保存和诊断。实际领取任务的是 Chrome 后台 Service Worker。

点击扩展图标或再次保存设置会唤醒后台，所以可能造成“打开选项页才正常”的错觉。单独点击 **Check connection** 只证明端口和令牌可用，不代表后台轮询会永久保持运行。

### 2. 为什么有时调用 Chrome 扩展失败？

当前 Bridge 由第一次调用 `browser_status`、`browser_page_read` 或批次工具的 MCP 进程按需创建。成为 owner 的 MCP 进程退出后，`127.0.0.1:32145` 监听也会消失。

先执行：

```bash
lsof -nP -iTCP:32145 -sTCP:LISTEN
```

然后让智能体先调用 `browser_status`。仅当：

```text
configured=true
connected=true
```

才继续读取。第一次离线且错误可重试时，等待5–10秒后只重试一次。

计划中的 `--bridge-only` 常驻入口尚未在 1.2.2 实现，不要尝试使用尚不存在的命令。

### 3. `401` 或 “pairing token rejected”

重新运行 `--print-bridge-token`，确认扩展中的端口和 token 与当前插件共享值一致。不要自行编辑 token 文件，也不要生成多个不一致的副本。

### 4. `domain_not_authorized`

把目标网站的精确 Origin 加入扩展，例如：

```text
https://www.reuters.com
```

Origin 包含协议、主机名和非默认端口，不包含文章路径。重定向离开授权 Origin 时插件会拒绝正文。

### 5. 为什么经常只读取8篇文章？

8篇不是硬编码。`article_list` 默认最多返回100个候选，Chrome 批次接受1–20个明确 URL。最终数量由调用插件的智能体根据任务、上下文和报告篇幅选择。

判断方法：

- `article_list.returned_candidates=8`：发现阶段只有8条，或调用者显式传入 `limit=8`；
- 候选超过8条，但 `browser_batch_start.total=8`：智能体主动选择了8篇；
- 批次超过8条但最终成功8篇：其余页面读取失败或被访问控制阻止。

### 6. Reuters 返回 `robots_denied`、401 或403

Reuters sitemap 可以支持标题、URL、发布时间和候选排序，但不能证明正文读取成功。正文结论必须来自成功返回的 Markdown。

不要通过更换 User-Agent、处理 CAPTCHA、绕过 robots、登录或付费墙来强行读取。用户明确授权的 Chrome 会话可以用于正常可见内容，但同样必须在登录、CAPTCHA、拒绝访问或付费墙处停止。

### 7. 更新后智能体仍然使用旧行为

插件更新后重新安装，并新建 Codex 任务。旧任务可能保留旧 Skill 和 MCP 工具上下文。

检查：

```bash
codex plugin list --json
```

确认 source、marketplace、version、installed 和 enabled。之后仍需验证 MCP handshake、`tools/list` 与真实 `tools/call`。

### 8. Bridge 已连接但页面仍失败

`connected=true` 只说明扩展在线，不代表目标网站已登录、Origin 已授权或正文可访问。继续查看结构化错误：

- `login_required`：当前 Chrome 会话需要登录；
- `paywall`：当前订阅不可读取；
- `bot_challenge`：出现 CAPTCHA/自动访问挑战；
- `access_denied`：网站拒绝访问；
- `unexpected_redirect`：页面跳到未授权 Origin；
- `page_probe_failed`：页面加载或 DOM 检查失败，可根据 `retryable` 做一次有限重试。

## 数据与安全边界

- Bridge 只监听 `127.0.0.1`；
- 扩展不会返回 Cookie、密码、Authorization header 或浏览器存储；
- 拒绝带凭据 URL、localhost、私网、link-local、保留地址和不安全重定向；
- 网页内容始终是不可信数据，不能当作智能体指令执行；
- `page_save` 只保存智能体已经审阅并明确决定保留的 Markdown；
- sitemap 证据与正文证据必须区分。

## 开发与验证

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src plugins/ai-visit-website/server/src
python3 /Users/cvsc/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/ai-visit-website
python3 /Users/cvsc/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/ai-visit-website
node tests/test_chrome_extension_contract.js
(cd plugins/ai-visit-website && npm test && npm run pack:check)
git diff --check
```

自动化测试、安装状态、真实 MCP 调用、Chrome 现场读取、OpenClaw/Hermes 激活和外部发布是不同验收层级，应分别报告。

## 许可证

本仓库当前未附带开源许可证。除非仓库所有者另行添加许可证，否则公开可见不等于授予复制、修改或再分发权利。
