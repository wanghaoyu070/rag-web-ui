# RAG Desk

**让你的文档成为可对话的知识库。**

RAG Desk是支持本地模型、文档语义检索与来源引用的开源知识库应用，由 [wanghaoyu070](https://github.com/wanghaoyu070) 维护与持续改进。

基于 [RAG Web UI](https://github.com/rag-web-ui/rag-web-ui) 开发，保留上游 Git 历史和许可证。RAG Desk目前处于早期迭代阶段。

## 可以做什么

- 创建知识库，上传 PDF、DOCX、Markdown 和 TXT 文档。
- 解析文档、建立向量索引，查看处理状态并测试检索。
- 基于资料多轮问答，展示模型生成的引用。
- 使用 API Key 调用检索接口，返回相关片段与元数据。
- 通过 Ollama 使用本地模型，也保留上游的外部模型适配能力。

## 本地启动

需要 Docker Desktop、Docker Compose 和已运行的 Ollama。

```sh
git clone https://github.com/wanghaoyu070/zhipage.git
cd zhipage
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
cp deploy/local/.env.example deploy/local/.env
# 编辑 deploy/local/.env，将 SECRET_KEY 替换为随机值
docker compose -f deploy/local/compose.yml up -d --build
```

访问 http://localhost:8088 ，注册账户、创建知识库并上传文档。详见 [本地部署说明](LOCAL_DEPLOY.md)。

本地示例只绑定本机。Docker 项目名及数据卷暂保留 `rag-web-ui`，避免更名影响已有数据。真实密钥与 `.env` 不应提交到仓库。

## 已知限制

- 当前小模型可能在检索正确时仍错误拒答，或生成错误引用；回答需要核查。
- 多知识库聊天当前只使用第一个有效知识库进行检索。
- 文档列表尚不支持点击查看原文。
- API Key 接口返回检索片段，不直接生成问答回复。
- 尚未验证复杂 PDF/Word、扫描件、大批量文档与高并发；不应据此视为生产可用。

## 技术栈

Next.js、React、TypeScript、FastAPI、LangChain、MySQL、ChromaDB / Qdrant、MinIO、Ollama。

## 近期方向

- 修正问答模型适配、提示词和引用编号。
- 增加原文预览与下载入口。
- 改进检索相关性和多知识库支持。
- 完善关键流程验证与部署说明。

按独立改动逐步验证和提交。欢迎通过 [Issues](https://github.com/wanghaoyu070/zhipage/issues) 报告问题或提出建议，请勿上传密钥及敏感文档。

## 测试资料

[test-data/tcm-diet](test-data/tcm-diet) 提供中医饮食科普测试文本、虚构活动资料与预期答案，仅用于检索问答测试，不用于临床决策。

## 来源与许可证

本项目沿用仓库中的 [Apache-2.0 许可证](LICENSE)，保留上游版权、许可证和修改历史。上游原始说明归档于 [docs/upstream](docs/upstream)，其中关于使用范围的表述属于上游原文，不应被理解为RAG Desk新增的许可条款；上游 README 与许可证表述存在不一致，需进一步向上游核实。

RAG Desk的本地部署基线和后续改进由 wanghaoyu070 维护。本次品牌整理不改变上游代码的版权归属，也不新增许可限制。
