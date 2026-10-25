"""
SQLite database for job tracking and translation history in Online Subtitle Translator.
"""

from __future__ import annotations
import contextlib
import json
import sqlite3
import time
from pathlib import Path
from typing import List, Optional, Dict, Any
from app.core.config import DATABASE_FILE
from app.core.types import JobStatus


class Database:
    """Thread-safe SQLite storage for translation jobs and history."""

    def __init__(self, db_path: Path | str = DATABASE_FILE):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with contextlib.closing(self._get_connection()) as conn:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS jobs (
                        id TEXT PRIMARY KEY,
                        video_path TEXT NOT NULL,
                        pipeline TEXT NOT NULL,
                        status TEXT NOT NULL,
                        start_seconds REAL NOT NULL,
                        end_seconds REAL NOT NULL,
                        translation_provider TEXT,
                        translation_model TEXT,
                        output_srt_path TEXT,
                        translated_srt_path TEXT,
                        error_message TEXT,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    )
                """)

    def create_job(
        self,
        job_id: str,
        video_path: str,
        pipeline: str,
        start_seconds: float = 0.0,
        end_seconds: float = 0.0,
        translation_provider: str = "",
        translation_model: str = "",
        output_srt_path: str = ""
    ) -> None:
        now = time.time()
        with contextlib.closing(self._get_connection()) as conn:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO jobs (
                        id, video_path, pipeline, status, start_seconds, end_seconds,
                        translation_provider, translation_model, output_srt_path,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job_id, video_path, pipeline, JobStatus.PENDING.value,
                    start_seconds, end_seconds, translation_provider,
                    translation_model, output_srt_path, now, now
                ))

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: Optional[str] = None,
        translated_srt_path: Optional[str] = None
    ) -> None:
        now = time.time()
        with contextlib.closing(self._get_connection()) as conn:
            with conn:
                updates = ["status = ?", "updated_at = ?"]
                params: List[Any] = [status.value, now]

                if error_message is not None:
                    updates.append("error_message = ?")
                    params.append(error_message)
                if translated_srt_path is not None:
                    updates.append("translated_srt_path = ?")
                    params.append(translated_srt_path)

                params.append(job_id)
                conn.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?", params)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with contextlib.closing(self._get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with contextlib.closing(self._get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def delete_job(self, job_id: str) -> None:
        with contextlib.closing(self._get_connection()) as conn:
            with conn:
                conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
