# 门窗识图顾问工具

一个本地运行、可投喂知识、可上传图片识别、可生成快捷回复的门窗顾问工作台。知识库已经内置到仓库 `data/`，不再依赖 `/Users/cc/Desktop/门窗知识库` 这类本机路径。

## 已实现

- 上传截面图、样角图、报价图、玻璃爆裂图，生成结构分析和可复制回复。
- 知识投喂入口：标题、标签、图文内容、回复模板、配图一并入库。
- 仓库内置知识库：`data/knowledge_base.json`、`data/knowledge/*.md`。
- 安全备份：每次写入会先备份到 `data/kb_backups`。
- Vision API 可选：配置 `LLM_API_KEY` 后走 OpenAI-compatible 图像分析；不配置也能用本地知识库和规则降级分析。
- 保留原训练台、悬浮窗、评论采集和对话蒸馏接口。

## 启动

```bash
cd /Users/cc/Documents/New\ project\ 2/win
python3 -m pip install -r requirements.txt
PYTHONPATH=src python3 main.py
```

如果 `8787` 端口被占用：

```bash
CUSTOMER_ASSISTANT_PORT=8791 PYTHONPATH=src python3 main.py
```

打开：

```text
http://127.0.0.1:8787
```

## 配置识图模型

复制 `.env.example` 或直接导出环境变量：

```bash
export LLM_API_KEY="你的 Key"
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL="gpt-4o-mini"
PYTHONPATH=src python3 main.py
```

也可以编辑 `config.yaml`，但不要把真实 Key 提交到 GitHub。

## API

```bash
# 健康检查
curl http://127.0.0.1:8787/api/health

# 知识库检索
curl -X POST http://127.0.0.1:8787/api/kb/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"富轩青龙压线结构 799","limit":3}'

# 图片识别分析
curl -X POST http://127.0.0.1:8787/api/vision/analyze \
  -F 'file=@/absolute/path/to/window.webp' \
  -F 'question=帮我看这个截面结构怎么样'
```

## 测试

```bash
cd /Users/cc/Documents/New\ project\ 2/win
python3 -m pytest
```

当前基础测试覆盖：配置读取、知识库恢复和备份、知识投喂、图片分析接口、客服分析、训练队列、对话记录、GitHub 归档、桌面包检查。

## 目录

```text
config.yaml
data/
  knowledge/
  knowledge_base.json
  learning_queue.json
src/customer_context_assistant/
static/
tasks/
tests/
logs/
output/
```

## 失败排查

- 页面不是本工具：说明 `8787` 被其他服务占用，用 `CUSTOMER_ASSISTANT_PORT=8791` 启动。
- 上传识图只有规则分析：说明未配置 `LLM_API_KEY`。
- OCR 没识别文字：图片太干净或系统缺少 OCR 环境，Vision API 仍可基于图像本身分析。
- 知识库损坏：从 `data/kb_backups` 自动恢复，或回退到 `tasks/knowledge_base.seed.json`。
