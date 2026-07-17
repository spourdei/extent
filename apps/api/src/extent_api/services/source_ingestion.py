"""Download and page-aware parsing contracts for real source evidence."""

from __future__ import annotations

import csv
import hashlib
import posixpath
import re
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from io import BytesIO, StringIO
from pathlib import PurePosixPath
from typing import Literal, Protocol
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError

DownloadErrorCode = Literal[
    "inaccessible",
    "not_found",
    "provider_failure",
    "rate_limited",
]
OcrErrorCode = Literal[
    "ocr_engine_unavailable",
    "ocr_no_text",
    "ocr_recognition_failed",
    "ocr_render_failed",
    "ocr_timeout",
]

_PDF_FORM_FIELD_MARKER = re.compile(r"[ \t]*\{\{[0-9A-F]{6}\}\}[ \t]*")
_DOCX_DOCUMENT_PATH = "word/document.xml"
_DOCX_MAX_DOCUMENT_XML_BYTES = 20_000_000
_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_SHEET_NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_REL_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
_XLSX_MAX_ARCHIVE_FILES = 200
_XLSX_MAX_TOTAL_UNCOMPRESSED_BYTES = 50_000_000
_XLSX_MAX_PART_BYTES = 10_000_000
_XLSX_MAX_SHEETS = 20
_XLSX_MAX_ROWS_PER_SHEET = 10_000
_XLSX_MAX_COLUMNS = 200
_XLSX_CELL_REFERENCE = re.compile(r"^([A-Z]{1,3})[1-9]\d*$")
_XLSX_BUILTIN_DATE_FORMAT_IDS = frozenset(
    {*range(14, 23), *range(27, 37), *range(45, 48), *range(50, 59)}
)


@dataclass(frozen=True)
class BinaryDownloadRequest:
    file_id: str
    resource_key: str | None = None


@dataclass(frozen=True)
class TextExportRequest:
    file_id: str
    resource_key: str | None = None


@dataclass(frozen=True)
class BinaryDownloadSuccess:
    content: bytes
    status: Literal["ok"] = "ok"


@dataclass(frozen=True)
class BinaryDownloadError:
    code: DownloadErrorCode
    retryable: bool
    status: Literal["error"] = "error"


BinaryDownloadResponse = BinaryDownloadSuccess | BinaryDownloadError


class SourceContentProvider(Protocol):
    def download_binary(self, request: BinaryDownloadRequest) -> BinaryDownloadResponse: ...

    def export_text(self, request: TextExportRequest) -> BinaryDownloadResponse: ...


class PdfOcrProvider(Protocol):
    def extract_pages(self, content: bytes) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class ParsedPdfBlock:
    content_hash: str
    normalized_end_exclusive: int
    normalized_start: int
    ordinal: int
    page_index_zero_based: int
    printed_page_label: str | None
    text: str


@dataclass(frozen=True)
class ParsedPdf:
    blocks: tuple[ParsedPdfBlock, ...]
    content_hash: str
    page_count: int
    extraction_method: Literal["embedded_text", "ocr"] = "embedded_text"


@dataclass(frozen=True)
class ParsedTextBlock:
    content_hash: str
    line_start_one_based: int
    normalized_end_exclusive: int
    normalized_start: int
    ordinal: int
    text: str


@dataclass(frozen=True)
class ParsedTableRow:
    line_start_one_based: int
    ordinal: int
    values: tuple[str, ...]


@dataclass(frozen=True)
class ParsedDocumentTable:
    headers: tuple[str, ...]
    malformed_rows: int
    ordinal: int
    rows: tuple[ParsedTableRow, ...]
    section: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class ParsedText:
    blocks: tuple[ParsedTextBlock, ...]
    content_hash: str
    tables: tuple[ParsedDocumentTable, ...] = ()


class TextExtractionError(ValueError):
    def __init__(
        self,
        code: Literal[
            "docx_archive_too_large",
            "invalid_csv",
            "invalid_docx",
            "invalid_encoding",
            "invalid_xlsx",
            "no_text",
        ],
    ):
        super().__init__(code)
        self.code = code


class PdfOcrError(RuntimeError):
    def __init__(self, code: OcrErrorCode):
        super().__init__(code)
        self.code = code


class PdfExtractionError(ValueError):
    def __init__(
        self,
        code: Literal[
            "encrypted_pdf",
            "invalid_pdf",
            "no_text",
            "ocr_engine_unavailable",
            "ocr_no_text",
            "ocr_recognition_failed",
            "ocr_render_failed",
            "ocr_timeout",
        ],
    ):
        super().__init__(code)
        self.code = code


def parse_text_pdf(
    content: bytes,
    *,
    max_block_chars: int = 1_800,
) -> ParsedPdf:
    """Extract page text into exact, reversible page-relative blocks."""

    reader = _read_pdf(content)
    labels = reader.page_labels
    pages: list[str] = []
    for page in reader.pages:
        try:
            extracted = page.extract_text()
        except (PdfReadError, KeyError, TypeError, ValueError) as error:
            raise PdfExtractionError("invalid_pdf") from error
        pages.append(extracted or "")
    parsed = _parsed_pdf(
        content,
        page_texts=pages,
        page_labels=labels,
        extraction_method="embedded_text",
        max_block_chars=max_block_chars,
    )
    if not parsed.blocks:
        raise PdfExtractionError("no_text")
    return parsed


def parse_ocr_pdf(
    content: bytes,
    *,
    provider: PdfOcrProvider,
    max_block_chars: int = 1_800,
) -> ParsedPdf:
    """Extract OCR-derived, page-relative blocks after embedded text is unavailable."""

    reader = _read_pdf(content)
    try:
        pages = provider.extract_pages(content)
    except PdfOcrError as error:
        raise PdfExtractionError(error.code) from error
    if len(pages) != len(reader.pages):
        raise PdfExtractionError("ocr_recognition_failed")
    parsed = _parsed_pdf(
        content,
        page_texts=pages,
        page_labels=reader.page_labels,
        extraction_method="ocr",
        max_block_chars=max_block_chars,
    )
    if not parsed.blocks:
        raise PdfExtractionError("ocr_no_text")
    return parsed


def _read_pdf(content: bytes) -> PdfReader:
    try:
        reader = PdfReader(BytesIO(content), strict=False)
    except (PdfReadError, OSError, ValueError) as error:
        raise PdfExtractionError("invalid_pdf") from error
    if reader.is_encrypted:
        raise PdfExtractionError("encrypted_pdf")
    return reader


def _parsed_pdf(
    content: bytes,
    *,
    page_texts: list[str] | tuple[str, ...],
    page_labels: list[str],
    extraction_method: Literal["embedded_text", "ocr"],
    max_block_chars: int,
) -> ParsedPdf:
    blocks: list[ParsedPdfBlock] = []
    ordinal = 0
    for page_index, extracted in enumerate(page_texts):
        normalized = _normalize_pdf_text(extracted)
        if not normalized:
            continue
        label = (
            page_labels[page_index] if page_index < len(page_labels) else str(page_index + 1)
        )
        for start, end, text in _bounded_text_blocks(normalized, max_block_chars):
            blocks.append(
                ParsedPdfBlock(
                    content_hash=hashlib.sha256(text.encode()).hexdigest(),
                    normalized_end_exclusive=end,
                    normalized_start=start,
                    ordinal=ordinal,
                    page_index_zero_based=page_index,
                    printed_page_label=label,
                    text=text,
                )
            )
            ordinal += 1
    return ParsedPdf(
        blocks=tuple(blocks),
        content_hash=hashlib.sha256(content).hexdigest(),
        page_count=len(page_texts),
        extraction_method=extraction_method,
    )


def parse_plain_text(content: bytes, *, max_block_chars: int = 1_800) -> ParsedText:
    """Decode UTF-8 text into exact blocks addressable by normalized line number."""

    decoded = _decode_utf8(content)
    normalized = _normalize_page_text(decoded)
    if not normalized:
        raise TextExtractionError("no_text")
    return _parsed_text(normalized, content=content, max_block_chars=max_block_chars)


def parse_csv(content: bytes, *, max_block_chars: int = 1_800) -> ParsedText:
    """Parse RFC 4180-style comma-separated records into stable row-addressable text."""

    decoded = _decode_utf8(content)
    try:
        rows = csv.reader(StringIO(decoded, newline=""), dialect="excel", strict=True)
        cell_rows = [tuple(_normalize_structured_cell(cell) for cell in row) for row in rows]
    except csv.Error as error:
        raise TextExtractionError("invalid_csv") from error
    cell_rows = [row for row in cell_rows if any(cell for cell in row)]
    normalized = "\n".join("\t".join(row) for row in cell_rows)
    if not normalized:
        raise TextExtractionError("no_text")
    tables: tuple[ParsedDocumentTable, ...] = ()
    if len(cell_rows) >= 2 and len(cell_rows[0]) >= 2:
        headers = cell_rows[0]
        tables = (
            ParsedDocumentTable(
                headers=headers,
                malformed_rows=sum(len(row) != len(headers) for row in cell_rows[1:]),
                ordinal=1,
                rows=tuple(
                    ParsedTableRow(
                        line_start_one_based=index + 1,
                        ordinal=index,
                        values=row,
                    )
                    for index, row in enumerate(cell_rows[1:], start=1)
                    if len(row) == len(headers)
                ),
            ),
        )
    return _parsed_text(
        normalized,
        content=content,
        max_block_chars=max_block_chars,
        tables=tables,
    )


def parse_docx(content: bytes, *, max_block_chars: int = 1_800) -> ParsedText:
    """Extract DOCX body paragraphs and table rows in document order."""

    document_xml = _read_docx_document_xml(content)
    if b"<!DOCTYPE" in document_xml.upper() or b"<!ENTITY" in document_xml.upper():
        raise TextExtractionError("invalid_docx")
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as error:
        raise TextExtractionError("invalid_docx") from error
    body = root.find(f".//{_word_tag('body')}")
    if body is None:
        raise TextExtractionError("invalid_docx")
    lines: list[str] = []
    tables: list[ParsedDocumentTable] = []
    current_section: str | None = None
    previous_paragraph: str | None = None
    for child in body:
        if child.tag == _word_tag("p"):
            paragraph = _docx_paragraph_text(child)
            if paragraph:
                lines.append(paragraph)
                previous_paragraph = paragraph
                if _docx_paragraph_is_heading(child):
                    current_section = paragraph
        elif child.tag == _word_tag("tbl"):
            table_rows = _docx_table_rows(child)
            table_line_start = len(lines) + 1
            lines.extend(table_rows)
            split_rows = [tuple(row.split("\t")) for row in table_rows]
            if len(split_rows) >= 2 and len(split_rows[0]) >= 2:
                headers = split_rows[0]
                tables.append(
                    ParsedDocumentTable(
                        headers=headers,
                        malformed_rows=sum(len(row) != len(headers) for row in split_rows[1:]),
                        ordinal=len(tables) + 1,
                        rows=tuple(
                            ParsedTableRow(
                                line_start_one_based=table_line_start + index,
                                ordinal=index,
                                values=row,
                            )
                            for index, row in enumerate(split_rows[1:], start=1)
                            if len(row) == len(headers)
                        ),
                        section=current_section,
                        title=previous_paragraph,
                    )
                )
    normalized = _normalize_page_text("\n".join(lines))
    if not normalized:
        raise TextExtractionError("no_text")
    return _parsed_text(
        normalized,
        content=content,
        max_block_chars=max_block_chars,
        tables=tuple(tables),
    )


def parse_xlsx(content: bytes, *, max_block_chars: int = 1_800) -> ParsedText:
    """Extract bounded XLSX worksheets into line- and table-addressable text."""

    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            if (
                len(infos) > _XLSX_MAX_ARCHIVE_FILES
                or sum(info.file_size for info in infos) > _XLSX_MAX_TOTAL_UNCOMPRESSED_BYTES
                or any(info.flag_bits & 0x1 for info in infos)
            ):
                raise TextExtractionError("invalid_xlsx")
            for info in infos:
                path = PurePosixPath(info.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise TextExtractionError("invalid_xlsx")

            workbook = _xlsx_xml(archive, "xl/workbook.xml")
            workbook_properties = workbook.find(f"{{{_SHEET_NAMESPACE}}}workbookPr")
            uses_1904_dates = workbook_properties is not None and workbook_properties.get(
                "date1904", ""
            ).casefold() in {"1", "true"}
            relationships = _xlsx_relationships(archive)
            shared_strings = _xlsx_shared_strings(archive)
            style_formats = _xlsx_style_formats(archive)
            sheets = workbook.findall(f".//{{{_SHEET_NAMESPACE}}}sheet")
            if not sheets or len(sheets) > _XLSX_MAX_SHEETS:
                raise TextExtractionError("invalid_xlsx")

            lines: list[str] = []
            tables: list[ParsedDocumentTable] = []
            for sheet_ordinal, sheet in enumerate(sheets, start=1):
                name = sheet.get("name", "").strip()
                relationship_id = sheet.get(f"{{{_OFFICE_REL_NAMESPACE}}}id", "")
                target = relationships.get(relationship_id)
                if not name or target is None:
                    raise TextExtractionError("invalid_xlsx")
                sheet_root = _xlsx_xml(archive, target)
                rendered_rows = _xlsx_rows(
                    sheet_root,
                    shared_strings=shared_strings,
                    style_formats=style_formats,
                    uses_1904_dates=uses_1904_dates,
                )
                if not rendered_rows:
                    continue
                lines.append(f"Sheet: {name}")
                row_lines: list[tuple[int, tuple[str, ...]]] = []
                for values in rendered_rows:
                    line_number = len(lines) + 1
                    lines.append("\t".join(values))
                    row_lines.append((line_number, values))
                header_position = next(
                    (
                        index
                        for index, (_, values) in enumerate(row_lines)
                        if len(values) >= 2 and sum(bool(value) for value in values) >= 2
                    ),
                    None,
                )
                if header_position is None:
                    continue
                _, headers = row_lines[header_position]
                data_rows = [
                    ParsedTableRow(
                        line_start_one_based=line_number,
                        ordinal=ordinal,
                        values=values,
                    )
                    for ordinal, (line_number, values) in enumerate(
                        row_lines[header_position + 1 :], start=1
                    )
                    if len(values) == len(headers) and any(values)
                ]
                if data_rows:
                    tables.append(
                        ParsedDocumentTable(
                            headers=headers,
                            malformed_rows=sum(
                                len(values) != len(headers)
                                for _, values in row_lines[header_position + 1 :]
                                if any(values)
                            ),
                            ordinal=sheet_ordinal,
                            rows=tuple(data_rows),
                            section=name,
                            title=(
                                row_lines[0][1][0]
                                if header_position > 0 and row_lines[0][1]
                                else name
                            ),
                        )
                    )
    except TextExtractionError:
        raise
    except (KeyError, OSError, RuntimeError, ValueError, zipfile.BadZipFile) as error:
        raise TextExtractionError("invalid_xlsx") from error

    normalized = _normalize_page_text("\n".join(lines))
    if not normalized:
        raise TextExtractionError("no_text")
    return _parsed_text(
        normalized,
        content=content,
        max_block_chars=max_block_chars,
        tables=tuple(tables),
    )


def _xlsx_xml(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    try:
        info = archive.getinfo(name)
    except KeyError as error:
        raise TextExtractionError("invalid_xlsx") from error
    if info.is_dir() or info.file_size > _XLSX_MAX_PART_BYTES:
        raise TextExtractionError("invalid_xlsx")
    payload = archive.read(info)
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise TextExtractionError("invalid_xlsx")
    try:
        return ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise TextExtractionError("invalid_xlsx") from error


def _xlsx_relationships(archive: zipfile.ZipFile) -> dict[str, str]:
    root = _xlsx_xml(archive, "xl/_rels/workbook.xml.rels")
    relationships: dict[str, str] = {}
    for relationship in root.findall(f"{{{_PACKAGE_REL_NAMESPACE}}}Relationship"):
        relationship_id = relationship.get("Id", "")
        target = relationship.get("Target", "")
        relationship_type = relationship.get("Type", "")
        if target.startswith("/") or target.startswith("xl/"):
            resolved_target = target.lstrip("/")
        else:
            resolved_target = f"xl/{target}"
        normalized_target = posixpath.normpath(resolved_target)
        path = PurePosixPath(normalized_target)
        if (
            not relationship_id
            or relationship.get("TargetMode") == "External"
            or not relationship_type.endswith("/worksheet")
            or "\\" in target
            or path.is_absolute()
            or ".." in path.parts
            or not normalized_target.startswith("xl/")
        ):
            continue
        relationships[relationship_id] = normalized_target
    return relationships


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    try:
        root = _xlsx_xml(archive, "xl/sharedStrings.xml")
    except TextExtractionError:
        return ()
    return tuple(
        _normalize_structured_cell(
            "".join(text.text or "" for text in item.iter(f"{{{_SHEET_NAMESPACE}}}t"))
        )
        for item in root.findall(f"{{{_SHEET_NAMESPACE}}}si")
    )


def _xlsx_style_formats(archive: zipfile.ZipFile) -> tuple[str, ...]:
    try:
        root = _xlsx_xml(archive, "xl/styles.xml")
    except TextExtractionError:
        return ()
    custom = {
        item.get("numFmtId", ""): item.get("formatCode", "")
        for item in root.findall(f".//{{{_SHEET_NAMESPACE}}}numFmt")
    }
    return tuple(
        custom.get(
            item.get("numFmtId", ""),
            (
                "builtin-date"
                if item.get("numFmtId", "").isdigit()
                and int(item.get("numFmtId", "")) in _XLSX_BUILTIN_DATE_FORMAT_IDS
                else item.get("numFmtId", "")
            ),
        )
        for item in root.findall(f".//{{{_SHEET_NAMESPACE}}}cellXfs/{{{_SHEET_NAMESPACE}}}xf")
    )


def _xlsx_rows(
    root: ElementTree.Element,
    *,
    shared_strings: tuple[str, ...],
    style_formats: tuple[str, ...],
    uses_1904_dates: bool,
) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for row in root.findall(f".//{{{_SHEET_NAMESPACE}}}sheetData/{{{_SHEET_NAMESPACE}}}row"):
        if len(rows) >= _XLSX_MAX_ROWS_PER_SHEET:
            raise TextExtractionError("invalid_xlsx")
        cells: dict[int, str] = {}
        for cell in row.findall(f"{{{_SHEET_NAMESPACE}}}c"):
            reference = cell.get("r", "")
            matched = _XLSX_CELL_REFERENCE.fullmatch(reference)
            if matched is None:
                raise TextExtractionError("invalid_xlsx")
            column = _xlsx_column_index(matched.group(1))
            if column >= _XLSX_MAX_COLUMNS:
                raise TextExtractionError("invalid_xlsx")
            cells[column] = _xlsx_cell_value(
                cell,
                shared_strings=shared_strings,
                style_formats=style_formats,
                uses_1904_dates=uses_1904_dates,
            )
        if not cells or not any(cells.values()):
            continue
        last_column = max(cells)
        values = tuple(cells.get(index, "") for index in range(last_column + 1))
        while values and not values[-1]:
            values = values[:-1]
        if values:
            rows.append(values)
    return tuple(rows)


def _xlsx_column_index(letters: str) -> int:
    value = 0
    for letter in letters:
        value = value * 26 + ord(letter) - ord("A") + 1
    return value - 1


def _xlsx_cell_value(
    cell: ElementTree.Element,
    *,
    shared_strings: tuple[str, ...],
    style_formats: tuple[str, ...],
    uses_1904_dates: bool,
) -> str:
    cell_type = cell.get("t", "n")
    value_node = cell.find(f"{{{_SHEET_NAMESPACE}}}v")
    raw = "" if value_node is None else (value_node.text or "")
    if cell_type == "inlineStr":
        raw = "".join(text.text or "" for text in cell.iter(f"{{{_SHEET_NAMESPACE}}}t"))
    elif cell_type == "s":
        try:
            raw = shared_strings[int(raw)]
        except (IndexError, ValueError) as error:
            raise TextExtractionError("invalid_xlsx") from error
    elif cell_type == "b":
        raw = "TRUE" if raw == "1" else "FALSE"
    if cell_type != "n" or not raw:
        return _normalize_structured_cell(raw)
    try:
        style_index = int(cell.get("s", "0"))
    except ValueError as error:
        raise TextExtractionError("invalid_xlsx") from error
    format_code = style_formats[style_index] if style_index < len(style_formats) else ""
    return _xlsx_format_number(raw, format_code, uses_1904_dates=uses_1904_dates)


def _xlsx_format_number(raw: str, format_code: str, *, uses_1904_dates: bool) -> str:
    try:
        number = float(raw)
    except ValueError as error:
        raise TextExtractionError("invalid_xlsx") from error
    normalized_format = format_code.casefold()
    if "builtin-date" in normalized_format or (
        "y" in normalized_format and "d" in normalized_format
    ):
        epoch = date(1904, 1, 1) if uses_1904_dates else date(1899, 12, 30)
        return (epoch + timedelta(days=int(number))).isoformat()
    if "$" in format_code:
        return f"${number:,.0f}" if number.is_integer() else f"${number:,.2f}"
    if "%" in format_code:
        return f"{number * 100:g}%"
    return str(int(number)) if number.is_integer() else str(number)


def _decode_utf8(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise TextExtractionError("invalid_encoding") from error


def _normalize_structured_cell(value: str) -> str:
    return re.sub(r"[\t\r\n ]+", " ", value.replace("\x00", "")).strip()


def _read_docx_document_xml(content: bytes) -> bytes:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            try:
                document = archive.getinfo(_DOCX_DOCUMENT_PATH)
            except KeyError as error:
                raise TextExtractionError("invalid_docx") from error
            if document.is_dir() or document.file_size > _DOCX_MAX_DOCUMENT_XML_BYTES:
                raise TextExtractionError("docx_archive_too_large")
            with archive.open(document) as stream:
                document_xml = stream.read(_DOCX_MAX_DOCUMENT_XML_BYTES + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise TextExtractionError("invalid_docx") from error
    if len(document_xml) > _DOCX_MAX_DOCUMENT_XML_BYTES:
        raise TextExtractionError("docx_archive_too_large")
    return document_xml


def _docx_table_rows(table: ElementTree.Element) -> list[str]:
    rows: list[str] = []
    for row in table.findall(f".//{_word_tag('tr')}"):
        cells = [
            " ".join(
                text
                for paragraph in cell.findall(f".//{_word_tag('p')}")
                if (text := _docx_paragraph_text(paragraph))
            )
            for cell in row.findall(f"./{_word_tag('tc')}")
        ]
        normalized = "\t".join(cells).rstrip()
        if normalized.strip():
            rows.append(normalized)
    return rows


def _docx_paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == _word_tag("t"):
            parts.append(node.text or "")
        elif node.tag == _word_tag("tab"):
            parts.append("\t")
        elif node.tag in {_word_tag("br"), _word_tag("cr")}:
            parts.append("\n")
        elif node.tag == _word_tag("noBreakHyphen"):
            parts.append("-")
    return _normalize_structured_cell("".join(parts))


def _docx_paragraph_is_heading(paragraph: ElementTree.Element) -> bool:
    style = paragraph.find(f"./{_word_tag('pPr')}/{_word_tag('pStyle')}")
    if style is None:
        return False
    value = style.get(_word_tag("val"), "")
    return value.casefold().startswith("heading")


def _word_tag(local_name: str) -> str:
    return f"{{{_WORD_NAMESPACE}}}{local_name}"


def _parsed_text(
    normalized: str,
    *,
    content: bytes,
    max_block_chars: int,
    tables: tuple[ParsedDocumentTable, ...] = (),
) -> ParsedText:
    block_ranges = (
        _bounded_line_blocks(normalized, max_block_chars)
        if tables
        else _bounded_text_blocks(normalized, max_block_chars)
    )
    blocks = tuple(
        ParsedTextBlock(
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            line_start_one_based=1 + normalized.count("\n", 0, start),
            normalized_end_exclusive=end,
            normalized_start=start,
            ordinal=ordinal,
            text=text,
        )
        for ordinal, (start, end, text) in enumerate(block_ranges)
    )
    return ParsedText(
        blocks=blocks,
        content_hash=hashlib.sha256(content).hexdigest(),
        tables=tables,
    )


def _normalize_page_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    value = "\n".join(line.rstrip() for line in value.split("\n"))
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _normalize_pdf_text(value: str) -> str:
    without_form_markers = _PDF_FORM_FIELD_MARKER.sub(" ", value)
    return _normalize_page_text(without_form_markers)


def _bounded_text_blocks(value: str, limit: int) -> list[tuple[int, int, str]]:
    if limit < 200:
        raise ValueError("PDF block limit is too small")
    blocks: list[tuple[int, int, str]] = []
    cursor = 0
    while cursor < len(value):
        end = min(cursor + limit, len(value))
        if end < len(value):
            search_floor = cursor + limit // 2
            candidates = [
                value.rfind("\n\n", search_floor, end),
                value.rfind("\n", search_floor, end),
                value.rfind(" ", search_floor, end),
            ]
            boundary = max(candidates)
            if boundary > cursor:
                end = boundary
        raw = value[cursor:end]
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        start = cursor + leading
        trimmed_end = cursor + trailing
        if trimmed_end > start:
            blocks.append((start, trimmed_end, value[start:trimmed_end]))
        cursor = end
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
    return blocks


def _bounded_line_blocks(value: str, limit: int) -> list[tuple[int, int, str]]:
    """Chunk structured text without splitting a source row across blocks.

    Complete table artifacts retain row-level provenance by normalized line
    number. A block boundary inside a row makes that row impossible to cite
    exactly, so a single unusually long row is allowed to exceed the preferred
    block size instead of being silently omitted from later analysis.
    """

    if limit < 200:
        raise ValueError("text block limit is too small")
    blocks: list[tuple[int, int, str]] = []
    cursor = 0
    while cursor < len(value):
        preferred_end = min(cursor + limit, len(value))
        if preferred_end == len(value):
            end = preferred_end
        else:
            end = value.rfind("\n", cursor, preferred_end + 1)
            if end <= cursor:
                following_line_end = value.find("\n", preferred_end)
                end = len(value) if following_line_end < 0 else following_line_end
        raw = value[cursor:end]
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        start = cursor + leading
        trimmed_end = cursor + trailing
        if trimmed_end > start:
            blocks.append((start, trimmed_end, value[start:trimmed_end]))
        cursor = end
        while cursor < len(value) and value[cursor] == "\n":
            cursor += 1
    return blocks
