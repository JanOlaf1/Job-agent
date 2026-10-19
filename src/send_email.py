"""Email formatting and transport only. Importing this module never sends mail."""
import os
import smtplib
from email.message import EmailMessage
from html import escape

from .reporting import digest, job_summary, selection_note, status_label
from .config import PROFILE
from .tracker import primary_url, split_values


def html_digest(result):
    """Escaped, email-client friendly HTML; no untrusted HTML from job sources."""
    e = lambda value: escape(str(value or ""), quote=True)
    parts = ['<!doctype html><html lang="fi"><body style="font-family:Arial,sans-serif;color:#172b4d;max-width:760px;margin:auto;padding:24px">',
             '<h1 style="margin-bottom:8px">Job Agent · päiväraportti</h1>',
             f'<p>{e(result["run_time"])} · {e(status_label(result["status"]))}</p>',
             f'<div style="background:#edf3fb;border-left:4px solid #164c96;padding:16px"><strong>{e(job_summary(result))}</strong>'
             f'<p style="margin-bottom:0">Uusia työpaikkoja: <strong>{len(result["new_jobs"])}</strong> · Uusia tai muuttuneita koulutuksia: <strong>{len(result.get("new_studies", []))}</strong></p></div>',
             f'<p style="font-size:14px;color:#46566b">{e(selection_note(result))}</p>']
    if result["status"] in {"DEGRADED", "FAILED"}:
        parts.append('<p style="background:#fff3cd;padding:14px">Hakutulos ei ole kattava. Tarkista lähteiden ongelmat viestin lopusta.</p>')
    for label, rows, limit in [("Uudet työpaikat", result["new_jobs"], 20),
                               ("Uudet tai muuttuneet koulutukset", result.get("new_studies", []), PROFILE["training_digest_limit"])]:
        parts.append(f'<h2>{label}</h2>')
        if not rows:
            parts.append(f'<p>{e(job_summary(result)) if label == "Uudet työpaikat" else "Ei uusia tai muuttuneita koulutuksia tässä koosteessa."}</p>')
        for row in sorted(rows, key=lambda r: int(r.get("score", 0)), reverse=True)[:limit]:
            parts += ['<article style="border:1px solid #ccd5df;padding:18px;margin:16px 0">',
                      f'<h3>{e(row.get("title"))}</h3>',
                      f'<p><strong>{e(row.get("company") or row.get("institution") or "Organisaatio tuntematon")}</strong><br>{e(row.get("location") or "Sijainti tuntematon")}</p>',
                      f'<p>Sopivuus profiiliisi: <strong>{e(row.get("score", 0))}/100</strong> · {e(status_label(row.get("classification")))}</p>']
            for key, title in [("date_posted", "Julkaistu"), ("summary", "Yhteenveto"), ("remote_type", "Toteutus"),
                               ("start_date", "Ajankohta"), ("price", "Hinta"), ("deadline", "Hakuaika päättyy"),
                               ("application_status", "Haku"), ("eligibility", "Hakukelpoisuus"), ("sources", "Lähde")]:
                if row.get(key):
                    value = status_label(row[key]) if key in {"application_status", "remote_type"} else row[key]
                    parts.append(f'<p><strong>{title}:</strong> {e(value)}</p>')
            reasons = split_values(row.get("score_reasons"), " ; ")
            for title, selected in [("Miksi voisi sopia", [r for r in reasons if r.startswith("+")]),
                                    ("Puutteet / tarkistettavaa", [r for r in reasons if not r.startswith("+")])]:
                if selected:
                    parts.append(f'<strong>{title}</strong><ul>' + ''.join(f'<li>{e(r)}</li>' for r in selected) + '</ul>')
            url = primary_url(row)
            if url:
                parts.append(f'<p><a href="{e(url)}" style="background:#164c96;color:white;padding:10px 16px;display:inline-block">Katso {"koulutus" if row.get("study_id") else "työpaikka"}</a></p>')
            parts.append('</article>')
    if len(result["new_jobs"]) > 20 or len(result.get("new_studies", [])) > PROFILE["training_digest_limit"]:
        parts.append('<p>Kaikki valitut uudet löydökset ovat liitteessä new_results.md.</p>')
    if result.get("observations"):
        parts.append('<h2>Työmarkkinan havainnot</h2><ul>' + ''.join(f'<li>{e(s)}</li>' for s in result["observations"]) + '</ul>')
    parts.append('<h2>Haun kattavuus</h2>'
                 f'<p>Tällä ajolla luettuja hakutuloksia: {result.get("normalized_count", 0)}. '
                 f'Lähetysrajan täyttäviä työpaikkoja: {result.get("relevant_count", len(result["new_jobs"]))}. '
                 'Aiemmin lähetettyjä paikkoja ei luetella uudelleen. Historiassa oleva ilmoitus ei yksin takaa, että paikka on yhä avoinna.</p>')
    parts.append('<ul>' + ''.join(f'<li><strong>{e(name)}:</strong> {e(status_label(s["status"]))}' +
                 (f' — {e(s["last_error"])}' if s.get("last_error") else '') + '</li>' for name, s in result.get("sources", {}).items()) + '</ul>')
    return ''.join(parts) + '</body></html>'


def build_email(result):
    """Build a previewable message from the exact result used by reporting."""
    message = EmailMessage()
    if result.get("message_id"):
        message["Message-ID"] = result["message_id"]
    count = len(result.get("new_studies", []))
    subject = f"Job Agent: {result['strong_count']} vahvaa + {result['review_count']} harkittavaa uutta työpaikkaa"
    if not result["new_jobs"]:
        subject = "Job Agent: ei uusia sopivia työpaikkoja"
        if result["status"] == "DEGRADED":
            subject = "Job Agent: osittainen haku, ei uusia osumia luetuista tuloksista"
    if count:
        subject += f" | {count} uutta/muuttunutta koulutusta"
    if result["status"] == "FAILED":
        subject = "Job Agent: haku epäonnistui"
    elif result["status"] == "DEGRADED" and result["new_jobs"]:
        subject += " [osittainen haku]"
    message["Subject"] = subject + " — " + result["run_time"][:10]
    limit = PROFILE["training_digest_limit"]
    shortened = len(result["new_jobs"]) > 20 or count > limit
    body = digest(result, job_limit=20, study_limit=limit)
    if shortened:
        body += f"\nNäytetään enintään 20 työpaikkaa ja {limit} koulutusta. Kaikki uudet tulokset liitteessä.\n"
    message.set_content(body)
    message.add_alternative(html_digest(result), subtype="html")
    if shortened:
        message.add_attachment(digest(result).encode("utf-8"), maintype="text", subtype="markdown", filename="new_results.md")
    return message


def email_settings():
    """Validate SMTP configuration before a long search or any history writes."""
    required = {key: os.environ.get(key) for key in ("SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO")}
    missing = [key for key, value in required.items() if not value or not value.strip()]
    if missing:
        raise ValueError("Sähköpostiasetukset puuttuvat: " + ", ".join(missing) +
                         ". Täytä projektin .env tiedoston .env.example mukaan.")
    try:
        port = int(os.environ.get("SMTP_PORT", "465"))
    except ValueError:
        raise ValueError("SMTP_PORT pitää olla kokonaisluku 1–65535") from None
    if not 1 <= port <= 65535:
        raise ValueError("SMTP_PORT pitää olla kokonaisluku 1–65535")
    return dict(required, host=os.environ.get("SMTP_HOST") or "smtp.gmail.com", port=port)


def send_email(message):
    """Send a prepared message over TLS; propagate failures to the caller."""
    required = email_settings()
    message["From"] = required["SMTP_USER"]
    message["To"] = required["EMAIL_TO"]
    with smtplib.SMTP_SSL(required["host"], required["port"], timeout=30) as smtp:
        smtp.login(required["SMTP_USER"], required["SMTP_PASSWORD"])
        smtp.send_message(message)
