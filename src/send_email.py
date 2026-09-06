import csv
import json
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


RELEVANT_FILE = Path("relevant_jobs.csv")
TRACKER_FILE = Path("job_tracker.csv")
REPORT_FILE = Path("jobs.md")
SOURCE_HEALTH_FILE = Path("source_health.json")

MAX_JOBS_IN_EMAIL = 30
TOP_TRACKER_JOBS = 5


def now_helsinki():
    try:
        return datetime.now(ZoneInfo("Europe/Helsinki"))
    except Exception:
        return datetime.now()


def load_csv(path):
    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def load_new_jobs():
    rows = load_csv(RELEVANT_FILE)

    rows.sort(
        key=lambda row: int(row.get("score") or 0),
        reverse=True,
    )

    return rows


def load_tracker():
    rows = load_csv(TRACKER_FILE)

    rows.sort(
        key=lambda row: int(row.get("score") or 0),
        reverse=True,
    )

    return rows


def load_run_time():
    if not SOURCE_HEALTH_FILE.exists():
        return now_helsinki().strftime("%d.%m.%Y %H:%M")

    try:
        payload = json.loads(
            SOURCE_HEALTH_FILE.read_text(encoding="utf-8")
        )

        raw = payload.get("run_time", "")

        if raw:
            dt = datetime.fromisoformat(raw)
            return dt.strftime("%d.%m.%Y %H:%M")

    except Exception:
        pass

    return now_helsinki().strftime("%d.%m.%Y %H:%M")


def primary_url(row):
    urls = [
        item.strip()
        for item in (row.get("urls") or "").split(" || ")
        if item.strip()
    ]

    return urls[0] if urls else ""


def active_tracker_jobs(rows):
    allowed_statuses = {"UUSI", "TARKISTETTU"}

    active = [
        row for row in rows
        if (row.get("status") or "UUSI").upper() in allowed_statuses
    ]

    active.sort(
        key=lambda row: int(row.get("score") or 0),
        reverse=True,
    )

    return active


def active_processes(rows):
    process_statuses = {"HAETTU", "HAASTATTELU", "TARJOUS"}

    return [
        row for row in rows
        if (row.get("status") or "").upper() in process_statuses
    ]


def add_job_to_lines(lines, job):
    score = job.get("score", "0")
    title = job.get("title", "")
    company = job.get("company", "")
    location = job.get("location", "")
    deadline = job.get("deadline", "")
    sources = job.get("sources", "")
    url = primary_url(job)

    lines.append(f"{score}/100 — {title}")

    if company:
        lines.append(f"Yritys: {company}")

    if location:
        lines.append(f"Sijainti: {location}")

    if deadline:
        lines.append(f"Deadline: {deadline}")

    if sources:
        lines.append(f"Lähteet: {sources}")

    if url:
        lines.append(url)

    reasons = [
        item.strip()
        for item in (job.get("score_reasons") or "").split(" ; ")
        if item.strip()
    ]

    for reason in reasons[:4]:
        lines.append(f"- {reason}")

    lines.append("")


def build_body(new_jobs, tracker_rows):
    run_time = load_run_time()
    active = active_tracker_jobs(tracker_rows)
    processes = active_processes(tracker_rows)

    lines = [
        "Job Agent - päiväraportti",
        "",
        f"Haku suoritettu: {run_time}",
        f"Uusia sopivia työpaikkoja: {len(new_jobs)}",
        f"Aktiivisia työpaikkoja trackerissa: {len(active)}",
        f"Aktiivisia hakuprosesseja: {len(processes)}",
        "",
    ]

    if new_jobs:
        lines.extend([
            "UUDET SOPIVAT TYÖPAIKAT",
            "",
        ])

        for job in new_jobs[:MAX_JOBS_IN_EMAIL]:
            add_job_to_lines(lines, job)

        if len(new_jobs) > MAX_JOBS_IN_EMAIL:
            hidden = len(new_jobs) - MAX_JOBS_IN_EMAIL

            lines.extend([
                f"Sähköpostissa näytetään {MAX_JOBS_IN_EMAIL} parhaiten pisteytettyä.",
                f"Lisäksi {hidden} muuta sopivaa työpaikkaa löytyy jobs.md-liitteestä.",
                "",
            ])

    else:
        lines.extend([
            "Ei uusia sopivia työpaikkoja tällä ajolla.",
            "Haku suoritettiin silti onnistuneesti.",
            "",
        ])

        # Jos uusia ei ole, näytä muutama paras aktiivinen paikka,
        # jotta päiväraportista näkee myös mitä trackerissa on tällä hetkellä.
        if active:
            lines.extend([
                f"PARHAAT AKTIIVISET TRACKERISSA (TOP {min(TOP_TRACKER_JOBS, len(active))})",
                "",
            ])

            for job in active[:TOP_TRACKER_JOBS]:
                add_job_to_lines(lines, job)

    lines.extend([
        "Täydellinen raportti on jobs.md-liitteessä.",
        "",
        "Tämä viesti lähetetään jokaisen onnistuneen päivittäisen ajon jälkeen.",
    ])

    return "\n".join(lines)


def main():
    load_dotenv()

    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    email_to = os.environ.get("EMAIL_TO")

    if not smtp_user or not smtp_password or not email_to:
        raise RuntimeError(
            "SMTP_USER, SMTP_PASSWORD tai EMAIL_TO puuttuu. "
            "Tarkista .env tai GitHub Secrets."
        )

    new_jobs = load_new_jobs()
    tracker_rows = load_tracker()

    if new_jobs:
        subject = f"Job Agent: {len(new_jobs)} uutta sopivaa työpaikkaa"
    else:
        subject = "Job Agent: ei uusia sopivia työpaikkoja tänään"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_user
    message["To"] = email_to
    message.set_content(
        build_body(
            new_jobs,
            tracker_rows,
        )
    )

    if REPORT_FILE.exists():
        message.add_attachment(
            REPORT_FILE.read_bytes(),
            maintype="text",
            subtype="markdown",
            filename="jobs.md",
        )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(
            smtp_user,
            smtp_password,
        )

        smtp.send_message(
            message
        )

    print(
        f"Päiväraportti lähetetty osoitteeseen {email_to}. "
        f"Uusia sopivia työpaikkoja: {len(new_jobs)}."
    )


if __name__ == "__main__":
    main()
