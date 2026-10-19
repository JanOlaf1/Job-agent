import json
from unittest.mock import MagicMock
import pytest
from src.job_search import listing_pages, parse_job_details, parse_search_page, run_status, search_jobs
from src.scoring import score_job

SOURCE = dict(name="Example", url="https://example.org/search", marker="/jobs/")


def test_unknown_location_and_unlisted_title_survive_enrichment():
    cards = '<article><h2>Customer Solutions Specialist</h2><a href="/jobs/1">Apply</a></article>'
    candidates = parse_search_page(cards, SOURCE)
    assert len(candidates) == 1
    posting = {"@type": "JobPosting", "title": "Customer Solutions Specialist",
               "description": "SaaS implementation B2B sales", "hiringOrganization": {"name": "Real Employer"},
               "jobLocation": {"address": {"addressLocality": "Helsinki"}}, "identifier": {"value": "123"}}
    html = '<script type="application/ld+json">' + json.dumps(posting) + '</script><footer>Senior nurse driver jobs</footer>'
    job = score_job(parse_job_details(html, candidates[0]))
    assert job["classification"] == "STRONG"
    assert job["company"] == "Real Employer"
    assert job["source_ids"] == "Example:123"
    assert job["url"] == "https://example.org/jobs/1"


def test_blocked_source_is_not_empty(monkeypatch):
    monkeypatch.setattr("src.job_search.robots_allowed", lambda *args: None)
    session = MagicMock()
    session.get.return_value.status_code = 403
    jobs, health = search_jobs([SOURCE, SOURCE], session)
    assert not jobs
    assert health["Example"]["status"] == "BLOCKED"
    assert session.get.call_count == 1
    assert run_status(health) == "FAILED"


def test_empty_is_distinct_from_unreadable():
    assert parse_search_page("No jobs found", SOURCE) == []
    with pytest.raises(ValueError):
        parse_search_page('<div id="app"></div>', SOURCE)


@pytest.mark.parametrize("text", ["20 jobs", "100 jobs", "20 työpaikkaa"])
def test_unreadable_nonzero_results_are_not_reported_as_empty(text):
    with pytest.raises(ValueError):
        parse_search_page(f'<h1>{text}</h1><div id="app"></div>', SOURCE)


def test_blocked_detail_retains_candidate_but_is_not_healthy(monkeypatch):
    monkeypatch.setattr("src.job_search.robots_allowed", lambda *args: None)
    session = MagicMock()
    card = MagicMock(status_code=200, text='<article><a href="/jobs/1">Account Manager</a></article>')
    denied = MagicMock(status_code=403)
    session.get.side_effect = [card, denied]
    jobs, health = search_jobs([SOURCE], session)
    assert len(jobs) == 1
    assert jobs[0]["detail_status"] == "BLOCKED"
    assert health["Example"]["status"] == "PARTIAL"
    assert run_status(health) == "FAILED"


def test_html_pagination_follows_next_without_guessing_parameters(monkeypatch):
    monkeypatch.setattr("src.job_search.robots_allowed", lambda *args: None)
    session = MagicMock()
    session.get.side_effect = [
        MagicMock(status_code=200, text='<a href="?page=1" rel="next">Next</a>'),
        MagicMock(status_code=200, text='<p>Last page</p>'),
    ]
    pages = list(listing_pages(session, dict(SOURCE, max_pages=5), {}))
    assert len(pages) == 2
    assert session.get.call_args_list[1].args[0] == "https://example.org/search?page=1"


def test_html_page_limit_keeps_found_jobs_and_marks_partial(monkeypatch):
    monkeypatch.setattr("src.job_search.robots_allowed", lambda *args: None)
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=200,
        text='<article><a href="/jobs/1">Account Manager</a></article><a rel="next" href="?page=1">Next</a>')
    jobs, health = search_jobs([dict(SOURCE, max_pages=1)], session, max_details=0)
    assert len(jobs) == 1
    assert health["Example"]["status"] == "PARTIAL"
    assert health["Example"]["failed"] == 1


@pytest.mark.parametrize("href", ["https://other.example/search?page=2", "/login", "?page=0"])
def test_bad_or_circular_pagination_is_detected(monkeypatch, href):
    monkeypatch.setattr("src.job_search.robots_allowed", lambda *args: None)
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=200, text=f'<a rel="next" href="{href}">Next</a>')
    with pytest.raises(ValueError, match="pagination|page limit"):
        list(listing_pages(session, dict(SOURCE, max_pages=3), {}))
