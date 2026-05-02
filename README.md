# 门窗售前顾问助手 (Gemini 智能增强版)

本地运行的门窗售前客服辅助工具。现在的版本已由 **Gemini 1.5 Flash** 深度驱动，支持结合本地知识库的智能分析与评论区自动化采集。

## 核心功能 (2026-05-02 更新)

- **Gemini RAG 分析**：系统不再仅仅进行关键词匹配，而是利用 Gemini 结合您的“实战知识库”和对话上下文，生成既专业又具有引导性的回复建议。
- **评论区对话采集**：专门适配小红书等平台的评论区截图。能够自动识别评论层级，将各路大神的经验或客户的疑问一键提取，自动转化为您的专属知识库。
- **知识库自动学习**：遇到新问题时，Gemini 会自动为您总结知识点草稿，包括标题、专业内容、标签和话术模板，您只需在训练台中点击“通过”即可完成入库。
- **原生悬浮窗口**：通过 `floating_region_assistant.py` 启动，支持全局截图识别和剪贴板自动分析。

## 配置 LLM 引擎

要激活 AI 增强功能，请编辑根目录下的 `config.yaml`：

```yaml
llm:
  api_key: "您的 Gemini API Key"
  base_url: "https://generativelanguage.googleapis.com/v1beta/openai/"
  model: "gemini-1.5-flash"
```

*注：如果没有 API Key，工具仍将回退到本地话术模板模式运行。*

## 启动方式

```bash
# 方式 A：原生悬浮助手（推荐，最新功能）
export PYTHONPATH=src
python3 floating_region_assistant.py

# 方式 B：网页版管理后台
export PYTHONPATH=src
python3 main.py
```

## 开发接力 (Codex)

详细的工程进度和后续待办事项请参考：`CODEX_TASK.md`。

---

## 目录结构

```text
customer_context_assistant/
  config.yaml
  main.py
  requirements.txt
  src/customer_context_assistant/
  static/
  tasks/
  tests/
  data/
```
