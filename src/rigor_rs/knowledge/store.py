from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from rigor_rs.knowledge.models import (
    CacheStatus,
    CitationRecord,
    CodeRecord,
    PaperIdentifiers,
    PaperRecord,
    QueueItem,
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class KnowledgeStore:
    def __init__(self, database: Path) -> None:
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def migrate(self) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self._lock, self.connect() as connection:
            connection.executescript(schema)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(1, ?)",
                (utc_now(),),
            )
            connection.commit()

    def counts(self) -> dict[str, int]:
        tables = (
            "papers", "paper_versions", "paper_identifiers", "code_implementations",
            "citation_edges", "paper_vectors", "query_cache", "ingestion_queue",
            "ingestion_events", "provider_usage",
        )
        with self.connect() as connection:
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}

    def enqueue(self, work_key: str, source: str, payload_json: str, requested_query: str | None = None) -> int:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO ingestion_queue(work_key, source, requested_query, payload_json, state, updated_at)
                   VALUES(?,?,?,?, 'pending', ?)
                   ON CONFLICT(work_key) DO UPDATE SET
                     source=excluded.source, requested_query=excluded.requested_query,
                     payload_json=excluded.payload_json, state='pending', lease_timestamp=NULL,
                     last_error=NULL, updated_at=excluded.updated_at""",
                (work_key, source, requested_query, payload_json, now),
            )
            return int(connection.execute("SELECT queue_id FROM ingestion_queue WHERE work_key=?", (work_key,)).fetchone()[0])

    def resume_expired_leases(self, lease_seconds: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(seconds=lease_seconds)).isoformat()
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE ingestion_queue SET state='pending', lease_timestamp=NULL, updated_at=?
                   WHERE state='processing' AND lease_timestamp < ?""",
                (utc_now(), cutoff),
            )
            return cursor.rowcount

    def lease_next(self) -> QueueItem | None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM ingestion_queue WHERE state='pending' ORDER BY queue_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """UPDATE ingestion_queue SET state='processing', attempt_count=attempt_count+1,
                   lease_timestamp=?, updated_at=? WHERE queue_id=?""",
                (utc_now(), utc_now(), row["queue_id"]),
            )
            return QueueItem(
                queue_id=row["queue_id"], work_key=row["work_key"], source=row["source"],
                requested_query=row["requested_query"], payload_json=row["payload_json"],
                attempt_count=row["attempt_count"] + 1,
            )

    def finish_queue(self, queue_id: int, state: str, error: str | None = None) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE ingestion_queue SET state=?, last_error=?, lease_timestamp=NULL, updated_at=? WHERE queue_id=?",
                (state, error, utc_now(), queue_id),
            )

    def append_ingestion_event(
        self, queue_id: int | None, work_key: str, source: str, outcome: str,
        paper_id: str | None, content_hash: str | None, detail: dict[str, Any],
    ) -> str:
        event_id = f"ing-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO ingestion_events(event_id, queue_id, work_key, source, outcome,
                   paper_id, content_hash, detail_json, occurred_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                (event_id, queue_id, work_key, source, outcome, paper_id, content_hash,
                 json.dumps(detail, sort_keys=True), utc_now()),
            )
        return event_id

    def upsert_paper(
        self, paper: PaperRecord, vector: bytes | None, embedding_model: str | None,
        embedding_revision: str | None, dimension: int | None,
    ) -> str:
        record_json = paper.model_dump_json()
        with self.transaction() as connection:
            existing = connection.execute("SELECT content_hash FROM papers WHERE paper_id=?", (paper.paper_id,)).fetchone()
            if existing and existing["content_hash"] == paper.content_hash:
                return "unchanged"
            outcome = "updated" if existing else "inserted"
            connection.execute(
                """INSERT INTO papers(paper_id,title,authors_json,venue,year,abstract,paper_url,license,
                   retracted,trust_tier,content_completeness,priority_areas_json,relevance_notes,keywords_json,
                   sanitizer_flags_json,quarantined,raw_content_hash,content_hash,retrieved_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(paper_id) DO UPDATE SET title=excluded.title,authors_json=excluded.authors_json,
                   venue=excluded.venue,year=excluded.year,abstract=excluded.abstract,paper_url=excluded.paper_url,
                   license=excluded.license,retracted=excluded.retracted,trust_tier=excluded.trust_tier,
                   content_completeness=excluded.content_completeness,priority_areas_json=excluded.priority_areas_json,
                   relevance_notes=excluded.relevance_notes,keywords_json=excluded.keywords_json,
                   sanitizer_flags_json=excluded.sanitizer_flags_json,quarantined=excluded.quarantined,
                   raw_content_hash=excluded.raw_content_hash,content_hash=excluded.content_hash,
                   retrieved_at=excluded.retrieved_at""",
                (paper.paper_id, paper.title, json.dumps(paper.authors), paper.venue, paper.year,
                 paper.abstract, paper.paper_url, paper.license, int(paper.retracted), paper.trust_tier,
                 paper.content_completeness, json.dumps(paper.priority_areas), paper.relevance_notes,
                 json.dumps(paper.keywords), json.dumps(paper.sanitizer_flags), int(paper.quarantined),
                 paper.content_hash, paper.content_hash, paper.retrieved_at),
            )
            cursor = connection.execute(
                "INSERT INTO paper_versions(paper_id,content_hash,record_json,created_at) VALUES(?,?,?,?)",
                (paper.paper_id, paper.content_hash, record_json, utc_now()),
            )
            connection.execute("UPDATE papers SET current_version_id=? WHERE paper_id=?", (cursor.lastrowid, paper.paper_id))
            connection.execute("DELETE FROM paper_identifiers WHERE paper_id=?", (paper.paper_id,))
            for kind, value in paper.identifiers.stable_values():
                connection.execute(
                    "INSERT INTO paper_identifiers(paper_id,kind,value) VALUES(?,?,?)",
                    (paper.paper_id, kind, value),
                )
            connection.execute("DELETE FROM code_implementations WHERE paper_id=?", (paper.paper_id,))
            for code in paper.code:
                connection.execute(
                    """INSERT INTO code_implementations(repository_url,pinned_commit,license,stars,topics_json,
                       paper_id,source_url,content_hash,retrieved_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (code.repository_url, code.pinned_commit, code.license, code.stars, json.dumps(code.topics),
                     paper.paper_id, code.source_url, code.content_hash, code.retrieved_at),
                )
            connection.execute("DELETE FROM paper_fts WHERE paper_id=?", (paper.paper_id,))
            connection.execute(
                "INSERT INTO paper_fts(paper_id,title,abstract,keywords,priority_areas,relevance_notes) VALUES(?,?,?,?,?,?)",
                (paper.paper_id, paper.title, paper.abstract or "", " ".join(paper.keywords),
                 " ".join(paper.priority_areas), paper.relevance_notes),
            )
            if vector is not None and embedding_model and embedding_revision and dimension:
                connection.execute(
                    """INSERT INTO paper_vectors(paper_id,embedding_model_id,embedding_revision,dimension,vector)
                       VALUES(?,?,?,?,?) ON CONFLICT(paper_id) DO UPDATE SET
                       embedding_model_id=excluded.embedding_model_id,embedding_revision=excluded.embedding_revision,
                       dimension=excluded.dimension,vector=excluded.vector""",
                    (paper.paper_id, embedding_model, embedding_revision, dimension, vector),
                )
            return outcome

    def _paper_from_row(self, row: sqlite3.Row, connection: sqlite3.Connection) -> PaperRecord:
        identifiers = {"doi": None, "arxiv_id": None, "openalex_id": None}
        for identifier in connection.execute("SELECT kind,value FROM paper_identifiers WHERE paper_id=?", (row["paper_id"],)):
            identifiers[identifier["kind"]] = identifier["value"]
        code = [CodeRecord(
            repository_url=item["repository_url"], pinned_commit=item["pinned_commit"], license=item["license"],
            stars=item["stars"], topics=json.loads(item["topics_json"]), paper_id=item["paper_id"],
            source_url=item["source_url"], retrieved_at=item["retrieved_at"], content_hash=item["content_hash"],
            verified=bool(item["pinned_commit"] and item["license"]),
        ) for item in connection.execute("SELECT * FROM code_implementations WHERE paper_id=?", (row["paper_id"],))]
        return PaperRecord(
            paper_id=row["paper_id"], title=row["title"], authors=json.loads(row["authors_json"]),
            year=row["year"], venue=row["venue"], abstract=row["abstract"],
            identifiers=PaperIdentifiers.model_validate(identifiers), paper_url=row["paper_url"], license=row["license"],
            retracted=bool(row["retracted"]), trust_tier=row["trust_tier"],
            content_completeness=row["content_completeness"], priority_areas=json.loads(row["priority_areas_json"]),
            relevance_notes=row["relevance_notes"], keywords=json.loads(row["keywords_json"]),
            sanitizer_flags=json.loads(row["sanitizer_flags_json"]), quarantined=bool(row["quarantined"]),
            content_hash=row["content_hash"], retrieved_at=row["retrieved_at"], code=code,
        )

    def get_paper(self, paper_id: str) -> PaperRecord | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM papers WHERE paper_id=?", (paper_id,)).fetchone()
            return self._paper_from_row(row, connection) if row else None

    def list_papers(self) -> list[PaperRecord]:
        with self.connect() as connection:
            return [self._paper_from_row(row, connection) for row in connection.execute("SELECT * FROM papers ORDER BY paper_id")]

    def search_fts(self, query: str, limit: int) -> list[tuple[str, float]]:
        # OR recall: cast a broad net. Precision (deciding whether a candidate is
        # actually relevant enough to count as a "local match") is enforced afterward
        # in RetrievalService._local_matches via a term-overlap-fraction filter, not
        # here — an AND-only query would reject genuinely relevant papers whose title
        # doesn't happen to contain every query word (e.g. filler words like "for").
        terms = [term for term in query.replace('"', " ").split() if term]
        if not terms:
            return []
        fts_query = " OR ".join(f'"{term}"' for term in terms[:20])
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT paper_id,bm25(paper_fts) AS score FROM paper_fts WHERE paper_fts MATCH ? ORDER BY score LIMIT ?",
                (fts_query, limit),
            ).fetchall()
            return [(row["paper_id"], float(row["score"])) for row in rows]

    def vector_rows(self) -> list[tuple[str, int, bytes]]:
        with self.connect() as connection:
            return [(row["paper_id"], row["dimension"], row["vector"]) for row in connection.execute("SELECT paper_id,dimension,vector FROM paper_vectors")]

    def put_cache(self, cache_key: str, provider: str, request: dict[str, Any], response: dict[str, Any], ttl_seconds: int) -> None:
        now = datetime.now(UTC)
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO query_cache(cache_key,provider,request_json,response_json,created_at,expires_at,hit_count)
                   VALUES(?,?,?,?,?,?,0) ON CONFLICT(cache_key) DO UPDATE SET provider=excluded.provider,
                   request_json=excluded.request_json,response_json=excluded.response_json,created_at=excluded.created_at,
                   expires_at=excluded.expires_at,hit_count=0""",
                (cache_key, provider, json.dumps(request, sort_keys=True), json.dumps(response, sort_keys=True),
                 now.isoformat(), (now + timedelta(seconds=ttl_seconds)).isoformat()),
            )

    def get_cache(self, cache_key: str) -> dict[str, Any] | None:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM query_cache WHERE cache_key=? AND expires_at>?", (cache_key, utc_now())).fetchone()
            if row is None:
                return None
            connection.execute("UPDATE query_cache SET hit_count=hit_count+1 WHERE cache_key=?", (cache_key,))
            return json.loads(row["response_json"])

    def add_citation(self, citation: CitationRecord) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO citation_edges(source_paper_id,target_paper_id,relation,provider) VALUES(?,?,?,?)",
                (citation.source_paper_id, citation.target_paper_id, citation.relation, citation.provider),
            )

    def citations(self, work_id: str, direction: str, limit: int) -> list[CitationRecord]:
        column = "source_paper_id" if direction == "cites" else "target_paper_id"
        with self.connect() as connection:
            return [CitationRecord.model_validate(dict(row)) for row in connection.execute(
                f"SELECT source_paper_id,target_paper_id,relation,provider FROM citation_edges WHERE {column}=? LIMIT ?",
                (work_id, limit),
            )]

    def code_search(self, query: str, language: str, min_stars: int, limit: int) -> list[CodeRecord]:
        pattern = f"%{query.casefold()}%"
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM code_implementations WHERE lower(repository_url) LIKE ?
                   AND COALESCE(stars,0)>=? ORDER BY COALESCE(stars,0) DESC, repository_url LIMIT ?""",
                (pattern, min_stars, limit),
            ).fetchall()
            return [CodeRecord(
                repository_url=row["repository_url"], pinned_commit=row["pinned_commit"], license=row["license"],
                stars=row["stars"], topics=json.loads(row["topics_json"]), paper_id=row["paper_id"],
                source_url=row["source_url"], retrieved_at=row["retrieved_at"], content_hash=row["content_hash"],
                verified=bool(row["pinned_commit"] and row["license"]),
            ) for row in rows]

    def record_usage(self, session_id: str, experiment_id: str, provider: str, request_id: str, **values: int) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO provider_usage(session_id,experiment_id,provider,request_id,outbound_requests,
                   documents_returned,response_characters,bytes_received,error_count,retry_count,occurred_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (session_id, experiment_id, provider, request_id, values.get("outbound_requests", 0),
                 values.get("documents_returned", 0), values.get("response_characters", 0),
                 values.get("bytes_received", 0), values.get("error_count", 0), values.get("retry_count", 0), utc_now()),
            )

    def usage_totals(self, session_id: str, experiment_id: str) -> dict[str, int]:
        with self.connect() as connection:
            session = connection.execute(
                """SELECT COALESCE(SUM(outbound_requests),0),COALESCE(SUM(documents_returned),0),
                   COALESCE(SUM(response_characters),0) FROM provider_usage WHERE session_id=?""", (session_id,)
            ).fetchone()
            experiment = connection.execute(
                """SELECT COALESCE(SUM(outbound_requests),0),COALESCE(SUM(documents_returned),0),
                   COALESCE(SUM(response_characters),0) FROM provider_usage WHERE session_id=? AND experiment_id=?""",
                (session_id, experiment_id),
            ).fetchone()
        return {
            "session_provider_requests": session[0], "session_documents": session[1],
            "session_response_characters": session[2], "experiment_provider_requests": experiment[0],
            "experiment_documents": experiment[1], "experiment_response_characters": experiment[2],
        }

    def request_usage(self, request_id: str) -> dict[str, int]:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COALESCE(SUM(outbound_requests),0),COALESCE(SUM(documents_returned),0),
                   COALESCE(SUM(response_characters),0) FROM provider_usage WHERE request_id=?""",
                (request_id,),
            ).fetchone()
        return {
            "provider_requests": row[0],
            "documents_returned": row[1],
            "response_characters": row[2],
        }

    def reindex_fts(self) -> int:
        with self.transaction() as connection:
            connection.execute("DELETE FROM paper_fts")
            rows = connection.execute("SELECT * FROM papers").fetchall()
            for row in rows:
                connection.execute(
                    "INSERT INTO paper_fts(paper_id,title,abstract,keywords,priority_areas,relevance_notes) VALUES(?,?,?,?,?,?)",
                    (row["paper_id"], row["title"], row["abstract"] or "", " ".join(json.loads(row["keywords_json"])),
                     " ".join(json.loads(row["priority_areas_json"])), row["relevance_notes"]),
                )
            return len(rows)
