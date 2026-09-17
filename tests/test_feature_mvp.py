from backend.database import (
    create_saved_search,
    list_saved_searches,
    create_reminder,
    list_reminders,
    mark_reminder_done,
)


def test_saved_searches_and_reminders_round_trip():
    search = create_saved_search(
        name="Python Remote",
        keywords="python engineer",
        location="Remote",
        sites=["linkedin", "indeed"],
        filters={"remote": True},
    )
    assert search["name"] == "Python Remote"
    assert search["keywords"] == "python engineer"
    assert search["location"] == "Remote"

    saved = list_saved_searches()
    assert any(item["name"] == "Python Remote" for item in saved)

    reminder = create_reminder(
        job_id=1,
        reminder_type="follow_up",
        due_at="2026-09-20T12:00:00",
        note="Follow up with recruiter",
    )
    assert reminder["type"] == "follow_up"
    assert reminder["note"] == "Follow up with recruiter"

    pending = list_reminders(status="pending")
    assert any(item["job_id"] == 1 for item in pending)

    done = mark_reminder_done(reminder["id"])
    assert done["done"] is True

    done_list = list_reminders(status="done")
    assert any(item["id"] == reminder["id"] for item in done_list)
