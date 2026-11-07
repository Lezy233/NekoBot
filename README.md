# NekoBot
## 项目结构

```text
项目根/
├── .env                        # CHAT_API_DEEPSEEK / SUMMARY_API_DEEPSEEK
├── plugins/
│   └── chat/
│       ├── __init__.py         # 展示层：事件处理、消息组装
│       ├── llm.py              # 获取层：异步调 DeepSeek
│       ├── store.py            # 存储层：SQLite 历史
│       ├── persona.py          # 人格加载
│       ├── overrides.py        # 按会话注入特殊身份/情感
│       ├── sticker.py          # 表情标签解析、表情列表注入
│       ├── compress.py         # 上下文压缩：窗口外历史压缩为摘要
│       └── config.py           # 配置读取
├── persona/
│   ├── default.local.md        # 人格文件（gitignored）
│   ├── default.example.md      # 人格模板
│   ├── overrides.local.toml    # 特殊身份/情感配置（gitignored）
│   └── overrides.example.toml  # overrides 模板
├── stickers/                   # 表情包目录，支持子目录分类与软链接
└── data/                       # chat.db
```

## 如何开始

在项目根目录运行 `nb run` .

## 参考文档

- [NoneBot文档](https://nonebot.dev/)
- [NapCat文档](https://napcat.napneko.icu/)

