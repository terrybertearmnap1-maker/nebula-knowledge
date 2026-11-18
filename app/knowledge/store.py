"""SQLite-backed, team-scoped document store and lexical search index."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from app.config import Settings
from app.knowledge.errors import (
    DocumentNotFound,
    DocumentParseError,
    DuplicateDocument,
    TeamNotFound,
)
from app.knowledge.models import DocumentRecord, SearchHit, StoredChunk, TeamRecord
from app.knowledge.parsing import (
    build_chunks,
    detect_extension,
    parse_document,
    sanitize_filename,
)
from app.knowledge.retrieval import bm25_search, tokenize

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_TEAM_ID = "default"
DEFAULT_TEAM_NAME = "默认团队"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class KnowledgeBase:
    """Stores documents and chunks per team, and retrieves citable passages."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        data_dir = Path(settings.data_dir)
        if not data_dir.is_absolute():
            data_dir = PROJECT_ROOT / data_dir
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir = self.data_dir / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "team_kb.sqlite3"
        self._init_db()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._db() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS teams (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    page_count INTEGER,
                    chunk_count INTEGER NOT NULL,
                    stored_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(team_id, sha256)
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    page INTEGER,
                    heading TEXT,
                    content TEXT NOT NULL,
                    tokens TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_documents_team ON documents(team_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_team ON chunks(team_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO teams (id, name, created_at) VALUES (?, ?, ?)",
                (DEFAULT_TEAM_ID, DEFAULT_TEAM_NAME, _now()),
            )
            connection.commit()

    # ------------------------------------------------------------------ teams

    def create_team(self, name: str) -> TeamRecord:
        team_id = uuid4().hex
        created_at = _now()
        with self._db() as connection:
            connection.execute(
                "INSERT INTO teams (id, name, created_at) VALUES (?, ?, ?)",
                (team_id, name, created_at),
            )
            connection.commit()
        return TeamRecord(id=team_id, name=name, created_at=created_at)

    def list_teams(self) -> list[TeamRecord]:
        with self._db() as connection:
            rows = connection.execute(
                """
                SELECT t.id, t.name, t.created_at,
                       (SELECT COUNT(*) FROM documents d WHERE d.team_id = t.id) AS document_count
                FROM teams t
                ORDER BY CASE WHEN t.id = ? THEN 0 ELSE 1 END, t.created_at, t.name
                """,
                (DEFAULT_TEAM_ID,),
            ).fetchall()
        return [self._to_team(row) for row in rows]

    def get_team(self, team_id: str) -> TeamRecord | None:
        with self._db() as connection:
            row = connection.execute(
                """
                SELECT t.id, t.name, t.created_at,
                       (SELECT COUNT(*) FROM documents d WHERE d.team_id = t.id) AS document_count
                FROM teams t WHERE t.id = ?
                """,
                (team_id,),
            ).fetchone()
        return self._to_team(row) if row else None

    def require_team(self, team_id: str) -> TeamRecord:
        team = self.get_team(team_id)
        if team is None:
            raise TeamNotFound(f"team not found: {team_id}")
        return team

    @staticmethod
    def _to_team(row: sqlite3.Row) -> TeamRecord:
        return TeamRecord(
            id=row["id"],
            name=row["name"],
            created_at=row["created_at"],
            document_count=int(row["document_count"]),
        )

    # -------------------------------------------------------------- documents

    def add_document(
        self,
        team_id: str,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> DocumentRecord:
        self.require_team(team_id)
        filename = sanitize_filename(filename)
        suffix = detect_extension(filename)
        digest = hashlib.sha256(data).hexdigest()

        with self._db() as connection:
            existing = connection.execute(
                "SELECT id FROM documents WHERE team_id = ? AND sha256 = ?",
                (team_id, digest),
            ).fetchone()
        if existing:
            raise DuplicateDocument(existing["id"])

        try:
            parsed = parse_document(filename, data)
            chunks = build_chunks(
                parsed,
                chunk_size=self.settings.chunk_size,
                overlap=self.settings.chunk_overlap,
            )
        except DocumentParseError:
            raise

        document_id = uuid4().hex
        created_at = _now()
        team_upload_dir = self.upload_dir / team_id
        team_upload_dir.mkdir(parents=True, exist_ok=True)
        stored_path = team_upload_dir / f"{document_id}{suffix}"
        stored_path.write_bytes(data)

        try:
            with self._db() as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO documents
                            (id, team_id, filename, content_type, size_bytes, sha256,
                             page_count, chunk_count, stored_path, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document_id,
                            team_id,
                            filename,
                            content_type or "application/octet-stream",
                            len(data),
                            digest,
                            parsed.page_count,
                            len(chunks),
                            str(stored_path),
                            created_at,
                        ),
                    )
                    for chunk in chunks:
                        counts = Counter(tokenize(chunk.content))
                        connection.execute(
                            """
                            INSERT INTO chunks
                                (id, document_id, team_id, chunk_index, page, heading,
                                 content, tokens, token_count, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                f"{document_id}-{chunk.index:04d}",
                                document_id,
                                team_id,
                                chunk.index,
                                chunk.page,
                                chunk.heading,
                                chunk.content,
                                json.dumps(dict(counts), ensure_ascii=False),
                                sum(counts.values()),
                                created_at,
                            ),
                        )
        except sqlite3.IntegrityError as exc:
            stored_path.unlink(missing_ok=True)
            with self._db() as connection:
                row = connection.execute(
                    "SELECT id FROM documents WHERE team_id = ? AND sha256 = ?",
                    (team_id, digest),
                ).fetchone()
            raise DuplicateDocument(row["id"] if row else "unknown") from exc
        except Exception:
            stored_path.unlink(missing_ok=True)
            raise

        return DocumentRecord(
            id=document_id,
            team_id=team_id,
            filename=filename,
            content_type=content_type or "application/octet-stream",
            size_bytes=len(data),
            page_count=parsed.page_count,
            chunk_count=len(chunks),
            created_at=created_at,
            stored_path=str(stored_path),
        )

    def list_documents(self, team_id: str) -> list[DocumentRecord]:
        self.require_team(team_id)
        with self._db() as connection:
            rows = connection.execute(
                """
                SELECT id, team_id, filename, content_type, size_bytes, page_count,
                       chunk_count, created_at, stored_path
                FROM documents WHERE team_id = ?
                ORDER BY created_at DESC, filename
                """,
                (team_id,),
            ).fetchall()
        return [self._to_document(row) for row in rows]

    def get_document(self, team_id: str, document_id: str) -> DocumentRecord:
        with self._db() as connection:
            row = connection.execute(
                """
                SELECT id, team_id, filename, content_type, size_bytes, page_count,
                       chunk_count, created_at, stored_path
                FROM documents WHERE id = ? AND team_id = ?
                """,
                (document_id, team_id),
            ).fetchone()
        if row is None:
            raise DocumentNotFound(f"document not found: {document_id}")
        return self._to_document(row)

    def delete_document(self, team_id: str, document_id: str) -> None:
        document = self.get_document(team_id, document_id)
        with self._db() as connection:
            with connection:
                connection.execute(
                    "DELETE FROM documents WHERE id = ? AND team_id = ?",
                    (document_id, team_id),
                )
        Path(document.stored_path).unlink(missing_ok=True)

    @staticmethod
    def _to_document(row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            id=row["id"],
            team_id=row["team_id"],
            filename=row["filename"],
            content_type=row["content_type"],
            size_bytes=int(row["size_bytes"]),
            page_count=row["page_count"],
            chunk_count=int(row["chunk_count"]),
            created_at=row["created_at"],
            stored_path=row["stored_path"],
        )

    # --------------------------------------------------------------- retrieval

    def search(self, team_id: str, query: str, top_k: int | None = None) -> list[SearchHit]:
        self.require_team(team_id)
        with self._db() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.document_id, c.chunk_index, c.page, c.heading,
                       c.content, c.tokens, c.token_count, d.filename
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.team_id = ?
                """,
                (team_id,),
            ).fetchall()

        chunks: list[StoredChunk] = []
        for row in rows:
            try:
                tokens = json.loads(row["tokens"])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(tokens, dict):
                continue
            chunks.append(
                StoredChunk(
                    id=row["id"],
                    document_id=row["document_id"],
                    filename=row["filename"],
                    chunk_index=int(row["chunk_index"]),
                    page=row["page"],
                    heading=row["heading"],
                    content=row["content"],
                    tokens={str(key): int(value) for key, value in tokens.items()},
                    token_count=int(row["token_count"]),
                )
            )

        return bm25_search(
            chunks,
            query,
            top_k=top_k or self.settings.retrieval_top_k,
        )

    def stats(self, team_id: str) -> tuple[int, int]:
        self.require_team(team_id)
        with self._db() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM documents WHERE team_id = ?) AS documents,
                    (SELECT COUNT(*) FROM chunks WHERE team_id = ?) AS chunks
                """,
                (team_id, team_id),
            ).fetchone()
        return int(row["documents"]), int(row["chunks"])
