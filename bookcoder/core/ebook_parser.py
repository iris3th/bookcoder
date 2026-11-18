from __future__ import annotations

import html
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from .models import Book, Chapter, InputFormat


class ParseError(Exception):
    """Raised when a book cannot be parsed."""


SUPPORTED_EXTENSIONS = {
    ".epub": InputFormat.EPUB,
    ".mobi": InputFormat.MOBI,
    ".azw3": InputFormat.AZW3,
    ".txt": InputFormat.TXT,
}


def detect_format(path: Path) -> InputFormat:
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ParseError(
            f"Unsupported file format '{ext}'. Supported formats: EPUB (.epub), MOBI (.mobi), AZW3 (.azw3), TXT (.txt)."
        )
    return SUPPORTED_EXTENSIONS[ext]


def validate_file(path: Path) -> tuple[InputFormat, int]:
    if not path.exists():
        raise ParseError(f"File does not exist: {path}")
    if not path.is_file():
        raise ParseError(f"Not a file: {path}")
    fmt = detect_format(path)
    size = path.stat().st_size
    if size == 0:
        raise ParseError("The selected file is empty.")
    # Basic corruption/signature checks
    try:
        if fmt == InputFormat.EPUB:
            if not zipfile.is_zipfile(path):
                raise ParseError("The EPUB file appears to be corrupted or is not a valid EPUB archive.")
        elif fmt in (InputFormat.MOBI, InputFormat.AZW3):
            with path.open("rb") as f:
                header = f.read(256)
            # Kindle formats (MOBI/AZW3/KF8) vary; be permissive and let parser/extractor validate.
            if len(header) < 68:
                raise ParseError(f"The {fmt.value.upper()} file appears to be too small or corrupted.")
        elif fmt == InputFormat.TXT:
            # Ensure it is readable as text (best effort)
            with path.open("rb") as f:
                sample = f.read(4096)
            if b"\x00" in sample:
                # could be UTF-16 or binary; try to decode later, but warn-like behavior avoided
                pass
    except OSError as e:
        raise ParseError(f"Could not read file: {e}") from e
    return fmt, size


def parse_book(path: Path, progress: Optional[Callable[[str], None]] = None) -> Book:
    path = Path(path).expanduser().resolve()
    fmt, size = validate_file(path)
    if progress:
        progress(f"Parsing {path.name}...")

    if fmt == InputFormat.EPUB:
        title, author, chapters = _parse_epub(path)
    elif fmt == InputFormat.MOBI:
        title, author, chapters = _parse_kindle_book(path, InputFormat.MOBI)
    elif fmt == InputFormat.AZW3:
        title, author, chapters = _parse_kindle_book(path, InputFormat.AZW3)
    else:
        title, author, chapters = _parse_txt(path)

    # Filter out empty chapters but keep structure if everything empty? ensure at least one
    cleaned: list[Chapter] = []
    for i, ch in enumerate(chapters):
        text = normalize_narration_text(ch.text)
        if text.strip():
            cleaned.append(Chapter.create(ch.title or f"Section {i + 1}", text, len(cleaned), ch.source_hint))
    if not cleaned:
        raise ParseError("No readable text content could be extracted from this file.")

    return Book(
        source_path=path,
        format=fmt,
        title=title or path.stem,
        author=author or "",
        chapters=cleaned,
        file_size=size,
    )


# ----------------------------- EPUB ---------------------------------

def _parse_epub(path: Path) -> tuple[str, str, list[Chapter]]:
    try:
        import ebooklib
        from ebooklib import epub
    except Exception as e:
        raise ParseError(
            "EPUB support requires the 'ebooklib' package. Please install project dependencies (ebooklib)."
        ) from e

    try:
        book = epub.read_epub(str(path))
    except Exception as e:
        raise ParseError(f"Failed to read EPUB file: {e}") from e

    title = _first_meta(book, "DC", "title") or path.stem
    author = _first_meta(book, "DC", "creator") or ""

    # Build TOC title map by href
    toc_titles = _extract_epub_toc_titles(book)

    chapters: list[Chapter] = []
    # Use spine order for reading order
    spine_ids = [item_id for item_id, _linear in book.spine]
    id_to_item = {item.get_id(): item for item in book.get_items()}
    seen_hrefs: set[str] = set()

    for idx, item_id in enumerate(spine_ids):
        item = id_to_item.get(item_id)
        if item is None:
            continue
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        href = getattr(item, "file_name", "") or getattr(item, "href", "") or item_id
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        try:
            content = item.get_content()
        except Exception:
            continue
        text, heading = _html_to_text_and_heading(content)
        if not text.strip():
            continue
        chap_title = toc_titles.get(_normalize_href(href)) or toc_titles.get(href) or heading or f"Chapter {len(chapters) + 1}"
        # Skip obvious non-content sections
        if _looks_like_non_content(chap_title, text):
            continue
        chapters.append(Chapter.create(chap_title, text, len(chapters), source_hint=href))

    # Fallback: if spine produced nothing useful, iterate documents
    if not chapters:
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            href = getattr(item, "file_name", "") or item.get_id()
            try:
                content = item.get_content()
            except Exception:
                continue
            text, heading = _html_to_text_and_heading(content)
            if not text.strip():
                continue
            chap_title = toc_titles.get(_normalize_href(href)) or heading or f"Section {len(chapters) + 1}"
            if _looks_like_non_content(chap_title, text):
                continue
            chapters.append(Chapter.create(chap_title, text, len(chapters), source_hint=href))

    return title, author, chapters


def _first_meta(book, namespace: str, name: str) -> str:
    try:
        vals = book.get_metadata(namespace, name)
        if vals:
            v = vals[0]
            if isinstance(v, tuple):
                return str(v[0] or "").strip()
            return str(v).strip()
    except Exception:
        pass
    return ""


def _extract_epub_toc_titles(book) -> dict[str, str]:
    titles: dict[str, str] = {}

    def walk(entries):
        for e in entries or []:
            try:
                # ebooklib.epub.Link or Section
                if hasattr(e, "href") and hasattr(e, "title"):
                    href = _normalize_href(str(e.href))
                    titles[href] = str(e.title).strip()
                elif isinstance(e, tuple) and len(e) == 2:
                    # (Section, [children]) or (Link, [])
                    sec, children = e
                    if hasattr(sec, "href") and hasattr(sec, "title"):
                        titles[_normalize_href(str(sec.href))] = str(sec.title).strip()
                    walk(children)
                elif hasattr(e, "__iter__"):
                    walk(list(e))
            except Exception:
                continue

    try:
        walk(book.toc)
    except Exception:
        pass
    return titles


def _normalize_href(href: str) -> str:
    return href.split("#", 1)[0].strip()


# -------------------------- MOBI / AZW3 ------------------------------

def _parse_kindle_book(path: Path, fmt: InputFormat) -> tuple[str, str, list[Chapter]]:
    label = fmt.value.upper() if fmt in (InputFormat.MOBI, InputFormat.AZW3) else "Kindle"
    # Try the 'mobi' package which extracts mobi/azw/azw3 content to a temp directory
    try:
        import mobi as mobi_lib  # type: ignore
    except Exception:
        mobi_lib = None

    if mobi_lib is not None:
        tempdir = None
        try:
            tempdir, extracted_path = mobi_lib.extract(str(path))
            extracted = Path(extracted_path)
            # mobi.extract may return an .epub, .html, or a directory with html/opf
            if extracted.is_file() and extracted.suffix.lower() == ".epub":
                return _parse_epub(extracted)
            if extracted.is_file() and extracted.suffix.lower() in {".html", ".xhtml", ".htm"}:
                return _parse_html_book(extracted, fallback_title=path.stem)
            base_dir = Path(tempdir) if tempdir else extracted.parent
            # Look for extracted epub inside
            for cand in base_dir.rglob("*.epub"):
                try:
                    return _parse_epub(cand)
                except Exception:
                    continue
            # Look for OPF to get spine order
            opfs = list(base_dir.rglob("*.opf"))
            if opfs:
                return _parse_opf_book(opfs[0], fallback_title=path.stem)
            # Fallback: gather html files
            html_files = sorted(
                [p for p in base_dir.rglob("*") if p.suffix.lower() in {".html", ".xhtml", ".htm"}]
            )
            if html_files:
                chapters = []
                for i, hf in enumerate(html_files):
                    try:
                        text, heading = _html_to_text_and_heading(hf.read_bytes())
                    except Exception:
                        continue
                    if text.strip():
                        chapters.append(Chapter.create(heading or hf.stem, text, len(chapters), source_hint=str(hf)))
                if chapters:
                    return path.stem, "", chapters
        except ParseError:
            raise
        except Exception:
            # Fall through to ebook-convert fallback; mobi package may not support all AZW3/KF8 files.
            pass
        finally:
            # mobi usually creates tempdir; leave cleanup to OS/temp if unknown, but try
            try:
                if tempdir and os.path.isdir(tempdir):
                    # don't aggressively delete if it's user's dir; mobi uses tempfile.mkdtemp typically
                    pass
            except Exception:
                pass

    # Fallback: try Calibre's ebook-convert if available
    import shutil
    import subprocess

    ebook_convert = shutil.which("ebook-convert")
    if ebook_convert:
        with tempfile.TemporaryDirectory() as td:
            out_epub = Path(td) / "converted.epub"
            try:
                subprocess.run(
                    [ebook_convert, str(path), str(out_epub)],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=300,
                )
                if out_epub.exists():
                    return _parse_epub(out_epub)
            except Exception as e:
                raise ParseError(
                    f"{label} conversion failed using ebook-convert: {e}. "
                    "For best results, install the 'mobi' Python package and/or Calibre (ebook-convert)."
                ) from e

    if fmt == InputFormat.AZW3:
        raise ParseError(
            "AZW3 support requires extracting/converting the Kindle file. "
            "Install the 'mobi' Python package or Calibre's 'ebook-convert' to process AZW3 files. "
            "Note: DRM-protected Kindle books cannot be processed."
        )

    raise ParseError(
        "MOBI support requires the 'mobi' Python package (or Calibre's ebook-convert). "
        "Please install dependencies to process MOBI files."
    )


def _parse_mobi(path: Path) -> tuple[str, str, list[Chapter]]:
    # Backward-compatible wrapper
    return _parse_kindle_book(path, InputFormat.MOBI)


def _parse_html_book(path: Path, fallback_title: str) -> tuple[str, str, list[Chapter]]:
    text, heading = _html_to_text_and_heading(Path(path).read_bytes())
    title = heading or fallback_title
    # Try to split into chapters by headings inside the single HTML
    chapters = _split_htmlish_text_into_chapters(text) if text else []
    if not chapters and text.strip():
        chapters = [Chapter.create(title, text, 0, source_hint=str(path))]
    return title, "", chapters


def _parse_opf_book(opf_path: Path, fallback_title: str) -> tuple[str, str, list[Chapter]]:
    # Minimal OPF parsing without extra deps
    try:
        import xml.etree.ElementTree as ET

        tree = ET.parse(str(opf_path))
        root = tree.getroot()
        # namespaces are messy in OPF; strip them
        def strip_ns(tag: str) -> str:
            return tag.split("}", 1)[-1] if "}" in tag else tag

        manifest = {}
        for elem in root.iter():
            if strip_ns(elem.tag) == "item":
                item_id = elem.attrib.get("id")
                href = elem.attrib.get("href")
                if item_id and href:
                    manifest[item_id] = href

        spine_hrefs = []
        for elem in root.iter():
            if strip_ns(elem.tag) == "itemref":
                idref = elem.attrib.get("idref")
                if idref and idref in manifest:
                    spine_hrefs.append(manifest[idref])

        base = opf_path.parent
        chapters = []
        title = fallback_title
        author = ""
        # metadata best-effort
        for elem in root.iter():
            tag = strip_ns(elem.tag).lower()
            if tag == "title" and (elem.text or "").strip() and title == fallback_title:
                title = elem.text.strip()
            if tag in {"creator", "author"} and (elem.text or "").strip() and not author:
                author = elem.text.strip()

        for href in spine_hrefs or manifest.values():
            target = (base / href.split("#", 1)[0]).resolve()
            if not target.exists() or target.suffix.lower() not in {".html", ".xhtml", ".htm", ".xml"}:
                continue
            try:
                text, heading = _html_to_text_and_heading(target.read_bytes())
            except Exception:
                continue
            if text.strip():
                chapters.append(Chapter.create(heading or f"Section {len(chapters)+1}", text, len(chapters), str(target)))
        return title, author, chapters
    except Exception as e:
        raise ParseError(f"Failed to parse MOBI/OPF content: {e}") from e


# ----------------------------- TXT ----------------------------------

_CHAPTER_HEADING_RE = re.compile(
    r"^(?:\s*)("
    r"chapter\s+\d+[\w\-\.]*"
    r"|chapter\s+[ivxlcdm]+"
    r"|part\s+\d+[\w\-\.]*"
    r"|part\s+[ivxlcdm]+"
    r"|book\s+\d+[\w\-\.]*"
    r"|prologue|epilogue|introduction|preface|foreword|afterword"
    r"|fejezet\s+\d+[\w\-\.]*"  # Hungarian
    r"|rész\s+\d+[\w\-\.]*"
    r"|előszó|utószó|bevezetés|prológus|epilógus"
    r"|\d+\.?\s*$"
    r")\s*(?:[:\.\-–—]\s*(.*))?$",
    re.IGNORECASE,
)


def _parse_txt(path: Path) -> tuple[str, str, list[Chapter]]:
    raw = _read_text_file(path)
    # Normalize line endings
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.strip("\ufeff\n ")
    if not text:
        raise ParseError("The text file is empty.")

    lines = text.split("\n")
    # Detect title/author from first few non-empty lines heuristically
    title = path.stem
    author = ""
    non_empty = [ln.strip() for ln in lines[:20] if ln.strip()]
    if non_empty:
        # Common pattern: Title \n Author \n ...
        if len(non_empty[0]) <= 120:
            title = non_empty[0]
        if len(non_empty) > 1 and len(non_empty[1]) <= 80 and not _CHAPTER_HEADING_RE.match(non_empty[1]):
            maybe_author = re.sub(r"^(by|szerző:|írta:)\s+", "", non_empty[1], flags=re.I)
            if 2 <= len(maybe_author.split()) <= 6:
                author = maybe_author

    chapters = _split_txt_into_chapters(text)
    return title, author, chapters


def _read_text_file(path: Path) -> str:
    data = path.read_bytes()
    # Handle BOMs
    for enc in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "utf-8", "cp1250", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", errors="replace")


def _split_txt_into_chapters(text: str) -> list[Chapter]:
    lines = text.split("\n")
    indices: list[tuple[int, str]] = []  # (line_index, title)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _is_likely_heading(stripped, lines, i):
            indices.append((i, _clean_heading(stripped)))

    if not indices:
        # No headings detected: split into logical chunks by size/paragraph groups
        return _split_by_size(text)

    chapters: list[Chapter] = []
    # Preface/content before first heading
    first_idx = indices[0][0]
    preamble = "\n".join(lines[:first_idx]).strip()
    if preamble and len(preamble.split()) > 40:
        chapters.append(Chapter.create("Introduction", preamble, 0, source_hint="preamble"))

    for n, (start, heading) in enumerate(indices):
        end = indices[n + 1][0] if n + 1 < len(indices) else len(lines)
        body_lines = lines[start + 1 : end]
        body = "\n".join(body_lines).strip()
        # If body is tiny, the "heading" might be a false positive; but include anyway if some text
        if not body and n + 1 < len(indices):
            continue
        chap_text = body if body else heading
        idx = len(chapters)
        chapters.append(Chapter.create(heading or f"Chapter {idx + 1}", chap_text, idx, source_hint=f"line:{start+1}"))

    if not chapters:
        return _split_by_size(text)
    return chapters


def _is_likely_heading(stripped: str, lines: list[str], i: int) -> bool:
    if len(stripped) > 120:
        return False
    if _CHAPTER_HEADING_RE.match(stripped):
        return True
    # ALL CAPS short line with blank line before/after
    letters = [c for c in stripped if c.isalpha()]
    if letters and stripped.upper() == stripped and any(c.isalpha() for c in stripped):
        words = stripped.split()
        if 1 <= len(words) <= 10:
            prev_blank = (i == 0) or (lines[i - 1].strip() == "")
            next_blank = (i + 1 >= len(lines)) or (lines[i + 1].strip() == "")
            if prev_blank or next_blank:
                # avoid shouting sentences
                if not stripped.endswith((".", "!", "?")) or len(words) <= 4:
                    return True
    # Numbered heading like "1. The Beginning" short
    if re.match(r"^\d{1,3}[\.\)]\s+\S+", stripped) and len(stripped) <= 80:
        prev_blank = (i == 0) or (lines[i - 1].strip() == "")
        if prev_blank:
            return True
    return False


def _clean_heading(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip("-–—: ")
    return s[:120] if len(s) > 120 else s


def _split_by_size(text: str, target_chars: int = 12000) -> list[Chapter]:
    # Split on paragraph boundaries into reasonably sized sections
    paras = re.split(r"\n\s*\n", text)
    chapters: list[Chapter] = []
    buf: list[str] = []
    buf_len = 0
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if buf_len + len(p) > target_chars and buf:
            idx = len(chapters)
            chapters.append(Chapter.create(f"Part {idx + 1}", "\n\n".join(buf), idx))
            buf = [p]
            buf_len = len(p)
        else:
            buf.append(p)
            buf_len += len(p)
    if buf:
        idx = len(chapters)
        title = "Text" if idx == 0 else f"Part {idx + 1}"
        chapters.append(Chapter.create(title, "\n\n".join(buf), idx))
    return chapters


# ----------------------- HTML/Text utilities -------------------------

def _html_to_text_and_heading(content: bytes | str) -> tuple[str, str]:
    if isinstance(content, bytes):
        for enc in ("utf-8", "utf-8-sig", "cp1250", "latin-1"):
            try:
                s = content.decode(enc)
                break
            except Exception:
                continue
        else:
            s = content.decode("utf-8", errors="replace")
    else:
        s = content

    # Try BeautifulSoup for robust parsing
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(s, "html.parser")
        # Remove non-narrated elements
        for tag in soup(["script", "style", "nav", "aside", "footer", "header", "noscript", "svg", "img"]):
            tag.decompose()
        # Remove elements that look like page numbers / toc / footnotes in common ebooks (best effort)
        for tag in soup.find_all(attrs={"class": re.compile(r"page.?num|pagenum|toc|footnote|endnote|nav", re.I)}):
            tag.decompose()
        for tag in soup.find_all(attrs={"epub:type": re.compile(r"pagebreak|toc|footnote|endnote", re.I)}):
            tag.decompose()

        heading = ""
        h = soup.find(["h1", "h2", "h3", "title"])
        if h:
            heading = h.get_text(" ", strip=True)

        # Preserve paragraph breaks
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for p in soup.find_all(["p", "div", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "tr"]):
            p.insert_before("\n")
            p.insert_after("\n")

        text = soup.get_text(" ", strip=False)
    except Exception:
        # Fallback: crude tag stripping
        heading = ""
        m = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", s, re.I | re.S)
        if m:
            heading = re.sub(r"<[^>]+>", " ", m.group(1))
            heading = html.unescape(re.sub(r"\s+", " ", heading)).strip()
        s2 = re.sub(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", s, flags=re.I | re.S)
        s2 = re.sub(r"<br\s*/?>", "\n", s2, flags=re.I)
        s2 = re.sub(r"</(p|div|li|h\d|tr|blockquote)>", "\n", s2, flags=re.I)
        s2 = re.sub(r"<[^>]+>", " ", s2)
        text = html.unescape(s2)

    text = _clean_extracted_text(text)
    heading = re.sub(r"\s+", " ", html.unescape(heading)).strip()
    return text, heading


def _clean_extracted_text(text: str) -> str:
    # Unescape entities and normalize whitespace while preserving paragraph breaks
    text = text.replace("\xa0", " ")
    # collapse spaces/tabs
    text = re.sub(r"[ \t\f\v]+", " ", text)
    # normalize newlines
    text = re.sub(r"\s*\n\s*", "\n", text)
    # collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # remove lines that are just page numbers or stray artifacts
    cleaned_lines = []
    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            cleaned_lines.append("")
            continue
        if re.fullmatch(r"\d{1,4}", s):
            continue
        if re.fullmatch(r"[-–—•*]\s*\d{0,4}", s):
            continue
        cleaned_lines.append(s)
    text = "\n".join(cleaned_lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def normalize_narration_text(text: str) -> str:
    """Clean text for TTS: remove artifacts that shouldn't be read aloud."""
    if not text:
        return ""
    t = text
    # Remove URLs
    t = re.sub(r"https?://\S+|www\.\S+", " ", t)
    # Remove HTML entities leftovers
    t = html.unescape(t)
    # Remove stray markup-like tokens
    t = re.sub(r"<[^>]+>", " ", t)
    # Remove bracketed numeric refs like [1], (12) when isolated footnote markers (conservative)
    t = re.sub(r"\[\d+\]", " ", t)
    # Replace fancy quotes/dashes with simpler forms for more consistent TTS handling
    # (keep punctuation, TTS engines handle it fine; but normalize weird chars)
    t = t.replace("\u00ad", "")  # soft hyphen
    t = t.replace("\ufeff", "")
    # Normalize whitespace
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s*\n\s*", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    # Fix spaces before punctuation
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    return t.strip()


def _looks_like_non_content(title: str, text: str) -> bool:
    t = (title or "").strip().lower()
    non_content_titles = {
        "table of contents", "contents", "toc", "copyright", "title page",
        "cover", "index", "acknowledgments", "acknowledgements", "notes",
        "bibliography", "references", "about the author", "also by",
        "tartalomjegyzék", "tartalom", "impresszum", "kolofon", "névmutató",
    }
    if t in non_content_titles:
        # allow if substantial text? TOC/copyright usually should be skipped
        if len(text.split()) < 800:
            return True
    # Very short navigation-like text
    if len(text.split()) < 5 and "contents" in t:
        return True
    return False


def _split_htmlish_text_into_chapters(text: str) -> list[Chapter]:
    # Used as fallback; reuse txt splitter heuristics on plain text
    return _split_txt_into_chapters(text)
