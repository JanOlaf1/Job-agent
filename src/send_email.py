import csv
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv


RELEVANT_FILE = Path("relevant_jobs.csv")
REPORT_FILE = Path("jobs.md")
MAX_JOBS_IN_EMAIL = 30


def load_jobs():
    if not RELEVANT_FILE.exists():
        return []

    with open(RELEVANT_FILE, "r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    rows.sort(
        key=lambda row: int(row.get("score") or 0),
        reverse=True,
    )

    return rows


def primary_url(row):
    urls = [
        item.strip()
        for item in (row.get("urls") or "").split(" || ")
        if item.strip()
    ]

    return urls[0] if urls else ""


def build_body(jobs):
    lines = [
        f"Job Agent löysi tällä ajolla {len(jobs)} uutta 70+ pisteen työpaikkaa.",
        "",
    ]

    for job in jobs[:MAX_JOBS_IN_EMAIL]:
        score = job.get("score", "0")
        title = job.get("title", "")
        company = job.get("company", "")
        deadline = job.get("deadline", "")
        sources = job.get("sources", "")
        url = primary_url(job)

        lines.append(f"{score}/100 — {title}")

        if company:
            lines.append(f"Yritys: {company}")

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

    if len(jobs) > MAX_JOBS_IN_EMAIL:
        lines.append(
            f"Sähköpostissa näytetään ensimmäiset {MAX_JOBS_IN_EMAIL} osumaa."
        )
        lines.append("Täydellinen raportti on liitteenä jobs.md-tiedostossa.")

    return "\n".join(lines)


def main():
    load_dotenv()

    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    email_to = os.environ.get("EMAIL_TO")

    if not smtp_user or not smtp_password or not email_to:
        print(
            "Sähköpostia ei lähetetty: "
            "SMTP_USER, SMTP_PASSWORD tai EMAIL_TO puuttuu."
        )
        return

    jobs = load_jobs()

    if not jobs:
        print("Ei uusia 70+ pisteen työpaikkoja. Sähköpostia ei lähetetä.")
        return

    message = EmailMessage()
    message["Subject"] = f"Job Agent: {len(jobs)} uutta hyvää työpaikkaa"
    message["From"] = smtp_user
    message["To"] = email_to
    message.set_content(build_body(jobs))

    if REPORT_FILE.exists():
        message.add_attachment(
            REPORT_FILE.read_bytes(),
            maintype="text",
            subtype="markdown",
            filename="jobs.md",
        )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(message)

    print(f"Sähköposti lähetetty osoitteeseen {email_to}.")


if __name__ == "__main__":
    main()
