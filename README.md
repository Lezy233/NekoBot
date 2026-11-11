# NekoBot

基于 NoneBot2 + OneBot V11 的 QQ 私聊机器人，DeepSeek 驱动，带表情回复与会话压缩。

## 项目结构

```text
项目根/
├── .env                        # CHAT_API_DEEPSEEK / SUMMARY_API_DEEPSEEK / VISION_API_DEEPSEEK
├── plugins/
│   └── chat/
│       ├── __init__.py         # 展示层：事件处理、消息组装、计划渲染与分条发送
│       ├── plan.py             # 表达计划解析：LLM 输出协议、校验、历史规范化
│       ├── llm.py              # 获取层：异步调 DeepSeek（聊天 + 摘要）
│       ├── sticker.py          # 表情层：catalog.json 元数据 + intent 检索
│       ├── store.py            # 存储层：SQLite 历史与摘要
│       ├── persona.py          # 人格加载
│       ├── overrides.py        # 按会话注入特殊身份/情感
│       ├── compress.py         # 上下文压缩：窗口外历史压缩为摘要
│       ├── debug.py            # 管理员调试指令（<admin> 模式）
│       └── config.py           # 配置读取
├── persona/
│   ├── default.local.md        # 人格文件（gitignored）
│   ├── default.example.md      # 人格模板
│   ├── overrides.local.toml    # 特殊身份/情感配置（gitignored）
│   └── overrides.example.toml  # overrides 模板
├── stickers/
│   ├── catalog.json            # 表情目录：path + intents + aliases
│   └── emoji/                  # 表情包目录，支持子目录分类与软链接
├── tests/                      # unittest 验收测试（无需真实 QQ / DeepSeek）
└── data/                       # chat.db
```

## 架构与输出逻辑

### 一次回复的数据流

```text
私聊消息
  │  过滤：非私聊 / 自身消息 / 空消息；管理员消息先走 debug 指令
  ▼
store.append(user) ──→ compress.maybe_compress（超阈值时压缩窗口外历史）
  ▼
build_messages：人格 → 会话 override → 输出协议 → 历史摘要 → 滑动窗口历史 → 当前消息
  ▼
llm.chat（唯一一次 LLM 调用，DeepSeek 异步请求）
  ▼
plan.parse_plan：把 LLM 输出解析为表达计划 ChatPlan（确定性校验）
  ▼
render_plan：text → 纯文本；sticker → sticker.resolve_sticker(intent) 检索真实图片
  ▼
逐条 matcher.send，相邻消息 sleep 0.35～0.9s，最后一条后不休眠
  ▼
store.append(assistant, plan_to_transcript(plan)) —— 历史只写规范化文本
```

三种表示严格分离：LLM 内部的 JSON 协议、发出去的 QQ 消息、留给模型读的历史文本，互不混用。

### 多模态（图片/表情包识别）

- 用户私聊中的图片（照片与 QQ 表情包）随消息一起交给视觉模型识别：含图片且配置了 `VISION_API_DEEPSEEK` 时，用 `vision_api` / `vision_model` 发起这一次（仍只有这一次）LLM 调用，content 为 OpenAI 多模态格式（`text` + `image_url`）
- 每条消息最多取 3 张图片（按 URL），未配置视觉模型时回退到文本模型，按 `[图片]` 占位文本处理
- 会话历史中图片以 `[图片]` 占位（不含 URL、不入 CQ 码），摘要压缩时与表情消息同样视为媒体折叠

### 表达计划（plan.py）

LLM 不直接输出 QQ 正文，而是输出 JSON 表达计划：

```json
{"messages": [
  {"type": "text", "content": "还没睡"},
  {"type": "sticker", "intent": "speechless"},
  {"type": "text", "content": "有事说事"}
]}
```

- `messages` 为 1～3 个有序元素，每个元素是一条待发送消息，空行无分条语义
- `text` 必须有非空 `content`；`sticker` 只携带 `intent`，不写文件名/路径/URL/CQ 码
- intent 仅允许 `happy`、`speechless`、`angry`、`shy`、`comfort`、`awkward`，每次回复最多一个 sticker
- 协议提示由 `plan.output_protocol_prompt()` 统一生成并作为独立 system 消息注入，人格文件只管语气，不含协议内容

`parse_plan()` 是确定性的应用层边界：

- 合法 JSON 但结构非法 → 抛 `PlanError`
- `{`/`[` 开头的损坏 JSON → 抛 `PlanError`，调用方回退安全文本，**绝不把原文发给用户或写进历史**
- 兼容模型偶发包裹的一对 ```` ```json ```` 围栏和 `角色：` 前缀；普通自然语言按单条文本兼容
- `plan_to_transcript()` 把计划规范化为历史文本（表情写作 `[表情:speechless]`）

### 表情检索（sticker.py）

- `stickers/catalog.json` 登记 `path`（相对 stickers/）、`intents`、`aliases`；加载时校验相对路径、禁止 `..`、必须在 stickers/ 内、文件存在且扩展名合法，无效条目静默跳过
- 索引按 catalog mtime 缓存并自动失效；同一 intent 多张候选时随机选一张
- `resolve_sticker(intent)`：未知 intent / 无候选 / 读取失败一律返回 None，主流程丢弃该表情保留文本
- 保留 `render()`（按文件名取图）与 `list_dir()`（列目录）供 `<emoji>` 调试指令使用
- catalog 为全部 6 个 intent 配了真实候选（同 intent 多张时随机选一张），避免模型选到无图 intent 被静默丢弃

### 消息组装与历史（build_messages / store / compress）

- 顺序：人格 → 会话级 override → 输出协议 → 历史摘要 → 滑动窗口历史 → 当前用户消息
- 用户消息先入库再组装，因此窗口内最后一条 user 消息会被去重
- 历史超过 `CHAT_COMPRESS_THRESHOLD` 条时，窗口外历史经本地折叠后由 DeepSeek 压缩为摘要，滑动窗口与特殊身份 override 行为保持不变

## 群聊

- **白名单**：只与 `persona/overrides.local.toml` 中存在条目的群对话（`[group."群号"]` 节的 prompt 同时作为该群的注入）；私聊不受白名单限制
- **管理员调试**：`admin_users` 在群聊和私聊中都可使用 `<admin>` 调试指令，不受白名单限制
- **自主参与**：白名单群内每条消息走一次 LLM 调用（含参与判断协议），模型判断话题无关或不想参与时输出空计划 `{"messages":[]}`，应用跳过本次发言；群聊中协议损坏同样静默跳过，不打扰群成员
- **发送者区分**：群聊用户消息以「昵称（QQ号）：正文」格式入库并传给模型；群聊历史、摘要压缩与私聊共用同一存储

## 管理员调试

私聊发送 `<admin>` 进入调试模式，`</admin>` 退出，`<help>` 查看指令。常用：

- `<echo> 文本` — 走与 AI 回复相同的表达计划渲染管线并分条发送；支持 `[表情:名称]` 标签、普通文本和 JSON 表达计划。模拟 AI 连发多条短句：`<echo> {"messages":[{"type":"text","content":"A"},{"type":"text","content":"B"},{"type":"text","content":"C"}]}`
- `<emoji> "名称"` / `<emoji> ls [目录]` — 按文件名取图 / 列目录
- `<compact>` — 手动触发上下文压缩
- `<clear> private=QQ号` / `<clear> public=群号` — 删除指定私聊/群聊会话的全部聊天记录（含摘要），需 `<YES>`/`<yes>` 二次确认，其他输入视为取消
- `<persona>` / `<history>` — 查看人格加载与历史条数

## 测试

```bash
python -m compileall plugins tests
python -m unittest discover -s tests -v
```

测试只使用临时目录与 mock，不访问真实 QQ、DeepSeek 或 data/chat.db。

## 如何开始

### 本机开发

本机开发使用 `.env` 保存配置。先在项目根目录新建 `.env`，至少填写：

```dotenv
CHAT_API_DEEPSEEK=<你的 DeepSeek API Key>
CHAT_ADMIN_USERS=<你的 QQ 号>
```

`SUMMARY_API_DEEPSEEK` 和 `VISION_API_DEEPSEEK` 可按需配置；摘要模型缺省时复用聊天配置，未配置视觉模型时图片按 `[图片]` 占位文本处理。

安装依赖并启动：

```bash
poetry install --only main --no-root
poetry run python bot.py
```

Poetry 默认把虚拟环境放在 `~/.cache/pypoetry/virtualenvs/`，项目目录中没有 `.venv` 不代表未使用虚拟环境。可用 `poetry env info` 查看实际环境。

### Docker 部署

Docker 部署使用 `.env.prod`，与供本机开发使用的 `.env` 区分。先新建 `.env.prod`：

```dotenv
CHAT_API_DEEPSEEK=<你的 DeepSeek API Key>
CHAT_ADMIN_USERS=<你的 QQ 号>
SUMMARY_API_DEEPSEEK=
VISION_API_DEEPSEEK=
```

然后初始化人格、会话覆盖配置和数据目录：

```bash
cp persona/default.example.md persona/default.local.md
cp persona/overrides.example.toml persona/overrides.local.toml
mkdir -p data
```

其中第二次复制是可选的；不需要私聊/群聊专属注入或群聊白名单时，可以不创建 `overrides.local.toml`。创建后请删除示例条目，再填写自己的配置。

构建并启动：

```bash
LOCAL_UID=$(id -u) LOCAL_GID=$(id -g) docker compose up -d --build
```

`LOCAL_UID` 和 `LOCAL_GID` 让容器用户与宿主机当前用户匹配，避免挂载的 `data/` 出现写入权限问题；当前用户的 UID/GID 都是 1000 时，也可以直接运行 `docker compose up -d --build`。

查看状态和日志：

```bash
docker compose ps
docker compose logs -f
```

按 `Ctrl+C` 只会退出日志查看，不会停止机器人。修改 `.env.prod` 或 `compose.yaml` 后执行 `docker compose up -d` 重新创建容器；修改 Python 代码或依赖后执行 `docker compose up -d --build` 重新构建。仅执行 `docker compose restart` 不会重新加载 `env_file`。

### 连接 NapCat

NapCat 是独立的 QQ 协议端，不包含在本仓库中。安装并登录 NapCat 后，创建 OneBot V11 反向 WebSocket 客户端：

- NapCat 直接运行在宿主机：连接 `ws://127.0.0.1:8080/onebot/v11/ws`。
- NapCat 也运行在 Docker 中：需先接入本项目的 Compose 网络，再连接 `ws://nekobot:8080/onebot/v11/ws`；此时 `127.0.0.1` 指向 NapCat 容器自身，不能用于连接 NekoBot。

如果配置了 `ONEBOT_ACCESS_TOKEN`，NapCat 与 NekoBot 两边必须一致。8080 端口默认只映射到宿主机回环地址，不要在没有访问控制的情况下暴露到公网。

### 数据、表情与迁移

- `data/chat.db` 保存会话历史，通过 `./data:/app/data` 挂载到宿主机；重建或重启容器不会清空它，备份时应保存该文件。
- `persona/` 以只读方式挂载。新用户应先从示例复制本地人格；`persona/overrides.local.toml` 才是代码实际读取的覆盖配置文件。
- `stickers/` 以只读方式挂载。`stickers/catalog.json` 会进入仓库，但 `stickers/emoji/` 中的实际图片被 Git 忽略；迁移到新机器时需单独准备图片，否则文字聊天仍可使用，但表情检索会失败。
- 表情通过 Base64 内联发送，不需要与 NapCat 共享图片目录。

### 隐私与公开仓库

`.gitignore` 已排除 `.env`、`.env.*`、`data/`、`persona/*.local.*` 和 `stickers/emoji/`，正常执行 `git add` 不会加入 API Key、聊天记录、本地人格或表情图片。不要使用 `git add -f` 强制加入这些文件；公开仓库前应使用 `git status` 和 `git diff --cached` 检查暂存内容。

`env_file` 只在创建容器时注入环境变量，不会把 `.env.prod` 复制进镜像。但宿主机 root/docker 用户以及容器内程序仍能读取这些值；不要公开分享未经脱敏的 `docker inspect`、`docker compose config` 或 `docker compose exec nekobot env` 输出。若密钥已经泄露，应立即在对应平台吊销并更换。

## 参考文档

- [NoneBot文档](https://nonebot.dev/)
- [NapCat文档](https://napcat.napneko.icu/)
- Prompt参考: [玖帕喵](https://jiupamiao.asia/market)
