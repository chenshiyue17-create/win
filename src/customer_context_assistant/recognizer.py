from __future__ import annotations

import logging
import os
import re
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

from customer_context_assistant.comment_visual_analyzer import find_comment_segments
from customer_context_assistant.models import MessageInput, RecognitionResponse


LOGGER = logging.getLogger(__name__)


def _vision_languages(language: str) -> list[str]:
    languages: list[str] = []
    if "chi" in language or "zh" in language:
        languages.append("zh-Hans")
    if "eng" in language or "en" in language:
        languages.append("en-US")
    return languages or ["zh-Hans", "en-US"]


def split_window_text(text: str) -> list[MessageInput]:
    messages: list[MessageInput] = []
    for index, raw_line in enumerate(line.strip() for line in text.splitlines() if line.strip()):
        sender = "agent" if re.match(r"^(客服|我|agent|support)[:：]", raw_line, re.I) else "customer"
        clean = re.sub(r"^(客户|用户|客服|我|agent|support)[:：]\s*", "", raw_line, flags=re.I)
        if clean:
            messages.append(MessageInput(id=f"msg-{index + 1}", sender=sender, text=clean))
    if not messages and text.strip():
        messages.append(MessageInput(id="msg-1", sender="customer", text=text.strip()))
    return messages


def latest_customer_messages(messages: list[MessageInput]) -> list[MessageInput]:
    for message in reversed(messages):
        if message.sender != "agent" and message.text.strip():
            return [MessageInput(id=message.id, sender="customer", text=message.text.strip())]
    return []


def recognize_text_payload(text: str) -> RecognitionResponse:
    return RecognitionResponse(source="text", text=text, messages=split_window_text(text))


def recognize_image_payload(data: bytes, language: str) -> RecognitionResponse:
    # 尝试自动检测是否为评论区截图
    # 如果高度/宽度比较大，或者包含明显的列表特征，可以优先尝试评论区模式
    return recognize_comment_section(data, language)


def recognize_comment_section(data: bytes, language: str) -> RecognitionResponse:
    """专门针对小红书评论区截图的识别逻辑"""
    import tempfile
    
    warnings: list[str] = []
    messages: list[MessageInput] = []
    all_text_parts = []
    
    # 验证图片
    try:
        image = Image.open(BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise ValueError("Uploaded file is not a readable image") from exc

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    
    try:
        segments = find_comment_segments(tmp_path)
        
        for index, seg in enumerate(segments):
            crop = image.crop(seg.bbox)
            crop_io = BytesIO()
            crop.save(crop_io, format="PNG")
            crop_data = crop_io.getvalue()
            
            # 对每一个评论块进行 OCR
            text = ""
            try:
                text = _recognize_with_tesseract(crop_data, language)
            except Exception:
                if sys.platform == "darwin":
                    try:
                        text = _recognize_with_macos_vision(crop_data, language)
                    except Exception:
                        pass
            
            if text.strip():
                # 尝试通过 BBOX 的左边距判断是否为二级回复
                # 小红书评论缩进通常在 10% 以上
                is_reply = seg.bbox[0] > (image.width * 0.12)
                prefix = "  [回复] " if is_reply else ""
                clean_text = text.replace("\n", " ").strip()
                messages.append(MessageInput(
                    id=f"comment-{index+1}",
                    sender="customer", 
                    text=f"{prefix}{clean_text}"
                ))
                all_text_parts.append(clean_text)
                
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    if not messages:
        # 降级到普通 OCR
        return _recognize_generic_image(data, language)

    return RecognitionResponse(
        source="comment_section",
        text="\n".join(all_text_parts),
        messages=messages,
        warnings=warnings
    )


def _recognize_generic_image(data: bytes, language: str) -> RecognitionResponse:
    warnings: list[str] = []
    text = ""
    try:
        text = _recognize_with_tesseract(data, language)
    except Exception as exc:
        LOGGER.warning("Tesseract OCR unavailable: %s", exc)

    if not text and sys.platform == "darwin":
        try:
            text = _recognize_with_macos_vision(data, language)
        except Exception as exc:
            LOGGER.warning("macOS Vision OCR unavailable: %s", exc)

    if not text:
        warnings.append("OCR 没有识别到文字，请改用复制窗口文本或上传更清晰截图。")

    return RecognitionResponse(source="image", text=text, messages=split_window_text(text), warnings=warnings)


def _recognize_with_tesseract(data: bytes, language: str) -> str:
    import pytesseract

    bundled_root = Path(getattr(sys, "_MEIPASS", ""))
    bundled_tesseract = bundled_root / "bin" / "tesseract"
    bundled_tessdata = bundled_root / "tessdata"
    if bundled_tesseract.exists():
        pytesseract.pytesseract.tesseract_cmd = str(bundled_tesseract)
    if bundled_tessdata.exists():
        os.environ.setdefault("TESSDATA_PREFIX", str(bundled_tessdata))

    image = Image.open(BytesIO(data))
    return pytesseract.image_to_string(image, lang=language).strip()


def _recognize_with_macos_vision(data: bytes, language: str) -> str:
    import Foundation
    import Quartz
    import Vision

    ns_data = Foundation.NSData.dataWithBytes_length_(data, len(data))
    image_source = Quartz.CGImageSourceCreateWithData(ns_data, None)
    if image_source is None:
        raise ValueError("macOS Vision cannot read image data")
    cg_image = Quartz.CGImageSourceCreateImageAtIndex(image_source, 0, None)
    if cg_image is None:
        raise ValueError("macOS Vision cannot create CGImage")

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLanguages_(_vision_languages(language))
    if hasattr(Vision, "VNRequestTextRecognitionLevelAccurate"):
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, {})
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(error or "macOS Vision OCR request failed")

    lines: list[str] = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if candidates:
            lines.append(str(candidates[0].string()))
    return "\n".join(lines).strip()
