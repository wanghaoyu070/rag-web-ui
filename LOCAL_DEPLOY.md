# 本地部署与开发

本仓库基于 https://github.com/rag-web-ui/rag-web-ui ，保留上游历史与许可证。

## 首次启动

需要 Docker Desktop、Docker Compose 和宿主机 Ollama。源码建议放在不受 iCloud 自动卸载影响的目录。

```sh
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
cp deploy/local/.env.example deploy/local/.env
# 编辑 deploy/local/.env，将 SECRET_KEY 替换成随机值
# 可用 python3 -c 'import secrets; print(secrets.token_urlsafe(48))' 生成
docker compose -f deploy/local/compose.yml up -d --build
```

入口：http://localhost:8088；API 文档：http://localhost:8088/redoc；MinIO 控制台：http://localhost:9001。
服务仅绑定本机，数据保存于 Docker 命名卷。示例数据库和存储密码仅用于本机测试。
网页可自行注册账户。不要提交 .env、真实密钥、用户凭据和上传文件。

## 日常操作

```sh
docker compose -f deploy/local/compose.yml ps
docker compose -f deploy/local/compose.yml logs --tail=100 backend nginx
curl http://localhost:8088/api/health
# 修改代码后重建并应用
docker compose -f deploy/local/compose.yml up -d --build
# 停止，保留数据
docker compose -f deploy/local/compose.yml down
```

宿主机 Ollama 必须运行。不要对当前服务执行 down -v，否则会删除数据卷。

## 本地兼容处理

前端不挂载源码以保留 standalone 构建结果；修正前端健康检查；Nginx 配置复制到镜像以避开文件共享问题；保留代理 Host 的端口；Chroma 服务和客户端固定 0.6.3；本地 Python 约束避免新旧 LangChain 混装和无用 CUDA 依赖。

## 验证与已知限制

已验证：前端生产构建与类型检查、数据库迁移、API 健康、注册登录、TXT 上传与处理、检索、本地问答、浏览器导航和流式响应。pip check 通过。
未验证：复杂 PDF/Word、扫描件、批量处理和高并发。
已发现：3B 模型会在检索到正确资料后仍错误拒答，且引用格式或编号可能错误；多知识库问答只使用第一个有效知识库。问答适配和提示尚待改进，不能视为生产可用。

## 测试文档

`test-data/tcm-diet/上传文档` 中的5个TXT用于上传，测试题和使用说明不要上传，避免答案泄漏。

## 持续开发

保留 upstream 指向原项目，origin 指向个人仓库。按独立改动逐次实现、验证、提交。提交格式：`fix: 中文说明`、`feat: 中文说明` 等。
