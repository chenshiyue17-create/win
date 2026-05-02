from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Callable
from math import cos, pi, sin

from PIL import Image

from customer_context_assistant.assistant_engine import AssistantEngine
from customer_context_assistant.config import Settings, load_settings
from customer_context_assistant.conversation_store import ConversationStore, infer_session_id_from_text, normalize_session_id
from customer_context_assistant.interaction_store import InteractionStore
from customer_context_assistant.knowledge_base import KnowledgeBase
from customer_context_assistant.learning_engine import LearningQueue
from customer_context_assistant.models import AnalyzeRequest, AnalyzeResponse
from customer_context_assistant.recognizer import latest_customer_messages, recognize_image_payload, recognize_text_payload
from desktop_launcher import start_server


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def normalized(self) -> "Region":
        return Region(
            left=min(self.left, self.right),
            top=min(self.top, self.bottom),
            right=max(self.left, self.right),
            bottom=max(self.top, self.bottom),
        )

    def is_valid(self, min_size: int = 12) -> bool:
        normalized = self.normalized()
        return normalized.width >= min_size and normalized.height >= min_size


class LocalAssistant:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.kb = KnowledgeBase(
            self.settings.knowledge_base.source_file,
            seed_file=self.settings.knowledge_base.seed_file,
            backup_dir=self.settings.knowledge_base.backup_dir,
            min_entries=self.settings.knowledge_base.min_entries,
        )
        self.engine = AssistantEngine(self.kb, self.settings.knowledge_base, self.settings.assistant, llm_config=self.settings.llm)
        self.learning_queue = LearningQueue(self.settings.root / "data" / "learning_queue.json", llm_config=self.settings.llm)
        self.interaction_store = InteractionStore(self.settings.root / "data" / "interactions")
        self.conversation_store = ConversationStore(self.settings.root / "data" / "conversations.json")

    def resolve_session_id(self, text: str, requested_session_id: str) -> str:
        return infer_session_id_from_text(text, requested_session_id)

    def analyze_text(self, text: str, session_id: str = "default") -> tuple[AnalyzeResponse, str]:
        recognized = recognize_text_payload(text)
        target_messages = latest_customer_messages(recognized.messages)
        safe_session_id = self.resolve_session_id(text, session_id)
        if not target_messages:
            return AnalyzeResponse(hints=[]), safe_session_id
        analysis_messages = self.conversation_store.recent_context(safe_session_id, limit=8) + target_messages
        candidates = self.learning_queue.ingest_messages(target_messages, self.kb, source="floating_text")
        response = self.engine.analyze(AnalyzeRequest(messages=analysis_messages, include_safety=True, session_id=safe_session_id))
        self.conversation_store.append_messages(safe_session_id, target_messages)
        self.interaction_store.append(
            source="floating_text",
            input_type="clipboard",
            raw_text=text,
            messages=target_messages,
            output=response,
            learning_candidate_ids=[candidate.id for candidate in candidates],
            metadata={"session_id": safe_session_id},
        )
        return response, safe_session_id

    def analyze_image(self, image_path: Path, session_id: str = "default") -> tuple[str, AnalyzeResponse, list[str], str]:
        data = image_path.read_bytes()
        recognized = recognize_image_payload(data, self.settings.recognition.ocr_language)
        target_messages = latest_customer_messages(recognized.messages)
        safe_session_id = self.resolve_session_id(recognized.text, session_id)
        if not target_messages:
            return recognized.text, AnalyzeResponse(hints=[]), recognized.warnings, safe_session_id
        analysis_messages = self.conversation_store.recent_context(safe_session_id, limit=8) + target_messages
        candidates = self.learning_queue.ingest_messages(target_messages, self.kb, source="floating_region")
        response = self.engine.analyze(AnalyzeRequest(
            messages=analysis_messages, 
            include_safety=True, 
            session_id=safe_session_id,
            image_bytes=data
        ))
        self.conversation_store.append_messages(safe_session_id, target_messages)
        self.interaction_store.append(
            source="floating_region",
            input_type="screenshot",
            ocr_text=recognized.text,
            screenshot_path=image_path,
            messages=target_messages,
            output=response,
            learning_candidate_ids=[candidate.id for candidate in candidates],
            metadata={"session_id": safe_session_id},
        )
        return recognized.text, response, recognized.warnings, safe_session_id

    def radar_for_session(self, session_id: str) -> dict[str, int]:
        return self.conversation_store.get_or_create(session_id).radar


def region_to_dict(region: Region) -> dict[str, int]:
    normalized = region.normalized()
    return {"left": normalized.left, "top": normalized.top, "right": normalized.right, "bottom": normalized.bottom}


def region_from_dict(payload: dict[str, int]) -> Region:
    return Region(int(payload["left"]), int(payload["top"]), int(payload["right"]), int(payload["bottom"])).normalized()


def load_floating_state(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_floating_state(path: Path, *, session_id: str, region: Region | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"session_id": normalize_session_id(session_id)}
    if region is not None:
        payload["region"] = region_to_dict(region)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def screen_capture_authorized() -> bool:
    if sys.platform != "darwin":
        return True
    try:
        import Quartz

        preflight = getattr(Quartz, "CGPreflightScreenCaptureAccess", None)
        if preflight is None:
            return True
        return bool(preflight())
    except Exception:
        return True


def ensure_screen_capture_permission() -> None:
    if screen_capture_authorized():
        return
    raise PermissionError(
        "屏幕录制权限未允许，已阻止本次截图请求，因此不会反复弹系统授权窗口。\n"
        "请点“打开权限设置”，在“屏幕录制”里允许“门窗工具”，然后完全退出并重新打开 App。"
    )


def capture_screen(output_path: Path) -> Path:
    ensure_screen_capture_permission()
    try:
        subprocess.run(["screencapture", "-x", str(output_path)], check=True, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise PermissionError("截图失败。请在 macOS 系统设置里允许“门窗工具”或 Python 使用屏幕录制权限，然后重新打开 App。") from exc
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise PermissionError("没有拿到屏幕截图。请确认已允许屏幕录制权限。")
    return output_path


def crop_region(source_path: Path, region: Region, output_path: Path) -> Path:
    return crop_region_from_space(source_path, region, output_path, None)


def crop_region_from_space(
    source_path: Path,
    region: Region,
    output_path: Path,
    coordinate_space_size: tuple[int, int] | None = None,
) -> Path:
    normalized = region.normalized()
    if not normalized.is_valid():
        raise ValueError("选择区域太小，请重新框选聊天内容。")
    with Image.open(source_path) as image:
        crop_box = region_to_image_box(normalized, image.size, coordinate_space_size)
        cropped = image.crop(crop_box)
        cropped.save(output_path)
    return output_path


def region_to_image_box(
    region: Region,
    image_size: tuple[int, int],
    coordinate_space_size: tuple[int, int] | None,
) -> tuple[int, int, int, int]:
    normalized = region.normalized()
    if coordinate_space_size is None:
        scale_x = 1.0
        scale_y = 1.0
    else:
        space_width, space_height = coordinate_space_size
        if space_width <= 0 or space_height <= 0:
            raise ValueError("选区坐标空间无效，请重新框选。")
        scale_x = image_size[0] / space_width
        scale_y = image_size[1] / space_height
    left = max(0, min(image_size[0], round(normalized.left * scale_x)))
    top = max(0, min(image_size[1], round(normalized.top * scale_y)))
    right = max(0, min(image_size[0], round(normalized.right * scale_x)))
    bottom = max(0, min(image_size[1], round(normalized.bottom * scale_y)))
    if right - left < 1 or bottom - top < 1:
        raise ValueError("选区换算后为空，请重新框选聊天内容。")
    return left, top, right, bottom


def capture_region(region: Region, output_path: Path) -> Path:
    ensure_screen_capture_permission()
    normalized = region.normalized()
    if not normalized.is_valid():
        raise ValueError("监听区域太小，请重新框选聊天内容。")
    geometry = f"{normalized.left},{normalized.top},{normalized.width},{normalized.height}"
    try:
        subprocess.run(["screencapture", "-x", "-R", geometry, str(output_path)], check=True, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as exc:
        raise PermissionError("监听截图失败。请允许屏幕录制权限后再点“开始监听”或重新打开 App。") from exc
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise PermissionError("监听区域截图为空。请确认屏幕录制权限已允许。")
    return output_path


def normalize_ocr_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def image_fingerprint(image_path: Path, size: int = 16) -> int:
    with Image.open(image_path) as image:
        gray = image.convert("L").resize((size, size))
        pixels = list(gray.getdata())
    average = sum(pixels) / len(pixels)
    value = 0
    for index, pixel in enumerate(pixels):
        if pixel >= average:
            value |= 1 << index
    return value


def fingerprint_distance(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def format_hints(response: AnalyzeResponse, warnings: list[str] | None = None) -> str:
    lines: list[str] = []
    for warning in warnings or []:
        lines.append(f"注意：{warning}")
    if not response.hints:
        lines.append("没有识别到可分析的客户消息。可复制聊天文字后点“粘贴分析”。")
        return "\n".join(lines)
    for index, hint in enumerate(response.hints, start=1):
        lines.append(f"{index}. {hint.intent} · {int(hint.confidence * 100)}%")
        lines.append("互动分析（内部看，不复制给客户）：")
        lines.append(hint.interaction_analysis or hint.summary)
        if hint.warnings:
            lines.append("风险：" + "；".join(hint.warnings))
        lines.append("可复制回复：")
        lines.append(hint.suggested_reply)
        if hint.matched_entries:
            titles = " / ".join(match.entry.title for match in hint.matched_entries[:3])
            lines.append("命中：" + titles)
        lines.append("")
    return "\n".join(lines).strip()


def first_suggested_reply(response: AnalyzeResponse) -> str:
    for hint in response.hints:
        if hint.suggested_reply.strip():
            return hint.suggested_reply.strip()
    return ""


class RegionSelector:
    def __init__(self, on_selected: Callable[[Region], None], on_cancel: Callable[[], None]) -> None:
        import tkinter as tk

        self.tk = tk
        self.on_selected = on_selected
        self.on_cancel = on_cancel
        self.finished = False
        self.start_x = 0
        self.start_y = 0
        self.rect_id: int | None = None
        self.shade_ids: list[int] = []
        self.root = tk.Toplevel()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.32)
        self.root.configure(cursor="crosshair")

        self.root.update_idletasks()
        self.screen_size = (self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        self.canvas = tk.Canvas(self.root, width=self.screen_size[0], height=self.screen_size[1], bg="#111827", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_rectangle(18, 18, 560, 74, fill="#111827", outline="#f97316", width=3)
        self.canvas.create_text(
            24,
            24,
            text="直接在当前桌面上拖动选择聊天区域，松开后会锁定红色监听框",
            fill="#ffffff",
            anchor="nw",
            font=("Helvetica", 16, "bold"),
        )
        self.canvas.create_text(
            24,
            50,
            text="Esc 取消",
            fill="#ffd7ba",
            anchor="nw",
            font=("Helvetica", 12, "bold"),
        )
        self.canvas.bind("<ButtonPress-1>", self._start)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._finish)
        self.root.bind("<Escape>", lambda _event: self.cancel())
        self.root.protocol("WM_DELETE_WINDOW", self.cancel)

    def _point(self, event) -> tuple[int, int]:
        x = max(0, min(self.screen_size[0], int(event.x)))
        y = max(0, min(self.screen_size[1], int(event.y)))
        return x, y

    def _start(self, event) -> None:
        self.start_x, self.start_y = self._point(event)
        self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline="#f97316", width=5)

    def _drag(self, event) -> None:
        if self.rect_id is not None:
            x, y = self._point(event)
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, x, y)

    def _finish(self, event) -> None:
        self.finished = True
        end_x, end_y = self._point(event)
        region = Region(self.start_x, self.start_y, end_x, end_y).normalized()
        self.root.destroy()
        self.on_selected(region)

    def cancel(self) -> None:
        if self.finished:
            return
        self.finished = True
        try:
            self.root.destroy()
        finally:
            self.on_cancel()


class RegionOverlay:
    def __init__(self, tk_module, region: Region, accent: str = "#c94f3d") -> None:
        self.tk = tk_module
        self.region = region.normalized()
        self.accent = accent
        self.windows: list[object] = []
        self.thickness = 8
        self._create_frame_windows()
        self._raise_all()

    def _window(self, width: int, height: int, x: int, y: int, bg: str):
        window = self.tk.Toplevel()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.configure(bg=bg)
        window.geometry(f"{max(1, width)}x{max(1, height)}+{x}+{y}")
        self.windows.append(window)
        return window

    def _create_frame_windows(self) -> None:
        r = self.region
        t = self.thickness
        self._window(r.width + t * 2, t, r.left - t, r.top - t, self.accent)
        self._window(r.width + t * 2, t, r.left - t, r.bottom, self.accent)
        self._window(t, r.height, r.left - t, r.top, self.accent)
        self._window(t, r.height, r.right, r.top, self.accent)

        label_width = min(max(260, r.width), 420)
        label = self._window(label_width, 34, r.left, max(0, r.top - 42), self.accent)
        canvas = self.tk.Canvas(label, width=label_width, height=34, bg=self.accent, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_text(
            12,
            17,
            text=f"已锁定监听区 {r.width}×{r.height}",
            fill="#ffffff",
            anchor="w",
            font=("Helvetica", 13, "bold"),
        )

    def _raise_all(self) -> None:
        for window in self.windows:
            try:
                window.lift()
                window.attributes("-topmost", True)
            except Exception:
                pass

    def destroy(self) -> None:
        for window in self.windows:
            try:
                window.destroy()
            except Exception:
                pass
        self.windows = []


class FloatingAssistantApp:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import messagebox

        self.tk = tk
        self.messagebox = messagebox
        self.assistant = LocalAssistant()
        self.state_path = self.assistant.settings.root / "data" / "floating_state.json"
        self.root = tk.Tk()
        self.root.title("门窗售前悬浮助手")
        self.root.geometry("430x720+940+60")
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#151b22")
        self.root.bind("<F6>", lambda _event: self.select_region())
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.status = tk.StringVar(value="可悬浮在微信/网页客服旁边")
        self.current_session = tk.StringVar(value="客户-1")
        self.latest_reply = ""
        self.hotkey_listener = None
        self.monitor_region: Region | None = None
        self.monitor_thread: threading.Thread | None = None
        self.monitor_stop = threading.Event()
        self.change_probe_seconds = 0.45
        self.change_stable_seconds = 0.9
        self.change_distance_threshold = 5
        self.last_seen_text = ""
        self.last_visual_fingerprint: int | None = None
        self.is_monitoring = False
        self.region_overlay: RegionOverlay | None = None
        self.permission_notice_visible = False
        self._load_saved_state()
        self._build_ui()
        self._start_global_hotkey()
        if self.monitor_region is not None:
            self.root.after(900, lambda: self.show_region_overlay(self.monitor_region) if self.monitor_region else None)

    def _build_ui(self) -> None:
        tk = self.tk
        from tkinter import ttk

        self.palette = {
            "bg": "#f6f5f1",
            "panel": "#ffffff",
            "ink": "#151b22",
            "muted": "#667085",
            "line": "#d8d5cc",
            "accent": "#c94f3d",
            "accent_hover": "#f4d7cf",
            "soft": "#ebe7dc",
            "green": "#2f6f63",
        }
        self.root.configure(bg=self.palette["bg"])
        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        self.style.configure(
            "Tool.TButton",
            background=self.palette["soft"],
            foreground=self.palette["ink"],
            bordercolor=self.palette["line"],
            focusthickness=1,
            focuscolor=self.palette["accent"],
            font=("Helvetica", 12, "bold"),
            padding=(10, 8),
        )
        self.style.map(
            "Tool.TButton",
            background=[("active", self.palette["accent_hover"]), ("pressed", self.palette["accent_hover"])],
            foreground=[("disabled", "#98a2b3"), ("active", self.palette["ink"])],
        )
        self.style.configure(
            "Primary.Tool.TButton",
            background=self.palette["accent"],
            foreground="#ffffff",
            bordercolor=self.palette["accent"],
            font=("Helvetica", 12, "bold"),
            padding=(10, 8),
        )
        self.style.map(
            "Primary.Tool.TButton",
            background=[("active", "#a94131"), ("pressed", "#8f3528")],
            foreground=[("active", "#ffffff"), ("pressed", "#ffffff")],
        )

        outer = tk.Frame(self.root, bg=self.palette["bg"])
        outer.pack(fill="both", expand=True, padx=12, pady=12)

        header = tk.Frame(outer, bg=self.palette["panel"], highlightbackground=self.palette["line"], highlightthickness=1)
        header.pack(fill="x", pady=(0, 10))
        tk.Label(header, text="门窗工具", bg=self.palette["panel"], fg=self.palette["ink"], font=("Helvetica", 18, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(header, text="售前识别 · 知识提示 · 互动蒸馏", bg=self.palette["panel"], fg=self.palette["muted"], font=("Helvetica", 11)).pack(anchor="w", padx=12)
        tk.Label(header, textvariable=self.status, bg=self.palette["panel"], fg=self.palette["green"], font=("Helvetica", 11, "bold")).pack(anchor="w", padx=12, pady=(4, 10))

        session_bar = tk.Frame(outer, bg=self.palette["bg"])
        session_bar.pack(fill="x", pady=(0, 8))
        tk.Label(session_bar, text="客户会话", bg=self.palette["bg"], fg=self.palette["muted"], font=("Helvetica", 11, "bold")).pack(side="left")
        self.session_entry = tk.Entry(session_bar, textvariable=self.current_session, bg="#fffdf8", fg=self.palette["ink"], relief="solid", bd=1, font=("Helvetica", 12))
        self.session_entry.pack(side="left", fill="x", expand=True, padx=8, ipady=5)
        self._button(session_bar, "新会话", self.new_session).pack(side="left")

        actions = tk.Frame(outer, bg=self.palette["bg"])
        actions.pack(fill="x", pady=(0, 8))
        self._button(actions, "选择监听区", self.select_region, primary=True).pack(side="left", fill="x", expand=True, padx=(0, 5))
        self._button(actions, "粘贴分析", self.analyze_clipboard).pack(side="left", fill="x", expand=True, padx=5)
        self._button(actions, "训练台", self.open_trainer).pack(side="left", fill="x", expand=True, padx=(5, 0))

        quick_actions = tk.Frame(outer, bg=self.palette["bg"])
        quick_actions.pack(fill="x", pady=(0, 10))
        self.monitor_button = self._button(quick_actions, "开始监听", self.toggle_monitoring)
        self.monitor_button.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self._button(quick_actions, "复制建议", self.copy_latest_reply).pack(side="left", fill="x", expand=True, padx=5)
        self._button(quick_actions, "重新置顶", self.raise_window).pack(side="left", fill="x", expand=True, padx=5)

        utility_actions = tk.Frame(outer, bg=self.palette["bg"])
        utility_actions.pack(fill="x", pady=(0, 10))
        self._button(utility_actions, "打开权限设置", self.open_privacy_settings).pack(side="left", fill="x", expand=True, padx=(0, 5))
        self._button(utility_actions, "清空失效锁", self.clear_stale_lock).pack(side="left", fill="x", expand=True, padx=5)

        radar_frame = tk.Frame(outer, bg=self.palette["panel"], highlightbackground=self.palette["line"], highlightthickness=1)
        radar_frame.pack(fill="x", pady=(0, 10))
        tk.Label(radar_frame, text="客户雷达图", bg=self.palette["panel"], fg=self.palette["muted"], font=("Helvetica", 11, "bold")).pack(anchor="w", padx=12, pady=(8, 0))
        self.radar_canvas = tk.Canvas(radar_frame, height=185, bg=self.palette["panel"], highlightthickness=0)
        self.radar_canvas.pack(fill="x", padx=8, pady=(2, 8))
        self.draw_radar()

        output_frame = tk.Frame(outer, bg=self.palette["panel"], highlightbackground=self.palette["line"], highlightthickness=1)
        output_frame.pack(fill="both", expand=True)
        tk.Label(output_frame, text="分析结果", bg=self.palette["panel"], fg=self.palette["muted"], font=("Helvetica", 11, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        self.text = tk.Text(output_frame, wrap="word", bg="#fffdf8", fg=self.palette["ink"], insertbackground=self.palette["ink"], relief="flat", padx=12, pady=10, font=("Helvetica", 13), spacing1=2, spacing3=6)
        self.text.pack(fill="both", expand=True, padx=8, pady=(6, 8))
        self._set_output("把这个小窗放到微信、网页客服或社交工具旁边。\n\n按 F6 或点“选择监听区”框选客户聊天区域。工具会记住上次选区；画面内容变化并稳定后，会自动识别昵称/客户标识、切换会话、OCR 分析并更新建议。")

    def _button(self, parent, text: str, command, primary: bool = False):
        from tkinter import ttk

        return ttk.Button(parent, text=text, command=command, style="Primary.Tool.TButton" if primary else "Tool.TButton")

    def _set_output(self, value: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)

    def _start_global_hotkey(self) -> None:
        if os.environ.get("MENCHUANG_ENABLE_GLOBAL_HOTKEY") != "1":
            self.status.set("前台 F6 可框选；全局热键默认关闭，避免反复弹辅助功能权限")
            return
        try:
            from pynput import keyboard

            def on_press(key) -> None:
                if key == keyboard.Key.f6:
                    self.root.after(0, self.select_region)

            self.hotkey_listener = keyboard.Listener(on_press=on_press)
            threading.Thread(target=self.hotkey_listener.start, daemon=True).start()
            self.status.set("全局 F6 可框选；也可点按钮")
        except Exception:
            self.status.set("前台 F6 可框选；全局热键未启用")

    def select_region(self) -> None:
        self.permission_notice_visible = False
        self.stop_monitoring(update_status=False, keep_overlay=True)
        self.hide_region_overlay()
        self.status.set("正在打开选区层，直接在当前桌面上框选")
        self.root.withdraw()
        self.root.after(250, self._open_selector)

    def _open_selector(self) -> None:
        try:
            RegionSelector(lambda region: self._handle_region(region), self._cancel_region_selection)
        except Exception as exc:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.status.set("打开选区失败")
            self._show_permission_help(str(exc))

    def _cancel_region_selection(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        if self.monitor_region is not None:
            self.show_region_overlay(self.monitor_region)
            self.status.set("已取消框选，保留上次监听区")
        else:
            self.status.set("已取消框选")

    def _handle_region(self, region: Region) -> None:
        self.root.deiconify()
        self.root.lift()
        normalized = region.normalized()
        if not normalized.is_valid():
            self.status.set("选择区域太小")
            self._set_output("选择区域太小，请重新框选聊天内容。")
            return
        self.monitor_region = normalized
        self.persist_state()
        self.show_region_overlay(normalized)
        self.status.set(f"已锁定监听区 {normalized.width}×{normalized.height}，正在识别")
        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="door-window-region-"))
            crop_path = capture_region(normalized, tmp_dir / "selected-region.png")
            text, response, warnings, session_id = self.assistant.analyze_image(crop_path, self.active_session_id())
            self.apply_detected_session(session_id)
            self.last_seen_text = normalize_ocr_text(text)
            self.last_visual_fingerprint = image_fingerprint(crop_path)
            self._save_latest_region(crop_path)
            selected = self.monitor_region or normalized
            self._display_region_result(text, response, warnings, f"已锁定监听区 {selected.width}×{selected.height}，等待内容更新")
            self.start_monitoring()
        except Exception as exc:
            self.status.set("监听区已锁定，截图权限或识别失败")
            self._show_permission_help(str(exc))

    def _display_region_result(self, text: str, response: AnalyzeResponse, warnings: list[str], status: str) -> None:
        self.latest_reply = first_suggested_reply(response)
        self.status.set(status)
        self.draw_radar()
        header = f"识别文本：\n{text or '未识别到文字'}\n\n提示：\n"
        self._set_output(header + format_hints(response, warnings))

    def start_monitoring(self) -> None:
        self.permission_notice_visible = False
        if self.monitor_region is None:
            self.select_region()
            return
        if self.is_monitoring:
            return
        self.monitor_stop.clear()
        self.is_monitoring = True
        self.monitor_button.configure(text="暂停监听")
        self.show_region_overlay(self.monitor_region)
        self.monitor_thread = threading.Thread(target=self._monitor_region_loop, args=(self.monitor_region, self.active_session_id()), daemon=True)
        self.monitor_thread.start()

    def stop_monitoring(self, update_status: bool = True, keep_overlay: bool = False) -> None:
        self.monitor_stop.set()
        self.is_monitoring = False
        if hasattr(self, "monitor_button"):
            self.monitor_button.configure(text="开始监听")
        if not keep_overlay:
            self.hide_region_overlay()
        if update_status:
            self.status.set("监听已暂停")

    def toggle_monitoring(self) -> None:
        if self.is_monitoring:
            self.stop_monitoring()
            return
        self.start_monitoring()

    def _monitor_region_loop(self, region: Region, session_id: str) -> None:
        pending_fingerprint: int | None = None
        pending_path: Path | None = None
        pending_since = 0.0
        while not self.monitor_stop.wait(self.change_probe_seconds):
            try:
                tmp_dir = Path(tempfile.mkdtemp(prefix="door-window-live-region-"))
                capture_path = capture_region(region, tmp_dir / "live-region.png")
                current_fingerprint = image_fingerprint(capture_path)
                if self.last_visual_fingerprint is not None and fingerprint_distance(self.last_visual_fingerprint, current_fingerprint) < self.change_distance_threshold:
                    pending_fingerprint = None
                    pending_path = None
                    pending_since = 0.0
                    self.root.after(0, lambda: self.status.set("监听中：等待内容更新"))
                    continue
                if pending_fingerprint != current_fingerprint:
                    pending_fingerprint = current_fingerprint
                    pending_path = capture_path
                    pending_since = monotonic()
                    self.root.after(0, lambda: self.status.set("检测到画面变化，等待稳定"))
                    continue
                if monotonic() - pending_since < self.change_stable_seconds:
                    continue
                stable_path = pending_path or capture_path
                self._save_latest_region(stable_path)
                text, response, warnings, detected_session_id = self.assistant.analyze_image(stable_path, session_id)
                self.root.after(0, lambda detected_session_id=detected_session_id: self.apply_detected_session(detected_session_id))
                normalized_text = normalize_ocr_text(text)
                if not normalized_text:
                    self.last_visual_fingerprint = current_fingerprint
                    self.root.after(0, lambda: self.status.set("内容已变化，但未识别到文字"))
                    continue
                if normalized_text == self.last_seen_text:
                    self.last_visual_fingerprint = current_fingerprint
                    self.root.after(0, lambda: self.status.set("画面变化但文字未变，未重新分析"))
                    continue
                self.last_seen_text = normalized_text
                self.last_visual_fingerprint = current_fingerprint
                pending_fingerprint = None
                pending_path = None
                pending_since = 0.0
                self.root.after(0, lambda text=text, response=response, warnings=warnings: self._display_region_result(text, response, warnings, "检测到新内容，已自动分析"))
            except Exception as exc:
                self.root.after(0, lambda exc=exc: self._handle_monitor_error(exc))
                break

    def _save_latest_region(self, image_path: Path) -> None:
        output_dir = self.assistant.settings.root / "output" / "region_captures"
        output_dir.mkdir(parents=True, exist_ok=True)
        saved_path = output_dir / "latest-region.png"
        saved_path.write_bytes(image_path.read_bytes())

    def show_region_overlay(self, region: Region) -> None:
        self.hide_region_overlay()
        self.region_overlay = RegionOverlay(self.tk, region, self.palette["accent"])

    def hide_region_overlay(self) -> None:
        if self.region_overlay is not None:
            self.region_overlay.destroy()
            self.region_overlay = None

    def _handle_monitor_error(self, exc: Exception) -> None:
        self.stop_monitoring(update_status=False, keep_overlay=True)
        if self.monitor_region is not None and self.region_overlay is None:
            self.show_region_overlay(self.monitor_region)
        self.status.set("监听失败，已暂停；选区边框保留")
        self._show_permission_help(str(exc))

    def analyze_clipboard(self) -> None:
        try:
            text = self.root.clipboard_get()
            response, session_id = self.assistant.analyze_text(text, self.active_session_id())
            self.apply_detected_session(session_id)
            self.latest_reply = first_suggested_reply(response)
            self.status.set(f"已分析剪贴板 · {self.active_session_id()}")
            self.draw_radar()
            self._set_output("剪贴板文本：\n" + text + "\n\n提示：\n" + format_hints(response))
        except Exception as exc:
            self.status.set("剪贴板分析失败")
            self._set_output(str(exc))

    def copy_latest_reply(self) -> None:
        if not self.latest_reply:
            self.status.set("还没有可复制的建议")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.latest_reply)
        self.root.update()
        self.status.set("已复制第一条建议回复")

    def raise_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.status.set("已重新置顶")

    def open_trainer(self) -> None:
        try:
            start_server("127.0.0.1", 8788)
        except Exception:
            pass
        subprocess.run(["open", "http://127.0.0.1:8788/kb-trainer"], check=False)

    def open_privacy_settings(self) -> None:
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"], check=False)

    def clear_stale_lock(self) -> None:
        lock_dir = Path("/tmp/menchuang-tool.lock")
        pid_file = lock_dir / "pid"
        try:
            pid = int(pid_file.read_text().strip()) if pid_file.exists() else 0
        except Exception:
            pid = 0
        if pid:
            try:
                os.kill(pid, 0)
                self.status.set("当前工具仍在运行，不清理锁")
                return
            except OSError:
                pass
        try:
            if pid_file.exists():
                pid_file.unlink()
            lock_dir.rmdir()
            self.status.set("已清理失效启动锁")
        except FileNotFoundError:
            self.status.set("没有发现失效启动锁")
        except Exception as exc:
            self.status.set("清理锁失败")
            self._set_output(str(exc))

    def _show_permission_help(self, message: str) -> None:
        if self.permission_notice_visible:
            self.status.set("权限未通过，监听已暂停")
            return
        self.permission_notice_visible = True
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self._set_output(
            "权限或截图失败，App 已保持打开。\n\n"
            + message
            + "\n\n处理步骤：\n"
            + "1. 点下面“打开权限设置”。\n"
            + "2. 在“屏幕录制”里允许“门窗工具”或 Python。\n"
            + "3. 完全退出并重新打开门窗工具 App。\n\n"
            + "工具不会再自动反复请求权限；授权后请手动点“选择监听区”或“开始监听”。\n"
            + "如果仍打不开，删除失效锁：/tmp/menchuang-tool.lock；新版启动器已经会自动清理失效锁。"
        )

    def active_session_id(self) -> str:
        return normalize_session_id(self.current_session.get())

    def apply_detected_session(self, session_id: str) -> None:
        safe_session_id = normalize_session_id(session_id)
        if safe_session_id and safe_session_id != self.active_session_id():
            self.current_session.set(safe_session_id)
            self.status.set(f"已自动识别客户：{safe_session_id}")
        self.persist_state()
        if hasattr(self, "radar_canvas"):
            self.draw_radar()

    def new_session(self) -> None:
        self.stop_monitoring(update_status=False)
        session_id = "客户-" + datetime.now().strftime("%H%M%S")
        self.current_session.set(session_id)
        self.last_seen_text = ""
        self.latest_reply = ""
        self.status.set(f"已切换新会话：{session_id}")
        self._set_output(f"已切换到新客户会话：{session_id}\n\n不同客户进度会分开保存，不会混在一起。")
        self.persist_state()
        self.draw_radar()

    def draw_radar(self) -> None:
        if not hasattr(self, "radar_canvas"):
            return
        canvas = self.radar_canvas
        canvas.delete("all")
        radar = self.assistant.radar_for_session(self.active_session_id())
        dimensions = list(radar.keys()) or ["需求清晰", "预算敏感", "成交紧迫", "信任程度", "风险顾虑", "决策成熟"]
        values = [radar.get(item, 0) for item in dimensions]
        width = max(canvas.winfo_width(), 380)
        cx, cy, radius = width / 2, 92, 54
        for step in (0.33, 0.66, 1.0):
            points: list[float] = []
            for index in range(len(dimensions)):
                angle = -pi / 2 + 2 * pi * index / len(dimensions)
                points.extend([cx + cos(angle) * radius * step, cy + sin(angle) * radius * step])
            canvas.create_polygon(points, outline=self.palette["line"], fill="", width=1)
        data_points: list[float] = []
        for index, value in enumerate(values):
            angle = -pi / 2 + 2 * pi * index / len(dimensions)
            axis_x = cx + cos(angle) * radius
            axis_y = cy + sin(angle) * radius
            canvas.create_line(cx, cy, axis_x, axis_y, fill=self.palette["line"])
            label_x = cx + cos(angle) * (radius + 30)
            label_y = cy + sin(angle) * (radius + 22)
            label = f"{dimensions[index]} {value}"
            canvas.create_text(label_x, label_y, text=label, fill=self.palette["ink"], font=("Helvetica", 10), width=76)
            data_points.extend([cx + cos(angle) * radius * value / 100, cy + sin(angle) * radius * value / 100])
        if data_points:
            canvas.create_polygon(data_points, outline=self.palette["accent"], fill="#f4d7cf", width=2)
            for point_index in range(0, len(data_points), 2):
                x, y = data_points[point_index], data_points[point_index + 1]
                canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=self.palette["accent"], outline=self.palette["accent"])
        canvas.create_text(12, 168, text=f"会话：{self.active_session_id()} · 随聊天实时更新", anchor="w", fill=self.palette["muted"], font=("Helvetica", 10))

    def _load_saved_state(self) -> None:
        state = load_floating_state(self.state_path)
        session_id = state.get("session_id")
        if isinstance(session_id, str) and session_id.strip():
            self.current_session.set(normalize_session_id(session_id))
        region = state.get("region")
        if isinstance(region, dict):
            try:
                restored = region_from_dict(region)
                if restored.is_valid():
                    self.monitor_region = restored
                    self.status.set("已恢复上次监听区，点“开始监听”后再读取屏幕")
            except Exception:
                self.monitor_region = None

    def persist_state(self) -> None:
        save_floating_state(self.state_path, session_id=self.active_session_id(), region=self.monitor_region)

    def close(self) -> None:
        self.stop_monitoring(update_status=False)
        self.hide_region_overlay()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def force_cleanup_environment(port: int = 8788) -> None:
    """彻底强制清理旧进程、端口占用和残留锁文件"""
    import subprocess
    import os
    import signal
    
    # 1. 强力清理 /tmp 锁
    for lock in ["/tmp/menchuang-tool.lock", "/tmp/customer-assistant.lock"]:
        if os.path.exists(lock):
            try:
                if os.path.isdir(lock):
                    import shutil
                    shutil.rmtree(lock, ignore_errors=True)
                else:
                    os.remove(lock)
            except: pass

    # 2. 释放 8788 端口 (杀死任何正在占用的进程)
    try:
        pids = subprocess.check_output(["lsof", "-t", f"-i:{port}"]).decode().strip().split("\n")
        for pid in pids:
            if pid and int(pid) != os.getpid():
                os.kill(int(pid), signal.SIGKILL)
    except: pass

    # 3. 杀死所有相关的 Python 助手进程
    try:
        current_pid = os.getpid()
        pids = subprocess.check_output(["pgrep", "-f", "floating_region_assistant.py"]).decode().strip().split("\n")
        for pid in pids:
            if pid and int(pid) != current_pid:
                os.kill(int(pid), signal.SIGKILL)
    except: pass


def main() -> None:
    # 启动前自清理，防止任何形式的冲突
    force_cleanup_environment()
    FloatingAssistantApp().run()


if __name__ == "__main__":
    main()
