# 社团数据库型 RAG 机器人

一个以“数据库检索优先”为核心的社团 AI 机器人 MVP。

## 能力

- 管理后台录入社团结构化信息，并带草稿、待发布、已发布状态
- 机器人优先从数据库读取关键字段，用模板直出回答
- 对 FAQ、制度、介绍类补充说明做轻量文本检索，作为辅助 RAG
- 记录聊天日志和未命中问题，方便持续补知识

## 启动

```bash
python3 -m app.server
```

默认服务地址：`http://localhost:3000`

后台页面：`http://localhost:3000/admin`

## 模型 API 配置

1. 复制配置文件：

```bash
cp .env.example .env
```

2. 按你的模型 API 修改 `.env`：

```env
HOST=127.0.0.1
PORT=3000
MODEL_BASE_URL=https://api.openai.com/v1
MODEL_NAME=gpt-4o-mini
MODEL_API_KEY=your_api_key_here
MODEL_TIMEOUT_MS=20000
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=your_embedding_api_key_here
```

3. 启动项目：

```bash
python3 -m app.server
```

说明：

- 后端默认按 OpenAI 兼容接口调用外部模型 API
- 语义检索需要额外可用的 Embedding 模型接口
- 关键字段仍然直接来自数据库，不会交给模型改写
- 如果没有配置 API Key，系统仍可运行，只是 `hybrid` 补充说明不会增强
- 如果没有配置 Embedding 模型，系统会退回普通文本匹配兜底，语义召回不会生效
- 聊天模型和 Embedding 现在支持分开配置不同的 API Key

## 常见 API 配置

- OpenAI：

```env
MODEL_BASE_URL=https://api.openai.com/v1
MODEL_NAME=gpt-4o-mini
MODEL_API_KEY=你的密钥
```

- DeepSeek 兼容 API：

```env
MODEL_BASE_URL=https://api.deepseek.com/v1
MODEL_NAME=deepseek-chat
MODEL_API_KEY=你的密钥
```

- Embedding 建议：

```env
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=你的 OpenAI Embedding 密钥
```

如果你的聊天模型平台本身不提供 `/embeddings` 接口，语义检索就需要单独接一个 Embedding 提供方。

- 其他 OpenAI 兼容平台也可以直接接，只需要替换 `MODEL_BASE_URL`、`MODEL_NAME` 和 `MODEL_API_KEY`

## 部署方式

- 把本项目部署到服务器或本地机器
- 通过 `.env` 配置外部模型 API
- 对外只暴露本项目服务端口，不需要自己维护 GPU 模型服务

## 运行测试

```bash
python3 -m unittest discover -s tests
```

## 主要接口

- `POST /chat`
- `GET /faq`
- `GET /admin/entities`
- `POST /admin/entities`
- `PUT /admin/entities/:id`
- `POST /admin/entities/:id/publish`
- `GET /admin/chat-logs`
- `GET /admin/unmatched-questions`

## 数据设计

统一使用 `entities` 表管理不同类型记录，类型包括：

- `club_profile`
- `department`
- `event`
- `signup_rule`
- `contact`
- `faq_entry`
- `policy_article`

每条记录都具备：

- `status`
- `effective_at`
- `updated_at`
- `updated_by`
- `version`

关键字段由机器人直接从数据库读取，不交给模型改写。

## 代码说明

- `app/server.py`：Python HTTP 服务入口
- `app/chat.py`：数据库优先问答逻辑
- `app/repository.py`：SQLite 数据访问
- `app/model.py`：外部模型 API 调用
- `public/`：前端页面资源
