import io
import os
import tempfile
import uuid
from xml.sax.saxutils import escape

from ebooklib import epub
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Episode, Story
from app.services.episode_text import full_episode_writing_text

_NOVEL_CJK_FONT = "NovelCJK"


def _para_xml(text: str) -> str:
    return escape(text).replace("\n", "<br/>")


def _find_cjk_font_path() -> str | None:
    env = (os.environ.get("PDF_FONT_PATH") or "").strip()
    if env and os.path.isfile(env):
        return env
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.otf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _ensure_cjk_font_registered() -> str:
    if _NOVEL_CJK_FONT in pdfmetrics.getRegisteredFontNames():
        return _NOVEL_CJK_FONT
    path = _find_cjk_font_path()
    if not path:
        raise ValueError(
            "한글 PDF용 폰트를 찾을 수 없습니다. Docker 이미지에는 Noto CJK가 포함됩니다. "
            "로컬에서는 `brew install font-noto-sans-cjk` 후 PDF_FONT_PATH에 .otf 경로를 지정하세요."
        )
    pdfmetrics.registerFont(TTFont(_NOVEL_CJK_FONT, path))
    return _NOVEL_CJK_FONT


async def build_story_text(session: AsyncSession, story_id: uuid.UUID) -> tuple[Story, str]:
    r = await session.execute(select(Story).where(Story.id == story_id))
    story = r.scalar_one_or_none()
    if not story:
        raise ValueError("story not found")
    r2 = await session.execute(
        select(Episode)
        .where(Episode.story_id == story_id)
        .options(selectinload(Episode.bodies))
        .order_by(Episode.chapter_num)
    )
    eps = list(r2.scalars().all())
    parts = [f"{story.title}\n\n"]
    for e in eps:
        parts.append(f"\n\n=== Chapter {e.chapter_num} ===\n\n")
        blob = full_episode_writing_text(e) or (e.raw_memory or "")
        parts.append(blob.strip())
    return story, "".join(parts)


def to_txt_bytes(full_text: str) -> bytes:
    return full_text.encode("utf-8")


def to_pdf_bytes(title: str, full_text: str) -> bytes:
    """UTF-8 본문 PDF. CJK 지원을 위해 시스템 Noto CJK 등 TTF/OTF 필요."""
    font_name = _ensure_cjk_font_registered()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=title,
        author="Novel Writing Agent",
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ExportTitle",
        parent=styles["Heading1"],
        fontName=font_name,
        fontSize=16,
        leading=22,
        spaceAfter=14,
    )
    heading_style = ParagraphStyle(
        "ExportChapter",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=12,
        leading=16,
        spaceBefore=10,
        spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "ExportBody",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=10.5,
        leading=15,
        spaceAfter=4,
    )

    flow: list = []
    blocks = [b.strip() for b in full_text.split("\n\n") if b.strip()]
    for i, block in enumerate(blocks):
        is_chapter_heading = block.startswith("=== ") and block.endswith(" ===")
        if i == 0 and not is_chapter_heading:
            flow.append(Paragraph(_para_xml(block), title_style))
        elif is_chapter_heading:
            flow.append(Paragraph(_para_xml(block), heading_style))
        else:
            flow.append(Paragraph(_para_xml(block), body_style))
        flow.append(Spacer(1, 0.15 * cm))

    doc.build(flow)
    return buf.getvalue()


def to_epub_bytes(title: str, full_text: str) -> bytes:
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(title)
    book.set_language("ko")
    book.add_author("Novel Writing Agent")
    ch = epub.EpubHtml(title="본문", file_name="chap.xhtml", lang="ko")
    safe = full_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ch.content = f"<pre style='white-space:pre-wrap;font-family:serif'>{safe}</pre>"
    book.add_item(ch)
    book.toc = [ch]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", ch]
    tmp = tempfile.NamedTemporaryFile(suffix=".epub", delete=False)
    tmp.close()
    try:
        epub.write_epub(tmp.name, book, {})
        with open(tmp.name, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp.name)
