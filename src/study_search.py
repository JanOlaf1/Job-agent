"""Opintopolku external API: Finland-wide studies, separate from job models/scoring."""
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from .config import (REQUEST_DELAY, STUDY_API, STUDY_MAX_DETAILS, STUDY_MAX_PAGES,
                     STUDY_PAGE_SIZE, STUDY_SUBJECTS, STUDY_TERMS, USER_AGENT)
from .job_search import fetch_page
from .scoring import classify_score, has

STUDY_FIELDS = "study_id title institution location study_type scope remote_type eligibility application_status application_periods deadline score classification score_reasons sources urls first_seen last_seen detail_checked status notes".split()


def localized(value):
    if isinstance(value, dict):
        return value.get("fi") or value.get("en") or value.get("sv") or ""
    return str(value or "")


def plain(value):
    return BeautifulSoup(localized(value), "html.parser").get_text(" ", strip=True)


def study_type(title, code, metadata):
    if has(title, ["doctoral", "tohtori", "tohtoriohjelma", "phd"]):
        return "DOCTORAL"
    if has(title, ["bachelor", "kandidaatti", "kandidaatin"]) and has(title, ["master", "master's", "maisteri", "maisterin"]):
        return "BACHELOR + MASTER"
    if has(title, ["yamk", "ylempi amk", "master", "master's", "maisteri", "maisteriohjelma"]):
        return "MASTER / YAMK"
    if metadata.get("isAvoinKorkeakoulutus"):
        return "OPEN HIGHER EDUCATION / " + ("MODULE" if code == "kk-opintokokonaisuus" else "COURSE")
    return {"kk-opintojakso": "COURSE", "kk-opintokokonaisuus": "MODULE",
            "erikoistumiskoulutus": "SPECIALISATION", "muu": "CONTINUING EDUCATION",
            "amk": "UAS DEGREE", "yo": "UNIVERSITY DEGREE", "amm": "VOCATIONAL"}.get(code, code or "UNKNOWN")


def application_info(periods, now=None):
    """Use explicit application intervals, retaining exact deadline time and all rounds."""
    now = now or datetime.now(ZoneInfo("Europe/Helsinki"))
    parsed = []
    for period in periods:
        start, end = period.get("alkaa", ""), period.get("paattyy", "")
        if not start:
            continue
        try:
            begin = datetime.fromisoformat(start)
            finish = datetime.fromisoformat(end) if end else None
            begin = begin if begin.tzinfo else begin.replace(tzinfo=ZoneInfo("Europe/Helsinki"))
            finish = finish if finish is None or finish.tzinfo else finish.replace(tzinfo=ZoneInfo("Europe/Helsinki"))
        except ValueError:
            continue
        parsed.append((begin, finish, end))
    active = [p for p in parsed if p[0] <= now and (p[1] is None or now <= p[1])]
    future = [p for p in parsed if p[0] > now]
    if active:
        return "OPEN", min((p[2] for p in active if p[2]), default="")
    if future:
        return "UPCOMING", min(future, key=lambda p: p[0])[2]
    return ("CLOSED", max((p[2] for p in parsed), default="")) if parsed else ("UNKNOWN", "")


def normalize_study(hit, offering, details=None):
    """Normalize documented API fields; never infer online delivery from missing data."""
    details = details or {}
    metadata = details.get("metadata") or {}
    title = localized(details.get("nimi") or offering.get("toteutusNimi") or hit.get("nimi"))
    oid = offering["toteutusOid"]
    teaching = metadata.get("opetus") or {}
    formats = " ".join(localized(x.get("nimi")) for x in (teaching.get("opetustapa") or []))
    formats += " " + plain(teaching.get("opetustapaKuvaus"))
    online = has(formats, ["online", "verkko-opetus", "etäopetus", "distance learning"])
    contact = has(formats, ["lähiopetus", "contact teaching", "on campus"])
    hybrid = has(formats, ["monimuoto-opetus", "monimuoto", "hybrid", "blended"])
    remote = "HYBRID" if hybrid or online and contact else "ONLINE" if online else "ON_SITE" if contact else "UNKNOWN"
    timetable = " ".join(localized(x.get("nimi")) for x in (teaching.get("opetusaika") or []))
    if has(timetable, ["iltaopetus", "evening", "part-time", "osa-aikainen"]):
        remote += " / PART_TIME_OR_EVENING"
    periods = []
    if metadata.get("hakuaika"):
        periods.append(metadata["hakuaika"])
    for option in details.get("hakukohteet") or []:
        periods.extend(option.get("hakuajat") or [])
    application_status, deadline = application_info(periods)
    if not periods and isinstance(details.get("hakuAuki"), bool):
        application_status = "OPEN" if details["hakuAuki"] else "CLOSED"
    requirements = []
    for option in details.get("hakukohteet") or []:
        requirements += [localized(v.get("nimi")) for v in (option.get("pohjakoulutusvaatimus") or [])]
    eligibility = "TARKISTA: " + ", ".join(dict.fromkeys(requirements)) if requirements else "UNKNOWN — tarkista esitiedot ja hakukelpoisuus"
    scope = metadata.get("opintojenLaajuusNumero") or hit.get("opintojenLaajuusNumero")
    if scope is None:
        low, high = hit.get("opintojenLaajuusNumeroMin"), hit.get("opintojenLaajuusNumeroMax")
        scope = str(low) if low == high and low is not None else f"{low}–{high}" if low is not None else ""
    unit = localized((metadata.get("opintojenLaajuusyksikko") or hit.get("opintojenLaajuusyksikko") or {}).get("nimi"))
    prices = []
    for fee in teaching.get("maksut") or []:
        kind = fee.get("maksullisuustyyppi", "")
        amount = fee.get("maksunMaara")
        if kind == "maksuton":
            prices.append("Maksuton")
        elif kind:
            prices.append(kind + (f": {amount} (lähteen summa; tarkista ehdot)" if amount is not None else " — tarkista summa ja ehdot"))
    price_description = plain(teaching.get("maksullisuusKuvaus"))
    if price_description:
        prices.append(price_description[:300])
    starts = []
    for option in details.get("hakukohteet") or []:
        season = option.get("paateltyAlkamiskausi") or {}
        date = option.get("paateltyAlkamisajankohta") or {}
        if date.get("henkilokohtainenSuunnitelma"):
            starts.append("Henkilökohtaisen suunnitelman mukaan")
        elif season.get("kausiUri") and season.get("vuosi"):
            name = {"kausi_s": "Syksy", "kausi_k": "Kevät"}.get(season["kausiUri"].split("#")[0], season["kausiUri"])
            starts.append(f"{name} {season['vuosi']}")
        elif date.get("pvm") and date.get("alkamiskausityyppi") != "alkamiskausi ja -vuosi":
            starts.append(date["pvm"])
    return {"study_id": oid, "title": title, "institution": localized(offering.get("oppilaitosNimi")),
            "location": ", ".join(localized(c.get("nimi")) for c in (offering.get("kunnat") or [])) or "Finland / UNKNOWN",
            "description": plain(metadata.get("kuvaus") or hit.get("kuvaus")),
            "study_type": study_type(title, hit.get("koulutustyyppi"), metadata),
            "scope": f"{scope} {unit}".strip() if scope else "UNKNOWN", "remote_type": remote,
            "summary": plain(metadata.get("kuvaus") or hit.get("kuvaus"))[:450],
            "price": " ; ".join(dict.fromkeys(prices)) or "UNKNOWN — tarkista koulutuksen sivulta",
            "start_date": " ; ".join(dict.fromkeys(starts)) or "UNKNOWN — tarkista koulutuksen sivulta",
            "eligibility": eligibility, "application_status": application_status, "deadline": deadline,
            "application_periods": json.dumps(sorted({(p.get('alkaa', ''), p.get('paattyy', '')) for p in periods}), ensure_ascii=False),
            "sources": "Opintopolku", "urls": f"https://opintopolku.fi/konfo/fi/toteutus/{oid}",
            "detail_ok": bool(details),
            "detail_checked": datetime.now(ZoneInfo("Europe/Helsinki")).isoformat() if details else ""}


def score_study(study):
    """Subject 40, background 20, flexibility 15, level 15, open application 10."""
    text = f"{study['title']} {study.get('description', '')}"
    subjects = [name for name, words in STUDY_SUBJECTS.items() if has(text, words)]
    reasons = []
    score = 0
    if subjects:
        score += 40
        reasons.append("+40 kiinnostava aihe: " + ", ".join(subjects))
        score += 20 if any(s in subjects for s in ["IT", "BUSINESS"]) else 10
        reasons.append("+20 rakentaa IT/liiketalous-taustalle" if score == 60 else "+10 vastaa yhteiskunnallista kiinnostusta")
    flexible = any(s in study.get("remote_type", "") for s in ["ONLINE", "HYBRID", "PART_TIME"])
    if flexible:
        score += 15
        reasons.append("+15 joustava toteutus; tarkista pakolliset lähipäivät")
    kind = study.get("study_type", "UNKNOWN")
    if kind == "MASTER / YAMK":
        score += 15
        reasons.append("+15 jatkotutkinto; soveltuva tutkinto ja mahdollinen työkokemusvaatimus tarkistettava")
    elif any(t in kind for t in ["MODULE", "CONTINUING", "SPECIALISATION"]):
        score += 10
        reasons.append("+10 osaamista täydentävä kokonaisuus")
    elif "COURSE" in kind:
        score += 5
        reasons.append("+5 yksittäinen kurssi, ei kokonainen tutkinto")
    if study.get("application_status") == "OPEN":
        score += 10
        reasons.append("+10 haku avoinna")
    if study.get("application_status") == "CLOSED":
        score -= 20
        reasons.append("-20 haku päättynyt; seuraa seuraavaa hakukierrosta")
    if kind == "DOCTORAL":
        score -= 100
        reasons.append("-100 tohtoriopinnot eivät ole nykyisen BBA-taustan suora jatko")
    if not subjects:
        score = 0
        reasons.append("ei toivottua opiskelualaa")
    reasons.append("? hakukelpoisuutta ei vahvistettu automaattisesti")
    if study.get("remote_type", "UNKNOWN") == "UNKNOWN":
        reasons.append("? etätoteutus tuntematon; paikkakunta ei estä opiskeluvaihtoehtoa")
    score = max(0, min(100, score))
    return dict(study, score=score, classification=classify_score(score), score_reasons=" ; ".join(reasons))


def search_studies(terms=None, session=None, previous=None):
    """Search nationwide via documented external routes; bounded requests report truncation."""
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    stat = {"status": "EMPTY", "ok": 0, "raw_jobs": 0, "detail_ok": 0, "failed": 0, "last_error": ""}
    found, studies = {}, []
    blocked = False
    for term in terms if terms is not None else STUDY_TERMS:
        if blocked:
            break
        try:
            for page in range(1, STUDY_MAX_PAGES + 1):
                time.sleep(REQUEST_DELAY)
                response = fetch_page(session, STUDY_API + "/search/toteutukset-koulutuksittain?" +
                                      requests.compat.urlencode({"keyword": term, "page": page, "size": STUDY_PAGE_SIZE, "lng": "fi"}))
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get("hits"), list) or not isinstance(data.get("total"), int):
                    raise ValueError("Unexpected Opintopolku search schema")
                stat["ok"] += 1
                for hit in data["hits"]:
                    for offering in hit.get("toteutukset") or []:
                        try:
                            normalize_study(hit, offering)
                            found[offering["toteutusOid"]] = (hit, offering)
                        except (ValueError, KeyError, TypeError, AttributeError):
                            stat["failed"] += 1
                            stat["last_error"] = "Malformed study search item skipped"
                if page * STUDY_PAGE_SIZE >= data["total"]:
                    break
                if page == STUDY_MAX_PAGES:
                    stat["failed"] += 1
                    stat["last_error"] = "Search page limit reached; coverage is partial"
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError, PermissionError) as error:
            stat["failed"] += 1
            stat["last_error"] = str(error)
            blocked = isinstance(error, PermissionError)
    stat["raw_jobs"] = len(found)
    print(f"[Studies] {len(found)} toteutusta; luetaan enintään {STUDY_MAX_DETAILS} lisätietosivua.", flush=True)
    # Read likely relevant offerings first; retain the rest as uncertain search-card data.
    previous = previous or {}
    ordered = sorted(found.values(), key=lambda pair: (
        previous.get(pair[1]["toteutusOid"], {}).get("detail_checked", ""),
        -score_study(normalize_study(*pair))["score"]))
    for index, (hit, offering) in enumerate(ordered):
        if index < STUDY_MAX_DETAILS and index % 25 == 0:
            print(f"[Studies] Lisätiedot {index + 1}/{min(len(ordered), STUDY_MAX_DETAILS)}", flush=True)
        details = None
        if not blocked and index < STUDY_MAX_DETAILS:
            try:
                time.sleep(REQUEST_DELAY)
                details = fetch_page(session, STUDY_API + "/toteutus/" + offering["toteutusOid"] +
                                     "?koulutus=true&hakukohteet=true&haut=true").json()
                if not isinstance(details, dict) or details.get("oid") != offering["toteutusOid"]:
                    raise ValueError("Unexpected Opintopolku detail schema")
                normalize_study(hit, offering, details)
                stat["detail_ok"] += 1
            except (requests.RequestException, ValueError, PermissionError, TypeError, AttributeError, KeyError) as error:
                details = None
                stat["failed"] += 1
                stat["last_error"] = str(error)
                blocked = isinstance(error, PermissionError)
        else:
            stat["failed"] += 1
            if not blocked:
                stat["last_error"] = "Detail limit reached; some eligibility/deadlines remain unknown"
        studies.append(normalize_study(hit, offering, details))
    stat["status"] = ("BLOCKED" if blocked and not stat["ok"] else "PARTIAL" if stat["ok"] and stat["failed"]
                      else "FAILED" if stat["failed"] else "HEALTHY" if found else "EMPTY")
    return studies, {"Opintopolku": stat}
