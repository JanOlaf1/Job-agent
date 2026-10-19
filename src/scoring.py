"""Selitettävä pisteytys: kukin ulottuvuus lasketaan vain kerran."""
import re

from .config import (CROSSOVER, IT, JUNIOR, LOW_SCORE_MIN, PROFILE, REVIEW_SCORE_MIN,
                     SALES, SOFTWARE, STRONG_SCORE_MIN, TECH, UNWANTED, UUSIMAA)


def has(text, terms):
    """Match words/phrases, so Java is not counted inside JavaScript."""
    return any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I) for term in terms)


def classify_score(score):
    score = int(score or 0)
    if score >= STRONG_SCORE_MIN:
        return "STRONG"
    if score >= REVIEW_SCORE_MIN:
        return "REVIEW"
    return "LOW" if score >= LOW_SCORE_MIN else "REJECTED"


def location_fit(location, description=""):
    """Unknown remains reviewable; remote must explicitly include Finland."""
    text = f"{location} {description}".lower()
    remote = has(text, ["remote", "etätyö", "etänä", "telecommute"])
    finland = has(text, ["finland", "suomi", "suomesta", "suomessa", "fi"])
    if has(text, ["us only", "usa only", "uk only", "must be based in the us", "must reside in germany"]):
        return -75, "-75 työ edellyttää asumista Suomen ulkopuolella"
    if remote and finland:
        return 10, "+10 etätyö Suomesta"
    if has(location, UUSIMAA) or (not location and has(description, UUSIMAA)):
        return 10, "+10 Uusimaa"
    if not location or location.lower() in {"unknown", "finland", "suomi", "fi"} or remote:
        return 0, "? sijainti / etätyöoikeus Suomesta varmistettava"
    return -75, "-75 sijainti Uudenmaan ulkopuolella; ei vahvistettua etätyötä Suomesta"


def score_job(job):
    """Return a copy with category, score, classification and readable reasons."""
    title = job.get("title") or ""
    description = job.get("description") or ""
    text = f"{title} {description}"
    software = has(title, SOFTWARE)
    commercial = has(text, SALES)
    technology = has(text, [term for term in TECH if term != "it"] + PROFILE["skills"]) or bool(re.search(r"\bIT\b", text))
    customer_technology_work = technology and has(description, [
        "implementation", "onboarding", "customer requirements", "customer-facing",
        "customer interviews", "client solutions", "asiakastarpeet", "asiakastyö"])
    crossover = has(title, CROSSOVER) or ((commercial and technology or customer_technology_work) and not software)
    it = software or has(text, IT)
    junior = has(title, JUNIOR) or has(description, JUNIOR + [
        "recent graduates",
        "graduates welcome", "suitable for graduates", "no experience required",
        "junior role", "entry-level role", "0-2 years", "0–2 years", "vastavalmistunut"])
    category = "IT + MYYNTI" if crossover else "IT" if it else "MYYNTI" if commercial else "MUU"
    reasons = []
    score = 0

    def add(points, reason):
        nonlocal score
        score += points
        reasons.append(f"{points:+d} {reason}")

    add(30 if category != "MUU" else 0, f"roolisopivuus: {category}")
    add(20 if crossover or commercial and not software else 15 if junior and it else 5 if it else 0,
        "kokemus: asiakas-/IT-palvelutausta" if crossover or commercial and not software
        else "kokemus: opinnot ja projektit, ei pitkää kehittäjäuraa")
    skills = [s for s in PROFILE["skills"] if has(text, [s])]
    add(10 if skills else 5 if technology else 0,
        "teknologia: " + (", ".join(skills) if skills else "IT-palvelujen ymmärrys"))
    add(15 if commercial else 0, "kaupallinen työ: myynti ja asiakkuudet")
    add(10 if crossover else 0, "teknologian ja asiakastyön yhdistelmä")
    add(5 if junior else 0, "junior-/aloitustaso")
    points, reason = location_fit(job.get("location", ""), description)
    score += points
    reasons.append(reason)

    # Kokemusvaatimukset poimitaan vain kokemuksesta puhuvista lauseista.
    years = []
    for sentence in re.split(r"[.!?\n]", description.lower()):
        if not has(sentence, ["experience", "kokemus", "kokemusta", "kokemuksen"]):
            continue
        for match in re.finditer(r"(\d+)\s*(?:[-–]\s*\d+)?\s*\+?\s*(?:years?|vuotta|vuoden)", sentence):
            years.append(int(match.group(1)))
    required = max(years, default=0)
    senior = has(title, ["senior", "lead", "principal", "architect", "director", "head of", "chief"])
    if senior:
        add(-55 if software else -30, "senioriteetti ylittää nykyisen taustan")
    if required >= 3:
        add(-50 if software else -20 if required >= 5 else -10,
            f"pyytää vähintään {required} vuotta kokemusta")
    elif required:
        reasons.append(f"? pyytää {required} vuotta kokemusta; tarkista vaadittu ala")
    if software and not junior:
        add(-15, "ohjelmistotyön junior-sopivuus ei ole vahvistettu")
    if has(title, ["myyjä", "salesperson", "sales assistant", "shop assistant"]) and not (
        technology or has(text, ["b2b", "yritysmyynti", "ratkaisumyynti", "account management"])
    ):
        add(-45, "yleinen myymälämyynti; tavoiteltu B2B-/teknologiayhteys puuttuu")
    if has(title, UNWANTED) and not software:
        add(-100, "ei kuulu toivottuihin ammatteihin")
    if not title.strip():
        add(-100, "tehtävänimike puuttuu")
    if category == "MUU":
        add(-40, "ei tunnistettua yhteyttä tavoiterooleihin")
    if job.get("detail_status") not in (None, "HEALTHY"):
        reasons.append("? koko ilmoitusta ei saatu luettua; tarkista vaatimukset linkistä")
    score = max(0, min(100, score))
    gaps = [s for s in PROFILE["skill_watchlist"] if has(text, [s])
            and not has(s, PROFILE["skills"] + PROFILE["strong_skills"])]
    if gaps:
        reasons.append("? ilmoituksessa mainitaan " + ", ".join(gaps) + "; osaamista ei ole vahvistettu profiilissa")
    return dict(job, category=category, score=score, classification=classify_score(score),
                summary=" ".join(description.split())[:450], skill_gaps=" | ".join(gaps),
                score_reasons=" ; ".join(r for r in reasons if not r.startswith("+0 ")))


def market_observations(jobs, minimum):
    """Count mentions once per deduplicated relevant posting, never infer requirements."""
    counts = {}
    for job in jobs:
        if int(job.get("score", 0)) < minimum or job.get("link_status") == "BROKEN":
            continue
        for skill in PROFILE["skill_watchlist"]:
            if has(f"{job.get('title', '')} {job.get('description', '')}", [skill]):
                counts[skill] = counts.get(skill, 0) + 1
    return [f"{skill} mainittiin {count} tämän haun relevantissa ilmoituksessa."
            for skill, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3] if count >= 2]
