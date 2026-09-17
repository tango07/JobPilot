from backend.database import create_feedback, list_feedback


def test_feedback_round_trip():
    entry = create_feedback(job_id=1, sentiment="useful", comment="Strong skills overlap")

    assert entry["job_id"] == 1
    assert entry["sentiment"] == "useful"
    assert entry["comment"] == "Strong skills overlap"

    feedback = list_feedback(job_id=1)
    assert any(item["job_id"] == 1 and item["sentiment"] == "useful" for item in feedback)
