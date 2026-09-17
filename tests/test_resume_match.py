import backend.ai as ai


def test_score_job_fit_uses_resume_and_skill_overlap(monkeypatch):
    monkeypatch.setattr(ai, "is_ai_ready", lambda: False)
    profile = {
        "current_title": "Senior Python Engineer",
        "desired_title": "Python Engineer",
        "years_experience": 5,
        "skills": ["python", "fastapi", "postgres", "docker", "redis"],
        "summary": "Senior software engineer focused on backend systems, APIs, and cloud deployment.",
    }
    result = ai.score_job_fit(
        "Python Engineer",
        "Build APIs with Python, FastAPI, PostgreSQL, Redis, and Docker. Need backend engineering experience and deployment work.",
        profile,
    )

    assert isinstance(result["score"], int)
    assert 0 <= result["score"] <= 100
    assert result["score"] >= 60
    assert "python" in " ".join(result["reasons"]).lower()


def test_score_jobs_fit_returns_results_for_each_job(monkeypatch):
    monkeypatch.setattr(ai, "is_ai_ready", lambda: False)
    profile = {"skills": ["python", "fastapi"], "desired_title": "Python Engineer"}
    jobs = [
        {"id": 11, "title": "Python Engineer", "description": "Python and FastAPI"},
        {"id": 12, "title": "Frontend Engineer", "description": "JavaScript and CSS"},
    ]

    results = ai.score_jobs_fit(jobs, profile)

    assert [item["id"] for item in results] == [11, 12]
    assert all(isinstance(item["score"], int) for item in results)
