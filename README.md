# NekoBot
## 项目结构

```text
项目根/
├── .env                    # DEEPSEEK_API_KEY
├── plugins/
│   └── chat/
│       ├── __init__.py     # 展示层：事件处理
│       ├── llm.py          # 获取层：异步调 DeepSeek
│       ├── store.py        # 存储层：SQLite 历史
│       ├── persona.py      # 人格加载
│       └── config.py       # 配置读取
├── persona/
│   └── default.md          # 人格文件
└── data/                   # chat.db
```

## 如何开始

在项目根目录运行 `nb run` .

## 参考文档

- [NoneBot文档](https://nonebot.dev/)
- [NapCat文档](https://napcat.napneko.icu/)

