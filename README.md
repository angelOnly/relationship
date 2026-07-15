# 关系复盘｜盖洛普对话与长期复盘工具

一个可直接用 Docker 部署的小型双人关系复盘网页。除每日记录外，新增了注入双方盖洛普才干画像的对话助手：它会用少量问题厘清场景，自动分析双方内在期待、才干状态与沟通方式，并只把完成后的精炼案例写入 SQLite。

## 页面

- `/chat`：盖洛普场景对话、自动行为反馈、相似历史检索与进步趋势
- `/actions`：双方必须停止和开始练习的行动清单
- `/journal`：每日双人记录、历史查询、每周小结、月度复盘

## 模型配置

复制 `.env.example` 为 `.env.local`，在本地文件中配置服务端模型变量。`.env.local` 已被 Git 与 Docker 构建上下文忽略，浏览器不会接触 API 密钥。当前应用调用 OpenAI 兼容的 `/chat/completions` 接口。

项目内的 `skills/gallup-relationship-review` 会在每一轮模型对话中注入。澄清阶段不写长期数据库；只有模型完成结构化分析后，才保存摘要、关键词、双方期待、才干状态、沟通方案、行为反馈、自动评分和进步判断。

## Docker Compose 部署

```bash
cd relationship_journal
docker compose up -d --build
```

浏览器打开：

```text
http://服务器IP:8080
```

停止：

```bash
docker compose down
```

更新代码后重建：

```bash
docker compose up -d --build
```

## 数据持久化

SQLite 数据库保存在：

```text
./data/relationship.db
```

`docker-compose.yml` 已将本地 `./data` 挂载到容器 `/app/data`，重建容器不会丢数据。

网页右上角还提供：

- 导出当前月份 CSV
- 备份全部记录 JSON

建议定期备份整个 `data` 目录。

## 更换端口

将 `docker-compose.yml` 中：

```yaml
ports:
  - "8080:8080"
```

改为例如：

```yaml
ports:
  - "8090:8080"
```

然后访问 `http://服务器IP:8090`。

## 反向代理

使用 Nginx Proxy Manager 时，将 Forward Hostname/IP 指向运行 Docker 的机器 IP，Forward Port 填 `8080`，Scheme 选 `http`。

## 说明

当前版本没有账号登录，适合部署在家庭内网、VPN、ZeroTier 或带访问控制的反向代理后。若直接暴露公网，建议在 Nginx Proxy Manager 或 Cloudflare Access 增加认证。
