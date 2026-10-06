from backend.database import (
    activate_profile,
    create_application,
    create_feedback,
    create_profile,
    create_reminder,
    create_saved_search,
    cleanup_old_jobs,
    get_applications,
    get_custom_sites,
    get_jobs,
    list_feedback,
    list_reminders,
    list_saved_searches,
    upsert_custom_site,
    upsert_job,
)
from datetime import timedelta
from backend.database import _utcnow, get_conn


def _job(site, external_id):
    return upsert_job({
        "site": site,
        "job_id": external_id,
        "title": "Python Engineer",
        "company": "Example Co",
        "location": "Remote",
        "job_type": "full-time",
        "salary": "",
        "description": "Python role",
        "url": "https://example.com/job",
        "apply_url": "https://example.com/apply",
        "easy_apply": 0,
        "date_posted": "",
        "status": "new",
    })


def test_profile_owned_records_are_isolated():
    first_job = _job("linkedin", "same-external-job")
    create_application(first_job, "linkedin", "Python Engineer", "Example Co")
    create_saved_search("First", "python")
    create_reminder(first_job, "follow_up", "2026-10-01T09:00:00")
    create_feedback(first_job, "useful")
    upsert_custom_site("first-site", "First Site", "https://one.example", "https://one.example?q={keywords}", "#000", "#fff", "FS")

    second = create_profile("Second")
    activate_profile(second["id"])

    assert get_jobs() == []
    assert get_applications() == []
    assert list_saved_searches() == []
    assert list_reminders() == []
    assert list_feedback() == []
    assert get_custom_sites() == []

    second_job = _job("linkedin", "same-external-job")
    assert second_job != first_job


def test_cleanup_preserves_reviewed_pipeline_records():
    stale_new = _job("indeed", "stale-new")
    stale_applied = _job("indeed", "stale-applied")
    with get_conn() as conn:
        old = (_utcnow() - timedelta(days=20)).isoformat()
        conn.execute("UPDATE jobs SET date_found=?, status='new' WHERE id=?", (old, stale_new))
        conn.execute("UPDATE jobs SET date_found=?, status='applied' WHERE id=?", (old, stale_applied))

    assert cleanup_old_jobs(days=10) == 1
    assert [job["id"] for job in get_jobs()] == [stale_applied]
