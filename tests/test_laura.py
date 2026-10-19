"""Laura's public browser response shape, verified with live markup in October 2026."""
from unittest.mock import MagicMock
import json
from urllib.parse import parse_qs

import pytest

from src.job_search import build_sources, listing_pages, parse_job_details, parse_search_page, search_jobs
from src.scoring import score_job
from src.config import PROFILE
from src.tracker import primary_url


SOURCE = next(s for s in build_sources() if s.get("adapter") == "laura")


def card(number=1, title="Sovellusasiantuntija"):
    return f'''<li class="job_listing" id="job_listing-{number}">
      <a class="job_listing-clickbox" aria-label="{title}"
         href="https://laura.fi/avoimet-tyopaikat/example/role/{number}/"></a>
      <div class="job_listing-title">{title}</div>
      <div class="job_listing-company">Example Oy</div>
      <div class="job_listing-location-text">Helsinki</div></li>'''


def response(html, pages=1, found=True):
    return MagicMock(status_code=200, text="response", json=lambda: dict(
        html=html, found_jobs=found, max_num_pages=pages))


@pytest.fixture(autouse=True)
def no_robot_network_or_delay(monkeypatch):
    monkeypatch.setattr("src.job_search.robots_allowed", lambda *args: None)


def test_laura_reads_all_pages_and_preserves_card_fields():
    session = MagicMock()
    session.post.side_effect = [response(card(1), 2), response(card(2), 2)]
    pages = list(listing_pages(session, SOURCE, {}))
    jobs = [job for html in pages for job in parse_search_page(html, SOURCE)]
    assert len(jobs) == 2
    assert jobs[0]["company"] == "Example Oy"
    assert jobs[0]["location"] == "Helsinki"
    assert jobs[0]["title"] == "Sovellusasiantuntija"
    assert jobs[0]["source_url"].endswith("/1")
    calls = session.post.call_args_list
    assert [c.kwargs["data"]["page"] for c in calls] == [1, 2]
    filters = parse_qs(calls[0].kwargs["data"]["form_data"])
    assert filters["job_tag[]"] == ["IT & tietoliikenne"]
    assert "uusimaa" in filters["search_regions[]"]


def test_remote_query_has_no_region_restriction():
    session = MagicMock()
    session.post.return_value = response("", 0, False)
    source = dict(SOURCE, remote_search=True)
    assert list(listing_pages(session, source, {})) == ["No jobs found"]
    data = session.post.call_args.kwargs["data"]
    assert data["search_keywords"] == "etä"
    assert "search_regions" not in data["form_data"]


def test_laura_excludes_category_links():
    html = card() + '<a href="/avoimet-tyopaikat/osaamisalueet/">Osaamisalueet</a>'
    assert len(parse_search_page(html, SOURCE)) == 1


@pytest.mark.parametrize("payload", [{}, {"html": "", "found_jobs": True, "max_num_pages": 1},
    {"html": "", "found_jobs": False, "max_num_pages": 3}])
def test_unreadable_or_inconsistent_search_is_not_empty(payload):
    session = MagicMock()
    session.post.return_value = MagicMock(status_code=200, text="response", json=lambda: payload)
    with pytest.raises((ValueError, KeyError)):
        list(listing_pages(session, SOURCE, {}))


def test_page_limit_retains_discoveries_and_marks_partial(monkeypatch):
    monkeypatch.setattr("src.job_search.LAURA_MAX_PAGES", 1)
    session = MagicMock()
    session.post.return_value = response(card(), 2)
    jobs, health = search_jobs([SOURCE], session, max_details=0)
    assert len(jobs) == 1
    assert health["Laura"]["status"] == "PARTIAL"
    assert health["Laura"]["failed"] == 1
    assert "page limit reached" in health["Laura"]["last_error"]
    assert "Preview detail limit" in health["Laura"]["last_error"]


def test_repeating_page_is_detected():
    session = MagicMock()
    session.post.return_value = response(card(), 3)
    with pytest.raises(ValueError, match="repeated page"):
        list(listing_pages(session, SOURCE, {}))
    assert session.post.call_count == 2


def test_blocked_laura_does_not_request_other_laura_searches():
    session = MagicMock()
    session.post.return_value = MagicMock(status_code=429, text="Too many requests")
    jobs, health = search_jobs([SOURCE, SOURCE], session)
    assert jobs == []
    assert health["Laura"]["status"] == "BLOCKED"
    assert session.post.call_count == 1


@pytest.mark.parametrize("title,description", [
    ("Asiakkuuspäällikkö", "Yritysmyynti ja SaaS-ratkaisut"),
    ("Sovellusasiantuntija", "Asiakastyö ja järjestelmien käyttöönotto"),
    ("Käyttöönottoasiantuntija", "CRM ja asiakastyö"),
    ("IT-tuki harjoittelija", "Python ja käyttäjien tukeminen"),
])
def test_finnish_target_roles_are_relevant(title, description):
    job = score_job(dict(title=title, description=description, location="Helsinki"))
    assert job["score"] >= 60


def test_general_retail_stays_rejected_after_vocabulary_expansion():
    job = score_job(dict(title="Myymälämyyjä", description="Asiakaspalvelu", location="Helsinki"))
    assert job["classification"] == "REJECTED"


def test_finnish_discovery_terms_are_not_lost_to_encoding():
    assert "asiakkuuspäällikkö" in PROFILE["secondary_roles"]
    assert "ohjelmistokehittäjä" in PROFILE["secondary_roles"]
    assert not any("?" in term for term in PROFILE["secondary_roles"])


def test_employer_link_is_preferred_over_laura():
    assert primary_url(dict(canonical_url="https://laura.fi/avoimet-tyopaikat/a/b/1/",
        urls="https://employer.example/apply/42")) == "https://employer.example/apply/42"


def test_card_facts_survive_incomplete_structured_posting():
    html = card().replace('</li>', '<li class="job_listing-date">Julkaistu 19.10.2026</li>'
        '<li class="uranus-application-deadline">Haku päättyy 30.10.2026</li></li>')
    candidate = parse_search_page(html, SOURCE)[0]
    posting = {"@type": "JobPosting", "description": "CRM ja asiakastyö"}
    detail = '<script type="application/ld+json">' + json.dumps(posting) + '</script>'
    row = parse_job_details(detail, candidate)
    assert row["company"] == "Example Oy"
    assert row["location"] == "Helsinki"
    assert row["date_posted"] == "2026-10-19"
    assert row["deadline"] == "2026-10-30"
