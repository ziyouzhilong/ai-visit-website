# AI Visit website 1.2.2 后续开发交接

更新时间：2026-08-21（Asia/Shanghai）

## 2026-08-21 发布更新

插件版本已更新并重新打包为 `1.2.2`，Chrome 扩展仍为 `1.5.0`。新增 `README_CN.md`、`CHANGELOG.md`、中文 Release notes 和常见问题解决方法；发布文件位于：

```text
release/ai-visit-website-1.2.2.tgz
release/ai-visit-website-1.2.2.zip
release/ai-visit-website-chrome-extension-1.5.0.zip
release/SHA256SUMS-1.2.2.txt
```

发布包已完成独立环境 MCP 验收：`initialize` 返回 `1.2.2`，`tools/list` 返回 11 个工具，`archive_search` 真实调用成功。`--bridge-only` 仍未实现，OpenClaw/Hermes 真实宿主激活仍需分别验收。以下 1.2.1 内容保留为历史基线和问题证据。

## 0. 当前结论

`AI Visit website` 当前本机版本为 `1.2.1`，已经形成 Codex、OpenClaw、Hermes Agent 可复用的多宿主插件包，支持：

- 网站发现、文章候选列表；
- Reuters robots 限制下的公开 sitemap 降级；
- 普通公开页面 Markdown 读取；
- 通过用户明确授权、已配对的 Chrome 会话读取网页正文；
- 1–20 个 URL 的顺序批量读取、状态查询和取消；
- 智能体审阅后的 Markdown 归档、哈希去重与检索；
- 由智能体选择文章、判断重要性并编写有证据边界的报告。

2026-08-20 已完成真实 Reuters 端到端验收：从 500 个 sitemap 候选中检查最新 120 个，选择 9 篇 World、Business、Technology 新闻。公开 `page_read` 返回 `403 / robots_denied`；Chrome 首批成功 6 篇、3 篇 `page_probe_failed`，对这 3 篇做一次有限重试后全部成功。最终取得 9 篇正文，没有处理 CAPTCHA、绕过登录/付费墙或自动归档。

当前首要生产问题是 Bridge 生命周期：Bridge 由某个 MCP 进程在第一次调用 `browser_status` 或浏览器读取工具时按需创建，没有正式手动常驻入口。MCP 进程退出或切换后，扩展可能无法连接。下一步应实现 `--bridge-only`，并补齐诊断、文档和验收。

当前 1.2.1 代码、文档、测试和发布包已保存到 Git 基线提交 `bbfede8`；后续开发仍不得使用会覆盖未提交工作的破坏性 Git 操作。

### 2026-08-20 Chrome 扩展智能体化更新

当前开发目录已迁移到：

```text
/Users/cvsc/Documents/项目开发文件夹/agentictools
```

Chrome 扩展 1.5.0 已改名为 `AI Visit website`，界面和权限已收敛为智能体 Browser Bridge：

- 删除人工保存网页、snippets、标签/文件夹、导入导出、快捷键和右键菜单；
- 删除 `reuters-validation.*` 验证页面与消息入口；
- 保留 `reuters-article-extractor.js`，因为它是智能体读取 Reuters 正文的生产提取器；
- 点击扩展图标只打开 Bridge 设置页；
- 不自动删除浏览器中遗留的 snippets/tags 数据，避免升级造成不可逆数据损失；
- 当前可安装包为 `release/ai-visit-website-chrome-extension-1.5.0.zip`。

修改前 Git 回退标签：

```text
baseline-ai-visit-website-1.2.1-extension-1.5.0
```

## 1. 下次任务可直接复制的启动提示

```text
请继续开发 AI Visit website 1.2.1。

先完整阅读：
/Users/cvsc/Documents/项目开发文件夹/agentictools/NEXT_SESSION_HANDOFF_CN.md

工作目录：
/Users/cvsc/Documents/项目开发文件夹/agentictools

开始后先执行只读检查：
- git status --short --branch
- git log --oneline --decorate -8
- git tag --list
- git remote -v
- codex plugin list --json 中 ai-visit-website 的安装状态
- lsof -nP -iTCP:32145 -sTCP:LISTEN

约束：
1. 先检查工作区，不得 reset、clean、checkout 覆盖或未经确认 stash。
2. 当前仓库同时保存插件、Chrome 扩展源码和发布包；不要从历史父仓库覆盖当前扩展。
3. canonical Python 源码与插件内置副本必须保持一致。
4. 不绕过 robots、CAPTCHA、登录、付费墙或网站访问控制。
5. sitemap 标题、URL、时间只是发现证据；正文结论必须来自成功读取的 Markdown。
6. page_save 只能保存已经审阅且任务明确要求保留的正文。
7. 不得打印或复制 browser-bridge-token 到聊天、日志或报告。
8. 不得修改或删除现有回退标签；未经用户确认不要 push、发布或删除现有 release 包。

首要任务：
为 plugins/ai-visit-website/bin/ai-visit-website-mcp 增加 --bridge-only，
让 Bridge 可独立监听 127.0.0.1:32145，保持到用户 Ctrl+C 或宿主管理器停止。
同时增加不泄露令牌的 --bridge-status 或等价诊断，更新 README 和中文 Bridge 文档，
验证独立 Bridge 与另一个 MCP stdio 进程能共享端口、令牌和任务队列。

实施前先运行测试建立基线；实施后执行本文完整验证清单。
```

## 2. 仓库与回退边界

### 历史父扩展仓库（仅供来源追溯）

| 项目 | 当前值 |
| --- | --- |
| 路径 | `/Users/cvsc/Documents/snippet extension v1.4.3` |
| 分支 | `feature/page-markdown-capture` |
| HEAD | `b83ba1b Fix Copy button to use clipboard` |
| tag / remote | 均无 |
| 状态 | dirty，包含已修改和大量未跟踪文件 |

不要再把该父仓库作为当前 Chrome 扩展的 canonical 开发目录，也不要用它覆盖当前仓库中的扩展副本。

### 当前 agentictools 仓库

| 项目 | 当前值 |
| --- | --- |
| 路径 | `/Users/cvsc/Documents/项目开发文件夹/agentictools` |
| 分支 | `codex/chrome-extension-development` |
| 修改前基线 | `bbfede8 Checkpoint AI Visit website 1.2.1 and Chrome extension 1.5.0` |
| 回退标签 | `baseline-ai-visit-website-1.2.1-extension-1.5.0`、`chrome-extension-1.5.0-agent-ui` |
| remote | 无 |
| 状态 | Chrome 扩展已收敛为智能体 Bridge；以 `git status` 和 `git log` 为准 |

`baseline-ai-visit-website-1.2.1-extension-1.5.0` 保存修改前的完整 1.2.1/1.5.0 状态；`chrome-extension-1.5.0-agent-ui` 保存本轮智能体化界面。版本字符串本身不是回退锚点，应使用这些 Git 标签。

```bash
cd '/Users/cvsc/Documents/项目开发文件夹/agentictools'
git status --short --branch
git diff --stat
git diff --check
git log --oneline --decorate -8
git tag --list
git remote -v
```

未经用户确认，禁止运行：`git reset --hard`、`git clean`、`git checkout -- .`、`git stash`。

## 3. 当前版本、安装和发布包

| 项目 | 当前值 |
| --- | --- |
| Chrome 扩展 | `1.5.0` |
| 插件基础版本 | `1.2.1` |
| Codex 清单版本 | `1.2.1+codex.20260817235511` |
| Python runtime | `1.2.1` |
| Codex 插件 | `ai-visit-website@personal` |
| Codex 状态 | `installed=true, enabled=true` |
| Codex source | `/Users/cvsc/Documents/项目开发文件夹/agentictools/plugins/ai-visit-website` |
| Marketplace | `/Users/cvsc/Documents/项目开发文件夹/agentictools/.agents/plugins/marketplace.json` |
| Bridge | `http://127.0.0.1:32145` |

```text
release/ai-visit-website-1.2.1.tgz
大小：33586 bytes
SHA-256：4000653b53277d7e1b1b5efe0642ada3dfadc2fabfdbe8de556645022277a083

release/ai-visit-website-1.2.1.zip
大小：82749 bytes
SHA-256：2516a00c8e599b00f97e3c42a90a424f697f0f02531c468d504cbd62e8e963b8

release/ai-visit-website-chrome-extension-1.5.0.zip
大小：533949 bytes
SHA-256：682f5e960dbdba6da562892b21f52f7edf90bb7c63d4598acfc16ea1ad5c747f
```

发布包已生成并安装到 Codex，但没有上传到 npm、GitHub 或其他远端。

## 4. 代码结构与同步规则

canonical Python 源码：

```text
src/agentictools/browser_bridge.py
src/agentictools/sitemap_discovery.py
src/agentictools/adapters/crawl4ai.py
src/agentictools/models.py
src/agentictools/service.py
src/agentictools/mcp_server.py
src/agentictools/url_policy.py
```

插件内置副本：

```text
plugins/ai-visit-website/server/src/agentictools/
```

canonical 与插件 Skill：

```text
skills/ai-visit-website/SKILL.md
plugins/ai-visit-website/skills/ai-visit-website/SKILL.md
```

修改 canonical Python 后必须同步内置副本。测试 `test_bundled_server_and_skill_match_the_canonical_sources` 会检查一致性。

宿主清单和启动器：

```text
plugins/ai-visit-website/.codex-plugin/plugin.json
plugins/ai-visit-website/.mcp.json
plugins/ai-visit-website/openclaw.plugin.json
plugins/ai-visit-website/package.json
plugins/ai-visit-website/plugin.json
plugins/ai-visit-website/mcp.json
plugins/ai-visit-website/bin/ai-visit-website-mcp
```

当前仓库 Chrome 扩展关键文件：

```text
ai-visit-website-chrome-extension-1.5.0/agent-browser-bridge.js
ai-visit-website-chrome-extension-1.5.0/background.js
ai-visit-website-chrome-extension-1.5.0/settings.js
ai-visit-website-chrome-extension-1.5.0/settings.html
ai-visit-website-chrome-extension-1.5.0/settings.css
ai-visit-website-chrome-extension-1.5.0/reuters-article-extractor.js
```

## 5. MCP 工具合同

版本 1.2.1 暴露 11 个工具：

```text
site_discover
article_list
page_read
browser_status
browser_page_read
browser_cancel
browser_batch_start
browser_batch_status
browser_batch_cancel
page_save
archive_search
```

Codex 中工具可能延迟加载，名称通常为 `mcp__ai_visit_website__<tool>`。更新/安装后应使用新任务；精确命名空间仍为空时重启 Codex 后再查一次。

标准 JSON-RPC 顺序：`initialize` → `notifications/initialized` → `tools/list`/`tools/call`。工具必须通过 `tools/call` 调用，不能把工具名直接当作 JSON-RPC method。

## 6. Bridge 实现、故障原因与临时手动启动

Bridge 不是独立守护进程。第一次执行 `browser_status`、`browser_page_read` 或批量浏览工具时，服务才调用 `default_browser_bridge()`：

- 尝试创建 `127.0.0.1:32145` HTTP server；
- 使用用户级共享的 `browser-bridge-token`；
- Chrome 扩展轮询该 HTTP 队列；
- 若端口已由另一个插件进程占用，当前 MCP 进程作为 HTTP client 复用它；
- owner MCP 退出后监听消失；
- 批次状态只存在于创建批次的 MCP 进程内。

因此，看到 `agentictools-mcp` 进程不代表 32145 已监听。直接运行 stdio MCP 也不会主动创建 Bridge，因为 Bridge 是浏览器工具首次调用时才懒加载。

```bash
lsof -nP -iTCP:32145 -sTCP:LISTEN
```

正式 `--bridge-only` 尚未实现。macOS 临时手动启动：

```bash
AI_VISIT_WEBSITE_BRIDGE_PORT=32145 \
'/Users/cvsc/Library/Application Support/AI Visit website/venv/bin/python' \
-c 'from agentictools.browser_bridge import default_browser_bridge; import signal; default_browser_bridge(); print("Bridge listening on 127.0.0.1:32145"); signal.pause()'
```

终端必须保持打开，`Ctrl+C` 停止。该方法已在隔离端口 `32146` 验证：监听成功，未带配对令牌的 HTTP 请求返回 `401`，测试进程随后已停止。

一次性配对值可在本机终端打印：

```bash
cd '/Users/cvsc/Documents/项目开发文件夹/agentictools/plugins/ai-visit-website'
./bin/ai-visit-website-mcp --print-bridge-token
```

此命令会显示敏感令牌。令牌只能填入本机扩展设置，禁止复制到聊天、报告、日志或发布包。默认端口 `32145`；Reuters Origin 应明确授权为 `https://www.reuters.com`。

## 7. 2026-08-20 Reuters 真实验收

用户请求：`打开 Reuters 网站，阅读新闻，并给我一份简报。`

```text
site_discover:
  success=true
  adapter=robots-sitemap
  capture_warning=robots_denied
  候选上限=500

article_list:
  total_candidates=500
  returned_candidates=120

公开 page_read:
  success=false
  status_code=403
  failure.code=robots_denied
  retryable=false

browser_status:
  success=true
  configured=true
  connected=true
  extension_version=1.5.0

首批 run_id=reuters-brief-20260820-1539:
  total=9, succeeded=6, failed=3
  失败均为 page_probe_failed, retryable=true

有限重试 run_id=reuters-brief-20260820-1539-retry1:
  total=3, succeeded=3, failed=0

最终正文覆盖：9/9
自动归档：0
```

覆盖 World 6 篇、Business 2 篇、Technology 1 篇，主题包括：恒大判决、中美无人机关税、基辅导弹袭击、美伊经济威胁、油价与霍尔木兹供应、黑海小麦供应、美国 40 万亿美元债务、Nebius 50 亿美元融资、全球银行采用蚂蚁国际金融 AI。

必须保留的证据边界：

- robots policy 仍阻止普通自动客户端正文读取；Chrome 成功不改变该事实。
- sitemap 只用于标题、URL、发布时间和候选排序；具体事实来自成功返回的 Chrome Markdown。
- 首次 3 篇失败不是 CAPTCHA/付费墙/登录失败；因其 `retryable=true` 且重要，只重试一次。
- 公司效果数字必须归因，例如“外汇对冲和配置成本降低 60% 以上”是蚂蚁国际管理层说法，并非 Reuters 独立验证。
- 未调用 `page_save`，不能声称文章已归档。

## 8. 已验证和未验证边界

1.2.1 已完成：

- `.tgz`、`.zip` 打包；
- Codex marketplace 安装；
- 启动器检查；
- MCP `initialize`，server version `1.2.1`；
- `tools/list` 列出 11 个工具；
- 真实 `tools/call`、Bridge 连接、Reuters 批次正文读取和报告。

本次编写交接文档时没有重新运行完整 pytest、validator、compileall 或 npm pack 校验。开始代码修改前必须重新运行，建立当前 dirty 工作区基线。

1.2.1 尚未在当前阶段完成真实 OpenClaw Gateway 或 Hermes 主机端到端运行。不能把 Codex 成功等同于所有宿主生产验收。

## 9. 下一步：正式 `--bridge-only`

建议入口：

```bash
./bin/ai-visit-website-mcp --bridge-only
./bin/ai-visit-website-mcp --bridge-status
```

最低要求：

1. 复用现有用户级 Bridge 数据目录和令牌。
2. 只监听 `127.0.0.1`，默认端口 `32145`。
3. 前台保持至 `SIGINT`/`SIGTERM`，输出不得包含令牌。
4. 端口已被兼容 Bridge 占用时明确报告“已存在”或健康状态，不能静默假装自己是 owner。
5. `--bridge-only` 不启动 MCP stdio，不输出 JSON-RPC 噪声。
6. 另一个 MCP 进程能通过同一 Bridge 完成 `browser_status` 和页面读取。
7. `--bridge-status` 至少报告监听地址、是否可达、扩展在线状态和版本，不显示令牌。
8. 保留现有智能体首次调用自动启动行为。
9. 为 Ctrl+C、端口冲突、无效端口、令牌文件异常和重复启动补测试。
10. 修正文档中“仅启动 MCP server 就会启动 Bridge”的误导表述：

```text
README.md
plugins/ai-visit-website/README.md
/Users/cvsc/Documents/snippet extension v1.4.3/AI_AGENT_BROWSER_BRIDGE_CN.md
```

完成通用 CLI 后再评估 macOS LaunchAgent、Windows 服务和 Linux systemd user；不要把平台常驻管理混入本轮最小实现。

## 10. 完整验证命令

### Python、插件和 Skill

```bash
cd '/Users/cvsc/Documents/项目开发文件夹/agentictools'

.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src plugins/ai-visit-website/server/src

python3 /Users/cvsc/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py \
  plugins/ai-visit-website
python3 /Users/cvsc/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/ai-visit-website
python3 /Users/cvsc/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  plugins/ai-visit-website/skills/ai-visit-website

(cd plugins/ai-visit-website && npm test && npm run pack:check)
git diff --check
```

### Chrome 扩展

```bash
cd '/Users/cvsc/Documents/项目开发文件夹/agentictools'

node tests/test_chrome_extension_contract.js
node --check ai-visit-website-chrome-extension-1.5.0/agent-browser-bridge.js
node --check ai-visit-website-chrome-extension-1.5.0/background.js
node --check ai-visit-website-chrome-extension-1.5.0/settings.js
node --check ai-visit-website-chrome-extension-1.5.0/reuters-article-extractor.js
git diff --check
```

### `--bridge-only` 现场验收

1. 确认 32145 没有旧监听者。
2. 运行 `./bin/ai-visit-website-mcp --bridge-only`。
3. 不调用智能体工具，直接在扩展 Settings 点击 **Check Connection**，必须成功。
4. 在新 Codex 任务调用 `browser_status`，必须看到 `connected=true` 和扩展版本。
5. 读取一个授权网页，确认 Markdown、最终 URL 和 SHA-256。
6. 停止独立 Bridge，再调用 `browser_status`，确认自动启动路径仍能恢复监听。
7. 重复启动，确认端口冲突有明确安全输出。
8. 确认日志、测试和报告均不包含令牌、Cookie 或浏览器存储。

## 11. 打包、安装和完成定义

```bash
cd '/Users/cvsc/Documents/项目开发文件夹/agentictools/plugins/ai-visit-website'
npm pack

cd '/Users/cvsc/Documents/项目开发文件夹/agentictools'
codex plugin add ai-visit-website@personal -c enable.plugins=disabled
```

安装后新建 Codex 任务。安装状态只是第一层验收，还必须验证 manifest、启动器、MCP handshake、`tools/list` 和至少一次真实 `tools/call`。

下一阶段只有同时满足以下条件，才可报告 Bridge 生产化完成：

- `--bridge-only` 与安全状态入口已实现；
- 默认智能体自动启动路径仍兼容；
- canonical/内置副本和文档一致；
- Python、插件、Skill、Chrome 扩展测试通过；
- 独立 Bridge 与另一个 MCP 进程完成真实调用；
- Reuters 或另一个授权站点至少一篇正文读取成功；
- 无凭据泄漏、访问控制绕过或自动全量归档；
- 新功能完成后创建新的 Git 回退点和发布包，不覆盖现有标签。

当前已有修改前基线和 Chrome 扩展智能体化两个可靠标签。恢复时优先从标签新建恢复分支，不要用破坏性命令覆盖未提交工作。
