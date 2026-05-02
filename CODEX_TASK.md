# CODEX_TASK: 门窗售前顾问助手 - 智能增强版

当前任务处于“持续增强”阶段，已完成从本地搜索到 AI 驱动（Gemini）的架构升级。后续 Codex 接力开发请以此文档为准。

## 一、已完成核心更新 (2026-05-02)

1.  **AI 引擎切换 (Gemini)**：
    *   集成 `gemini-1.5-flash` 作为主大脑。
    *   实现 **RAG (检索增强生成)**：系统先检索本地知识库，再由 Gemini 结合上下文生成回复建议。
    *   配置文件 `config.yaml` 已支持 `llm` 块（api_key, base_url, model）。

2.  **评论区对话采集**：
    *   新增 `comment_visual_analyzer.py`：利用视觉密度算法识别小红书评论区的层级结构（BBOX 分割）。
    *   增强 `recognizer.py`：支持“评论区识别模式”，对每个评论块独立 OCR，识别回复缩进并保留对话流。

3.  **自动学习机制 (Learning Loop)**：
    *   修改 `learning_engine.py`：当未命中知识库或命中率低时，Gemini 自动介入总结新知识条目草稿（标题、内容、标签、回复模板）。

4.  **架构同步**：
    *   同步了最新的 `floating_region_assistant.py` 原生悬浮窗源码。
    *   更新了 `app.py` 后端接口，全面适配 LLM 配置。

## 二、当前项目结构

```text
customer_context_assistant/
  ├── config.yaml               # 核心配置（含 Gemini API Key）
  ├── floating_region_assistant.py # 【最新版】原生悬浮窗入口
  ├── main.py                   # 网页版后端入口
  ├── src/
  │   └── customer_context_assistant/
  │       ├── assistant_engine.py # AI 核心：Gemini RAG 逻辑
  │       ├── learning_engine.py  # 自动训练：Gemini 总结逻辑
  │       ├── recognizer.py       # 识别核心：适配评论区 OCR
  │       └── comment_visual_analyzer.py # 视觉辅助：评论区结构分割
  ├── data/
  │   ├── knowledge_base.json   # 活跃知识库（已导入 15 条实战知识）
  │   └── learning_queue.json   # 待审核的学习队列
  └── tasks/
      └── knowledge_base.seed.json # 种子知识库
```

## 三、后续接力方向

1.  **UI 交互优化**：
    *   在悬浮窗中增加“评论区采集”专用按钮。
    *   优化 OCR 结果在悬浮窗中的层级展示（区分原贴和回复）。
2.  **知识库管理增强**：
    *   增加知识条目的关联推荐功能（Gemini 推荐相关链接）。
    *   支持从 Excel/Word 批量导入复杂的产品参数表。
3.  **多模态探索**：
    *   利用 Gemini Pro Vision 直接对截图进行原生的视觉理解，减少对 Tesseract 的依赖。

## 四、运行与测试

*   **启动原生助手**：`export PYTHONPATH=src && python3 floating_region_assistant.py`
*   **启动网页后台**：`export PYTHONPATH=src && python3 main.py`
*   **运行识别测试**：`export PYTHONPATH=src && python3 -m pytest tests/test_recognizer.py`

---
*所有代码修改已保存，配置已就绪。Codex 可直接读取本文件继续开发。*
