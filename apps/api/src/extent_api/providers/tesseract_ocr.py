"""Local page OCR with in-memory PDF rendering and bounded Tesseract execution."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from io import BytesIO
from typing import Protocol

import pypdfium2 as pdfium

from extent_api.services.source_ingestion import PdfOcrError

_MAX_PAGE_TEXT_BYTES = 250_000


class PageRenderer(Protocol):
    def render_pages(self, content: bytes) -> Iterator[bytes]: ...


class PageOcrEngine(Protocol):
    def recognize(self, image: bytes) -> str: ...


class PdfiumPngRenderer:
    """Render one grayscale page at a time without retaining the source document."""

    def __init__(self, *, dpi: int = 300) -> None:
        if dpi < 150 or dpi > 400:
            raise ValueError("OCR rendering DPI must be between 150 and 400")
        self._scale = dpi / 72

    def render_pages(self, content: bytes) -> Iterator[bytes]:
        try:
            document = pdfium.PdfDocument(content)
        except (pdfium.PdfiumError, TypeError, ValueError) as error:
            raise PdfOcrError("ocr_render_failed") from error
        try:
            for page_index in range(len(document)):
                page = None
                bitmap = None
                image = None
                try:
                    page = document.get_page(page_index)
                    bitmap = page.render(scale=self._scale, grayscale=True)
                    image = bitmap.to_pil()
                    output = BytesIO()
                    image.save(output, format="PNG", optimize=True)
                    rendered = output.getvalue()
                except (pdfium.PdfiumError, OSError, TypeError, ValueError) as error:
                    raise PdfOcrError("ocr_render_failed") from error
                finally:
                    if image is not None:
                        image.close()
                    if bitmap is not None:
                        bitmap.close()
                    if page is not None:
                        page.close()
                yield rendered
        finally:
            document.close()


class TesseractPageOcrEngine:
    def __init__(self, *, executable: str, timeout_seconds: int = 30) -> None:
        if not executable.strip():
            raise ValueError("OCR executable cannot be empty")
        if timeout_seconds < 5 or timeout_seconds > 120:
            raise ValueError("OCR timeout must be between 5 and 120 seconds")
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    def recognize(self, image: bytes) -> str:
        try:
            result = subprocess.run(
                [self._executable, "stdin", "stdout", "-l", "eng", "--psm", "3"],
                input=image,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=self._timeout_seconds,
                check=False,
            )
        except FileNotFoundError as error:
            raise PdfOcrError("ocr_engine_unavailable") from error
        except subprocess.TimeoutExpired as error:
            raise PdfOcrError("ocr_timeout") from error
        except OSError as error:
            raise PdfOcrError("ocr_recognition_failed") from error
        if result.returncode != 0 or len(result.stdout) > _MAX_PAGE_TEXT_BYTES:
            raise PdfOcrError("ocr_recognition_failed")
        try:
            return result.stdout.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PdfOcrError("ocr_recognition_failed") from error


class TesseractPdfOcrProvider:
    def __init__(
        self,
        *,
        executable: str,
        renderer: PageRenderer | None = None,
        engine: PageOcrEngine | None = None,
    ) -> None:
        self._renderer = renderer or PdfiumPngRenderer()
        self._engine = engine or TesseractPageOcrEngine(executable=executable)

    def extract_pages(self, content: bytes) -> tuple[str, ...]:
        pages = tuple(
            self._engine.recognize(image) for image in self._renderer.render_pages(content)
        )
        if not any(page.strip() for page in pages):
            raise PdfOcrError("ocr_no_text")
        return pages


def ensure_tesseract_available(executable: str) -> None:
    if shutil.which(executable) is None:
        raise RuntimeError("configured OCR executable is unavailable")
