"""Run with python -m src.main. Default: preview only, no history changes or mail."""
import argparse
import json
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

if not __package__:
    raise SystemExit("Käynnistä projektin juuresta: python -m src.main (tai python main.py)")

try:
    from dotenv import load_dotenv
    from .config import digest_settings
    from .job_search import run_status, search_jobs
    from .reporting import write_reports
    from .scoring import market_observations, score_job
    from .send_email import build_email, email_settings, send_email
    from .study_search import STUDY_FIELDS, score_study, search_studies
    from .tracker import load_tracker, merge_jobs, merge_studies, save_tracker, select_digest, same_identity, primary_url
except ModuleNotFoundError as error:
    raise SystemExit(f"Puuttuva moduuli: {error.name}. Asenna riippuvuudet: python -m pip install -r requirements.txt") from None
except ValueError as error:
    raise SystemExit(str(error)) from None

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def deliver_pending(data_dir):
    """Retry the persisted digest; record SMTP acceptance before removing the outbox."""
    email_settings()
    pending = data_dir / "pending_email.json"
    if not pending.exists():
        print("Email: skipped — no pending digest")
        return {"status": "SUCCESS"}
    result = json.loads(pending.read_text(encoding="utf-8"))
    datasets = []
    for filename, key, field, fields in [("job_tracker.csv", "new_jobs", "job_id", None),
                                         ("study_tracker.csv", "new_studies", "study_id", STUDY_FIELDS)]:
        path = data_dir / filename
        rows = load_tracker(path, field)
        if any(item.get(field) not in rows for item in result.get(key, [])):
            raise ValueError(f"Pending digest does not match {filename}; restore its saved tracker before sending")
        datasets.append((path, key, field, fields, rows))
    send_email(build_email(result))
    now = datetime.now(ZoneInfo("Europe/Helsinki")).isoformat(timespec="seconds")
    for path, key, field, fields, rows in datasets:
        for item in result.get(key, []):
            if item[field] in rows:
                rows[item[field]].update(sent_at=now, notification_status="sent")
        if fields is None:
            save_tracker(path, rows)
        else:
            save_tracker(path, rows, fields)
    pending.unlink()
    result["email_status"] = "sent"
    print("Email: sent (SMTP accepted)")
    return result


def run(data_dir, output_dir, *, commit=False, mail=False, fixture=None, max_job_details=None, prepare=False):
    """Search, score, update in memory, report; persist/send only when explicitly selected."""
    if mail and not commit:
        raise ValueError("Sending mail requires persisting discoveries")
    if commit and max_job_details is not None:
        raise ValueError("The detail limit is only for previews")
    settings = digest_settings()
    if prepare and (not commit or mail):
        raise ValueError("Preparing mail requires --commit without --send-email")
    if mail or prepare:
        email_settings()
    print("=== JOB AGENT ===", flush=True)
    tracker = load_tracker(data_dir / "job_tracker.csv")
    archive = load_tracker(data_dir / "job_archive.csv")
    study_tracker = load_tracker(data_dir / "study_tracker.csv", "study_id")
    pending = data_dir / "pending_email.json"
    if (mail or prepare) and pending.exists():
        print("Retrying the existing digest before preparing another.")
        return deliver_pending(data_dir) if mail else json.loads(pending.read_text(encoding="utf-8"))
    if fixture:
        payload = json.loads(Path(fixture).read_text(encoding="utf-8"))
        jobs, sources = payload["jobs"], payload["sources"]
    else:
        print("[Jobs] Reading public sources and posting details...", flush=True)
        jobs, sources = search_jobs(max_details=max_job_details)
    raw_count = sum(s.get("raw_jobs", 0) for s in sources.values())
    scored, unique_scored = [], []
    for job in jobs:
        try:
            if not job.get("title") or not primary_url(job):
                continue
            row = score_job(job)
            scored.append(row)
            if not any(same_identity(row, previous) for previous in unique_scored):
                unique_scored.append(row)
        except (ValueError, TypeError, AttributeError):
            print("[Jobs] Skipped a malformed posting")
    result = merge_jobs(tracker, scored, archive)
    if fixture:
        studies, study_health = payload.get("studies", []), payload.get("study_sources", {})
    else:
        print(f"[Jobs] {len(jobs)} candidates. [Studies] Reading Opintopolku...", flush=True)
        try:
            studies, study_health = search_studies(previous=study_tracker)
        except Exception as error:
            studies, study_health = [], {"Opintopolku": {"status": "FAILED", "raw_jobs": 0, "last_error": f"Study adapter error: {type(error).__name__}"}}
    sources.update(study_health)
    scored_studies = []
    for study in studies:
        try:
            if study.get("study_id") and study.get("title") and primary_url(study):
                scored_studies.append(score_study(study))
        except (ValueError, TypeError, AttributeError):
            print("[Studies] Skipped a malformed study")
    result["new_studies"] = merge_studies(study_tracker, scored_studies)
    select_digest(result, tracker, study_tracker, settings)
    result.update(run_time=datetime.now(ZoneInfo("Europe/Helsinki")).isoformat(timespec="minutes"),
                  status=run_status(sources), sources=sources, raw_count=raw_count,
                  normalized_count=len(jobs), deduplicated_count=result["new_count"] + result["existing_count"])
    result.update(min_relevance_score=settings["min_relevance_score"],
                  observations=market_observations(unique_scored, settings["min_relevance_score"]),
                  relevant_count=sum(j["score"] >= settings["min_relevance_score"] and j.get("link_status") != "BROKEN" for j in unique_scored))
    should_send = bool(result["new_jobs"] or result["new_studies"] or settings["send_empty_digest"])
    result["email_status"] = "pending" if (mail or prepare) and should_send else "preview only" if not (mail or prepare) else "skipped: no new relevant items"
    result["message_id"] = f"<{uuid.uuid4().hex}@job-agent.local>"
    output_dir.mkdir(parents=True, exist_ok=True)
    write_reports(output_dir, result, tracker, study_tracker)
    message = build_email(result)
    body = message.get_body(preferencelist=("plain",)).get_content()
    (output_dir / "email_preview.txt").write_text(str(message["Subject"]) + "\n\n" + body, encoding="utf-8")
    (output_dir / "email_preview.html").write_text(message.get_body(preferencelist=("html",)).get_content(), encoding="utf-8")
    (output_dir / "source_health.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if commit:
        save_tracker(data_dir / "job_tracker.csv", tracker)
        save_tracker(data_dir / "study_tracker.csv", study_tracker, STUDY_FIELDS)
    if (mail or prepare) and should_send:
        write_json(pending, result)
    if mail and should_send:
        deliver_pending(data_dir)
        result["email_status"] = "sent"
    for name, stat in sources.items():
        print(f"{name}: {stat['status']} ({stat.get('raw_jobs', 0)} candidates) {stat.get('last_error', '')}")
    print(f"Raw: {raw_count} | Normalized: {len(jobs)} | Deduplicated: {result['deduplicated_count']}")
    print(f"New: {result['new_count']} | Existing: {result['existing_count']} | Rejected new: {result['rejected_count']}")
    print(f"Strong: {result['strong_count']} | Review: {result['review_count']} | Run: {result['status']}")
    print(f"Studies: {len(studies)} found | {len(result['new_studies'])} new/changed useful")
    print(f"Email: {result['email_status']} | Tracker: {'saved' if commit else 'unchanged'}")
    print(f"Report: {output_dir / 'jobs.md'}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="Save discoveries to trackers")
    parser.add_argument("--dry-run", action="store_true", help="Explicit preview; no state changes or email")
    parser.add_argument("--prepare-email", action="store_true", help="Persist outbox for delivery after Git push; requires --commit")
    parser.add_argument("--deliver-pending", action="store_true", help="Deliver only the persisted outbox")
    parser.add_argument("--send-email", action="store_true", help="Explicitly send real email; requires --commit")
    parser.add_argument("--fixture", type=Path, help="Offline fixture instead of live search")
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--max-job-details", type=int, help="Preview only: limit job detail requests; reports PARTIAL")
    args = parser.parse_args()
    if args.dry_run and (args.commit or args.send_email or args.prepare_email or args.deliver_pending):
        parser.error("--dry-run cannot save or send")
    if args.prepare_email and (not args.commit or args.send_email or args.fixture):
        parser.error("--prepare-email requires --commit and live data, without --send-email")
    if args.deliver_pending and (args.commit or args.send_email or args.prepare_email or args.fixture):
        parser.error("--deliver-pending is a separate operation")
    if args.send_email and (not args.commit or args.fixture):
        parser.error("--send-email requires --commit and cannot be used with --fixture")
    if args.max_job_details is not None and (args.commit or args.max_job_details < 0):
        parser.error("--max-job-details must be non-negative and cannot be used with --commit")
    output = args.output_dir or (args.data_dir if args.commit else ROOT / "preview")
    if not args.commit and output.resolve() == args.data_dir.resolve():
        parser.error("Dry-run output must be separate from the data directory")
    try:
        load_dotenv(ROOT / ".env")
        result = deliver_pending(args.data_dir) if args.deliver_pending else run(args.data_dir, output, commit=args.commit, mail=args.send_email,
                     fixture=args.fixture, max_job_details=args.max_job_details, prepare=args.prepare_email)
    except KeyboardInterrupt:
        print("\nAjo keskeytetty (Ctrl+C).")
        return 130
    except Exception as error:
        details = traceback.format_exc()
        print(f"Run status: FAILED — {error}")
        try:
            output.mkdir(parents=True, exist_ok=True)
            (output / "error.log").write_text(details, encoding="utf-8")
            (output / "source_health.json").write_text(json.dumps({"status": "FAILED", "error": str(error)}, ensure_ascii=False), encoding="utf-8")
            print(f"Koko traceback: {output / 'error.log'}")
        except OSError as log_error:
            print(f"Virhelokia ei voitu tallentaa: {log_error}")
        return 1
    return 1 if result["status"] == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
