"""Reports and email share the tracker result and the same linked cards."""
from .tracker import primary_url, split_values


STATUS_LABELS = {
    "SUCCESS": "Haku valmis", "DEGRADED": "Haku jäi osittaiseksi",
    "FAILED": "Haku epäonnistui", "HEALTHY": "Toimii",
    "EMPTY": "Ei hakutuloksia", "BLOCKED": "Lähde esti haun",
    "PARTIAL": "Osa tuloksista jäi lukematta",
    "STRONG": "Vahva osuma", "REVIEW": "Harkitse",
    "OPEN": "Haku avoinna", "UPCOMING": "Haku avautuu myöhemmin",
    "CLOSED": "Haku päättynyt", "UNKNOWN": "Tieto puuttuu",
}


def status_label(value):
    return STATUS_LABELS.get(value, value or "Tieto puuttuu")


def job_summary(result):
    """Never present missing source coverage as a confirmed zero result."""
    if result["status"] == "FAILED":
        return "Haku epäonnistui — uusien työpaikkojen määrää ei voida varmistaa."
    if result["new_jobs"]:
        return f"Sinulle on {len(result['new_jobs'])} uutta sopivaa työpaikkaa."
    if result["status"] == "DEGRADED":
        return "Ei uusia sopivia työpaikkoja luetuista tuloksista. Osa lähteistä jäi tarkistamatta."
    return "Ei uusia sopivia työpaikkoja tällä hakukerralla."


def selection_note(result):
    note = "Uusi = sopiva ilmoitus, jota ei ole vielä merkitty lähetetyksi. Mukana voi olla aiemmalla ajolla löytyneitä ilmoituksia."
    if result.get("min_relevance_score") is not None:
        note += f" Työpaikkojen lähetysraja: {result['min_relevance_score']}/100."
    return note + " Pisteet kuvaavat profiilisi ja ilmoituksen vastaavuutta, eivät työllistymisen todennäköisyyttä."


def format_card(row):
    """Render one job or study with its direct link and all scoring caveats."""
    lines = [f"### {row.get('score', 0)}/100 — {row.get('classification', '')} — {row['title']}", "",
             row.get("company") or row.get("institution") or "Organisaatio tuntematon",
             row.get("location") or "Sijainti tuntematon"]
    for key, label in [("date_posted", "Julkaistu"), ("summary", "Yhteenveto"), ("study_type", "Koulutustyyppi"), ("scope", "Laajuus"),
                       ("start_date", "Ajankohta"), ("price", "Hinta"),
                       ("remote_type", "Toteutus"), ("eligibility", "Hakukelpoisuus"),
                       ("application_status", "Haku"), ("deadline", "Hakuaika päättyy"),
                       ("change", "Muutos"), ("sources", "Lähteet")]:
        if row.get(key):
            lines.append(f"{label}: {row[key]}")
    lines += ["", "Miksi / huomioitavaa:"]
    lines += [f"- {reason}" for reason in split_values(row.get("score_reasons"), " ; ")]
    url = primary_url(row)
    lines += ["", f"[Avaa ilmoitus](<{url}>)" if url else "Linkki puuttuu — historiallinen tietue", ""]
    return "\n".join(lines)


def digest(result, job_limit=None, study_limit=None):
    """The concise shared new-items section; no independent new-item filtering."""
    sources = result.get("sources", {})
    working = sum(s["status"] in {"HEALTHY", "EMPTY"} for s in sources.values())
    lines = ["# JOB AGENT", "", f"Haku: {result['run_time']}", f"Ajotila: {status_label(result['status'])} ({result['status']})",
             "", job_summary(result), "",
             f"Uusia sopivia työpaikkoja: {len(result['new_jobs'])}",
             f"Tällä ajolla luettuja hakutuloksia: {result.get('normalized_count', 0)} | Lähetysrajan täyttäviä työpaikkoja: {result.get('relevant_count', len(result['new_jobs']))}",
             f"Vahvat: {result['strong_count']} | Harkitse: {result['review_count']}",
             f"Lähteet: {working}/{len(sources)} toiminnassa", "", selection_note(result), "", "## UUDET TYÖPAIKAT", ""]
    if not result["new_jobs"]:
        lines.append(job_summary(result))
    lines += [format_card(row) for row in result["new_jobs"][:job_limit]]
    studies = result.get("new_studies", [])
    if studies:
        lines += [f"## KOULUTUKSET — {len(studies)} UUTTA / MUUTTUNUTTA", ""]
        lines += [format_card(row) for row in studies[:study_limit]]
    problems = [f"- {name}: {s['status']} — {s.get('last_error', '')}" for name, s in sources.items()
                if s["status"] not in {"HEALTHY", "EMPTY"}]
    if problems:
        lines += ["", "Lähteiden ongelmat:"] + problems
    if result.get("observations"):
        lines += ["", "Työmarkkinan havainnot:"] + ["- " + text for text in result["observations"]]
    return "\n".join(lines) + "\n"


def write_reports(directory, result, tracker, studies=None):
    """Write current digest, job history and separate study history."""
    text = digest(result) + "\n## TYÖPAIKKAHISTORIA\n\n"
    text += "Kaikki löydöt säilyvät job_tracker.csv:ssä. Alla vähintään LOW-tasoiset sekä omat hakuprosessit.\n\n"
    for row in sorted(tracker.values(), key=lambda r: int(r.get("score") or 0), reverse=True):
        if int(row.get("score") or 0) >= 25 or row.get("status") in {"HAETTU", "HAASTATTELU", "TARJOUS"}:
            text += format_card(row) + f"Tila: {row.get('status', '')}\nMuistiinpanot: {row.get('notes', '')}\n\n"
    (directory / "jobs.md").write_text(text, encoding="utf-8")
    if studies is not None:
        text = "# Koulutukset — koko Suomi\n\nHakukelpoisuus tarkistetaan aina virallisesta ilmoituksesta.\n\n"
        text += "\n".join(format_card(row) for row in sorted(studies.values(), key=lambda r: int(r.get("score") or 0), reverse=True)
                          if row.get("classification") != "REJECTED")
        (directory / "studies.md").write_text(text, encoding="utf-8")
