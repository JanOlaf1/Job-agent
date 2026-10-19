import pytest
from src.tracker import canonicalize_url, load_tracker, merge_jobs, primary_url, save_tracker


def job(**kwargs):
    return dict(title="Account Manager", company="Example", location="Helsinki", score=44,
                sources="LinkedIn", urls="https://example.org/jobs/1", **kwargs)


def test_new_once_and_user_fields_survive(tmp_path):
    tracker = {}
    assert merge_jobs(tracker, [job()])["new_count"] == 1
    row = next(iter(tracker.values()))
    row.update(status="HAETTU", applied_date="2026-09-10", notes="Haastattelu", custom="keep")
    path = tmp_path / "tracker.csv"
    save_tracker(path, tracker)
    tracker = load_tracker(path)
    again = dict(job(), urls="https://example.org/jobs/1?utm_source=abc", score=0)
    assert merge_jobs(tracker, [again])["new_count"] == 0
    save_tracker(path, tracker)
    saved = next(iter(load_tracker(path).values()))
    assert (saved["status"], saved["notes"], saved["applied_date"], saved["custom"], saved["score"]) == ("HAETTU", "Haastattelu", "2026-09-10", "keep", "0")
    assert path.with_suffix(".csv.bak").exists()


def test_duplicate_url_and_source_id_and_distinct_openings():
    tracker = {}
    a = job(source_ids="LinkedIn:123")
    b = dict(a, urls="https://example.org/new-slug", title="Updated title")
    assert merge_jobs(tracker, [a, b])["new_count"] == 1
    assert len(tracker) == 1
    c = dict(a, urls="https://example.org/different", source_ids="LinkedIn:124")
    assert merge_jobs(tracker, [c])["new_count"] == 1


def test_cross_source_preserves_all_links_and_archive_identity():
    tracker = {}
    merge_jobs(tracker, [job(), dict(job(), sources="Other", urls="https://other.org/job/1")])
    assert len(tracker) == 1
    assert "https://other.org/job/1" in next(iter(tracker.values()))["urls"]
    assert merge_jobs({}, [job()], archive=tracker)["new_count"] == 0


def test_identity_parameters_preserved():
    assert canonicalize_url("https://example.org/job?id=2&utm_source=test") == "https://example.org/job?id=2"
    assert canonicalize_url("https://www.linkedin.com/jobs/view/title-123?trk=x") == "https://fi.linkedin.com/jobs/view/123"
    assert primary_url({"urls": "https://fi.linkedin.com/jobs/view/123 || https://employer.org/jobs/123"}) == "https://employer.org/jobs/123"


def test_malformed_tracker_cannot_be_overwritten(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("not,a,tracker\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_tracker(path)
