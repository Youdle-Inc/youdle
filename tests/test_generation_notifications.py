"""No-cost verification of real article counts and honest failure alerts."""
from scripts.notify_post_generation_status import generation_notice


def test_success_email_uses_saved_rows_and_actual_photo_count():
    job = {"status": "completed", "result": {"posts_generated": 2}}
    rows = [
        {"category": "SHOPPERS", "image_url": ""},
        {"category": "RECALL", "image_url": "https://example.com/official.jpg"},
    ]
    subject, body = generation_notice(job, rows)
    assert "2 saved drafts" in subject
    assert "1 shopper" in body and "1 recall" in body
    assert "1</strong> without photos" in body


def test_prevent_fake_success_when_job_count_differs_from_saved_rows():
    subject, body = generation_notice(
        {"status": "completed", "result": {"posts_generated": 7}},
        [{"category": "SHOPPERS", "image_url": ""}],
    )
    assert "mismatch" in subject
    assert "database has 1" in body


def test_no_default_success_when_job_record_missing():
    subject, _ = generation_notice(None, [])
    assert "could not be verified" in subject
    assert "generated successfully" not in subject.lower()


def test_failed_generation_does_not_claim_success_or_expose_raw_error():
    subject, body = generation_notice(
        {"status": "failed", "error": "model_unavailable secret-should-not-email"}, []
    )
    assert "failed" in subject
    assert "Gemini image model unavailable" in body
    assert "secret-should-not-email" not in body


def test_invalid_count_is_reported_as_mismatch():
    subject, body = generation_notice(
        {"status": "completed", "result": {"posts_generated": "not-a-number"}},
        [{"category": "SHOPPERS", "image_url": ""}],
    )
    assert "mismatch" in subject
    assert "not-a-number" in body
