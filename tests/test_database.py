"""
Tests for SQLite translation job tracking and status persistence.
"""

from app.core.database import Database
from app.core.types import JobStatus


def test_translation_job_lifecycle(temp_database):
    db = temp_database
    job_id = "trans_job_123"

    db.create_job(
        job_id=job_id,
        video_path="C:/videos/sample.en.srt",
        pipeline="TRANSLATION",
        start_seconds=1.0,
        end_seconds=120.0,
        translation_provider="cloudflare",
        translation_model="@cf/meta/llama-3.1-8b-instruct",
        output_srt_path="C:/videos/sample.fa.srt"
    )

    job = db.get_job(job_id)
    assert job is not None
    assert job["id"] == job_id
    assert job["status"] == JobStatus.PENDING.value
    assert job["translation_provider"] == "cloudflare"

    # Update to TRANSLATING
    db.update_job_status(job_id, JobStatus.TRANSLATING)
    assert db.get_job(job_id)["status"] == JobStatus.TRANSLATING.value

    # Update to COMPLETED
    db.update_job_status(job_id, JobStatus.COMPLETED, translated_srt_path="C:/videos/sample.fa.srt")
    completed_job = db.get_job(job_id)
    assert completed_job["status"] == JobStatus.COMPLETED.value
    assert completed_job["translated_srt_path"] == "C:/videos/sample.fa.srt"


def test_job_failure_and_cancellation(temp_database):
    db = temp_database

    # Failure tracking
    fail_id = "fail_job_456"
    db.create_job(fail_id, "test.srt", "TRANSLATION")
    db.update_job_status(fail_id, JobStatus.FAILED, error_message="Rate limit quota exceeded")
    failed_job = db.get_job(fail_id)
    assert failed_job["status"] == JobStatus.FAILED.value
    assert "quota exceeded" in failed_job["error_message"]

    # Cancelled tracking
    cancel_id = "cancel_job_789"
    db.create_job(cancel_id, "test.srt", "TRANSLATION")
    db.update_job_status(cancel_id, JobStatus.CANCELLED, error_message="Cancelled by user.")
    cancelled_job = db.get_job(cancel_id)
    assert cancelled_job["status"] == JobStatus.CANCELLED.value

    # Deletion
    db.delete_job(fail_id)
    assert db.get_job(fail_id) is None
