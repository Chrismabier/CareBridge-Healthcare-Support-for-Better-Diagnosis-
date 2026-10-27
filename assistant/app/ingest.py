"""Document ingestion: PDF / TXT / Markdown -> per-page text.

PDFs are read page by page with pypdf so every chunk in the vector store
knows its page number (the advanced feature: answers cite relevant pages).
All failure modes (corrupt file, encrypted PDF, scanned image-only PDF,
unsupported type) raise :class:`IngestError` with a message written for the
end user - the API turns that into a clean 422 instead of a traceback.
"""
from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class IngestError(Exception):
    pass


def extract_pages(filename: str, data: bytes) -> tuple[str, list[tuple[int, str]]]:
    """Return (kind, [(page_number, text), ...]) with 1-based page numbers."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "pdf", _extract_pdf(data)
    if lower.endswith((".txt", ".md", ".markdown")):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        if not text.strip():
            raise IngestError("That file appears to be empty.")
        # Treat form-feed separated text as pages; otherwise one page.
        pages = [p.strip() for p in text.split("\f")]
        return "text", [(i + 1, p) for i, p in enumerate(pages) if p]
    raise IngestError("Only PDF, TXT and Markdown files are supported right now.")


def _extract_pdf(data: bytes) -> list[tuple[int, str]]:
    if not data.startswith(b"%PDF"):
        raise IngestError("That file does not look like a valid PDF (missing %PDF header).")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise IngestError("This PDF is password-protected. Upload an unencrypted copy.")
        pages: list[tuple[int, str]] = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:
                text = ""
            pages.append((i, text))
    except IngestError:
        raise
    except PdfReadError as exc:
        raise IngestError(f"Could not read that PDF - it may be corrupted ({exc}).")
    except Exception as exc:  # defensive: pypdf can raise assorted errors on odd files
        raise IngestError(f"Could not read that PDF ({exc}).")

    non_empty = [(n, t) for n, t in pages if t]
    if not non_empty:
        raise IngestError(
            "No extractable text found in this PDF. It is probably a scanned/image PDF - "
            "OCR is not built in yet (see the README roadmap)."
        )
    return non_empty
