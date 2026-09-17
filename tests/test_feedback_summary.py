from backend.database import create_feedback, feedback_summary, upsert_job
from uuid import uuid4


def test_feedback_summary_groups_by_site():
    site = f"test-site-{uuid4().hex}"
    job_id = upsert_job({
        "site": site,
        "job_id": "feedback-summary-job",
        "title": "Python Engineer",
        "company": "Test Co",
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
    create_feedback(job_id, "useful")
    create_feedback(job_id, "not_useful")

    summary = feedback_summary()
    assert summary["overall"]["total"] >= 2
    site_summary = next(item for item in summary["by_site"] if item["site"] == site)
    assert site_summary["total"] == 2
    assert site_summary["useful_rate"] == 50