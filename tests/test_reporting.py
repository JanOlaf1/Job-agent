import json
import pytest
from unittest.mock import MagicMock
from src.job_search import parse_job_details, parse_search_page
from src.scoring import score_job
from src.reporting import digest, write_reports
from src.send_email import build_email, email_settings, send_email
from src.tracker import load_tracker, merge_jobs, save_tracker, urls_for


def test_44_point_job_and_url_reach_report_and_email(tmp_path):
    tracker = {}
    result = merge_jobs(tracker, [dict(title="Sales Development Representative", score=44,
                                     urls="https://example.org/apply?id=44&utm_source=x", sources="Example")])
    result.update(run_time="2026-09-24", status="DEGRADED", sources={"Example": {"status": "BLOCKED", "last_error": "HTTP 403"}})
    write_reports(tmp_path, result, tracker)
    message = build_email(result)
    for text in (digest(result), message.get_body(preferencelist=("plain",)).get_content(), (tmp_path / "jobs.md").read_text(encoding="utf-8")):
        assert "https://example.org/apply?id=44" in text
        assert "REVIEW" in text
        assert "BLOCKED" in text
    assert result["review_count"] == 1
    assert "1 harkittavaa" in message["Subject"]
    next_run = merge_jobs(tracker, list(tracker.values()))
    next_run.update(run_time="2026-09-25", status="SUCCESS", sources={})
    assert "Sales Development Representative" not in build_email(next_run).get_body(preferencelist=("plain",)).get_content()


def test_email_transport_is_mocked(monkeypatch):
    smtp = MagicMock()
    monkeypatch.setattr("src.send_email.smtplib.SMTP_SSL", smtp)
    for name in ("SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"):
        monkeypatch.setenv(name, "test")
    result = dict(new_jobs=[], strong_count=0, review_count=0, status="SUCCESS", run_time="test", sources={})
    send_email(build_email(result))
    smtp.return_value.__enter__.return_value.send_message.assert_called_once()


def test_large_digest_is_concise_without_losing_results():
    rows = [dict(title=f"Study {i}", urls=f"https://example.org/study/{i}", score=75) for i in range(11)]
    result = dict(new_jobs=[], new_studies=rows, strong_count=0, review_count=0,
                  status="SUCCESS", run_time="test", sources={})
    message = build_email(result)
    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "Study 10" not in body
    assert "Study 10" in next(message.iter_attachments()).get_payload(decode=True).decode("utf-8")
    assert "11" in message["Subject"]


def test_url_survives_search_enrichment_deduplication_csv_report_and_email(tmp_path):
    source = dict(name="Jobly", url="https://www.jobly.fi/search", marker="/tyopaikka/")
    card = '<article><h2>Digital Advisor</h2><a href="/tyopaikka/advisor?utm_source=test">Apply</a></article>'
    candidate = parse_search_page(card, source)[0]
    posting = {
        "@type": "JobPosting", "title": "Digital Advisor",
        "description": "SaaS implementation and customer requirements",
        "hiringOrganization": {"name": "Example Oy"},
        "jobLocation": {"address": {"addressLocality": "Helsinki"}},
        "url": "https://employer.example/apply?id=42&utm_source=board",
    }
    html = '<script type="application/ld+json">' + json.dumps(posting) + '</script>'
    job = score_job(parse_job_details(html, candidate))
    tracker = {}
    result = merge_jobs(tracker, [job, job])
    assert result["new_count"] == 1
    path = tmp_path / "job_tracker.csv"
    save_tracker(path, tracker)
    restored = load_tracker(path)
    row = restored[result["new_jobs"][0]["job_id"]]
    assert set(urls_for(row)) == {
        "https://www.jobly.fi/tyopaikka/advisor", "https://employer.example/apply?id=42",
    }
    result["new_jobs"] = [row]
    result.update(run_time="2026-09-24", status="SUCCESS", sources={})
    write_reports(tmp_path, result, restored)
    for text in ((tmp_path / "jobs.md").read_text(encoding="utf-8"), build_email(result).get_body(preferencelist=("plain",)).get_content()):
        assert "[Avaa ilmoitus](<https://employer.example/apply?id=42>)" in text
    assert merge_jobs(restored, [job])["new_jobs"] == []


def test_three_review_jobs_without_strong_jobs_are_emailed():
    jobs = [dict(title=f"Review role {i}", score=44, urls=f"https://example.org/jobs/{i}") for i in range(3)]
    result = merge_jobs({}, jobs)
    result.update(run_time="2026-09-24", status="SUCCESS", sources={})
    message = build_email(result)
    assert result["strong_count"] == 0
    assert result["review_count"] == 3
    assert "3 harkittavaa" in message["Subject"]
    assert "ei uusia" not in message["Subject"]
    for job in jobs:
        assert job["title"] in message.get_body(preferencelist=("plain",)).get_content()
        assert job["urls"] in message.get_body(preferencelist=("plain",)).get_content()


@pytest.mark.parametrize("port", ["invalid", "0", "65536"])
def test_invalid_smtp_port_is_explained(port, monkeypatch):
    for name in ("SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"):
        monkeypatch.setenv(name, "test")
    monkeypatch.setenv("SMTP_PORT", port)
    with pytest.raises(ValueError, match="SMTP_PORT"):
        email_settings()


@pytest.mark.parametrize("status,expected", [
    ("SUCCESS", "Ei uusia sopivia työpaikkoja tällä hakukerralla."),
    ("DEGRADED", "Osa lähteistä jäi tarkistamatta."),
    ("FAILED", "uusien työpaikkojen määrää ei voida varmistaa."),
])
def test_empty_digest_explains_search_coverage_in_both_formats(status, expected):
    result = dict(new_jobs=[], strong_count=0, review_count=0, status=status,
                  run_time="2026-10-19T08:05+03:00", min_relevance_score=60,
                  normalized_count=12, relevant_count=3,
                  sources={"Example": {"status": "BLOCKED", "last_error": "HTTP 403"}})
    message = build_email(result)
    for subtype in ("plain", "html"):
        body = message.get_body(preferencelist=(subtype,)).get_content()
        assert expected in body
        assert "Lähetysrajan täyttäviä työpaikkoja: 3" in body
        assert "lähetysraja: 60/100" in body
        assert "aiemmalla ajolla löytyneitä" in body
        assert "HTTP 403" in body
    if status == "DEGRADED":
        assert "osittainen haku" in message["Subject"]
    if status == "FAILED":
        assert "ei uusia" not in message["Subject"]


def test_html_explains_scores_and_translates_classification():
    result = merge_jobs({}, [dict(title="Developer", score=75, location="Helsinki",
                                 urls="https://example.org/job/1")])
    result.update(status="SUCCESS", run_time="2026-10-19", sources={})
    html = build_email(result).get_body(preferencelist=("html",)).get_content()
    assert "Vahva osuma" in html
    assert "työllistymisen todennäköisyyttä" in html
    assert "Helsinki" in html
    assert "STRONG" not in html
