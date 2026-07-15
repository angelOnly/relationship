# 关系复盘｜30 天文字沟通工具

一个可直接用 Docker 部署的小型双人关系复盘网页。数据保存在 SQLite 中，一个月一个周期，可查询历史、记录每日三行、行动评分、每周小结和月度复盘。

## 页面

- `/actions`：双方必须停止和开始练习的行动清单
- `/journal`：每日双人记录、历史查询、每周小结、月度复盘

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
