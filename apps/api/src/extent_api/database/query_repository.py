"""Owner-scoped persistence and bounded retrieval for workspace questions."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session as DatabaseSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from extent_api.database.models import (
    Answer,
    AnswerCitation,
    AnswerClaim,
    IngestionRun,
    Message,
    SourceBlock,
    SourceFile,
    Workspace,
)
from extent_api.models import CoverageManifest
from extent_api.providers.embeddings import Embedding
from extent_api.source_states import (
    FAILED_SOURCE_STATUSES,
    PENDING_SOURCE_STATUSES,
    PROCESSING_SOURCE_STATUSES,
    parse_internal_source_status,
)
from extent_api.token_forms import inflected_search_forms


@dataclass(frozen=True)
class SourceIssue:
    kind: str
    source_name: str | None = None


@dataclass(frozen=True)
class QueryContext:
    coverage: CoverageManifest
    gap_reasons: tuple[str, ...]
    run_id: UUID
    run_status: str
    workspace_id: UUID
    source_issues: tuple[SourceIssue, ...] = ()


@dataclass(frozen=True)
class RetrievedBlock:
    block_id: UUID
    drive_file_id: str
    line_start_one_based: int | None
    origin_kind: str
    page_index_zero_based: int | None
    path: tuple[str, ...]
    printed_page_label: str | None
    source_name: str
    source_file_id: UUID
    text: str
    pipeline_version: str | None = None
    structured_metadata: dict[str, object] | None = None
    source_content_hash: str | None = None


@dataclass(frozen=True)
class PassageRecord:
    block_id: UUID
    drive_file_id: str
    end_exclusive_in_block: int
    exact_quote: str
    line_start_one_based: int | None
    origin_kind: str
    page_index_zero_based: int | None
    path: tuple[str, ...]
    printed_page_label: str | None
    source_name: str
    start_in_block: int
    normalized_value: str | None = None
    raw_value: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class ClaimRecord:
    citations: tuple[PassageRecord, ...]
    claim_id: UUID
    relation: str
    text: str
    value: str | None


@dataclass(frozen=True)
class StoredQuestionResult:
    answer_id: UUID
    claims: tuple[ClaimRecord, ...]
    coverage_gap_reasons: tuple[str, ...]
    created_at: datetime
    generation_status: str
    message: str
    passages: tuple[PassageRecord, ...]
    policy_version: str
    question: str
    question_id: UUID
    status: str


def _lexical_variants(token: str) -> tuple[str, ...]:
    """Return deterministic singular/plural search forms without a field dictionary."""

    return inflected_search_forms(token)


def _lexical_pattern(token: str) -> str:
    """Return a PostgreSQL whole-word pattern for the token's safe inflections."""

    alternatives = "|".join(re.escape(variant) for variant in _lexical_variants(token))
    return rf"\m(?:{alternatives})\M"


def _structured_lexical_pattern(tokens: tuple[str, ...]) -> str:
    """Match one accepted field-label token sequence before a separator."""

    phrase = r"[[:space:]]+".join(
        rf"\m(?:{'|'.join(re.escape(variant) for variant in _lexical_variants(token))})\M"
        for token in tokens
    )
    return (
        phrase + r"[[:space:]]*"
        r"(?::|=|\||\t|[[:space:]]+[-" + "\N{EN DASH}\N{EM DASH}" + r"][[:space:]]+|"
        r"[[:space:]]+(?:is|are|was|were)[[:space:]]+)"
    )


class QueryRepository:
    def __init__(
        self,
        session: DatabaseSession,
        *,
        embedding_configuration_id: str | None = None,
    ) -> None:
        self._session = session
        self._embedding_configuration_id = embedding_configuration_id

    def get_context(self, *, user_id: UUID, workspace_id: UUID) -> QueryContext | None:
        row = self._session.execute(
            select(Workspace, IngestionRun)
            .join(IngestionRun, IngestionRun.workspace_id == Workspace.id)
            .where(Workspace.id == workspace_id, Workspace.user_id == user_id)
            .order_by(IngestionRun.created_at.desc())
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        workspace, run = row
        source_rows = self._session.execute(
            select(
                SourceFile.status,
                SourceFile.error_code,
                SourceFile.error_stage,
                SourceFile.name,
            ).where(SourceFile.run_id == run.id)
        ).all()
        source_statuses = [parse_internal_source_status(row.status) for row in source_rows]
        ready = source_statuses.count("ready")
        processing = sum(
            status in PENDING_SOURCE_STATUSES | PROCESSING_SOURCE_STATUSES
            for status in source_statuses
        )
        inaccessible_codes = {"inaccessible", "not_found"}
        unsafe_parse_codes = {
            "docx_archive_too_large",
            "encrypted_pdf",
            "invalid_csv",
            "invalid_docx",
            "invalid_encoding",
            "invalid_pdf",
            "no_text",
            "ocr_no_text",
        }
        inaccessible = sum(
            status in FAILED_SOURCE_STATUSES and error_code in inaccessible_codes
            for status, error_code, _, _ in source_rows
        )
        unsafe_to_parse = sum(
            status in FAILED_SOURCE_STATUSES
            and error_stage == "parse"
            and error_code in unsafe_parse_codes
            for status, error_code, error_stage, _ in source_rows
        )
        failed = sum(status in FAILED_SOURCE_STATUSES for status in source_statuses)
        failed -= inaccessible + unsafe_to_parse
        unsupported = source_statuses.count("unsupported")
        capped = source_statuses.count("capped")
        accounted = (
            ready + processing + failed + unsupported + capped + inaccessible + unsafe_to_parse
        )
        gap_reasons = [reason for reason in run.gap_reasons if reason != "failed" or failed > 0]
        for reason, count in (
            ("processing", processing),
            ("failed", failed),
            ("unsupported", unsupported),
            ("inaccessible", inaccessible),
            ("capped", capped),
            ("unsafe_to_parse", unsafe_to_parse),
        ):
            if count and reason not in gap_reasons:
                gap_reasons.append(reason)
        source_issues = tuple(
            SourceIssue(
                kind=(
                    "missing_file"
                    if error_code == "not_found"
                    else "access_denied"
                    if error_code == "inaccessible"
                    else "unsafe_to_parse"
                    if error_stage == "parse" and error_code in unsafe_parse_codes
                    else "source_failed"
                ),
                source_name=source_name,
            )
            for status, error_code, error_stage, source_name in source_rows
            if status in FAILED_SOURCE_STATUSES
        )
        source_issues = (
            *source_issues,
            *(
                SourceIssue(kind=status, source_name=source_name)
                for status, _, _, source_name in source_rows
                if status in {"capped", "unsupported"}
            ),
        )
        if processing or not run.discovery_complete:
            source_issues = (*source_issues, SourceIssue(kind="partial_sync"))
        return QueryContext(
            coverage=CoverageManifest(
                capped=capped,
                discovered=run.discovered_files,
                discovery_complete=run.discovery_complete,
                failed=failed,
                gap_reasons=gap_reasons,  # type: ignore[arg-type]
                inaccessible=inaccessible,
                processing=processing,
                ready=ready,
                unsafe_to_parse=unsafe_to_parse,
                unknown_branches=max(0, run.discovered_files - accounted),
                unstable=0,
                unsupported=unsupported,
            ),
            gap_reasons=tuple(gap_reasons),
            run_id=run.id,
            run_status=run.status,
            source_issues=source_issues,
            workspace_id=workspace.id,
        )

    def search_blocks(
        self,
        *,
        context: QueryContext,
        embedding: Embedding | None,
        limit: int,
        prefer_value_evidence: bool,
        structured_token_sequences: tuple[tuple[str, ...], ...],
        tokens: tuple[str, ...],
    ) -> list[RetrievedBlock]:
        query = (
            select(SourceBlock, SourceFile)
            .join(SourceFile, SourceFile.id == SourceBlock.source_file_id)
            .where(
                SourceBlock.workspace_id == context.workspace_id,
                SourceBlock.run_id == context.run_id,
                SourceFile.run_id == context.run_id,
                SourceFile.status == "ready",
            )
        )
        if embedding is not None:
            distance = SourceBlock.embedding.cosine_distance(list(embedding))
            query = query.where(SourceBlock.embedding.is_not(None))
            if self._embedding_configuration_id is not None:
                query = query.where(
                    SourceBlock.embedding_configuration_id == self._embedding_configuration_id,
                    SourceBlock.embedding_dimensions == len(embedding),
                )
            query = query.order_by(distance, SourceFile.ordinal, SourceBlock.ordinal)
        else:
            if not tokens:
                return []
            matches = [SourceBlock.text.op("~*")(_lexical_pattern(token)) for token in tokens]
            score: ColumnElement[int] = case((matches[0], 1), else_=0)
            for match in matches[1:]:
                score += case((match, 1), else_=0)
            ordering: list[ColumnElement[int]] = []
            lexical_filter: ColumnElement[bool] = or_(*matches)
            if prefer_value_evidence and structured_token_sequences:
                contains_structured_value = or_(
                    *(
                        SourceBlock.text.op("~*")(_structured_lexical_pattern(token_sequence))
                        for token_sequence in structured_token_sequences
                    )
                )
                ordering.append(case((contains_structured_value, 1), else_=0).desc())
                lexical_filter = or_(lexical_filter, contains_structured_value)
            ordering.append(score.desc())
            query = query.where(lexical_filter).order_by(
                *ordering, SourceFile.ordinal, SourceBlock.ordinal
            )
        rows = self._session.execute(query.limit(limit)).all()
        return [
            RetrievedBlock(
                block_id=block.id,
                drive_file_id=source.drive_file_id,
                line_start_one_based=block.line_start_one_based,
                origin_kind=block.origin_kind,
                page_index_zero_based=block.page_index_zero_based,
                path=tuple(source.path),
                printed_page_label=block.printed_page_label,
                source_name=source.name,
                source_file_id=source.id,
                structured_metadata=block.structured_metadata,
                source_content_hash=block.source_content_hash,
                text=block.text,
                pipeline_version=block.pipeline_version,
            )
            for block, source in rows
        ]

    def list_ready_blocks(self, *, context: QueryContext) -> list[RetrievedBlock]:
        """Return every ready block in stable source order without loading embeddings."""

        rows = self._session.execute(
            select(
                SourceBlock.id,
                SourceFile.drive_file_id,
                SourceBlock.line_start_one_based,
                SourceBlock.origin_kind,
                SourceBlock.page_index_zero_based,
                SourceFile.path,
                SourceBlock.printed_page_label,
                SourceFile.name,
                SourceFile.id,
                SourceBlock.text,
                SourceBlock.pipeline_version,
                SourceBlock.structured_metadata,
                SourceBlock.source_content_hash,
            )
            .join(SourceFile, SourceFile.id == SourceBlock.source_file_id)
            .where(
                SourceBlock.workspace_id == context.workspace_id,
                SourceBlock.run_id == context.run_id,
                SourceFile.run_id == context.run_id,
                SourceFile.status == "ready",
            )
            .order_by(
                SourceFile.ordinal,
                SourceFile.id,
                SourceBlock.ordinal,
                SourceBlock.id,
            )
        ).all()
        return [
            RetrievedBlock(
                block_id=block_id,
                drive_file_id=drive_file_id,
                line_start_one_based=line_start_one_based,
                origin_kind=origin_kind,
                page_index_zero_based=page_index_zero_based,
                path=tuple(path),
                printed_page_label=printed_page_label,
                source_name=source_name,
                source_file_id=source_file_id,
                structured_metadata=structured_metadata,
                source_content_hash=source_content_hash,
                text=text,
                pipeline_version=pipeline_version,
            )
            for (
                block_id,
                drive_file_id,
                line_start_one_based,
                origin_kind,
                page_index_zero_based,
                path,
                printed_page_label,
                source_name,
                source_file_id,
                text,
                pipeline_version,
                structured_metadata,
                source_content_hash,
            ) in rows
        ]

    def get_by_idempotency(
        self, *, workspace_id: UUID, idempotency_key: str
    ) -> StoredQuestionResult | None:
        answer_id = self._session.scalar(
            select(Answer.id)
            .join(Message, Message.id == Answer.question_message_id)
            .where(
                Answer.workspace_id == workspace_id,
                Message.idempotency_key == idempotency_key,
            )
        )
        return None if answer_id is None else self._read(answer_id)

    def list_results(
        self, *, user_id: UUID, workspace_id: UUID, limit: int
    ) -> list[StoredQuestionResult]:
        if not 1 <= limit <= 20:
            raise ValueError("history limit must be between 1 and 20")
        newest_answer_ids = list(
            self._session.scalars(
                select(Answer.id)
                .join(Workspace, Workspace.id == Answer.workspace_id)
                .where(
                    Answer.workspace_id == workspace_id,
                    Workspace.user_id == user_id,
                )
                .order_by(Answer.created_at.desc(), Answer.id.desc())
                .limit(limit)
            )
        )
        if not newest_answer_ids:
            return []

        question = aliased(Message)
        response = aliased(Message)
        answer_rows = self._session.execute(
            select(Answer, question.body, response.body)
            .join(question, question.id == Answer.question_message_id)
            .join(response, response.id == Answer.response_message_id)
            .where(Answer.id.in_(newest_answer_ids))
        ).all()
        answers_by_id = {
            answer.id: (answer, question_body, response_body)
            for answer, question_body, response_body in answer_rows
        }

        claims_by_answer: defaultdict[UUID, list[AnswerClaim]] = defaultdict(list)
        for claim in self._session.scalars(
            select(AnswerClaim)
            .where(AnswerClaim.answer_id.in_(newest_answer_ids))
            .order_by(AnswerClaim.answer_id, AnswerClaim.ordinal)
        ):
            claims_by_answer[claim.answer_id].append(claim)

        citations_by_answer: defaultdict[
            UUID, list[tuple[AnswerCitation, SourceBlock, SourceFile]]
        ] = defaultdict(list)
        for citation, block, source in self._session.execute(
            select(AnswerCitation, SourceBlock, SourceFile)
            .join(SourceBlock, SourceBlock.id == AnswerCitation.source_block_id)
            .join(SourceFile, SourceFile.id == SourceBlock.source_file_id)
            .where(AnswerCitation.answer_id.in_(newest_answer_ids))
            .order_by(AnswerCitation.answer_id, AnswerCitation.ordinal)
        ):
            citations_by_answer[citation.answer_id].append((citation, block, source))

        results: list[StoredQuestionResult] = []
        for answer_id in reversed(newest_answer_ids):
            answer_row = answers_by_id.get(answer_id)
            if answer_row is None:
                raise LookupError("answer no longer exists")
            answer, question_body, response_body = answer_row
            results.append(
                _stored_question_result(
                    answer=answer,
                    citation_rows=citations_by_answer[answer_id],
                    claim_rows=claims_by_answer[answer_id],
                    question_body=question_body,
                    response_body=response_body,
                )
            )
        return results

    def store_retrieval_result(
        self,
        *,
        context: QueryContext,
        generation_status: str = "not_configured",
        idempotency_key: str,
        message: str,
        now: datetime,
        passages: tuple[PassageRecord, ...],
        question: str,
    ) -> StoredQuestionResult:
        return self._store_result(
            claims=(),
            context=context,
            coverage_gap_reasons=context.gap_reasons,
            generation_status=generation_status,
            idempotency_key=idempotency_key,
            message=message,
            now=now,
            passages=passages,
            policy_version="retrieval-policy-v1",
            question=question,
            status="evidence_retrieved" if passages else "insufficient",
        )

    def store_publication_result(
        self,
        *,
        claims: tuple[ClaimRecord, ...],
        context: QueryContext,
        coverage_gap_reasons: tuple[str, ...] | None = None,
        idempotency_key: str,
        message: str,
        now: datetime,
        passages: tuple[PassageRecord, ...],
        question: str,
        status: str,
        policy_version: str = "publication-policy-v1",
    ) -> StoredQuestionResult:
        return self._store_result(
            claims=claims,
            context=context,
            coverage_gap_reasons=(
                context.gap_reasons if coverage_gap_reasons is None else coverage_gap_reasons
            ),
            generation_status="completed",
            idempotency_key=idempotency_key,
            message=message,
            now=now,
            passages=passages,
            policy_version=policy_version,
            question=question,
            status=status,
        )

    def _store_result(
        self,
        *,
        claims: tuple[ClaimRecord, ...],
        context: QueryContext,
        coverage_gap_reasons: tuple[str, ...],
        generation_status: str,
        idempotency_key: str,
        message: str,
        now: datetime,
        passages: tuple[PassageRecord, ...],
        policy_version: str,
        question: str,
        status: str,
    ) -> StoredQuestionResult:
        self._session.scalar(
            select(Workspace.id).where(Workspace.id == context.workspace_id).with_for_update()
        )
        existing = self.get_by_idempotency(
            workspace_id=context.workspace_id, idempotency_key=idempotency_key
        )
        if existing is not None:
            if existing.question != question:
                raise ValueError("idempotency key was used for another question")
            return existing

        next_ordinal = (
            self._session.scalar(
                select(func.max(Message.ordinal)).where(
                    Message.workspace_id == context.workspace_id
                )
            )
            or 0
        ) + 1
        question_message = Message(
            id=uuid4(),
            workspace_id=context.workspace_id,
            role="user",
            kind="question",
            body=question,
            idempotency_key=idempotency_key,
            ordinal=next_ordinal,
            created_at=now,
        )
        response_message = Message(
            id=uuid4(),
            workspace_id=context.workspace_id,
            role="assistant",
            kind="answer",
            body=message,
            ordinal=next_ordinal + 1,
            created_at=now,
        )
        answer = Answer(
            id=uuid4(),
            workspace_id=context.workspace_id,
            ingestion_run_id=context.run_id,
            question_message_id=question_message.id,
            response_message_id=response_message.id,
            status=status,
            generation_status=generation_status,
            summary=None,
            coverage_gap_reasons=list(coverage_gap_reasons),
            policy_version=policy_version,
            created_at=now,
        )
        claim_rows = [
            AnswerClaim(
                id=claim.claim_id,
                answer_id=answer.id,
                relation=claim.relation,
                text=claim.text,
                value=claim.value,
                ordinal=ordinal,
            )
            for ordinal, claim in enumerate(claims)
        ]
        citations: list[AnswerCitation] = [
            AnswerCitation(
                id=uuid4(),
                answer_id=answer.id,
                claim_id=None,
                source_block_id=passage.block_id,
                kind="retrieved",
                normalized_value=passage.normalized_value,
                exact_quote=passage.exact_quote,
                raw_value=passage.raw_value,
                role=passage.role,
                start_in_block=passage.start_in_block,
                end_exclusive_in_block=passage.end_exclusive_in_block,
                ordinal=ordinal,
            )
            for ordinal, passage in enumerate(passages)
        ]
        citation_ordinal = len(citations)
        for claim in claims:
            for passage in claim.citations:
                citations.append(
                    AnswerCitation(
                        id=uuid4(),
                        answer_id=answer.id,
                        claim_id=claim.claim_id,
                        source_block_id=passage.block_id,
                        kind="claim",
                        normalized_value=passage.normalized_value,
                        exact_quote=passage.exact_quote,
                        raw_value=passage.raw_value,
                        role=passage.role,
                        start_in_block=passage.start_in_block,
                        end_exclusive_in_block=passage.end_exclusive_in_block,
                        ordinal=citation_ordinal,
                    )
                )
                citation_ordinal += 1
        # These objects intentionally use immutable UUID foreign keys rather than ORM
        # relationship assignment. Flush each dependency layer so the database never
        # observes an answer before its messages, or a citation before its answer.
        self._session.add_all([question_message, response_message])
        self._session.flush()
        self._session.add(answer)
        self._session.flush()
        self._session.add_all(claim_rows)
        self._session.flush()
        self._session.add_all(citations)
        self._session.commit()
        return self._read(answer.id)

    def rollback(self) -> None:
        self._session.rollback()

    def _read(self, answer_id: UUID) -> StoredQuestionResult:
        question = aliased(Message)
        response = aliased(Message)
        row = self._session.execute(
            select(
                Answer,
                question.body,
                response.body,
            )
            .join(question, question.id == Answer.question_message_id)
            .join(response, response.id == Answer.response_message_id)
            .where(Answer.id == answer_id)
        ).one_or_none()
        if row is None:
            raise LookupError("answer no longer exists")
        answer, question_body, response_body = row
        claim_rows = list(
            self._session.scalars(
                select(AnswerClaim)
                .where(AnswerClaim.answer_id == answer_id)
                .order_by(AnswerClaim.ordinal)
            )
        )
        citation_rows = [
            (citation, block, source)
            for citation, block, source in self._session.execute(
                select(AnswerCitation, SourceBlock, SourceFile)
                .join(SourceBlock, SourceBlock.id == AnswerCitation.source_block_id)
                .join(SourceFile, SourceFile.id == SourceBlock.source_file_id)
                .where(AnswerCitation.answer_id == answer_id)
                .order_by(AnswerCitation.ordinal)
            )
        ]
        return _stored_question_result(
            answer=answer,
            citation_rows=citation_rows,
            claim_rows=claim_rows,
            question_body=question_body,
            response_body=response_body,
        )


def _stored_question_result(
    *,
    answer: Answer,
    citation_rows: list[tuple[AnswerCitation, SourceBlock, SourceFile]],
    claim_rows: list[AnswerClaim],
    question_body: str,
    response_body: str,
) -> StoredQuestionResult:
    passages = tuple(
        _passage_record(citation, block, source)
        for citation, block, source in citation_rows
        if citation.kind == "retrieved"
    )
    claims = tuple(
        ClaimRecord(
            citations=tuple(
                _passage_record(citation, block, source)
                for citation, block, source in citation_rows
                if citation.claim_id == claim.id
            ),
            claim_id=claim.id,
            relation=claim.relation,
            text=claim.text,
            value=claim.value,
        )
        for claim in claim_rows
    )
    return StoredQuestionResult(
        answer_id=answer.id,
        claims=claims,
        coverage_gap_reasons=tuple(answer.coverage_gap_reasons),
        created_at=answer.created_at,
        generation_status=answer.generation_status,
        message=response_body,
        passages=passages,
        policy_version=answer.policy_version,
        question=question_body,
        question_id=answer.question_message_id,
        status=answer.status,
    )


def _passage_record(
    citation: AnswerCitation, block: SourceBlock, source: SourceFile
) -> PassageRecord:
    return PassageRecord(
        block_id=block.id,
        drive_file_id=source.drive_file_id,
        end_exclusive_in_block=citation.end_exclusive_in_block,
        exact_quote=citation.exact_quote,
        line_start_one_based=(
            block.line_start_one_based + block.text.count("\n", 0, citation.start_in_block)
            if block.origin_kind == "text_lines" and block.line_start_one_based is not None
            else None
        ),
        origin_kind=block.origin_kind,
        page_index_zero_based=block.page_index_zero_based,
        path=tuple(source.path),
        printed_page_label=block.printed_page_label,
        normalized_value=citation.normalized_value,
        raw_value=citation.raw_value,
        role=citation.role,
        source_name=source.name,
        start_in_block=citation.start_in_block,
    )
