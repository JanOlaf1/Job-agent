"""CSV history and one definition of new. Never silently discard unreadable data."""
import csv
import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .scoring import classify_score

JOB_FIELDS = "job_id title company location category score classification score_reasons summary skill_gaps sources urls source_url canonical_url link_status source_ids date_posted deadline first_seen last_seen sent_at notification_status status applied_date notes".split()
USER_FIELDS = {"status", "applied_date", "notes", "first_seen"}


def split_values(value, separator=" || "):
    return value if isinstance(value, list) else [v.strip() for v in (value or "").split(separator) if v.strip()]


def canonicalize_url(url):
    """Remove tracking only; preserve query parameters that identify an opening."""
    value = str(url or "").strip()
    if re.search(r'[\s<>"\\]', value):
        return ""
    try:
        parts = urlsplit(value)
        if parts.username or parts.password or not parts.hostname or parts.port == 0:
            return ""
        parts.port  # Validate malformed ports.
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    host = parts.netloc.lower()
    path = parts.path.rstrip("/")
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        match = re.search(r"/jobs/view/(?:.*-)?(\d+)$", path)
        if match:
            return f"https://fi.linkedin.com/jobs/view/{match[1]}"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"trk", "trackingid", "refid", "fbclid", "gclid"}]
    return urlunsplit((parts.scheme, host, path, urlencode(sorted(query)), ""))


def urls_for(row):
    values = [row.get("canonical_url", "")] + split_values(row.get("urls")) + [row.get("url", ""), row.get("source_url", "")]
    return list(dict.fromkeys(u for value in values if (u := canonicalize_url(value))))


def primary_url(row):
    urls = urls_for(row)
    # Suora työnantajan linkki ennen aggregaattorin linkkiä, kun molemmat tunnetaan.
    boards = ("linkedin.com", "duunitori.fi", "jobly.fi", "indeed.com", "laura.fi")
    direct = [url for url in urls if not any(urlsplit(url).hostname == host or
              (urlsplit(url).hostname or "").endswith("." + host) for host in boards)]
    return (direct or urls or [""])[0]


def load_tracker(path, id_field="job_id"):
    """Read legacy/current CSV without changing user fields; malformed files fail closed."""
    path = Path(path)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or id_field not in reader.fieldnames:
            raise ValueError(f"Invalid tracker header: {path}")
        rows = {}
        for row in reader:
            key = row.get(id_field)
            if not key or key in rows or None in row or any(v is None for v in row.values()):
                raise ValueError(f"Invalid/duplicate tracker row: {path}, line {reader.line_num}")
            rows[key] = row
    return rows


def save_tracker(path, rows, fields=JOB_FIELDS):
    """Atomic CSV replacement with a previous-file backup and all extra columns retained."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(list(fields) + [k for row in rows.values() for k in row]))
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows.values())
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    temporary.replace(path)


def same_identity(a, b):
    if set(urls_for(a)) & set(urls_for(b)):
        return True
    if set(split_values(a.get("source_ids"))) & set(split_values(b.get("source_ids"))):
        return True
    # Eri lähteiden yhdistäminen vain täsmällisillä tiedoilla, ei sumeilla nimikkeillä.
    def norm(value):
        return " ".join((value or "").casefold().split())
    if not all(norm(a.get(k)) and norm(a.get(k)) == norm(b.get(k)) for k in ("title", "company", "location")):
        return False
    sources_a = set(split_values(a.get("sources"), " | "))
    sources_b = set(split_values(b.get("sources"), " | "))
    return bool(sources_a and sources_b and not sources_a & sources_b)


def merge_jobs(tracker, jobs, archive=None):
    """Update rows in place, preserving history; return new useful jobs once per discovery."""
    today = datetime.now(ZoneInfo("Europe/Helsinki")).date().isoformat()
    new_ids, existing_ids = set(), set()
    archive = archive or {}
    for job in jobs:
        match = next((key for key, row in tracker.items() if same_identity(row, job)), None)
        archived = next((row for row in archive.values() if same_identity(row, job)), None) if not match else None
        if archived:
            match = archived["job_id"]
            tracker[match] = dict(archived)
        if not match:
            identity = "|".join(split_values(job.get("source_ids")) or urls_for(job))
            if not identity:
                raise ValueError("Job has no stable URL or source ID")
            match = hashlib.sha256(identity.encode()).hexdigest()[:18]
            if match in tracker:
                raise ValueError("Conflicting job identity")
            tracker[match] = {"job_id": match, "first_seen": today, "status": "UUSI", "applied_date": "", "notes": "", "notification_status": "pending"}
            new_ids.add(match)
        else:
            existing_ids.add(match)
        row = tracker[match]
        for field, separator, incoming in [
            ("urls", " || ", urls_for(job)),
            ("sources", " | ", split_values(job.get("sources"), " | ")),
            ("source_ids", " || ", split_values(job.get("source_ids"))),
        ]:
            old = urls_for(row) if field == "urls" else split_values(row.get(field), separator)
            row[field] = separator.join(dict.fromkeys(old + incoming))
        for field in JOB_FIELDS:
            if field not in USER_FIELDS | {"job_id", "urls", "sources", "source_ids", "sent_at", "notification_status"} and field in job:
                if job[field] != "" or field in {"score", "score_reasons"}:
                    row[field] = job[field]
        row["classification"] = classify_score(row.get("score"))
        row["last_seen"] = today
    new = [tracker[key] for key in new_ids]
    useful = sorted((r for r in new if r["classification"] in {"STRONG", "REVIEW"}
                     and r.get("status") != "OHITA" and primary_url(r)),
                    key=lambda r: int(r.get("score") or 0), reverse=True)
    return {"new_jobs": useful, "new_count": len(new_ids), "existing_count": len(existing_ids - new_ids),
            "rejected_count": sum(r["classification"] == "REJECTED" for r in new),
            "strong_count": sum(r["classification"] == "STRONG" for r in useful),
            "review_count": sum(r["classification"] == "REVIEW" for r in useful)}


def merge_studies(tracker, studies):
    """Separate study identities; notify once for discovery or changed application facts."""
    today = datetime.now(ZoneInfo("Europe/Helsinki")).date().isoformat()
    changed = {}
    for study in studies:
        key = study["study_id"]
        previous = tracker.get(key)
        row = dict(previous or {"first_seen": today, "status": "UUSI", "notes": ""})
        for field, value in study.items():
            if field in USER_FIELDS or field in {"description", "detail_ok"}:
                continue
            # Epäonnistunut lisätietohaku ei tyhjennä aiemmin luettuja hakutietoja.
            if previous and not study.get("detail_ok", True) and field in {
                "deadline", "application_status", "application_periods", "eligibility", "remote_type", "scope",
                "detail_checked", "score", "classification", "score_reasons", "study_type", "price", "start_date", "summary"}:
                continue
            row[field] = value
        row["last_seen"] = today
        important_change = previous and any(row.get(k, "") != previous.get(k, "") for k in
                                           ("deadline", "application_status", "application_periods"))
        if not previous or important_change:
            row["notification_status"] = "pending"
        tracker[key] = row
        if (not previous or important_change) and row.get("classification") in {"STRONG", "REVIEW"} and row.get("status") != "OHITA" and primary_url(row):
            changed[key] = dict(row, change="UUSI" if not previous else "HAKUAIKA / HAKUTILA MUUTTUNUT")
    return sorted(changed.values(), key=lambda r: int(r["score"]), reverse=True)


def select_digest(result, tracker, studies, settings):
    """Old unlabelled history stays quiet; new unsent items wait until worth sending."""
    today = datetime.now(ZoneInfo("Europe/Helsinki")).date().isoformat()
    def eligible(row, minimum):
        return (row.get("notification_status") == "pending" and row.get("status") not in {"OHITA", "HAETTU", "HAASTATTELU", "TARJOUS"}
                and int(row.get("score") or 0) >= minimum and primary_url(row)
                and row.get("link_status") != "BROKEN"
                and (not row.get("deadline") or row["deadline"][:10] >= today))
    result["new_jobs"] = sorted((dict(row) for row in tracker.values() if eligible(row, settings["min_relevance_score"])),
                                key=lambda r: (-int(r["score"]), r["job_id"]))
    result["new_studies"] = sorted((dict(row) for row in studies.values()
        if eligible(row, settings["min_training_score"]) and row.get("detail_checked")
        and row.get("application_status") in {"OPEN", "UPCOMING"}),
        key=lambda r: (-int(r["score"]), r["study_id"]))
    result["strong_count"] = sum(r["classification"] == "STRONG" for r in result["new_jobs"])
    result["review_count"] = sum(r["classification"] == "REVIEW" for r in result["new_jobs"])
