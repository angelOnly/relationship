# 关系复盘｜盖洛普对话与长期复盘工具

一个面向双人长期使用、可用 Docker 部署的关系记录网页。当前版本为 `4.1.2`，重点是把“长期记录结构”和“某一阶段的具体矛盾”分开：表单保存事实、感受、需要与回应，阶段目标可以采纳、暂停、完成或归档，不需要关系状态一变化就重新开发数据库。

## 页面与使用方式

- `/journal`：只有一张按月切换的关系日历，默认选中今天；点击任意日期即可补记，并在同一个日期工作区切换“小娌记录／小元记录／AI 反馈”。周日会出现对应自然周的小结卡片；月度复盘按需从月份标题打开，不再平铺历史或固定周次。
- `/chat`：注入双方盖洛普画像的场景对话。手机端分为“对话／进步趋势／复盘库”；可以明确选择本次记录者，模型最多追问 1–3 个关键问题，再分析内在期待、才干状态、互动循环和正确沟通方式。
- `/actions`：分为“当前目标／共同底线／长期练习／历史目标”，阶段目标与长期规则不挤在同一个长页面里；手机端“添加目标”表单默认收起。

推荐流程：在日历选中当天或需要补记的日期 → 双方分别保存记录 → 点击“分析这一天” → 阅读 AI 的双向行为反馈与分数 → 在行动清单中决定是否采纳 AI 建议的唯一目标。每个周日可统一填写上一自然周（周一至周日）的小结，再生成对应周期的 AI 复盘。

AI 评分只评价本周期可观察行为，包括期待表达、才干调节、回应对方和合作修复，不评价人格、爱意或关系价值。信息不足时允许不评分，不要求用户自己填写量表。

## 长期通用记录结构

每日记录固定关注：

- 值得肯定的具体事实
- 最值得记录的事件
- 当时的感受和真正需要
- 小娌与小元各自如何表达、回应
- 修复请求与当前跟进状态

周记录关注重复模式和有效做法，按真实周日作为唯一键，覆盖周一至周日；月记录关注趋势和下个周期唯一重点。具体矛盾、临时策略和 AI 目标不会变成数据库列。

SQLite 使用通用文档与修订结构：

- `record_schemas`：记录当前表单定义和版本。
- `record_documents`：保存日、周、月的结构化内容。
- `record_revisions`：每次修改都保留一个版本。
- `action_items`：保存长期底线、练习和具有生命周期的阶段目标。
- `scene_analyses`：保存完成后的精炼盖洛普案例，支持关键词模糊检索。
- `period_reviews`：保存日、周、月 AI 评分、反馈和调整目标。

本项目处于开发初期，不执行旧表迁移；新数据库不会创建旧版 `daily_entries`、`weekly_summaries` 和 `monthly_summaries`。

## 人物与 JSON 约定

项目只有一份固定人物目录，界面、AI 输出、数据库元数据和导出统一使用：

```json
[
  {"id": "xiaoli", "name": "小娌"},
  {"id": "xiaoyuan", "name": "小元"}
]
```

`id` 只用于接口稳定识别，展示与数据库人物值使用“小娌／小元”。每日记录的 `author` 保存标准姓名，行动清单的 `owner` 只允许“共同／小娌／小元”。AI 数据不再使用 `score_me`、`score_partner` 一类角色耦合字段，而是拆成两个职责清楚的 JSON 列：

- `participants_json`：固定顺序的人物数组；每项包含人物引用、内在期待、才干状态、行为反馈和分数。
- `interaction_json`：双方共同形成的互动循环、沟通方案、下一步和互动评分。

这样新增人物属性时只扩展数组项，不需要继续增加 `*_me`、`*_partner` 数据库列；共同信息也不会重复写入两个人物对象。

## 盖洛普技能与长期背景

项目内的 `skills/gallup-relationship-review` 会在盖洛普聊天和周期复盘中注入。`性格细节.md` 提炼出的内容作为“需要由本次事实验证的长期背景”，不是固定人格结论，也不能用来为羞辱、威胁、控制或失信免责。

澄清阶段不写长期记忆。只有模型完成结构化分析后，应用才保存问题摘要、关键词、双方期待、才干状态、沟通方案、行为证据、自动评分、进步判断和时间戳，不保存寒暄与重复追问。

## 模型配置

复制 `.env.example` 为 `.env.local`，一行写一个变量，不要把多个变量连在同一行：

```dotenv
OPENAI_API_KEY=替换为你新生成的密钥
OPENAI_BASE_URL=https://llm-api.xiaolicloud.cn:18443/v1
OPENAI_MODEL_NAME=gemini-3.1-pro-high
OPENAI_TIMEOUT_SECONDS=45
OPENAI_JSON_MODE=0
```

等号两侧不需要空格，值通常也不需要引号。`.env.local` 已被 Git 和 Docker 构建上下文忽略；密钥只由 Flask 服务端读取，浏览器不会拿到密钥。

页面提供以下模型选择，服务端使用白名单映射：

| 页面名称 | 实际请求模型 |
| --- | --- |
| `gemini-3.1-pro-high` | `gemini-3.1-pro-high` |
| `gemini-3.5-flash-high` | `gemini-3-flash-agent` |
| `gemini-3.5-flash-medium` | `gemini-3.5-flash-low` |
| `gemini-3.1-flash-lite` | `gemini-3.1-flash-lite` |
| `gemini-3.5-flash-extra-low` | `gemini-3.5-flash-extra-low` |

应用调用 OpenAI 兼容的 `/chat/completions` 接口，实际使用的模型会随聊天分析或周期复盘记录到 SQLite。

## Docker Compose 部署

如果使用 Portainer、1Panel、群晖 Container Manager 等面板部署 Stack，不要依赖上传 `.env.local` 文件。请在面板的环境变量区域填写：

```dotenv
OPENAI_API_KEY=替换为你新生成的密钥
OPENAI_BASE_URL=https://llm-api.xiaolicloud.cn:18443/v1
OPENAI_MODEL_NAME=gemini-3.1-pro-high
OPENAI_TIMEOUT_SECONDS=45
OPENAI_JSON_MODE=0
```

截图里的 `env file /data/compose/15/.env.local not found` 表示部署面板在服务器临时目录里找不到 `.env.local`。当前 `docker-compose.yml` 已改为直接读取 Stack 环境变量，因此不需要把密钥文件上传到这个目录。

首次部署：

```bash
cd relationship_journal
docker compose --env-file .env.local up -d --build
```

浏览器打开 `http://服务器IP:8080`。手机与服务器处于同一局域网时，也可直接用手机访问这个地址。

如果部署后仍看到旧页面，确认服务器已经拿到当前项目文件，再强制重建容器：

```bash
docker compose down
docker compose build --no-cache
docker compose up -d --force-recreate
```

随后访问：

```text
http://服务器IP:8080/api/health
```

返回结果应包含 `"version":"4.1.2"`，且 `gallup_chat`、`period_reviews`、`participant_arrays`、`flexible_records`、`dynamic_actions`、`model_selector` 和 `calendar_journal` 都为 `true`。HTML 已禁用缓存，静态资源也带版本参数；如果健康检查仍不是 `4.1.2`，说明访问的仍是旧容器或旧反向代理目标。

停止服务：

```bash
docker compose down
```

## 数据持久化与备份

SQLite 数据库保存在 `./data/relationship.db`。`docker-compose.yml` 会把本地 `./data` 挂载到容器 `/app/data`，因此重建容器不会删除正式记录。

网页提供当前月份 CSV 导出和完整 JSON 备份。建议定期备份整个 `data` 目录。

## 手机显示

页面采用响应式布局：窄屏下月历保持七列、每天只显示轻量状态点；点击日期后才打开对应记录，周日小结和月度复盘默认收起。输入框使用至少 16px 字号，避免 iPhone 聚焦时自动放大；页面不应产生横向滚动。手机访问时使用服务器的局域网 IP，不要使用手机自身的 `127.0.0.1`。

## 更换端口与访问保护

要更换端口，可将 `docker-compose.yml` 中的 `"8080:8080"` 改为例如 `"8090:8080"`，随后访问 `http://服务器IP:8090`。

当前版本没有账号登录，适合家庭内网、VPN、ZeroTier，或带访问控制的反向代理。若直接暴露公网，请先在 Nginx Proxy Manager、Cloudflare Access 等入口增加认证；关系记录和 API 密钥都不适合裸露在公网。
