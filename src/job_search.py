"""Public HTML discovery, JobPosting enrichment and honest source health."""
import json
import re
import time
from datetime import datetime
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from .config import JOB_TERMS, JOBLY_MAX_PAGES, LAURA_MAX_PAGES, LAURA_PAGE_SIZE, REQUEST_DELAY, TIMEOUT, USER_AGENT
from .tracker import canonicalize_url


def check_response(response):
    if response.status_code in {401, 403, 429}:
        raise PermissionError(f"HTTP {response.status_code}")
    response.raise_for_status()
    if any(marker in response.text.lower() for marker in ["<title>just a moment", "<title>access denied", "verify you are human"]):
        raise PermissionError("Access challenge")
    return response


def fetch_page(session, url):
    return check_response(session.get(url, timeout=TIMEOUT))


def robots_allowed(session, url, cache):
    """Respect published robot rules; do not bypass blocked or unavailable rules."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in cache:
        response = session.get(origin + "/robots.txt", timeout=TIMEOUT)
        if response.status_code == 404:
            cache[origin] = None
        else:
            if response.status_code in {401, 403, 429}:
                raise PermissionError(f"robots.txt HTTP {response.status_code}")
            response.raise_for_status()
            parser = RobotFileParser()
            parser.parse(response.text.splitlines())
            cache[origin] = parser
    parser = cache[origin]
    if parser and not parser.can_fetch(USER_AGENT, url):
        raise PermissionError("robots.txt disallows automated access")
    delay = parser.crawl_delay(USER_AGENT) if parser else None
    time.sleep(max(REQUEST_DELAY, delay or 0))


def build_sources():
    """Small set of existing public sources; no guessed private APIs."""
    sources = []
    for term in JOB_TERMS:
        sources.append({"name": "Duunitori", "url": "https://duunitori.fi/tyopaikat?" + urlencode(
            {"alue": "uusimaa", "haku": term, "search_also_descr": "1"}), "marker": "/tyopaikat/tyo/"})
        for location in ("Helsinki, Uusimaa, Finland", "Finland"):
            params = {"keywords": term, "location": location}
            if location == "Finland":
                params["f_WT"] = "2"
            sources.append({"name": "LinkedIn", "url": "https://fi.linkedin.com/jobs/search/?" + urlencode(params),
                            "marker": "/jobs/view/"})
    sources.extend([
        {"name": "Jobly", "url": "https://www.jobly.fi/tyopaikat/it/uusimaa", "marker": "/tyopaikka/", "max_pages": JOBLY_MAX_PAGES},
        {"name": "Jobly", "url": "https://www.jobly.fi/tyopaikat/myynti/uusimaa", "marker": "/tyopaikka/", "max_pages": JOBLY_MAX_PAGES},
        {"name": "Academic Work", "url": "https://www.academicwork.fi/avoimet-tyopaikat", "marker": "/avoimet-tyopaikat/j/"},
    ])
    for tag, slug in [("IT & tietoliikenne", "it-tietoliikenne"), ("Myynti & hankinta", "myynti-hankinta")]:
        for remote in (False, True):
            sources.append({"name": "Laura", "adapter": "laura", "tag": tag,
                            "remote_search": remote,
                            "url": "https://laura.fi/avoimet-tyopaikat/?" + urlencode({"search_tags": slug}),
                            "marker": "/avoimet-tyopaikat/",
                            "posting_pattern": r"^/avoimet-tyopaikat/[^/]+/[^/]+/\d+/?$"})
    return sources


def listing_pages(session, source, robots):
    """Laura's public browser search, with bounded pagination and explicit truncation.

    Request shape verified against Laura's public assets/js/ajax-filters.js and
    uranus-tag-filter.js. This is not a supported or guaranteed stable API.
    """
    robots_allowed(session, source["url"], robots)
    if source.get("adapter") != "laura":
        current, seen = source["url"], set()
        for page in range(source.get("max_pages", 1)):
            if current in seen:
                raise ValueError(f"{source['name']}: repeated pagination URL")
            seen.add(current)
            if page:
                robots_allowed(session, current, robots)
            html = fetch_page(session, current).text
            yield html
            if "max_pages" not in source:
                return
            soup = BeautifulSoup(html, "html.parser")
            link = soup.select_one('a[rel~=next][href], .pager__item--next a[href]')
            if not link:
                return
            next_url = canonicalize_url(urljoin(current, link["href"]))
            origin = urlsplit(source["url"])
            target = urlsplit(next_url)
            if not next_url or (target.scheme, target.netloc, target.path) != (origin.scheme, origin.netloc, origin.path):
                raise ValueError(f"{source['name']}: pagination left the original search path")
            current = next_url
        raise ValueError(f"{source['name']}: page limit reached ({source['max_pages']}); some results remain unread")
    endpoint = "https://laura.fi/wp-content/themes/jobify-child/ajax.php?wpml_lang=fi"
    filters = [("job_tag[]", source["tag"])]
    if not source.get("remote_search"):
        filters += [("search_regions[]", region) for region in ("uusimaa", "paakaupunkiseutu", "uusimaa-paakaupunkiseutu")]
    seen = set()
    for page in range(1, LAURA_MAX_PAGES + 1):
        robots_allowed(session, endpoint, robots)
        response = check_response(session.post(endpoint, data={
            "action": "get_listings", "lang": "fi", "per_page": LAURA_PAGE_SIZE,
            "orderby": "date", "order": "DESC", "page": page,
            "search_keywords": "etä" if source.get("remote_search") else "",
            "form_data": urlencode(filters),
        }, timeout=TIMEOUT))
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("html"), str) or not isinstance(data.get("found_jobs"), bool):
            raise ValueError("Laura: search response structure changed")
        total_pages = int(data["max_num_pages"])
        if total_pages < 0 or (data["found_jobs"] and not data["html"].strip()):
            raise ValueError("Laura: inconsistent search response")
        if not data["found_jobs"]:
            if page == 1 and total_pages == 0:
                yield "No jobs found"
                return
            raise ValueError("Laura: unexpected empty page before end of results")
        if data["html"] in seen:
            raise ValueError("Laura: repeated page; pagination did not advance")
        seen.add(data["html"])
        yield data["html"]
        if page >= total_pages:
            return
    raise ValueError(f"Laura: page limit reached ({LAURA_MAX_PAGES}); some results remain unread")


def parse_search_page(html, source):
    """Keep direct posting links regardless of exact title or missing card location."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = {}
    for link in soup.find_all("a", href=True):
        url = canonicalize_url(urljoin(source["url"], link["href"]))
        if not url or source["marker"] not in urlsplit(url).path:
            continue
        if source.get("posting_pattern") and not re.search(source["posting_pattern"], urlsplit(url).path):
            continue
        card = link.find_parent("li") or link.find_parent("article") or link.parent
        heading = card.find(["h2", "h3", "h4"])
        title = (heading or link).get_text(" ", strip=True) or link.get("aria-label", "")
        if title:
            candidates.setdefault(url, {"title": title, "url": url, "sources": source["name"],
                                        "source_url": url, "description": card.get_text(" ", strip=True)[:2000], "location": ""})
            for field, selector in [("title", ".job_listing-title"), ("company", ".job_listing-company"),
                                    ("location", ".job_listing-location-text")]:
                tag = card.select_one(selector)
                if tag:
                    candidates[url][field] = tag.get_text(" ", strip=True)
            for field, selector in [("date_posted", ".job_listing-date"), ("deadline", ".uranus-application-deadline")]:
                tag = card.select_one(selector)
                match = re.search(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b", tag.get_text(" ", strip=True)) if tag else None
                if match:
                    try:
                        candidates[url][field] = datetime.strptime(match[0], "%d.%m.%Y").date().isoformat()
                    except ValueError:
                        pass
    if not candidates and not re.search(r"\bno (?:jobs|results)\b|\b0 (?:jobs|työpaikkaa)\b|\bei (?:löytynyt|avoimia työpaikkoja)\b", soup.get_text(" "), re.I):
        raise ValueError("No readable job cards or explicit empty result; possibly JavaScript/changed markup")
    return list(candidates.values())


def jsonld_objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from jsonld_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from jsonld_objects(child)


def academic_work_details(soup):
    """Read visible named sections, never recommendations or footer text."""
    headings = {"tehtävänkuvaus", "työtehtävät", "etsimme", "about the role", "job duties", "we are looking for"}
    sections = [h.parent.get_text(" ", strip=True) for h in soup.find_all("h2")
                if h.get_text(" ", strip=True).casefold() in headings]
    if not sections or not soup.find("h1"):
        raise ValueError("Academic Work: expected posting sections missing")
    result = {"title": soup.find("h1").get_text(" ", strip=True), "description": "\n".join(sections)}
    for label in soup.find_all("label"):
        field = {"sijainti": "location", "location": "location", "yritys": "company", "company": "company"}.get(label.get_text(strip=True).rstrip(":").casefold())
        value = label.find_next_sibling("p")
        if field and value:
            result[field] = value.get_text(" ", strip=True)
    return result


def detail_url(value, base):
    """Accept posting-shaped links; reject common home/search/login redirects."""
    if not isinstance(value, str) or not value.strip() or value.startswith("#"):
        return ""
    url = canonicalize_url(urljoin(base, value))
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.path.lower().rstrip("/") in {"", "/jobs", "/careers", "/search", "/login", "/tyopaikat", "/avoimet-tyopaikat"}:
        return ""
    return url


def parse_job_details(html, candidate, final_url=None):
    """Prefer structured posting text over navigation, recommendations or site footers."""
    soup = BeautifulSoup(html, "html.parser")
    posting = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        posting = next((obj for obj in jsonld_objects(data) if "JobPosting" in
                        ([obj.get("@type")] if isinstance(obj.get("@type"), str) else obj.get("@type") or [])), None)
        if posting:
            break
    result = dict(candidate)
    base = final_url or candidate["url"]
    if not detail_url(base, candidate["url"]):
        raise ValueError("Posting redirected to a home/search/login page")
    canonical = soup.find("link", rel="canonical", href=True)
    canonical = detail_url(canonical["href"], base) if canonical else ""
    if posting:
        result["title"] = posting.get("title") or candidate["title"]
        organization = posting.get("hiringOrganization") or {}
        result["company"] = (organization.get("name", "") if isinstance(organization, dict) else str(organization)) or candidate.get("company", "")
        result["description"] = BeautifulSoup(posting.get("description") or "", "html.parser").get_text(" ", strip=True)
        locations = posting.get("jobLocation") or []
        if isinstance(locations, dict):
            locations = [locations]
        parts = []
        for place in locations:
            address = place.get("address", {}) if isinstance(place, dict) else {}
            if isinstance(address, str):
                parts.append(address)
            elif isinstance(address, dict):
                for key in ("addressLocality", "addressRegion", "addressCountry"):
                    value = address.get(key)
                    if isinstance(value, dict):
                        value = value.get("name")
                    if value:
                        parts.append(str(value))
        if posting.get("jobLocationType") == "TELECOMMUTE":
            parts.append("Remote")
            countries = posting.get("applicantLocationRequirements") or []
            if isinstance(countries, dict):
                countries = [countries]
            parts.extend(c.get("name", "") for c in countries if isinstance(c, dict))
        result["location"] = ", ".join(dict.fromkeys(parts)) or candidate.get("location", "")
        result["date_posted"] = str(posting.get("datePosted") or candidate.get("date_posted") or "")[:10]
        result["deadline"] = str(posting.get("validThrough") or candidate.get("deadline") or "")[:10]
        identifier = posting.get("identifier") or {}
        if isinstance(identifier, dict) and identifier.get("value"):
            result["source_ids"] = f"{candidate['sources']}:{identifier['value']}"
        direct_url = detail_url(posting.get("url"), base)
    else:
        body = soup.select_one(".show-more-less-html__markup, .description__text, [itemprop=description], .job-description")
        if candidate.get("sources") == "Academic Work":
            result.update(academic_work_details(soup))
        elif not body:
            raise ValueError("No JobPosting or recognized description; keeping search card for review")
        else:
            result["description"] = body.get_text(" ", strip=True)
        heading = soup.find("h1")
        if heading:
            result["title"] = heading.get_text(" ", strip=True)
        for key, selector in [("location", ".topcard__flavor--bullet, [itemprop=jobLocation]"),
                              ("company", ".topcard__org-name-link, [itemprop=hiringOrganization]")]:
            tag = soup.select_one(selector)
            if tag:
                result[key] = tag.get_text(" ", strip=True)
    if not result.get("description"):
        raise ValueError("Empty posting description")
    result["source_url"] = candidate.get("source_url", candidate["url"])
    result["canonical_url"] = canonical or (direct_url if posting else "") or base
    result["urls"] = " || ".join(dict.fromkeys(u for u in [result["canonical_url"], direct_url if posting else "", base, candidate["url"]] if u))
    result["link_status"] = "VERIFIED_GET" if result["canonical_url"] == base else "PAGE_DECLARED"
    result["detail_status"] = "HEALTHY"
    return result


def source_status(stat):
    if stat["blocked"] and not stat["ok"]:
        return "BLOCKED"
    if stat["failed"] or stat["detail_failed"] or stat["blocked"]:
        return "PARTIAL" if stat["ok"] else "FAILED"
    return "HEALTHY" if stat["raw_jobs"] else "EMPTY"


def record_error(stat, error):
    """Keep pagination failures visible when later detail requests also fail."""
    errors = stat.setdefault("errors", [])
    text = str(error)
    if text not in errors:
        errors.append(text)
    stat["last_error"] = " | ".join(errors)


def search_jobs(sources=None, session=None, max_details=None):
    """Return enriched candidates and per-source health, continuing after source failures."""
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    stats, candidates, robots = {}, {}, {}
    for source in sources if sources is not None else build_sources():
        name = source["name"]
        stat = stats.setdefault(name, {"ok": 0, "failed": 0, "blocked": 0, "raw_jobs": 0,
                                       "detail_failed": 0, "detail_ok": 0, "last_error": ""})
        if stat["blocked"]:
            continue
        try:
            for html in listing_pages(session, source, robots):
                found = parse_search_page(html, source)
                stat["ok"] += 1
                stat["raw_jobs"] += len(found)
                for candidate in found:
                    candidates.setdefault(candidate["url"], candidate)
        except (requests.RequestException, PermissionError, ValueError, TypeError, KeyError) as error:
            stat["blocked" if isinstance(error, PermissionError) else "failed"] += 1
            record_error(stat, error)
    print(f"[Jobs] {len(candidates)} yksilöllistä hakukorttia; luetaan ilmoitukset.", flush=True)
    jobs = []
    for index, candidate in enumerate(candidates.values()):
        if index % 5 == 0:
            print(f"[Jobs] Ilmoitus {index + 1}/{len(candidates)}", flush=True)
        stat = stats[candidate["sources"]]
        if max_details is not None and index >= max_details:
            stat["detail_failed"] += 1
            record_error(stat, "Preview detail limit reached; remaining cards are unverified")
            jobs.append(dict(candidate, detail_status="PARTIAL"))
            continue
        if stat["blocked"]:
            stat["detail_failed"] += 1
            jobs.append(dict(candidate, detail_status="BLOCKED"))
            continue
        try:
            robots_allowed(session, candidate["url"], robots)
            response = fetch_page(session, candidate["url"])
            final_url = response.url if isinstance(response.url, str) else candidate["url"]
            job = parse_job_details(response.text, candidate, final_url)
            stat["detail_ok"] += 1
        except (requests.RequestException, PermissionError, ValueError, TypeError, AttributeError, KeyError) as error:
            stat["detail_failed"] += 1
            if isinstance(error, PermissionError):
                stat["blocked"] += 1
            record_error(stat, error)
            broken = isinstance(error, requests.HTTPError) and error.response is not None and error.response.status_code in {404, 410}
            job = dict(candidate, detail_status="BLOCKED" if isinstance(error, PermissionError) else "FAILED",
                       link_status="BROKEN" if broken or "redirected" in str(error) else "UNVERIFIED")
        jobs.append(job)
    for stat in stats.values():
        stat["status"] = source_status(stat)
    return jobs, stats


def run_status(sources):
    """No usable search is FAILED; explicit successful empty searches are usable."""
    values = list(sources.values())
    usable = any(s["status"] in {"HEALTHY", "EMPTY"} or s.get("detail_ok", 0) for s in values)
    if not usable:
        return "FAILED"
    return "SUCCESS" if all(s["status"] in {"HEALTHY", "EMPTY"} for s in values) else "DEGRADED"
