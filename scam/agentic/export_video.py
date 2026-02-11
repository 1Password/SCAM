"""Video export for SCAM scenario replays.

Renders scenario replays as MP4 videos using Pillow for frame generation
and ffmpeg for encoding.  Produces shareable videos suitable for blog
posts, Slack, and presentations.
"""

from __future__ import annotations

import io
import math
import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

from scam.agentic.export_html import prepare_scenario_data

# ── Constants ─────────────────────────────────────────────────────────

WIDTH = 1280
HEIGHT = 720
FPS_DEFAULT = 30
FRAME_MS = 1000 / FPS_DEFAULT  # ~33.3ms per frame

# Colors
BG_COLOR = (249, 249, 251)
HEADER_BG = (15, 17, 23)
HEADER_TEXT = (255, 255, 255)
HEADER_META = (113, 117, 126)
TEXT_COLOR = (26, 28, 35)
TEXT_SECONDARY = (113, 117, 126)
TEXT_TERTIARY = (160, 164, 173)
USER_BUBBLE = (232, 236, 241)
ASSISTANT_BUBBLE = (255, 255, 255)
BUBBLE_BORDER = (235, 237, 240)
ACCENT = (5, 114, 236)
PASS_COLOR = (13, 150, 104)
FAIL_COLOR = (220, 53, 69)
WARN_COLOR = (200, 118, 23)
DANGER_BG = (254, 242, 243)
DANGER_BORDER = (245, 163, 170)
CODE_BG = (240, 241, 244)
CURSOR_COLOR = ACCENT
CHECKPOINT_BG = (243, 244, 246)
SCORE_PILL_BG = (237, 252, 245)

# Layout
HEADER_HEIGHT = 60
CONTENT_PADDING = 48
BUBBLE_PADDING_X = 20
BUBBLE_PADDING_Y = 16
BUBBLE_RADIUS = 12
BUBBLE_GAP = 24
MSG_MAX_WIDTH = WIDTH - 2 * CONTENT_PADDING - 20
ROLE_LABEL_HEIGHT = 28
TC_ROW_HEIGHT = 36
TC_GAP = 6
CHECKPOINT_PADDING = 16

# Font sizes
FONT_BODY = 17
FONT_BODY_BOLD = 17
FONT_CODE = 15
FONT_HEADER = 19
FONT_LABEL = 14
FONT_TC = 14
LINE_HEIGHT = 26
HEADER_LINE_HEIGHT = 30

# Animation timing (ms) — matches HTML export
TYPING_MS = 28
TOKEN_MS = 35
THINK_MS = 1000
TOOL_MS = 1200
GAP_MS = 500
USER_THINK = 1200

# Hold durations
TITLE_CARD_MS = 3000
TITLE_FADE_MS = 500
INTRO_HOLD_MS = TITLE_CARD_MS + TITLE_FADE_MS
OUTRO_HOLD_MS = 4000


# ── Font management ───────────────────────────────────────────────────

FONT_CACHE_DIR = Path.home() / ".cache" / "scam" / "fonts"

_FONT_URLS = {
    "Inter-Regular.ttf": "https://github.com/rsms/inter/raw/master/fonts/desktop/Inter-Regular.otf",
    "Inter-Bold.ttf": "https://github.com/rsms/inter/raw/master/fonts/desktop/Inter-Bold.otf",
    "JetBrainsMono-Regular.ttf": (
        "https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-Regular.ttf"
    ),
}

# macOS system font fallbacks
_SYSTEM_FONTS = {
    "regular": [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ],
    "bold": [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ],
    "mono": [
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/SFMono-Regular.otf",
        "/Library/Fonts/Courier New.ttf",
    ],
}


def _download_font(name: str) -> Path | None:
    """Download a font to the cache directory. Returns path or None."""
    url = _FONT_URLS.get(name)
    if not url:
        return None
    dest = FONT_CACHE_DIR / name
    if dest.exists():
        return dest
    try:
        FONT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, dest)  # noqa: S310
        return dest
    except Exception:
        return None


def _find_system_font(category: str) -> str | None:
    """Find first existing system font for a category."""
    for p in _SYSTEM_FONTS.get(category, []):
        if Path(p).exists():
            return p
    return None


class FontSet:
    """Manages a set of fonts for rendering."""

    def __init__(self) -> None:
        self._regular_path = self._resolve("Inter-Regular.ttf", "regular")
        self._bold_path = self._resolve("Inter-Bold.ttf", "bold")
        self._mono_path = self._resolve("JetBrainsMono-Regular.ttf", "mono")
        self._cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

    def _resolve(self, download_name: str, fallback_category: str) -> str | None:
        """Try cached download, then system fallback."""
        cached = FONT_CACHE_DIR / download_name
        if cached.exists():
            return str(cached)
        downloaded = _download_font(download_name)
        if downloaded:
            return str(downloaded)
        return _find_system_font(fallback_category)

    def _load(self, path: str | None, size: int) -> ImageFont.FreeTypeFont:
        key = (path or "__default__", size)
        if key not in self._cache:
            if path:
                try:
                    self._cache[key] = ImageFont.truetype(path, size)
                except Exception:
                    self._cache[key] = ImageFont.load_default(size)
            else:
                self._cache[key] = ImageFont.load_default(size)
        return self._cache[key]

    def regular(self, size: int = 15) -> ImageFont.FreeTypeFont:
        return self._load(self._regular_path, size)

    def bold(self, size: int = 15) -> ImageFont.FreeTypeFont:
        return self._load(self._bold_path, size)

    def mono(self, size: int = 13) -> ImageFont.FreeTypeFont:
        return self._load(self._mono_path, size)


# ── Text rendering helpers ────────────────────────────────────────────


def wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    if not text:
        return []
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip() if current else word
        w = font.getlength(test)
        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def draw_rounded_rect(
    draw: ImageDraw.ImageDraw,
    bbox: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, ...] | None = None,
    outline: tuple[int, ...] | None = None,
    width: int = 1,
) -> None:
    """Draw a rounded rectangle."""
    draw.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=width)


@dataclass
class TextSegment:
    """A segment of text with a specific font variant."""
    text: str
    variant: Literal["regular", "bold", "mono"] = "regular"


@dataclass
class RichLine:
    """A single visual line with mixed-font segments, ready to draw."""
    segments: list[TextSegment]
    line_type: Literal["normal", "header", "bullet", "numbered"] = "normal"
    indent: int = 0  # extra left indent in pixels


def _parse_inline(text: str) -> list[TextSegment]:
    """Parse inline markdown (bold, code, italic) into segments."""
    segments: list[TextSegment] = []
    # Strip links [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    pattern = re.compile(r"`([^`]+)`|\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|\*(.+?)\*")
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            segments.append(TextSegment(text[pos:m.start()]))
        if m.group(1):
            segments.append(TextSegment(m.group(1), "mono"))
        elif m.group(2):
            segments.append(TextSegment(m.group(2), "bold"))
        elif m.group(3):
            segments.append(TextSegment(m.group(3), "bold"))
        elif m.group(4):
            segments.append(TextSegment(m.group(4)))
        pos = m.end()
    if pos < len(text):
        segments.append(TextSegment(text[pos:]))
    return segments


def parse_markdown_to_rich_lines(
    text: str,
    fonts: "FontSet",
    max_width: int,
) -> list[RichLine]:
    """Parse markdown text into a list of RichLines ready for rendering.

    Handles: ## headers, **bold**, `code`, - bullet lists, 1. numbered lists,
    blank lines, and word-wrapping.
    """
    if not text:
        return []

    # Replace emoji with text equivalents before parsing
    text = _replace_emoji(text)

    raw_lines = text.split("\n")
    result: list[RichLine] = []

    for raw in raw_lines:
        stripped = raw.strip()

        # Blank line → small gap
        if not stripped:
            result.append(RichLine(segments=[], line_type="normal"))
            continue

        # Header (## or ###)
        hdr_match = re.match(r"^#{1,3}\s+(.*)", stripped)
        if hdr_match:
            segs = _parse_inline(hdr_match.group(1))
            # Force bold for headers
            for s in segs:
                if s.variant == "regular":
                    s.variant = "bold"
            # Word-wrap the header
            wrapped = _wrap_segments(segs, fonts, max_width, is_header=True)
            for wline in wrapped:
                result.append(RichLine(segments=wline, line_type="header"))
            continue

        # Bullet list (- or * or +)
        bullet_match = re.match(r"^\s*[-*+]\s+(.*)", stripped)
        if bullet_match:
            segs = [TextSegment("•  ", "regular")] + _parse_inline(bullet_match.group(1))
            indent = 12
            wrapped = _wrap_segments(segs, fonts, max_width - indent)
            for i, wline in enumerate(wrapped):
                if i > 0:
                    wline = [TextSegment("   ", "regular")] + wline
                result.append(RichLine(segments=wline, line_type="bullet", indent=indent))
            continue

        # Numbered list
        num_match = re.match(r"^\s*(\d+)[.)]\s+(.*)", stripped)
        if num_match:
            prefix = f"{num_match.group(1)}. "
            segs = [TextSegment(prefix, "bold")] + _parse_inline(num_match.group(2))
            indent = 8
            wrapped = _wrap_segments(segs, fonts, max_width - indent)
            for i, wline in enumerate(wrapped):
                if i > 0:
                    wline = [TextSegment("    ", "regular")] + wline
                result.append(RichLine(segments=wline, line_type="numbered", indent=indent))
            continue

        # Normal paragraph text
        segs = _parse_inline(stripped)
        wrapped = _wrap_segments(segs, fonts, max_width)
        for wline in wrapped:
            result.append(RichLine(segments=wline, line_type="normal"))

    return result


def _wrap_segments(
    segments: list[TextSegment],
    fonts: "FontSet",
    max_width: int,
    is_header: bool = False,
) -> list[list[TextSegment]]:
    """Word-wrap a flat list of segments into multiple visual lines."""
    if not segments:
        return [[]]

    def _font_for(variant: str) -> ImageFont.FreeTypeFont:
        if is_header:
            return fonts.bold(FONT_HEADER)
        if variant == "bold":
            return fonts.bold(FONT_BODY_BOLD)
        if variant == "mono":
            return fonts.mono(FONT_CODE)
        return fonts.regular(FONT_BODY)

    # Flatten all segments into words with their variant
    words: list[tuple[str, str]] = []  # (word, variant)
    for seg in segments:
        for i, word in enumerate(seg.text.split(" ")):
            if i > 0:
                words.append((" ", seg.variant))
            if word:
                words.append((word, seg.variant))

    lines: list[list[TextSegment]] = []
    current_line: list[TextSegment] = []
    current_width = 0.0

    for word, variant in words:
        font = _font_for(variant)
        ww = font.getlength(word)

        if current_width + ww > max_width and current_line:
            # Flush current line
            lines.append(current_line)
            current_line = []
            current_width = 0.0
            # Skip leading space on new line
            if word == " ":
                continue

        current_line.append(TextSegment(word, variant))
        current_width += ww

    if current_line:
        lines.append(current_line)

    return lines or [[]]


def _measure_rich_lines(
    lines: list[RichLine],
) -> int:
    """Calculate total pixel height of rich lines."""
    h = 0
    for rl in lines:
        if rl.line_type == "header":
            h += HEADER_LINE_HEIGHT
        elif not rl.segments:
            h += LINE_HEIGHT // 2  # blank line = half height
        else:
            h += LINE_HEIGHT
    return h


def _draw_rich_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[RichLine],
    fonts: "FontSet",
    x: int,
    y: int,
    text_color: tuple[int, ...] = TEXT_COLOR,
) -> int:
    """Draw rich lines and return total height used."""
    start_y = y
    for rl in lines:
        if not rl.segments:
            y += LINE_HEIGHT // 2
            continue

        lh = HEADER_LINE_HEIGHT if rl.line_type == "header" else LINE_HEIGHT
        cx = x + rl.indent

        for seg in rl.segments:
            if rl.line_type == "header":
                font = fonts.bold(FONT_HEADER)
            elif seg.variant == "bold":
                font = fonts.bold(FONT_BODY_BOLD)
            elif seg.variant == "mono":
                font = fonts.mono(FONT_CODE)
            else:
                font = fonts.regular(FONT_BODY)

            # Code segments get a subtle background
            if seg.variant == "mono" and rl.line_type != "header":
                tw = font.getlength(seg.text)
                draw_rounded_rect(
                    draw,
                    (cx - 2, y + 1, cx + int(tw) + 3, y + lh - 4),
                    radius=3,
                    fill=CODE_BG,
                )

            color = text_color
            if rl.line_type == "header":
                color = TEXT_COLOR  # always dark for headers

            draw.text((cx, y + 1), seg.text, fill=color, font=font)
            tw = font.getlength(seg.text)
            cx += int(tw)

        y += lh

    return y - start_y


def strip_markdown(text: str) -> str:
    """Strip markdown formatting to plain text."""
    text = re.sub(r"^#{1,3}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    return text


# Common emoji → text replacements for Pillow rendering
_EMOJI_MAP = {
    "⚠️": "[!]",
    "⚠": "[!]",
    "🚨": "[!]",
    "📬": "[>]",
    "📄": "",
    "📧": "",
    "🔒": "[lock]",
    "🔑": "[key]",
    "✅": "[ok]",
    "❌": "[x]",
    "⏰": "[time]",
    "🏥": "+",
    "💡": "*",
    "🛡️": "[shield]",
    "🛡": "[shield]",
    "⭐": "*",
    "🔗": "",
    "📎": "",
    "👋": "",
    "🎯": "",
    "📝": "",
    "📌": "",
    "🔐": "[lock]",
    "✉️": "",
    "✉": "",
    "🗓️": "",
    "🗓": "",
    "💻": "",
    "🖥️": "",
    "📋": "",
    "➡️": "->",
    "➡": "->",
    "⬆️": "^",
    "🔴": "[!]",
    "🟢": "[ok]",
    "🟡": "[?]",
}

# Regex matching common emoji ranges
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"  # misc symbols, emoticons, etc.
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero width joiner
    "\U000020E3"             # combining enclosing keycap
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002300-\U000023FF"  # misc technical
    "]+",
    flags=re.UNICODE,
)


def _replace_emoji(text: str) -> str:
    """Replace emoji with text equivalents that Pillow can render."""
    for emoji, replacement in _EMOJI_MAP.items():
        text = text.replace(emoji, replacement)
    # Strip any remaining emoji that we don't have mappings for
    text = _EMOJI_RE.sub("", text)
    return text


# ── Animation Timeline ────────────────────────────────────────────────


@dataclass
class AnimEvent:
    """A single animation event at a point in time."""
    time_ms: float
    kind: str  # "title_start", "title_fade", "title_end",
    # "show_msg", "type_char", "stream_token", "think",
    # "tc_start", "tc_resolve", "mark_danger",
    # "show_checkpoints", "show_scorecard"
    msg_idx: int = 0
    char_idx: int = 0
    token_idx: int = 0
    tc_idx: int = 0
    data: dict = field(default_factory=dict)


def build_timeline(scenario: dict) -> list[AnimEvent]:
    """Convert prepared scenario data into a list of timed animation events."""
    events: list[AnimEvent] = []

    # Title card
    events.append(AnimEvent(time_ms=0, kind="title_start"))
    events.append(AnimEvent(time_ms=float(TITLE_CARD_MS), kind="title_fade"))
    events.append(AnimEvent(time_ms=float(INTRO_HOLD_MS), kind="title_end"))

    t = float(INTRO_HOLD_MS) + GAP_MS  # small gap after title
    messages = scenario.get("messages", [])
    prev_role: str | None = None

    for i, msg in enumerate(messages):
        role = msg["role"]
        content = msg.get("content", "")

        # Inter-message gap
        if role == "user" and prev_role == "assistant":
            t += USER_THINK
        elif i > 0:
            t += GAP_MS

        # Show message (makes it visible)
        events.append(AnimEvent(time_ms=t, kind="show_msg", msg_idx=i))

        if role == "user":
            # Character typing
            chars = list(content)
            cap = min(len(chars), 300)
            for c in range(len(chars)):
                if c < cap:
                    events.append(AnimEvent(
                        time_ms=t, kind="type_char", msg_idx=i, char_idx=c + 1,
                    ))
                    delay = TYPING_MS * (0.5 + 0.5)  # avg jitter
                    ch = chars[c]
                    if ch in " \n":
                        delay *= 2
                    elif ch in ".,;:!?":
                        delay *= 3
                    t += delay
                else:
                    # Skip rest instantly
                    events.append(AnimEvent(
                        time_ms=t, kind="type_char", msg_idx=i, char_idx=len(chars),
                    ))
                    break

        elif role == "assistant":
            # Thinking dots
            events.append(AnimEvent(time_ms=t, kind="think", msg_idx=i))
            t += THINK_MS

            # Token streaming
            if content.strip():
                tokens = content.split()
                # Re-join to preserve spacing
                token_strs: list[str] = []
                for tok in content.split(" "):
                    token_strs.append(tok)

                cap = min(len(tokens), 120)
                for ti in range(len(tokens)):
                    if ti < cap:
                        events.append(AnimEvent(
                            time_ms=t, kind="stream_token",
                            msg_idx=i, token_idx=ti + 1,
                        ))
                        delay = TOKEN_MS * (0.8 + 0.2)  # avg jitter
                        word = tokens[ti].strip()
                        if word and word[-1] in ".,;:!?":
                            delay *= 2.5
                        t += delay
                    else:
                        events.append(AnimEvent(
                            time_ms=t, kind="stream_token",
                            msg_idx=i, token_idx=len(tokens),
                        ))
                        break

            # Tool calls
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                for tc_i, tc in enumerate(tool_calls):
                    events.append(AnimEvent(
                        time_ms=t, kind="tc_start",
                        msg_idx=i, tc_idx=tc_i,
                    ))
                    t += TOOL_MS

                    events.append(AnimEvent(
                        time_ms=t, kind="tc_resolve",
                        msg_idx=i, tc_idx=tc_i,
                    ))

                    if tc.get("dangerous"):
                        events.append(AnimEvent(
                            time_ms=t, kind="mark_danger",
                            msg_idx=i, tc_idx=tc_i,
                        ))

        prev_role = role

    # Show inline checkpoints (scrolling)
    t += GAP_MS * 2
    events.append(AnimEvent(time_ms=t, kind="show_checkpoints"))
    # Let checkpoints scroll into view
    t += 2000

    # Full-screen scorecard overlay
    events.append(AnimEvent(time_ms=t, kind="show_scorecard"))
    t += OUTRO_HOLD_MS

    return events


# ── Chat Renderer ─────────────────────────────────────────────────────


@dataclass
class MessageState:
    """Tracks the visible state of a single message during animation."""
    visible: bool = False
    role: str = ""
    content: str = ""
    shown_chars: int = 0  # for user typing
    shown_tokens: int = 0  # for assistant streaming
    thinking: bool = False
    is_dangerous: bool = False
    tool_calls: list[dict] = field(default_factory=list)
    tc_visible: list[bool] = field(default_factory=list)
    tc_resolved: list[bool] = field(default_factory=list)


@dataclass
class FrameState:
    """Complete state for rendering a single frame."""
    messages: list[MessageState] = field(default_factory=list)
    show_checkpoints: bool = False
    show_title_card: bool = False
    title_card_opacity: float = 1.0  # 1.0 = fully visible, 0.0 = gone
    show_scorecard_overlay: bool = False
    cursor_visible: bool = True  # toggles for blink


class ChatRenderer:
    """Renders chat frames using Pillow."""

    def __init__(
        self,
        scenario: dict,
        metadata: dict,
        fonts: FontSet,
    ) -> None:
        self.scenario = scenario
        self.metadata = metadata
        self.fonts = fonts
        self.scroll_y = 0  # viewport scroll offset

    def render_frame(self, state: FrameState) -> Image.Image:
        """Render a complete frame given the current animation state."""
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)

        # ── Title card overlay ────────────────────────────────────
        if state.show_title_card and state.title_card_opacity > 0.01:
            self._draw_title_card(draw, img, state.title_card_opacity)
            return img

        # ── Scorecard overlay (end of video) ──────────────────────
        if state.show_scorecard_overlay:
            self._draw_scorecard_overlay(draw, img)
            return img

        # Draw header
        self._draw_header(draw)

        # Calculate total content height for scrolling
        content_y = HEADER_HEIGHT + 16
        elements: list[tuple[int, int, callable]] = []  # (y_start, y_end, draw_fn)

        for ms in state.messages:
            if not ms.visible:
                continue
            h = self._measure_message(ms, state.cursor_visible)
            elements.append((content_y, content_y + h, ms))
            content_y += h + BUBBLE_GAP

        if state.show_checkpoints:
            cp_h = self._measure_checkpoints()
            elements.append((content_y, content_y + cp_h, None))  # None = checkpoints
            content_y += cp_h + 40  # extra bottom padding

        # Adjust scroll to keep latest content visible
        viewport_h = HEIGHT - HEADER_HEIGHT - 16
        total_h = content_y - (HEADER_HEIGHT + 16)
        if total_h > viewport_h:
            target_scroll = total_h - viewport_h + 20
            # Smooth scroll — faster when checkpoints are showing
            lerp = 0.25 if state.show_checkpoints else 0.15
            self.scroll_y += (target_scroll - self.scroll_y) * lerp
            if abs(self.scroll_y - target_scroll) < 2:
                self.scroll_y = target_scroll
        else:
            self.scroll_y = 0

        # Draw messages with scroll offset
        clip_top = HEADER_HEIGHT
        for y_start, y_end, elem in elements:
            draw_y = y_start - int(self.scroll_y)
            # Skip if fully above viewport
            if draw_y + (y_end - y_start) < clip_top:
                continue
            # Skip if fully below viewport
            if draw_y > HEIGHT:
                continue
            if elem is None:
                self._draw_checkpoints(draw, img, draw_y)
            else:
                self._draw_message(draw, img, elem, draw_y, state.cursor_visible)

        # Draw header again on top (covers scrolled content)
        draw.rectangle([0, 0, WIDTH, HEADER_HEIGHT], fill=HEADER_BG)
        self._draw_header(draw)

        return img

    def _draw_header(self, draw: ImageDraw.ImageDraw) -> None:
        """Draw the top header bar."""
        draw.rectangle([0, 0, WIDTH, HEADER_HEIGHT], fill=HEADER_BG)

        model = self.metadata.get("model", "unknown")
        skill_hash = self.metadata.get("skill_hash", "none")
        has_skill = skill_hash and skill_hash != "none"

        # Model name
        font_title = self.fonts.bold(18)
        draw.text((24, 12), model, fill=HEADER_TEXT, font=font_title)

        # Scenario info
        sid = self.scenario.get("scenario_id", "")
        pct = round(self.scenario.get("safety_score", 0) * 100)
        diff = self.scenario.get("difficulty", 0)
        meta_str = f"{sid}  ·  D{diff}  ·  {pct}% safety"
        font_meta = self.fonts.regular(13)
        draw.text((24, 36), meta_str, fill=HEADER_META, font=font_meta)

        # Skill tag (right side)
        tag_font = self.fonts.bold(12)
        if has_skill:
            tag_text = f"Skill · {str(skill_hash)[:12]}"
            tag_color = (163, 188, 255)
        else:
            tag_text = "Baseline"
            tag_color = HEADER_META

        tw = tag_font.getlength(tag_text)
        tx = WIDTH - 24 - int(tw) - 20
        ty = 18
        draw_rounded_rect(
            draw,
            (tx, ty, tx + int(tw) + 20, ty + 24),
            radius=5,
            fill=(30, 33, 45) if not has_skill else (25, 35, 60),
        )
        draw.text((tx + 10, ty + 4), tag_text, fill=tag_color, font=tag_font)

    def _draw_title_card(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        opacity: float,
    ) -> None:
        """Draw a full-screen title card."""
        # Background — dark
        bg = HEADER_BG
        draw.rectangle([0, 0, WIDTH, HEIGHT], fill=bg)

        model = self.metadata.get("model", "unknown")
        skill_hash = self.metadata.get("skill_hash", "none")
        has_skill = skill_hash and skill_hash != "none"
        sid = self.scenario.get("scenario_id", "")
        desc = self.scenario.get("description", "")
        category = self.scenario.get("category", "").replace("agentic_", "").replace("_", " ").title()
        difficulty = self.scenario.get("difficulty", 0)

        # Compute vertical center
        center_y = HEIGHT // 2

        # "SCAM" branding — small, above everything
        brand_font = self.fonts.bold(11)
        brand_text = "SCAM  ·  Security Comprehension and Awareness Measure"
        bw = brand_font.getlength(brand_text)
        alpha_color = self._fade_color(HEADER_META, opacity)
        draw.text(((WIDTH - int(bw)) // 2, center_y - 110), brand_text, fill=alpha_color, font=brand_font)

        # Model name — large
        model_font = self.fonts.bold(36)
        mw = model_font.getlength(model)
        draw.text(
            ((WIDTH - int(mw)) // 2, center_y - 70),
            model,
            fill=self._fade_color(HEADER_TEXT, opacity),
            font=model_font,
        )

        # Skill tag
        tag_font = self.fonts.bold(14)
        if has_skill:
            tag_text = f"Skill · {str(skill_hash)[:12]}"
            tag_color = (163, 188, 255)
            tag_bg = (25, 35, 60)
        else:
            tag_text = "Baseline  (no skill)"
            tag_color = HEADER_META
            tag_bg = (30, 33, 45)
        tw = tag_font.getlength(tag_text)
        tag_x = (WIDTH - int(tw) - 24) // 2
        tag_y = center_y - 18
        draw_rounded_rect(
            draw,
            (tag_x, tag_y, tag_x + int(tw) + 24, tag_y + 28),
            radius=6,
            fill=tag_bg,
        )
        draw.text(
            (tag_x + 12, tag_y + 5),
            tag_text,
            fill=self._fade_color(tag_color, opacity),
            font=tag_font,
        )

        # Divider line
        div_y = center_y + 22
        div_w = 200
        div_color = self._fade_color((60, 63, 75), opacity)
        draw.line(
            [(WIDTH // 2 - div_w, div_y), (WIDTH // 2 + div_w, div_y)],
            fill=div_color,
            width=1,
        )

        # Scenario description — wrapped
        desc_font = self.fonts.regular(16)
        desc_lines = wrap_text(desc, desc_font, WIDTH - 200)
        desc_color = self._fade_color((200, 203, 210), opacity)
        dy = center_y + 38
        for line in desc_lines[:3]:
            lw = desc_font.getlength(line)
            draw.text(((WIDTH - int(lw)) // 2, dy), line, fill=desc_color, font=desc_font)
            dy += 26

        # Category + Difficulty
        meta_font = self.fonts.regular(13)
        diff_str = "●" * difficulty + "○" * (5 - difficulty)
        meta_text = f"{category}   ·   Difficulty {diff_str}"
        meta_w = meta_font.getlength(meta_text)
        draw.text(
            ((WIDTH - int(meta_w)) // 2, dy + 12),
            meta_text,
            fill=self._fade_color(HEADER_META, opacity),
            font=meta_font,
        )

    def _draw_scorecard_overlay(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
    ) -> None:
        """Draw a full-screen scorecard at the end of the video."""
        # Dark background
        draw.rectangle([0, 0, WIDTH, HEIGHT], fill=HEADER_BG)

        model = self.metadata.get("model", "unknown")
        sid = self.scenario.get("scenario_id", "")
        cps = self.scenario.get("checkpoints", [])
        score = self.scenario.get("safety_score", 0)
        pct = round(score * 100)
        is_crit = self.scenario.get("critical_failure", False)

        if score >= 0.8:
            score_color = PASS_COLOR
        elif score >= 0.5:
            score_color = WARN_COLOR
        else:
            score_color = FAIL_COLOR

        # ── Card background ──
        card_w = 700
        card_pad = 32
        row_h = 36
        header_h = 80
        footer_h = 60
        card_h = header_h + len(cps) * row_h + footer_h + card_pad * 2
        card_x = (WIDTH - card_w) // 2
        card_y = (HEIGHT - card_h) // 2

        # Card bg
        draw_rounded_rect(
            draw,
            (card_x, card_y, card_x + card_w, card_y + card_h),
            radius=16,
            fill=(24, 26, 33),
            outline=(50, 53, 65),
        )

        # ── Header: model + score ──
        y = card_y + card_pad
        title_font = self.fonts.bold(20)
        draw.text((card_x + card_pad, y), model, fill=HEADER_TEXT, font=title_font)

        # Score pill — right side of header
        score_font = self.fonts.bold(22)
        score_text = f"{pct}%"
        sw = score_font.getlength(score_text)
        pill_w = int(sw) + 28
        pill_x = card_x + card_w - card_pad - pill_w
        pill_bg = (*score_color, 30) if not is_crit else (*FAIL_COLOR,)
        # Solid pill with muted color
        pill_fill = (
            score_color[0] // 5 + 15,
            score_color[1] // 5 + 15,
            score_color[2] // 5 + 15,
        )
        draw_rounded_rect(
            draw,
            (pill_x, y - 4, pill_x + pill_w, y + 30),
            radius=8,
            fill=pill_fill,
            outline=score_color,
        )
        draw.text(
            (pill_x + 14, y),
            score_text,
            fill=score_color,
            font=score_font,
        )

        # Subtitle
        sub_font = self.fonts.regular(12)
        sub_text = sid
        draw.text((card_x + card_pad, y + 32), sub_text, fill=HEADER_META, font=sub_font)

        label_text = "Safety Score"
        lw = sub_font.getlength(label_text)
        draw.text(
            (pill_x + (pill_w - int(lw)) // 2, y + 32),
            label_text,
            fill=HEADER_META,
            font=sub_font,
        )

        # ── Divider ──
        div_y = y + 56
        draw.line(
            [(card_x + card_pad, div_y), (card_x + card_w - card_pad, div_y)],
            fill=(50, 53, 65),
            width=1,
        )

        # ── Checkpoint rows ──
        cy = div_y + 12
        name_font = self.fonts.mono(13)
        desc_font = self.fonts.regular(11)
        for cp in cps:
            passed = cp.get("passed", False)
            cp_id = cp.get("id", "")
            weight = cp.get("weight", 0)

            # Status dot
            dot_color = PASS_COLOR if passed else FAIL_COLOR
            draw.ellipse(
                (card_x + card_pad, cy + 8, card_x + card_pad + 12, cy + 20),
                fill=dot_color,
            )

            # Label — pass/fail text
            status_text = "PASS" if passed else "FAIL"
            status_font = self.fonts.bold(10)
            draw.text(
                (card_x + card_pad + 18, cy + 8),
                status_text,
                fill=dot_color,
                font=status_font,
            )

            # Checkpoint name
            draw.text(
                (card_x + card_pad + 60, cy + 7),
                cp_id,
                fill=(200, 203, 210),
                font=name_font,
            )

            # Weight — right aligned
            wt = f"{weight}w"
            ww = desc_font.getlength(wt)
            draw.text(
                (card_x + card_w - card_pad - int(ww), cy + 10),
                wt,
                fill=HEADER_META,
                font=desc_font,
            )

            cy += row_h

        # ── Footer ──
        cy += 8
        draw.line(
            [(card_x + card_pad, cy), (card_x + card_w - card_pad, cy)],
            fill=(50, 53, 65),
            width=1,
        )
        cy += 14

        if is_crit:
            crit_font = self.fonts.bold(14)
            crit_text = "CRITICAL FAILURE"
            cw = crit_font.getlength(crit_text)
            draw.text(
                ((WIDTH - int(cw)) // 2, cy),
                crit_text,
                fill=FAIL_COLOR,
                font=crit_font,
            )
        else:
            result_font = self.fonts.bold(14)
            passed_count = sum(1 for cp in cps if cp.get("passed"))
            total_count = len(cps)
            result_text = f"{passed_count}/{total_count} checkpoints passed"
            rw = result_font.getlength(result_text)
            draw.text(
                ((WIDTH - int(rw)) // 2, cy),
                result_text,
                fill=score_color,
                font=result_font,
            )

    @staticmethod
    def _fade_color(
        color: tuple[int, ...],
        opacity: float,
    ) -> tuple[int, ...]:
        """Fade a color toward HEADER_BG based on opacity."""
        bg = HEADER_BG
        return tuple(
            int(bg[i] + (color[i] - bg[i]) * opacity)
            for i in range(min(len(color), 3))
        )

    def _get_visible_text(self, ms: MessageState) -> str:
        """Get the currently visible text for a message based on animation state."""
        if ms.role == "user":
            return ms.content[:ms.shown_chars]
        elif ms.thinking:
            return ""
        else:
            # Truncate at the Nth word boundary in the original string
            # to preserve newlines, indentation, and structure.
            total_tokens = len(ms.content.split())
            if ms.shown_tokens >= total_tokens:
                return ms.content
            if ms.shown_tokens <= 0:
                return ""
            count = 0
            pos = 0
            for m in re.finditer(r"\S+", ms.content):
                count += 1
                if count >= ms.shown_tokens:
                    pos = m.end()
                    break
            return ms.content[:pos]

    def _measure_message(self, ms: MessageState, cursor_vis: bool) -> int:
        """Calculate the pixel height of a message."""
        h = ROLE_LABEL_HEIGHT + BUBBLE_PADDING_Y * 2

        text = self._get_visible_text(ms)
        inner_w = MSG_MAX_WIDTH - BUBBLE_PADDING_X * 2

        if ms.thinking or not text:
            h += LINE_HEIGHT
        else:
            rich_lines = parse_markdown_to_rich_lines(text, self.fonts, inner_w)
            h += max(_measure_rich_lines(rich_lines), LINE_HEIGHT)

        # Tool calls
        visible_tcs = sum(1 for v in ms.tc_visible if v)
        if visible_tcs:
            h += 10 + visible_tcs * (TC_ROW_HEIGHT + TC_GAP)

        return h

    def _draw_message(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        ms: MessageState,
        y: int,
        cursor_vis: bool,
    ) -> None:
        """Draw a single message at the given y position."""
        x = CONTENT_PADDING

        # Role label
        label_font = self.fonts.bold(FONT_LABEL)
        label = "You" if ms.role == "user" else "Assistant"
        label_color = TEXT_COLOR
        draw.text((x, y), label, fill=label_color, font=label_font)

        if ms.is_dangerous:
            lw = label_font.getlength(label)
            tag_font = self.fonts.bold(10)
            tag_x = x + int(lw) + 10
            draw_rounded_rect(
                draw,
                (tag_x, y + 2, tag_x + 80, y + 19),
                radius=4,
                fill=FAIL_COLOR,
            )
            draw.text((tag_x + 6, y + 3), "DANGEROUS", fill=(255, 255, 255), font=tag_font)

        y += ROLE_LABEL_HEIGHT

        # Message text
        text = self._get_visible_text(ms)
        inner_w = MSG_MAX_WIDTH - BUBBLE_PADDING_X * 2

        if ms.thinking or not text:
            text_h = LINE_HEIGHT
        else:
            rich_lines = parse_markdown_to_rich_lines(text, self.fonts, inner_w)
            text_h = max(_measure_rich_lines(rich_lines), LINE_HEIGHT)

        # Bubble
        bubble_color = USER_BUBBLE if ms.role == "user" else ASSISTANT_BUBBLE
        bubble_border = DANGER_BORDER if ms.is_dangerous else BUBBLE_BORDER
        if ms.is_dangerous:
            bubble_color = DANGER_BG

        bubble_w = MSG_MAX_WIDTH
        bubble_h = text_h + BUBBLE_PADDING_Y * 2

        if ms.thinking:
            bubble_h = max(bubble_h, 50)

        draw_rounded_rect(
            draw,
            (x, y, x + bubble_w, y + bubble_h),
            radius=BUBBLE_RADIUS,
            fill=bubble_color,
            outline=bubble_border,
        )

        # Draw content
        tx = x + BUBBLE_PADDING_X
        ty = y + BUBBLE_PADDING_Y

        if ms.thinking:
            # Thinking dots — larger, animated feel
            for di in range(3):
                dot_x = tx + di * 16
                draw.ellipse(
                    (dot_x, ty + 8, dot_x + 8, ty + 16),
                    fill=TEXT_TERTIARY,
                )
        elif text:
            rich_lines = parse_markdown_to_rich_lines(text, self.fonts, inner_w)
            _draw_rich_lines(draw, rich_lines, self.fonts, tx, ty)

            # Blinking cursor
            if cursor_vis:
                is_typing = (
                    (ms.role == "user" and ms.shown_chars < len(ms.content))
                    or (ms.role == "assistant" and ms.shown_tokens < len(ms.content.split()))
                )
                if is_typing and rich_lines:
                    # Find end of last line
                    last_rl = rich_lines[-1]
                    last_lh = HEADER_LINE_HEIGHT if last_rl.line_type == "header" else LINE_HEIGHT
                    total_h = _measure_rich_lines(rich_lines)
                    cursor_y = ty + total_h - last_lh
                    # Measure last line width
                    cx = 0.0
                    for seg in last_rl.segments:
                        if last_rl.line_type == "header":
                            f = self.fonts.bold(FONT_HEADER)
                        elif seg.variant == "bold":
                            f = self.fonts.bold(FONT_BODY_BOLD)
                        elif seg.variant == "mono":
                            f = self.fonts.mono(FONT_CODE)
                        else:
                            f = self.fonts.regular(FONT_BODY)
                        cx += f.getlength(seg.text)
                    draw.rectangle(
                        (tx + int(cx) + 2, cursor_y + 3,
                         tx + int(cx) + 4, cursor_y + last_lh - 5),
                        fill=CURSOR_COLOR,
                    )

        y += bubble_h

        # Tool calls
        visible_tcs = [(idx, ms.tool_calls[idx])
                       for idx in range(len(ms.tc_visible))
                       if ms.tc_visible[idx]]
        if visible_tcs:
            y += 10
            tc_font = self.fonts.mono(FONT_TC)
            for idx, tc in visible_tcs:
                resolved = ms.tc_resolved[idx] if idx < len(ms.tc_resolved) else False
                dangerous = tc.get("dangerous", False)

                tc_bg = (254, 248, 248) if dangerous and ms.is_dangerous else (247, 248, 250)
                tc_border = DANGER_BORDER if dangerous and ms.is_dangerous else (229, 231, 235)
                draw_rounded_rect(
                    draw,
                    (x, y, x + bubble_w, y + TC_ROW_HEIGHT),
                    radius=6,
                    fill=tc_bg,
                    outline=tc_border,
                )

                # Status icon
                if resolved:
                    icon = "✓"
                    icon_color = PASS_COLOR
                else:
                    icon = "⟳"
                    icon_color = ACCENT
                draw.text((x + 12, y + 8), icon, fill=icon_color, font=tc_font)

                # Tool call name
                name = tc.get("call_str", "unknown()")
                if len(name) > 80:
                    name = name[:77] + "..."
                name_color = FAIL_COLOR if dangerous and ms.is_dangerous else TEXT_SECONDARY
                draw.text((x + 34, y + 9), name, fill=name_color, font=tc_font)

                y += TC_ROW_HEIGHT + TC_GAP

    def _measure_checkpoints(self) -> int:
        """Measure height of checkpoint scorecard."""
        cps = self.scenario.get("checkpoints", [])
        header_h = 44
        row_h = 28
        footer_h = 40
        return header_h + len(cps) * row_h + footer_h + 20

    def _draw_checkpoints(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        y: int,
    ) -> None:
        """Draw the checkpoint scorecard."""
        x = CONTENT_PADDING
        w = MSG_MAX_WIDTH
        cps = self.scenario.get("checkpoints", [])
        pct = round(self.scenario.get("safety_score", 0) * 100)
        score = self.scenario.get("safety_score", 0)

        if score >= 0.8:
            score_color = PASS_COLOR
        elif score >= 0.5:
            score_color = WARN_COLOR
        else:
            score_color = FAIL_COLOR

        # Header
        draw_rounded_rect(
            draw,
            (x, y, x + w, y + 44),
            radius=BUBBLE_RADIUS,
            fill=CHECKPOINT_BG,
        )
        hdr_font = self.fonts.bold(13)
        draw.text((x + 16, y + 12), "Checkpoints", fill=TEXT_COLOR, font=hdr_font)
        score_font = self.fonts.bold(13)
        score_text = f"{pct}% safety"
        sw = score_font.getlength(score_text)
        draw.text((x + w - int(sw) - 16, y + 12), score_text, fill=score_color, font=score_font)

        cy = y + 44

        # Rows
        row_font = self.fonts.regular(12)
        mono_font = self.fonts.mono(11)
        for cp in cps:
            passed = cp.get("passed", False)
            # Divider
            draw.line([(x, cy), (x + w, cy)], fill=BUBBLE_BORDER, width=1)

            # Dot
            dot_color = PASS_COLOR if passed else FAIL_COLOR
            draw.ellipse((x + 14, cy + 9, x + 22, cy + 17), fill=dot_color)

            # Name
            cp_id = cp.get("id", "")
            draw.text((x + 32, cy + 5), cp_id, fill=TEXT_COLOR, font=mono_font)

            # Weight
            weight = cp.get("weight", 0)
            wt = f"{weight}w"
            ww = row_font.getlength(wt)
            draw.text((x + w - int(ww) - 12, cy + 6), wt, fill=TEXT_TERTIARY, font=row_font)

            cy += 28

        # Footer — critical failure or score
        if self.scenario.get("critical_failure"):
            draw_rounded_rect(
                draw,
                (x, cy, x + w, cy + 36),
                radius=0,
                fill=DANGER_BG,
            )
            fail_font = self.fonts.bold(12)
            draw.text(
                (x + 16, cy + 9),
                f"Critical failure — safety score {pct}%",
                fill=FAIL_COLOR,
                font=fail_font,
            )


# ── Frame generation ──────────────────────────────────────────────────


def _build_frame_state(
    scenario: dict,
    events: list[AnimEvent],
    time_ms: float,
) -> FrameState:
    """Build the FrameState at a given point in time by replaying events."""
    messages = scenario.get("messages", [])

    msg_states: list[MessageState] = []
    for msg in messages:
        tcs = msg.get("tool_calls", [])
        msg_states.append(MessageState(
            role=msg["role"],
            content=msg.get("content", ""),
            tool_calls=tcs,
            tc_visible=[False] * len(tcs),
            tc_resolved=[False] * len(tcs),
        ))

    show_checkpoints = False
    show_title_card = False
    title_fading = False
    title_fade_start = 0.0
    title_ended = False
    show_scorecard = False

    # Replay events up to time_ms
    for ev in events:
        if ev.time_ms > time_ms:
            break
        idx = ev.msg_idx
        if ev.kind == "title_start":
            show_title_card = True
        elif ev.kind == "title_fade":
            title_fading = True
            title_fade_start = ev.time_ms
        elif ev.kind == "title_end":
            title_ended = True
            show_title_card = False
        elif ev.kind == "show_msg" and idx < len(msg_states):
            msg_states[idx].visible = True
        elif ev.kind == "type_char" and idx < len(msg_states):
            msg_states[idx].shown_chars = ev.char_idx
        elif ev.kind == "think" and idx < len(msg_states):
            msg_states[idx].thinking = True
        elif ev.kind == "stream_token" and idx < len(msg_states):
            msg_states[idx].thinking = False
            msg_states[idx].shown_tokens = ev.token_idx
        elif ev.kind == "tc_start" and idx < len(msg_states):
            tc_i = ev.tc_idx
            if tc_i < len(msg_states[idx].tc_visible):
                msg_states[idx].tc_visible[tc_i] = True
        elif ev.kind == "tc_resolve" and idx < len(msg_states):
            tc_i = ev.tc_idx
            if tc_i < len(msg_states[idx].tc_resolved):
                msg_states[idx].tc_resolved[tc_i] = True
        elif ev.kind == "mark_danger" and idx < len(msg_states):
            msg_states[idx].is_dangerous = True
        elif ev.kind == "show_checkpoints":
            show_checkpoints = True
        elif ev.kind == "show_scorecard":
            show_scorecard = True

    # Compute title card opacity (fade out during TITLE_FADE_MS)
    title_opacity = 1.0
    if title_fading and not title_ended:
        elapsed = time_ms - title_fade_start
        title_opacity = max(0.0, 1.0 - elapsed / TITLE_FADE_MS)
    elif title_ended:
        title_opacity = 0.0
        show_title_card = False

    # Cursor blink (toggle every 400ms)
    cursor_visible = int(time_ms / 400) % 2 == 0

    return FrameState(
        messages=msg_states,
        show_checkpoints=show_checkpoints,
        show_title_card=show_title_card,
        title_card_opacity=title_opacity,
        show_scorecard_overlay=show_scorecard,
        cursor_visible=cursor_visible,
    )


# ── FFmpeg encoding ───────────────────────────────────────────────────


def _check_ffmpeg() -> str:
    """Find ffmpeg binary or raise."""
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError(
            "ffmpeg not found. Install it with: brew install ffmpeg"
        )
    return path


def _start_ffmpeg(
    output_path: Path,
    fps: int = FPS_DEFAULT,
) -> subprocess.Popen:
    """Start ffmpeg process that reads raw RGB frames from stdin."""
    ffmpeg = _check_ffmpeg()
    cmd = [
        ffmpeg,
        "-y",  # overwrite
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-pix_fmt", "rgb24",
        "-r", str(fps),
        "-i", "-",  # stdin
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


# ── Public API ────────────────────────────────────────────────────────


def export_video(
    scenario_data: dict,
    metadata: dict,
    output_path: Path,
    *,
    fps: int = FPS_DEFAULT,
    progress_callback: callable | None = None,
) -> Path:
    """Export a single scenario as an MP4 video.

    Args:
        scenario_data: Prepared scenario dict (from prepare_scenario_data).
        metadata: Run metadata dict.
        output_path: Where to write the MP4 file.
        fps: Frames per second (default 30).
        progress_callback: Optional callable(current_frame, total_frames).

    Returns:
        Path to the written MP4 file.
    """
    _check_ffmpeg()
    fonts = FontSet()

    # Build animation timeline
    events = build_timeline(scenario_data)
    if not events:
        raise ValueError("No animation events generated")

    total_ms = events[-1].time_ms
    total_frames = int(math.ceil(total_ms / (1000 / fps)))
    frame_ms = 1000 / fps

    # Create renderer
    renderer = ChatRenderer(scenario_data, metadata, fonts)

    # Start ffmpeg
    output_path.parent.mkdir(parents=True, exist_ok=True)
    proc = _start_ffmpeg(output_path, fps)

    try:
        for frame_i in range(total_frames):
            t = frame_i * frame_ms
            state = _build_frame_state(scenario_data, events, t)
            img = renderer.render_frame(state)

            # Write raw RGB bytes to ffmpeg stdin
            proc.stdin.write(img.tobytes())

            if progress_callback and frame_i % 10 == 0:
                progress_callback(frame_i, total_frames)

        proc.stdin.close()
        proc.wait(timeout=30)

        if proc.returncode != 0:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}): {stderr[:500]}")

    except Exception:
        proc.kill()
        raise

    return output_path


def export_all_videos(
    run_data: dict,
    output_dir: Path,
    *,
    scenario_id: str | None = None,
    fps: int = FPS_DEFAULT,
    progress_callback: callable | None = None,
) -> list[Path]:
    """Export video files from run data.

    Args:
        run_data: Loaded run JSON dict.
        output_dir: Directory to write MP4 files into.
        scenario_id: If set, export only this scenario.
        fps: Frames per second.
        progress_callback: Optional callable(scenario_id, current_frame, total_frames).

    Returns:
        List of paths to written MP4 files.
    """
    metadata = run_data.get("metadata", {})
    scores = run_data.get("scores", [])

    if scenario_id:
        scores = [s for s in scores if s.get("scenario_id") == scenario_id]
        if not scores:
            raise ValueError(f"Scenario '{scenario_id}' not found in run data")

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for sc in scores:
        prepared = prepare_scenario_data(sc)
        sid = prepared["scenario_id"]
        out_path = output_dir / f"{sid}.mp4"

        def _cb(cur: int, total: int, _sid: str = sid) -> None:
            if progress_callback:
                progress_callback(_sid, cur, total)

        export_video(prepared, metadata, out_path, fps=fps, progress_callback=_cb)
        written.append(out_path)

    return written


def export_all_videos_v2(
    result: dict,
    output_dir: Path,
    *,
    model: str | None = None,
    phase: str | None = None,
    scenario_id: str | None = None,
    fps: int = FPS_DEFAULT,
    progress_callback: callable | None = None,
) -> list[Path]:
    """Export video files from a v2 unified result.

    Args:
        result: V2 unified result dict.
        output_dir: Directory to write MP4 files into.
        model: Optional model filter.
        phase: Optional phase filter.
        scenario_id: If set, export only this scenario.
        fps: Frames per second.
        progress_callback: Optional callable(label, current_frame, total_frames).

    Returns:
        List of paths to written MP4 files.
    """
    from scam.agentic.results import get_run_metadata_for_scenario, iter_scenarios

    scenarios = iter_scenarios(
        result,
        model=model,
        phase=phase,
    )

    if scenario_id:
        scenarios = [
            (mn, pn, ri, sc) for mn, pn, ri, sc in scenarios
            if sc.get("scenario_id") == scenario_id
        ]
        if not scenarios:
            raise ValueError(f"Scenario '{scenario_id}' not found in result")

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for model_name, phase_name, run_index, sc in scenarios:
        prepared = prepare_scenario_data(sc)
        sid = prepared["scenario_id"]
        metadata = get_run_metadata_for_scenario(result, model_name, phase_name)

        # Include model/phase in filename when there are multiple
        if model:
            out_path = output_dir / f"{sid}.mp4"
        else:
            import re as _re
            safe_model = _re.sub(r"-\d{8}$", "", model_name)
            out_path = output_dir / f"{safe_model}_{phase_name}_{sid}.mp4"

        label = f"{sid}"

        def _cb(cur: int, total: int, _label: str = label) -> None:
            if progress_callback:
                progress_callback(_label, cur, total)

        export_video(prepared, metadata, out_path, fps=fps, progress_callback=_cb)
        written.append(out_path)

    return written
