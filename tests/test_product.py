import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup
from src.config import digest_settings
from src.job_search import parse_job_details, parse_search_page, search_jobs
from src.main import run, deliver_pending
from src.scoring import score_job, market_observations
from src.send_email import build_email
from src.tracker import canonicalize_url, load_tracker, merge_jobs, select_digest

FIXTURE = Path(__file__).parent / "fixtures" / "run.json"


@pytest.mark.parametrize("url", ["javascript:void(0)", "https://[bad", "https://host:bad/a", "https://user:secret@host/job", "https://host/hello world"])
def test_invalid_urls_are_rejected(url):
    assert canonicalize_url(url) == ""


def test_canonical_and_redirect_identity_survive():
    candidate = dict(title="Developer", url="https://board.example/jobs/old", sources="Board")
    data = {"@type": "JobPosting", "description": "Python", "url": "/jobs/42?utm_source=x"}
    html = '<link rel="canonical" href="/jobs/new?id=42&utm_source=x"><script type="application/ld+json">' + json.dumps(data) + '</script>'
    row = parse_job_details(html, candidate, "https://employer.example/jobs/new?id=42")
    assert row["canonical_url"] == "https://employer.example/jobs/new?id=42"
    assert row["source_url"] == candidate["url"]
    assert candidate["url"] in row["urls"]
    assert row["link_status"] == "VERIFIED_GET"
    assert merge_jobs({}, [dict(row, score=70), dict(row, score=70, sources="Employer")])["new_count"] == 1


def test_search_redirect_is_not_a_working_posting():
    with pytest.raises(ValueError, match="redirected"):
        parse_job_details('<div class="job-description">Apply</div>', dict(url="https://example.org/jobs/1", title="Job"), "https://example.org/jobs")


def test_relative_url_and_javascript_placeholder():
    source = dict(url="https://example.org/search", name="Example", marker="/jobs/")
    cards = parse_search_page('<a href="/jobs/42?utm_source=x">Account Manager</a><a href="javascript:void(0)">Other</a>', source)
    assert [c["url"] for c in cards] == ["https://example.org/jobs/42"]


def test_html_is_escaped_clickable_and_has_plain_fallback():
    result = merge_jobs({}, [dict(title='<script>alert(1)</script>', company='A&B', location='Helsinki', score=70,
                                  urls='https://example.org/jobs/1?id=2&lang=fi')])
    result.update(status="SUCCESS", sources={}, run_time="2026-09-25", new_studies=[])
    message = build_email(result)
    html = message.get_body(preferencelist=("html",)).get_content()
    soup = BeautifulSoup(html, "html.parser")
    assert not soup.find("script")
    assert soup.find("a")["href"] == 'https://example.org/jobs/1?id=2&lang=fi'
    assert "Katso työpaikka" in soup.get_text()
    assert 'https://example.org/jobs/1' in message.get_body(preferencelist=("plain",)).get_content()


def test_retail_is_not_saved_as_a_recommendation():
    row = score_job(dict(title="Myyjiä eri osastoille K-Citymarket Porvoo Jokiranta", location="Porvoo", description="Sales, customer service and technology"))
    assert row["classification"] == "REJECTED"


def test_skill_observations_are_counts_not_invented_requirements():
    jobs = [score_job(dict(title="Junior Software Developer", location="Helsinki", description="Python Azure Azure")) for _ in range(2)]
    assert "Azure" in jobs[0]["skill_gaps"]
    assert any("Azure mainittiin 2" in line for line in market_observations(jobs, 60))
    assert market_observations(jobs[:1], 60) == []


def test_threshold_and_old_history_and_broken_links(monkeypatch):
    monkeypatch.setenv("MIN_RELEVANCE_SCORE", "60")
    tracker = {}
    result = merge_jobs(tracker, [dict(title=f"Job {i}", score=score, urls=f"https://example.org/jobs/{i}") for i, score in enumerate([44, 70, 80])])
    rows = list(tracker.values())
    rows[1].pop("notification_status")  # Legacy history must stay quiet.
    rows[2]["link_status"] = "BROKEN"
    select_digest(result, tracker, {}, digest_settings())
    assert result["new_jobs"] == []


def test_prepare_does_not_send_and_delivery_prevents_repeat(tmp_path, monkeypatch):
    for key in ("SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"):
        monkeypatch.setenv(key, "test")
    sent = []
    monkeypatch.setattr("src.main.send_email", sent.append)
    run(tmp_path, tmp_path / "reports", fixture=FIXTURE, commit=True, prepare=True)
    assert not sent
    assert (tmp_path / "pending_email.json").exists()
    deliver_pending(tmp_path)
    assert len(sent) == 1
    assert sent[0]["Message-ID"]
    assert not (tmp_path / "pending_email.json").exists()
    result = run(tmp_path, tmp_path / "reports", fixture=FIXTURE, commit=True, prepare=True)
    assert result["new_jobs"] == []
    assert not (tmp_path / "pending_email.json").exists()
    deliver_pending(tmp_path)
    assert len(sent) == 1


def test_broken_source_does_not_hide_working_source(monkeypatch):
    monkeypatch.setattr("src.job_search.robots_allowed", lambda *args: None)
    session = MagicMock()
    import requests
    failed = MagicMock(status_code=500)
    failed.raise_for_status.side_effect = requests.HTTPError("500")
    card = MagicMock(status_code=200, text='<a href="/jobs/1">Account Manager</a>')
    detail = MagicMock(status_code=200, text='<div class="job-description">B2B sales</div>', url='https://ok.example/jobs/1')
    session.get.side_effect = [failed, card, detail]
    jobs, health = search_jobs([dict(name=n, url=f'https://{n}.example/search', marker='/jobs/') for n in ['bad','ok']], session)
    assert health['bad']['status'] == 'FAILED'
    assert health['ok']['status'] == 'HEALTHY'
    assert len(jobs) == 1


@pytest.mark.parametrize("key,value", [("MIN_RELEVANCE_SCORE", "101"), ("MIN_RELEVANCE_SCORE", "bad"), ("SEND_EMPTY_DIGEST", "maybe")])
def test_invalid_digest_settings_fail_clearly(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=key):
        digest_settings()


def test_academic_work_visible_sections_do_not_include_recommendations():
    html = '''<h1>Junior Python Developer</h1><div><label>Sijainti:</label><p>Helsinki</p></div>
    <div><h2>Tehtävänkuvaus</h2><p>Python API development</p></div>
    <div><h2>Etsimme</h2><p>Graduate, React</p></div>
    <footer>Senior nurse driver</footer>'''
    row = parse_job_details(html, dict(title="old", url="https://www.academicwork.fi/avoimet-tyopaikat/j/dev/123", sources="Academic Work"))
    assert row["location"] == "Helsinki"
    assert "nurse" not in row["description"]
    assert row["detail_status"] == "HEALTHY"


def test_closed_and_unread_training_does_not_enter_email():
    studies = {str(i): dict(study_id=str(i), title="Python", score=90, notification_status="pending",
                           urls=f"https://example.org/study/{i}", **extra)
               for i, extra in enumerate([dict(application_status="OPEN"),
                   dict(application_status="CLOSED", detail_checked="2026-09-25"),
                   dict(application_status="OPEN", detail_checked="2026-09-25")])}
    result = {}
    select_digest(result, {}, studies, digest_settings())
    assert [r["study_id"] for r in result["new_studies"]] == ["2"]


def test_training_failure_keeps_job_results(tmp_path, monkeypatch):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    monkeypatch.setattr("src.main.search_jobs", lambda **kw: (payload["jobs"], payload["sources"]))
    def fail(**kw):
        raise TypeError("Unexpected upstream schema")
    monkeypatch.setattr("src.main.search_studies", fail)
    result = run(tmp_path, tmp_path / "reports")
    assert len(result["new_jobs"]) == 3
    assert result["sources"]["Opintopolku"]["status"] == "FAILED"


def test_no_title_or_url_is_skipped(tmp_path, monkeypatch):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["jobs"] += [None, {"title": None}, {"title": "Bad URL", "url": "javascript:void(0)"}]
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = run(tmp_path, tmp_path / "reports", fixture=path)
    assert len(result["new_jobs"]) == 3


def test_dry_run_rejects_sending(tmp_path):
    import subprocess, sys
    result = subprocess.run([sys.executable, "-m", "src.main", "--dry-run", "--commit"], capture_output=True)
    assert result.returncode == 2
    assert b"cannot save or send" in result.stderr


def test_profile_validation(tmp_path):
    from src.config import load_profile
    path = tmp_path / "profile.json"
    path.write_text('{"skills": "invented"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid profile"):
        load_profile(path)


def test_workflow_persists_outbox_before_smtp():
    import yaml
    root = Path(__file__).resolve().parents[1]
    flow = yaml.load((root / ".github/workflows/job-agent.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert flow["on"]["schedule"][0]["cron"] == "17 5,14 * * *"
    assert "workflow_dispatch" in flow["on"]
    assert flow["permissions"]["contents"] == "write"
    steps = flow["jobs"]["search-jobs"]["steps"]
    ids = [s.get("id") for s in steps]
    assert ids.index("prepare") < ids.index("persist") < ids.index("deliver")
    delivery = next(s for s in steps if s.get("id") == "deliver")
    assert "steps.persist.outcome == 'success'" in delivery["if"]
    for key in ("SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"):
        assert delivery["env"][key] == "${{ secrets." + key + " }}"
