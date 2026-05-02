from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright
from customer_context_assistant.recognizer import recognize_comment_section
from customer_context_assistant.models import RecognitionResponse

LOGGER = logging.getLogger(__name__)

async def harvest_comments_from_url(url: str, language: str = "chi_sim+eng") -> RecognitionResponse:
    """通过 URL 异步采集评论并使用视觉引擎分析"""
    async with async_playwright() as p:
        # 启动浏览器 (使用常用 User-Agent 模拟真人)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 2400},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        LOGGER.info(f"正在访问 URL: {url}")
        try:
            # 访问页面并等待网络空闲
            await page.goto(url, wait_until="networkidle", timeout=60000)
            
            # 给一点额外的渲染时间（处理懒加载）
            await asyncio.sleep(3)
            
            # 自动向下滚动一点，触发更多评论加载
            await page.mouse.wheel(0, 800)
            await asyncio.sleep(2)

            # 获取页面截图
            screenshot_bytes = await page.screenshot(full_page=False)
            
            # 复用现有的评论区视觉识别逻辑
            return recognize_comment_section(screenshot_bytes, language)

        except Exception as e:
            LOGGER.error(f"URL 采集失败: {e}")
            return RecognitionResponse(
                source="url_harvest",
                text="",
                messages=[],
                warnings=[f"链接访问失败: {str(e)}。请确保链接可公开访问。"]
            )
        finally:
            await browser.close()
