"""Canonical source admission and parser selection from Drive metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal, assert_never

GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME_TYPE = "application/pdf"
CSV_MIME_TYPES = ("application/csv", "text/csv")

ParserKind = Literal["csv", "docx", "pdf", "plain_text"]
PipelineVersion = Literal[
    "csv-record-v1",
    "csv-record-v2",
    "docx-body-v1",
    "docx-body-v2",
    "pdf-ocr-page-v1",
    "pdf-page-v1",
    "plain-text-line-v1",
]
PdfExtractionMethod = Literal["embedded_text", "ocr"]
IngestionMode = Literal["download_binary", "download_text", "export_text"]
FormatRejectionReason = Literal["mime_extension_conflict", "unsupported_mime_type"]


@dataclass(frozen=True)
class AdmittedSourceFormat:
    ingestion_mode: IngestionMode
    parser_kind: ParserKind


@dataclass(frozen=True)
class RejectedSourceFormat:
    reason_code: FormatRejectionReason


SourceFormatDecision = AdmittedSourceFormat | RejectedSourceFormat


def pipeline_version_for(parser_kind: ParserKind) -> PipelineVersion:
    match parser_kind:
        case "csv":
            return "csv-record-v2"
        case "docx":
            return "docx-body-v2"
        case "pdf":
            return "pdf-page-v1"
        case "plain_text":
            return "plain-text-line-v1"
        case unreachable:
            assert_never(unreachable)


def pdf_pipeline_version_for(extraction_method: PdfExtractionMethod) -> PipelineVersion:
    match extraction_method:
        case "embedded_text":
            return "pdf-page-v1"
        case "ocr":
            return "pdf-ocr-page-v1"
        case unreachable:
            assert_never(unreachable)


_FORMAT_REGISTRY: dict[str, tuple[ParserKind, IngestionMode, frozenset[str]]] = {
    "application/csv": ("csv", "download_binary", frozenset({"", ".csv"})),
    DOCX_MIME_TYPE: ("docx", "download_binary", frozenset({"", ".docx"})),
    PDF_MIME_TYPE: ("pdf", "download_binary", frozenset({"", ".pdf"})),
    "text/csv": ("csv", "download_binary", frozenset({"", ".csv"})),
    "text/plain": (
        "plain_text",
        "download_text",
        frozenset({"", ".md", ".markdown", ".text", ".txt"}),
    ),
    "text/markdown": (
        "plain_text",
        "download_text",
        frozenset({"", ".md", ".markdown", ".mdown"}),
    ),
}

NON_PDF_INGESTION_MIME_TYPES = (
    *CSV_MIME_TYPES,
    DOCX_MIME_TYPE,
    GOOGLE_DOC_MIME_TYPE,
    "text/plain",
    "text/markdown",
)


def select_source_format(*, name: str, mime_type: str) -> SourceFormatDecision:
    """Reject spoofed supported formats and select one deterministic parser."""

    if mime_type == GOOGLE_DOC_MIME_TYPE:
        return AdmittedSourceFormat(
            ingestion_mode="export_text",
            parser_kind="plain_text",
        )
    registered = _FORMAT_REGISTRY.get(mime_type)
    if registered is None:
        return RejectedSourceFormat(reason_code="unsupported_mime_type")
    parser_kind, ingestion_mode, allowed_extensions = registered
    extension = PurePosixPath(name).suffix.casefold()
    if extension not in allowed_extensions:
        return RejectedSourceFormat(reason_code="mime_extension_conflict")
    return AdmittedSourceFormat(
        ingestion_mode=ingestion_mode,
        parser_kind=parser_kind,
    )
