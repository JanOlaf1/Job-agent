import csv
import hashlib
import html
import json
import re
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# TIEDOSTOT JA YLEISET ASETUKSET
# ============================================================

TRACKER_FILE = Path("job_tracker.csv")
ARCHIVE_FILE = Path("job_archive.csv")
OUTPUT_FILE = Path("jobs.md")
RELEVANT_FILE = Path("relevant_jobs.csv")
SOURCE_HEALTH_FILE = Path("source_health.json")

TIMEOUT = 20
SEARCH_DELAY = 0.45
DETAIL_DELAY = 0.25

# Sähköpostiin vain tämän rajan ylittävät uudet paikat.
RELEVANT_SCORE_MIN = 45

# jobs.md:hen myös "harkitse"-osio.
MAYBE_SCORE_MIN = 35

# Automaattinen arkistointi:
# - HAETTU -> 60 päivän jälkeen, ellei tila ole HAASTATTELU/TARJOUS
# - UUSI/TARKISTETTU -> jos ei ole löytynyt 30 päivään
APPLIED_ARCHIVE_DAYS = 60
STALE_ARCHIVE_DAYS = 30


# ============================================================
# OMA PROFIILI / PISTEYTYS
# ============================================================

PROFILE_SKILLS = {
    "java": 4,
    "python": 4,
    "sql": 3,
    "c#": 2,
    "react": 4,
    "javascript": 4,
    "typescript": 4,
    "html": 2,
    "css": 2,
    "tailwind": 2,
    "power platform": 3,
}

PROFILE_EXPERIENCE = {
    "b2b": 5,
    "uusasiakashankinta": 5,
    "new customer acquisition": 5,
    "prospecting": 4,
    "prospektointi": 4,
    "account management": 4,
    "asiakkuus": 3,
    "crm": 4,
    "solution sales": 4,
    "ratkaisumyy": 4,
    "it services": 4,
    "it-palvel": 4,
    "ict": 3,
    "telecom": 3,
    "telecommunication": 3,
    "customer success": 3,
    "asiakaspalvelu": 2,
    "customer service": 2,
}

JUNIOR_FRIENDLY = [
    "junior",
    "trainee",
    "graduate",
    "entry level",
    "entry-level",
    "early career",
    "academy",
    "vastavalmist",
    "0-2 years",
    "0–2 years",
    "1-2 years",
    "1–2 years",
]

EDUCATION_TERMS = [
    "bachelor",
    "tradenomi",
    "business information technology",
    "information technology",
    "computer science",
    "software development",
    "ohjelmistokehitys",
    "tietojenkäsittely",
    "korkeakoulututkinto",
    "university degree",
]

LANGUAGE_TERMS = [
    "finnish",
    "suomi",
    "english",
    "englanti",
]

TITLE_BONUSES = {
    "junior software developer": 40,
    "software developer": 34,
    "software engineer": 32,
    "it trainee": 40,
    "software trainee": 40,
    "graduate developer": 40,
    "test engineer": 30,
    "qa engineer": 30,
    "application specialist": 32,
    "it consultant": 32,
    "technology consultant": 30,
    "technical support specialist": 28,
    "power platform": 30,
    "account manager": 32,
    "account executive": 32,
    "sales consultant": 28,
    "sales specialist": 28,
    "business development": 30,
    "sales development": 30,
    "customer success": 28,
    "it sales": 34,
    "technical sales": 30,
    "solution advisor": 28,
    "solution consultant": 28,
}


# ============================================================
# HAKUSANAT
# ============================================================

ALL_TERMS = [
    "junior software developer",
    "software developer",
    "software engineer",
    "IT trainee",
    "graduate developer",
    "test engineer",
    "QA engineer",
    "application specialist",
    "IT consultant",
    "technical support specialist",
    "Power Platform",
    "account manager",
    "account executive",
    "B2B sales",
    "business development representative",
    "sales development representative",
    "sales consultant",
    "sales specialist",
    "IT sales",
    "customer success",
]

# LinkedIn palauttaa runsaasti päällekkäisiä osumia, joten siellä suppeampi lista.
LINKEDIN_TERMS = [
    "software developer",
    "IT trainee",
    "IT consultant",
    "application specialist",
    "account manager",
    "account executive",
    "B2B sales",
    "customer success",
]

# Indeed estää usein automaation. Jos ensimmäinen haku estyy,
# kaikki loput Indeed-haut ohitetaan automaattisesti.
INDEED_TERMS = [
    "software developer",
    "account manager",
]

# Työmarkkinatori on mukana, vaikka sen JS-pohjainen hakusivu
# voi palauttaa BeautifulSoupille 0 osumaa.
TYOMARKKINATORI_TERMS = [
    "software developer",
    "IT trainee",
    "IT consultant",
    "account manager",
    "B2B myynti",
    "customer success",
]


# ============================================================
# SUODATUS
# ============================================================

IT_WORDS = [
    "developer", "software", "ohjelmisto", "sovellus", "frontend", "backend",
    "fullstack", "full stack", "test engineer", "testaaja", "qa engineer",
    "application specialist", "sovellusasiantuntija", "järjestelmäasiantuntija",
    "system specialist", "it specialist", "ict-asiantuntija", "it consultant",
    "technical consultant", "technical support", "it support", "data analyst",
    "data engineer", "devops", "cloud", "power platform", "dynamics 365",
    "salesforce", "crm specialist",
]

SALES_WORDS = [
    "account manager", "key account manager", "account executive",
    "sales executive", "sales manager", "sales consultant", "sales specialist",
    "sales representative", "sales engineer", "technical sales",
    "solution sales", "myyntikonsultti", "myyntiasiantuntija",
    "ratkaisumyy", "tekninen myynti", "yritysmyy", "b2b",
    "business development", "sales development", "customer success",
    "customer onboarding", "commercial specialist", "business consultant",
    "asiakkuuspäällikkö", "myyntipäällikkö",
]

TOO_SENIOR = [
    "head of", "director", "vice president", "chief ", "cso", "cro",
    "toimitusjohtaja", "liiketoimintajohtaja", "myyntijohtaja",
    "kaupallinen johtaja", "country manager", "general manager",
    "principal ", "partner ", "lead developer", "lead engineer", "tech lead",
    "software architect", "solution architect", "enterprise architect",
    "senior software", "senior developer", "senior engineer",
    "senior consultant", "senior specialist",
]

UNWANTED = [
    "kuljettaja", "driver", "courier", "lähetti", "kuorma-auto",
    "varastotyöntekijä", "warehouse", "terminaalityöntekijä",
    "logistiikkityöntekijä", "logistiikkatyöntekijä", "keräilijä", "pakkaaja",
    "muuttomies", "autonasentaja", "mekaanikko", "siivooja", "cleaner",
    "kokki", "chef", "tarjoilija", "waiter", "barista",
    "lähihoitaja", "sairaanhoitaja", "rakennustyöntekijä",
]

LOW_LEVEL_SALES = [
    "kassatyöntekijä", "kassamyyjä", "cashier", "myymälämyyjä",
    "myymälätyöntekijä", "store assistant", "shop assistant",
    "retail assistant", "sales assistant", "promoottori", "promoter",
    "feissari", "varainhankkija", "ständimyyjä", "standimyyjä",
    "ovimyyjä", "door to door", "puhelinmyyjä", "telemarketer",
    "telemarketing", "ajanvaraaja",
]

UUSIMAA = [
    "helsinki", "espoo", "vantaa", "kauniainen", "kerava", "järvenpää",
    "jarvenpaa", "tuusula", "kirkkonummi", "sipoo", "nurmijärvi",
    "hyvinkää", "hyvinkaa", "lohja", "vihti", "porvoo", "uusimaa",
    "pääkaupunkiseutu", "paakaupunkiseutu", "pk-seutu",
    "helsinki metropolitan", "remote", "etätyö", "etatyö",
]

GENERIC_SALES = ["myyjä", "myyntineuvottelija", "salesperson"]

GOOD_SALES_CONTEXT = [
    "b2b", "yritys", "it ", "ict", "software", "saas", "teknologia",
    "technology", "ratkaisu", "solution", "account",
]


IGNORED_LINK_TITLES = {
    "lisää",
    "lue lisää",
    "katso",
    "avaa",
    "hae",
    "tutustu",
    "read more",
    "learn more",
    "apply",
    "view job",
    "see more",
}

# Selvästi väärät asiantuntija-alueet sinun hakuprofiiliisi.
IRRELEVANT_DOMAINS = [
    "tax & legal",
    "tax trainee",
    "legal trainee",
    "legal counsel",
    "juristi",
    "lakimies",
    "veroasiantuntija",
    "accounting trainee",
    "accounting",
    "kirjanpito",
    "bookkeeping",
    "audit trainee",
    "tilintarkastus",
    "real estate deals",
    "real estate trainee",
    "mergers & acquisitions",
    "m&a trainee",
    "deal advisory",
    "corporate finance",
    "finance trainee",
    "hr trainee",
    "human resources trainee",
    "people & culture trainee",
    "marketing trainee",
    "internal audit",
    "risk assurance",
    "strategy consulting",
    "sähkösuunnittel",
    "electrical engineer",
    "electrical design",
    "mechanical engineer",
    "mechanical design",
    "rakennutt",
    "construction",
]


# Trainee/graduate hyväksytään vain, jos ilmoituksessa on selkeä
# IT-, teknologia- tai B2B/myyntiyhteys.
TRAINEE_WORDS = [
    "trainee",
    "graduate",
    "intern",
    "internship",
    "harjoittelija",
]

STRONG_RELEVANCE_WORDS = [
    "software",
    "developer",
    "development",
    "ohjelmisto",
    "it ",
    "ict",
    "technology",
    "technical",
    "cyber",
    "cloud",
    "data",
    "ai ",
    "artificial intelligence",
    "application",
    "implementation",
    "power platform",
    "dynamics 365",
    "salesforce",
    "crm",
    "java",
    "python",
    "javascript",
    "typescript",
    "react",
    "sql",
    "b2b",
    "account manager",
    "account executive",
    "business development",
    "sales development",
    "customer success",
    "sales consultant",
    "sales specialist",
    "it sales",
    "technical sales",
]


# Hakusivulta hyväksytään vain sellaiset otsikot, jotka näyttävät oikeasti
# sinulle sopivilta työnimikkeiltä. Ympäröivä korttiteksti ei enää yksin riitä.
TARGET_ROLE_TITLES = [
    # Ohjelmistokehitys / IT
    "software developer",
    "software engineer",
    "ohjelmistokehittäjä",
    "ohjelmistosuunnittelija",
    "frontend developer",
    "front-end developer",
    "backend developer",
    "back-end developer",
    "fullstack developer",
    "full stack developer",
    "android developer",
    "ios developer",
    ".net developer",
    "application developer",
    "application specialist",
    "sovellusasiantuntija",
    "järjestelmäasiantuntija",
    "system specialist",
    "systems specialist",
    "it specialist",
    "ict specialist",
    "it-asiantuntija",
    "ict-asiantuntija",
    "it consultant",
    "ict consultant",
    "technology consultant",
    "technical consultant",
    "implementation consultant",
    "implementation specialist",
    "technical support specialist",
    "support specialist",
    "it support",
    "test engineer",
    "qa engineer",
    "software tester",
    "power platform",
    "dynamics 365",
    "crm specialist",
    "cybersecurity",
    "cyber security",
    "security analyst",

    # Kaupallinen / B2B
    "account manager",
    "key account manager",
    "account executive",
    "sales executive",
    "sales consultant",
    "sales specialist",
    "sales representative",
    "business developer",
    "business development",
    "sales development",
    "customer success",
    "customer onboarding",
    "solution advisor",
    "solution consultant",
    "solution sales",
    "myyntikonsultti",
    "myyntiasiantuntija",
    "asiakkuuspäällikkö",
    "yritysmyyjä",
    "b2b-myy",
    "b2b myy",
    "technical sales",
    "it sales",
    "ict sales",
    "sales engineer",
    "area sales manager",
    "aluemyyntipäällikkö",
]

# Pelkkä "trainee" ei kelpaa. Näiden pitää näkyä jo otsikossa.
TRAINEE_TITLE_RELEVANCE = [
    "software",
    "developer",
    "it ",
    "ict",
    "tech ",
    "technology",
    "technical",
    "cyber",
    "cloud",
    "data",
    "ai ",
    "artificial intelligence",
    "application",
    "implementation",
    "power platform",
    "dynamics",
    "salesforce",
    "crm",
    "project management",
]

# Selvästi väärät tekniset/toimialakohtaiset roolit.
IRRELEVANT_TECH_DOMAINS = [
    "sähkösuunnittel",
    "electrical designer",
    "electrical engineer",
    "electrical design",
    "mekaniikkasuunnittel",
    "mechanical engineer",
    "mechanical design",
    "rakennutt",
    "rakennussuunnittel",
    "construction",
    "civil engineer",
    "structural engineer",
    "lvi-suunnittel",
    "hvac",
    "kiinteistösuunnittel",
    "real estate",
    "geotekni",
    "geotechnical",
]

GENERIC_CATEGORY_TITLES = [
    "asennus, huolto ja korjaus",
    "asiakaspalvelu ja -tuki",
    "henkilöstöhallinto",
    "it, ict ja ohjelmistokehitys",
    "johto ja operatiivinen hallinto",
    "logistiikka, toimitusketju ja kuljetus",
    "media, markkinointi ja viestintä",
    "myynti ja liiketoiminnan kehitys",
    "projektin hallinta",
    "rakentaminen, kiinteistöt ja arkkitehtuuri",
    "ravintola, ruoka majoitus ja matkailu",
    "valmistus ja tuotanto",
    "vähittäis- ja tukkukauppa",
]


# ============================================================
# STAATTISET LÄHTEET
# ============================================================

STATIC_SOURCES = [
    {
        "name": "Jobly",
        "url": "https://www.jobly.fi/tyopaikat/it/uusimaa",
        "markers": ["/tyopaikka/"],
        "location_scoped": True,
    },
    {
        "name": "Jobly",
        "url": "https://www.jobly.fi/tyopaikat/myynti/uusimaa",
        "markers": ["/tyopaikka/"],
        "location_scoped": True,
    },
    {
        "name": "Academic Work",
        "url": "https://www.academicwork.fi/avoimet-tyopaikat/it",
        "markers": ["/avoimet-tyopaikat/j/"],
        "location_scoped": False,
    },
    {
        "name": "Academic Work",
        "url": "https://www.academicwork.fi/avoimet-tyopaikat?f=helsinki",
        "markers": ["/avoimet-tyopaikat/j/"],
        "location_scoped": False,
    },
    {
        "name": "Barona",
        "url": "https://www.baronacareers.com/fi/fi/job/helsinki",
        "markers": ["/job/"],
        "location_scoped": True,
    },
    {
        "name": "Manpower",
        "url": "https://www.manpower.fi/tyopaikka/it-ala/uusimaa",
        "markers": ["/tyopaikka/", "/job/"],
        "location_scoped": True,
    },
    {
        "name": "Eezy",
        "url": "https://tyopaikat.eezy.fi/",
        "markers": ["/jobs/", "/job/", "job="],
        "location_scoped": False,
    },
    {
        "name": "StaffPoint",
        "url": "https://www.staffpoint.fi/tyopaikat",
        "markers": ["/tyopaikat/", "/job/", "/jobs/"],
        "location_scoped": False,
    },
    {
        "name": "aTalent",
        "url": "https://atalent.fi/",
        "markers": ["/jobs/", "/job/", "/tyopaikat/", "/open-position/"],
        "location_scoped": False,
    },
    {
        "name": "The Hub",
        "url": "https://thehub.io/jobs/location/finland",
        "markers": ["/jobs/"],
        "location_scoped": False,
    },
    {
        "name": "MMA",
        "url": "https://tyopaikat.mma.fi/",
        "markers": ["/job/", "/jobs/", "/tyopaikka/"],
        "location_scoped": False,
    },
    {
        "name": "Work in Finland",
        "url": "https://www.workinfinland.com/en/open-jobs/?category=ict%2Csoftware-development",
        "markers": [],
        "location_scoped": False,
    },
    {
        "name": "Work in Finland",
        "url": "https://www.workinfinland.com/en/open-jobs/?category=sales",
        "markers": [],
        "location_scoped": False,
    },
]


# ============================================================
# TRACKER-KENTÄT
# ============================================================

TRACKER_FIELDS = [
    "job_id",
    "title",
    "company",
    "location",
    "category",
    "score",
    "score_reasons",
    "sources",
    "urls",
    "date_posted",
    "deadline",
    "first_seen",
    "last_seen",
    "status",
    "applied_date",
    "notes",
]

ALLOWED_STATUSES = {
    "UUSI",
    "TARKISTETTU",
    "HAETTU",
    "OHITA",
    "HAASTATTELU",
    "TARJOUS",
}


# ============================================================
# HTTP
# ============================================================

def make_session():
    session = requests.Session()

    retry = Retry(
        total=2,
        backoff_factor=0.8,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )

    session.mount("https://", HTTPAdapter(max_retries=retry))

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124 Safari/537.36"
        ),
        "Accept-Language": "fi-FI,fi;q=0.9,en;q=0.8",
    })

    return session


SESSION = make_session()


# ============================================================
# PERUSAPURIT
# ============================================================

def now_helsinki():
    try:
        return datetime.now(ZoneInfo("Europe/Helsinki"))
    except Exception:
        return datetime.now()


def today_string():
    return now_helsinki().strftime("%Y-%m-%d")


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def html_to_text(value):
    if not value:
        return ""

    soup = BeautifulSoup(html.unescape(str(value)), "html.parser")
    return clean_text(soup.get_text(" ", strip=True))


def normalize(value):
    value = clean_text(value).lower()
    value = re.sub(r"[^a-z0-9åäö+#]+", " ", value)
    return clean_text(value)


def has_any(text, words):
    text = text.lower()
    return any(word.lower() in text for word in words)


def safe_date(value):
    if not value:
        return ""

    value = str(value).strip()

    # ISO / ISO timestamp
    match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    if match:
        return match.group(1)

    # dd.mm.yyyy
    match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", value)
    if match:
        day, month, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    return ""


def category_for(title, text):
    combined = f"{title} {text}"
    is_it = has_any(combined, IT_WORDS)
    is_sales = has_any(combined, SALES_WORDS)

    if is_it and is_sales:
        return "IT + MYYNTI"
    if is_it:
        return "IT"
    if is_sales:
        return "MYYNTI"

    return None


def looks_like_target_role_title(title):
    title_low = clean_text(title).lower()

    if not title_low:
        return False

    if title_low in IGNORED_LINK_TITLES:
        return False

    if title_low in GENERIC_CATEGORY_TITLES:
        return False

    if has_any(title_low, IRRELEVANT_TECH_DOMAINS):
        return False

    if has_any(title_low, IRRELEVANT_DOMAINS):
        return False

    # Senior-roolit pois jo ennen ilmoituksen avaamista.
    # Jos samassa ilmoituksessa tarjotaan nimenomaan myös junior-tasoa,
    # sitä ei poisteta automaattisesti.
    if "senior" in title_low and "junior" not in title_low:
        return False

    if has_any(title_low, [
        "lead software",
        "lead developer",
        "lead engineer",
        "architect",
        "principal",
        "head of",
        "director",
        "vice president",
        "chief ",
    ]):
        return False

    # Trainee/intern hyväksytään vain, kun jo otsikko kertoo
    # selkeästä IT-/teknologiayhteydestä.
    if has_any(title_low, TRAINEE_WORDS):
        return has_any(title_low, TRAINEE_TITLE_RELEVANCE)

    return has_any(title_low, TARGET_ROLE_TITLES)


def is_relevant_profile_job(title, text):
    combined = f"{title} {text}".lower()

    # Otsikon on ensin näytettävä oikealta työnimikkeeltä.
    # Tämä poistaa yritysten nimet, kategoriat ja hakusivun navigaation.
    if not looks_like_target_role_title(title):
        return False

    # Selvästi väärät alat pois myös koko ilmoitustekstin perusteella.
    if has_any(combined, IRRELEVANT_DOMAINS):
        return False

    if has_any(combined, IRRELEVANT_TECH_DOMAINS):
        return False

    # Trainee/graduate/intern ei yksin riitä.
    if has_any(title.lower(), TRAINEE_WORDS):
        if not has_any(title.lower(), TRAINEE_TITLE_RELEVANCE):
            return False

    return category_for(title, text) is not None


def is_excluded(title, context):
    title_low = title.lower()

    if has_any(title_low, TOO_SENIOR):
        return True

    if has_any(title_low, UNWANTED):
        return True

    if has_any(title_low, LOW_LEVEL_SALES):
        return True

    if has_any(title_low, GENERIC_SALES):
        if not has_any(f"{title} {context}", GOOD_SALES_CONTEXT):
            return True

    return False


def location_ok(context):
    return has_any(context, UUSIMAA)


def get_context(element):
    best = clean_text(element.get_text(" ", strip=True))
    parent = element.parent

    for _ in range(4):
        if parent is None:
            break

        text = clean_text(parent.get_text(" ", strip=True))

        if len(best) < len(text) <= 1600:
            best = text

        parent = parent.parent

    return best


def looks_like_job_url(url, markers):
    low = url.lower()

    if any(marker.lower() in low for marker in markers):
        return True

    generic = [
        "/job/",
        "/jobs/",
        "/tyopaikka/",
        "/position/",
        "/vacancy/",
        "/career/",
    ]

    return any(item in low for item in generic)


def valid_candidate(title, context, location_scoped):
    if len(title) < 4:
        return False

    if title.lower().strip() in IGNORED_LINK_TITLES:
        return False

    if not is_relevant_profile_job(title, context):
        return False

    if is_excluded(title, context):
        return False

    if not location_scoped and not location_ok(context):
        return False

    return True


# ============================================================
# URL:N KANONISOINTI
# ============================================================

def canonicalize_url(source, url):
    p = urlsplit(url)
    scheme = p.scheme or "https"
    host = p.netloc.lower()
    path = re.sub(r"/+$", "", p.path)

    if source == "LinkedIn":
        match = re.search(r"/jobs/view/(?:.*-)?(\d+)$", path)

        if match:
            job_number = match.group(1)
            return f"https://fi.linkedin.com/jobs/view/{job_number}"

        return urlunsplit((scheme, host, path, "", ""))

    if source == "Indeed":
        query = parse_qs(p.query)

        if "jk" in query and query["jk"]:
            return f"https://fi.indeed.com/viewjob?jk={query['jk'][0]}"

    # Seurantaparametrit pois muilta sivuilta.
    return urlunsplit((scheme, host, path, "", ""))


def url_job_id(source, url):
    raw = f"{source}|{url}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:18]


# ============================================================
# HAKUSIVUJEN PARSIMINEN
# ============================================================

def make_candidate(source_name, title, url, context):
    canonical_url = canonicalize_url(source_name, url)

    return {
        "source": source_name,
        "title": clean_text(title),
        "url": canonical_url,
        "context": clean_text(context),
        "url_id": url_job_id(source_name, canonical_url),
    }


def find_job_link_near_heading(heading, source):
    parent = heading.parent

    for _ in range(4):
        if parent is None:
            break

        for link in parent.find_all("a", href=True):
            url = urljoin(source["url"], link["href"])

            if looks_like_job_url(url, source["markers"]):
                return url

        parent = parent.parent

    return None


def parse_search_page(source):
    response = SESSION.get(source["url"], timeout=TIMEOUT)

    if response.status_code in (403, 429):
        raise PermissionError(
            f"HTTP {response.status_code}, automaattinen haku estetty"
        )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    candidates = {}

    for link in soup.find_all("a", href=True):
        title = clean_text(link.get_text(" ", strip=True))
        context = get_context(link)
        url = urljoin(source["url"], link["href"])

        if not valid_candidate(title, context, source["location_scoped"]):
            continue

        if not looks_like_job_url(url, source["markers"]):
            continue

        candidate = make_candidate(source["name"], title, url, context)
        candidates[candidate["url_id"]] = candidate

    for heading in soup.find_all(["h2", "h3", "h4"]):
        title = clean_text(heading.get_text(" ", strip=True))
        context = get_context(heading)

        if not valid_candidate(title, context, source["location_scoped"]):
            continue

        url = find_job_link_near_heading(heading, source)

        if not url:
            continue

        candidate = make_candidate(source["name"], title, url, context)
        candidates[candidate["url_id"]] = candidate

    return list(candidates.values())


# ============================================================
# JOBPOSTING / KOKO ILMOITUKSEN LUKEMINEN
# ============================================================

def iter_jsonld_objects(value):
    if isinstance(value, dict):
        yield value

        for item in value.values():
            yield from iter_jsonld_objects(item)

    elif isinstance(value, list):
        for item in value:
            yield from iter_jsonld_objects(item)


def find_jobposting_jsonld(soup):
    for script in soup.find_all(
        "script",
        attrs={"type": "application/ld+json"},
    ):
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        for obj in iter_jsonld_objects(data):
            obj_type = obj.get("@type")

            if obj_type == "JobPosting":
                return obj

            if isinstance(obj_type, list) and "JobPosting" in obj_type:
                return obj

    return {}


def extract_company(jobposting, soup):
    organization = jobposting.get("hiringOrganization", {})

    if isinstance(organization, dict):
        name = clean_text(organization.get("name"))

        if name:
            return name

    meta_candidates = [
        ("meta", {"property": "og:site_name"}),
        ("meta", {"name": "author"}),
    ]

    for tag_name, attrs in meta_candidates:
        tag = soup.find(tag_name, attrs=attrs)

        if tag and tag.get("content"):
            value = clean_text(tag["content"])

            if value and len(value) < 120:
                return value

    return ""


def extract_location(jobposting):
    locations = jobposting.get("jobLocation", [])

    if isinstance(locations, dict):
        locations = [locations]

    parts = []

    for location in locations:
        if not isinstance(location, dict):
            continue

        address = location.get("address", {})

        if not isinstance(address, dict):
            continue

        for key in [
            "addressLocality",
            "addressRegion",
            "addressCountry",
        ]:
            value = address.get(key)

            if isinstance(value, dict):
                value = value.get("name")

            if value:
                parts.append(clean_text(value))

    # säilytä järjestys, poista duplikaatit
    unique = list(dict.fromkeys(parts))
    return ", ".join(unique)


def extract_deadline_from_text(text):
    patterns = [
        r"(?:hakuaika päättyy|haku päättyy|apply by|deadline)"
        r"[^0-9]{0,30}(\d{1,2}\.\d{1,2}\.\d{4})",
        r"(?:hakuaika päättyy|haku päättyy)"
        r"[^0-9]{0,30}(\d{1,2}\.\d{1,2}\.)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)

        if not match:
            continue

        value = match.group(1)

        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.", value):
            day, month = re.findall(r"\d+", value)
            year = now_helsinki().year
            return f"{year}-{int(month):02d}-{int(day):02d}"

        parsed = safe_date(value)

        if parsed:
            return parsed

    return ""


def fetch_job_details(candidate):
    result = {
        "title": candidate["title"],
        "company": "",
        "location": "",
        "date_posted": "",
        "deadline": "",
        "description": candidate["context"],
        "detail_ok": False,
    }

    try:
        response = SESSION.get(candidate["url"], timeout=TIMEOUT)

        if response.status_code in (403, 429):
            return result

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        jobposting = find_jobposting_jsonld(soup)

        if jobposting:
            result["title"] = clean_text(
                jobposting.get("title")
            ) or result["title"]

            result["company"] = extract_company(jobposting, soup)
            result["location"] = extract_location(jobposting)
            result["date_posted"] = safe_date(
                jobposting.get("datePosted")
            )
            result["deadline"] = safe_date(
                jobposting.get("validThrough")
            )
            result["description"] = html_to_text(
                jobposting.get("description")
            ) or result["description"]

        else:
            page_text = clean_text(soup.get_text(" ", strip=True))

            if page_text:
                result["description"] = page_text[:25000]

            result["company"] = extract_company({}, soup)

        if not result["deadline"]:
            result["deadline"] = extract_deadline_from_text(
                result["description"]
            )

        result["detail_ok"] = True

    except Exception:
        # Detail-sivun epäonnistuminen ei koskaan kaada koko ajoa.
        pass

    return result


# ============================================================
# PISTEYTYS
# ============================================================

def score_job(title, description):
    combined = f"{title} {description}".lower()
    title_low = title.lower()

    score = 0
    reasons = []

    category = category_for(title, description)

    if category == "IT + MYYNTI":
        score += 15
        reasons.append("+15 yhdistää IT:n ja kaupallisen taustan")
    elif category == "IT":
        score += 10
        reasons.append("+10 sopii IT-koulutukseen")
    elif category == "MYYNTI":
        score += 10
        reasons.append("+10 sopii kaupalliseen kokemukseen")

    # Työnimike
    title_bonus = 0
    title_reason = ""

    for phrase, points in TITLE_BONUSES.items():
        if phrase in title_low and points > title_bonus:
            title_bonus = points
            title_reason = phrase

    if title_bonus:
        score += title_bonus
        reasons.append(f"+{title_bonus} sopiva työnimike ({title_reason})")

    # Junior-ystävällisyys
    if has_any(combined, JUNIOR_FRIENDLY):
        score += 15
        reasons.append("+15 junior/trainee/graduate-taso")

    # Teknologiat
    skill_points = 0
    matched_skills = []

    for skill, points in PROFILE_SKILLS.items():
        if skill in combined:
            skill_points += points
            matched_skills.append(skill)

    skill_points = min(skill_points, 25)

    if skill_points:
        score += skill_points
        reasons.append(
            f"+{skill_points} teknologiat: "
            + ", ".join(matched_skills[:6])
        )

    # Kokemus
    exp_points = 0
    matched_exp = []

    for phrase, points in PROFILE_EXPERIENCE.items():
        if phrase in combined:
            exp_points += points
            matched_exp.append(phrase)

    exp_points = min(exp_points, 28)

    if exp_points:
        score += exp_points
        reasons.append(
            f"+{exp_points} kokemusosumat: "
            + ", ".join(matched_exp[:5])
        )

    # Koulutus
    if has_any(combined, EDUCATION_TERMS):
        score += 8
        reasons.append("+8 koulutustausta sopii")

    # Kielet
    if has_any(combined, LANGUAGE_TERMS):
        score += 4
        reasons.append("+4 kielivaatimukset sopivat")

    # Kokemusvuodet: miinukset korkeista vaatimuksista
    years = []

    for match in re.finditer(
        r"(\d+)\s*\+?\s*(?:years?|vuotta|vuoden)\s+(?:of\s+)?experience",
        combined,
    ):
        try:
            years.append(int(match.group(1)))
        except ValueError:
            pass

    for match in re.finditer(
        r"(?:vähintään|minimum|min\.?)\s*(\d+)\s*(?:vuotta|years?)",
        combined,
    ):
        try:
            years.append(int(match.group(1)))
        except ValueError:
            pass

    max_years = max(years) if years else 0

    if max_years >= 7:
        score -= 35
        reasons.append(f"-35 vaatii noin {max_years}+ vuotta kokemusta")
    elif max_years >= 5:
        score -= 25
        reasons.append(f"-25 vaatii noin {max_years}+ vuotta kokemusta")
    elif max_years >= 3:
        score -= 12
        reasons.append(f"-12 vaatii noin {max_years}+ vuotta kokemusta")

    if has_any(combined, TOO_SENIOR):
        score -= 25
        reasons.append("-25 ilmoituksessa senior/lead-tason merkkejä")

    score = max(0, min(100, score))

    return score, reasons


# ============================================================
# HAKULÄHTEIDEN RAKENTAMINEN
# ============================================================

def build_sources():
    sources = []

    for term in ALL_TERMS:
        params = {
            "alue": "uusimaa",
            "haku": term,
            "search_also_descr": "1",
        }

        sources.append({
            "name": "Duunitori",
            "url": f"https://duunitori.fi/tyopaikat?{urlencode(params)}",
            "markers": ["/tyopaikat/tyo/"],
            "location_scoped": True,
        })

    for term in LINKEDIN_TERMS:
        params = {
            "keywords": term,
            "location": "Helsinki, Uusimaa, Finland",
        }

        sources.append({
            "name": "LinkedIn",
            "url": f"https://fi.linkedin.com/jobs/search/?{urlencode(params)}",
            "markers": ["/jobs/view/"],
            "location_scoped": True,
        })

    for term in INDEED_TERMS:
        params = {
            "q": term,
            "l": "Uusimaa",
        }

        sources.append({
            "name": "Indeed",
            "url": f"https://fi.indeed.com/jobs?{urlencode(params)}",
            "markers": ["/viewjob", "/rc/clk", "/pagead/clk"],
            "location_scoped": True,
        })

    for term in TYOMARKKINATORI_TERMS:
        params = {"q": term}

        sources.append({
            "name": "Työmarkkinatori",
            "url": (
                "https://tyomarkkinatori.fi/henkiloasiakkaat/"
                f"avoimet-tyopaikat?{urlencode(params)}"
            ),
            "markers": ["/avoimet-tyopaikat/"],
            "location_scoped": False,
        })

    return sources + STATIC_SOURCES


# ============================================================
# LÄHTEIDEN AJO
# ============================================================

def collect_candidates():
    sources = build_sources()
    candidates = {}
    stats = {}
    blocked_sources = set()

    for i, source in enumerate(sources, start=1):
        name = source["name"]

        stat = stats.setdefault(
            name,
            {
                "ok": 0,
                "failed": 0,
                "skipped": 0,
                "raw_jobs": 0,
                "last_error": "",
            },
        )

        if name in blocked_sources:
            stat["skipped"] += 1
            continue

        print(f"[{i}/{len(sources)}] {name}")

        try:
            found = parse_search_page(source)

            for candidate in found:
                candidates[candidate["url_id"]] = candidate

            stat["ok"] += 1
            stat["raw_jobs"] += len(found)

            print(f"  -> {len(found)} hakutulosta")

        except PermissionError as error:
            stat["failed"] += 1
            stat["last_error"] = str(error)
            blocked_sources.add(name)
            print(
                f"  -> LÄHDE ESTI HAUN. "
                f"Loput {name}-haut ohitetaan."
            )

        except requests.Timeout as error:
            stat["failed"] += 1
            stat["last_error"] = f"Timeout: {error}"
            print("  -> TIMEOUT, jatketaan")

        except requests.RequestException as error:
            stat["failed"] += 1
            stat["last_error"] = str(error)
            print(f"  -> VERKKOVIRHE, jatketaan: {error}")

        except Exception as error:
            stat["failed"] += 1
            stat["last_error"] = str(error)
            print(f"  -> PARSINTAVIRHE, jatketaan: {error}")

        time.sleep(SEARCH_DELAY)

    return list(candidates.values()), stats


# ============================================================
# ILMOITUSTEN RIKASTAMINEN
# ============================================================

def enrich_candidates(candidates):
    enriched = []

    total = len(candidates)

    for index, candidate in enumerate(candidates, start=1):
        print(
            f"Luetaan ilmoitus {index}/{total}: "
            f"{candidate['title'][:70]}"
        )

        details = fetch_job_details(candidate)

        title = details["title"] or candidate["title"]
        description = details["description"] or candidate["context"]
        category = category_for(title, description)

        # Jos koko ilmoitus paljastaa roolin epärelevantiksi, pudotetaan pois.
        if not is_relevant_profile_job(title, description):
            continue

        if category is None:
            continue

        if is_excluded(title, description):
            continue

        score, reasons = score_job(title, description)

        enriched.append({
            "url_id": candidate["url_id"],
            "source": candidate["source"],
            "url": candidate["url"],
            "title": title,
            "company": details["company"],
            "location": details["location"],
            "date_posted": details["date_posted"],
            "deadline": details["deadline"],
            "category": category,
            "score": score,
            "score_reasons": reasons,
        })

        time.sleep(DETAIL_DELAY)

    return enriched


# ============================================================
# ERI SIVUSTOJEN DUPLIKAATTIEN YHDISTÄMINEN
# ============================================================

def same_cross_source_job(a, b):
    company_a = normalize(a.get("company"))
    company_b = normalize(b.get("company"))

    if not company_a or not company_b:
        return False

    if company_a != company_b:
        return False

    title_a = normalize(a.get("title"))
    title_b = normalize(b.get("title"))

    similarity = SequenceMatcher(
        None,
        title_a,
        title_b,
    ).ratio()

    if similarity < 0.90:
        return False

    # Jos molemmissa on sijainti, estä ilmeisen eri sijaintien yhdistäminen.
    loc_a = normalize(a.get("location"))
    loc_b = normalize(b.get("location"))

    if loc_a and loc_b:
        if (
            SequenceMatcher(None, loc_a, loc_b).ratio() < 0.55
            and not has_any(f"{loc_a} {loc_b}", ["remote", "etä"])
        ):
            return False

    return True


def merge_two_jobs(target, other):
    target["sources"] = list(dict.fromkeys(
        target.get("sources", []) + other.get("sources", [])
    ))

    target["urls"] = list(dict.fromkeys(
        target.get("urls", []) + other.get("urls", [])
    ))

    if not target.get("company") and other.get("company"):
        target["company"] = other["company"]

    if not target.get("location") and other.get("location"):
        target["location"] = other["location"]

    if not target.get("date_posted") and other.get("date_posted"):
        target["date_posted"] = other["date_posted"]

    # Käytä aikaisinta deadlinea, jos useita lähteitä antaa eri päivät.
    deadlines = [
        value for value in [
            target.get("deadline"),
            other.get("deadline"),
        ]
        if value
    ]

    if deadlines:
        target["deadline"] = min(deadlines)

    # Paras pistemäärä voittaa.
    if int(other.get("score", 0)) > int(target.get("score", 0)):
        target["score"] = other["score"]
        target["score_reasons"] = other["score_reasons"]

    return target


def cross_source_deduplicate(jobs):
    groups = []

    for job in jobs:
        prepared = dict(job)
        prepared["sources"] = [job["source"]]
        prepared["urls"] = [job["url"]]

        matched = False

        for group in groups:
            if same_cross_source_job(group, prepared):
                merge_two_jobs(group, prepared)
                matched = True
                break

        if not matched:
            groups.append(prepared)

    return groups


# ============================================================
# TRACKER
# ============================================================

def load_csv_rows(path):
    rows = {}

    if not path.exists():
        return rows

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)

            for row in reader:
                job_id = clean_text(row.get("job_id"))

                if job_id:
                    rows[job_id] = row

    except Exception as error:
        print(f"VAROITUS: {path} ei auennut: {error}")

    return rows


def load_tracker():
    rows = load_csv_rows(TRACKER_FILE)

    for row in rows.values():
        status = clean_text(row.get("status") or "UUSI").upper()

        if status not in ALLOWED_STATUSES:
            status = "UUSI"

        row["status"] = status
        row["notes"] = row.get("notes") or ""
        row["applied_date"] = row.get("applied_date") or ""

        # Kun käyttäjä muuttaa tilaksi HAETTU ja applied_date on tyhjä,
        # päivämäärä täytetään automaattisesti seuraavalla ajolla.
        if status == "HAETTU" and not row["applied_date"]:
            row["applied_date"] = today_string()

    return rows


def find_existing_match(job, tracker):
    company = normalize(job.get("company"))
    title = normalize(job.get("title"))

    # 1) URL löytyy jo trackerista
    for job_id, row in tracker.items():
        urls = [
            item.strip()
            for item in (row.get("urls") or "").split(" || ")
            if item.strip()
        ]

        if any(url in job.get("urls", []) for url in urls):
            return job_id

    # 2) sama yritys + hyvin samankaltainen työnimike
    if company:
        best_id = None
        best_ratio = 0.0

        for job_id, row in tracker.items():
            if normalize(row.get("company")) != company:
                continue

            ratio = SequenceMatcher(
                None,
                normalize(row.get("title")),
                title,
            ).ratio()

            if ratio > best_ratio:
                best_ratio = ratio
                best_id = job_id

        if best_ratio >= 0.90:
            return best_id

    return None


def create_job_id(job):
    company = normalize(job.get("company"))
    title = normalize(job.get("title"))

    if company:
        raw = f"{company}|{title}".encode("utf-8")
    else:
        raw = f"{job['sources'][0]}|{job['urls'][0]}".encode("utf-8")

    return hashlib.sha256(raw).hexdigest()[:18]


def merge_into_tracker(tracker, jobs):
    today = today_string()
    new_ids = []

    for job in jobs:
        existing_id = find_existing_match(job, tracker)

        if existing_id:
            row = tracker[existing_id]

            old_sources = [
                item.strip()
                for item in (row.get("sources") or "").split(" | ")
                if item.strip()
            ]

            old_urls = [
                item.strip()
                for item in (row.get("urls") or "").split(" || ")
                if item.strip()
            ]

            sources = list(dict.fromkeys(
                old_sources + job["sources"]
            ))

            urls = list(dict.fromkeys(
                old_urls + job["urls"]
            ))

            row.update({
                "title": job["title"],
                "company": job.get("company") or row.get("company", ""),
                "location": job.get("location") or row.get("location", ""),
                "category": job["category"],
                "score": str(job["score"]),
                "score_reasons": " ; ".join(job["score_reasons"]),
                "sources": " | ".join(sources),
                "urls": " || ".join(urls),
                "date_posted": job.get("date_posted") or row.get("date_posted", ""),
                "deadline": job.get("deadline") or row.get("deadline", ""),
                "last_seen": today,
            })

        else:
            job_id = create_job_id(job)

            tracker[job_id] = {
                "job_id": job_id,
                "title": job["title"],
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "category": job["category"],
                "score": str(job["score"]),
                "score_reasons": " ; ".join(job["score_reasons"]),
                "sources": " | ".join(job["sources"]),
                "urls": " || ".join(job["urls"]),
                "date_posted": job.get("date_posted", ""),
                "deadline": job.get("deadline", ""),
                "first_seen": today,
                "last_seen": today,
                "status": "UUSI",
                "applied_date": "",
                "notes": "",
            }

            new_ids.append(job_id)

    return tracker, new_ids


def parse_tracker_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def archive_old_rows(tracker):
    today = now_helsinki().date()
    archive = load_csv_rows(ARCHIVE_FILE)

    to_archive = []

    for job_id, row in tracker.items():
        status = row.get("status", "UUSI")
        applied_date = parse_tracker_date(row.get("applied_date", ""))
        last_seen = parse_tracker_date(row.get("last_seen", ""))

        should_archive = False

        # Haettu työ 60 päivän jälkeen pois aktiivisesta trackerista.
        # Haastattelu/tarjous ei arkistoidu automaattisesti.
        if status == "HAETTU" and applied_date:
            if today - applied_date >= timedelta(days=APPLIED_ARCHIVE_DAYS):
                should_archive = True

        # Uudet/tarkistetut vanhat ilmoitukset eivät täytä tracker.csv:tä ikuisesti.
        if status in {"UUSI", "TARKISTETTU", "OHITA"} and last_seen:
            if today - last_seen >= timedelta(days=STALE_ARCHIVE_DAYS):
                should_archive = True

        if should_archive:
            archived = dict(row)
            archived["archived_date"] = today.isoformat()
            archive[job_id] = archived
            to_archive.append(job_id)

    for job_id in to_archive:
        tracker.pop(job_id, None)

    save_archive(archive)

    return tracker, len(to_archive)


def save_archive(rows):
    if not rows:
        return

    fields = TRACKER_FIELDS + ["archived_date"]

    with open(ARCHIVE_FILE, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()

        for row in sorted(
            rows.values(),
            key=lambda item: item.get("archived_date", ""),
            reverse=True,
        ):
            writer.writerow({
                field: row.get(field, "")
                for field in fields
            })


def save_tracker(tracker):
    with open(TRACKER_FILE, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=TRACKER_FIELDS)
        writer.writeheader()

        rows = sorted(
            tracker.values(),
            key=lambda row: (
                int(row.get("score") or 0),
                row.get("last_seen", ""),
            ),
            reverse=True,
        )

        for row in rows:
            writer.writerow({
                field: row.get(field, "")
                for field in TRACKER_FIELDS
            })


def save_relevant_jobs(tracker, new_ids):
    rows = []

    for job_id in new_ids:
        row = tracker.get(job_id)

        if not row:
            continue

        if int(row.get("score") or 0) >= RELEVANT_SCORE_MIN:
            rows.append(row)

    with open(RELEVANT_FILE, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=TRACKER_FIELDS)
        writer.writeheader()

        for row in sorted(
            rows,
            key=lambda item: int(item.get("score") or 0),
            reverse=True,
        ):
            writer.writerow({
                field: row.get(field, "")
                for field in TRACKER_FIELDS
            })


# ============================================================
# RAPORTTI
# ============================================================

def primary_url(row):
    urls = [
        item.strip()
        for item in (row.get("urls") or "").split(" || ")
        if item.strip()
    ]

    return urls[0] if urls else ""


def write_job(file, row):
    score = int(row.get("score") or 0)

    file.write(f"## {score}/100 — {row['title']}\n\n")

    if row.get("company"):
        file.write(f"**Yritys:** {row['company']}  \n")

    if row.get("location"):
        file.write(f"**Sijainti:** {row['location']}  \n")

    file.write(f"**Tila:** {row.get('status', 'UUSI')}  \n")
    file.write(f"**Kategoria:** {row.get('category', '')}  \n")
    file.write(f"**Lähteet:** {row.get('sources', '')}  \n")
    file.write(f"**Löydetty:** {row.get('first_seen', '')}  \n")

    if row.get("date_posted"):
        file.write(f"**Julkaistu:** {row['date_posted']}  \n")

    if row.get("deadline"):
        file.write(f"**Deadline:** {row['deadline']}  \n")

    reasons = [
        item.strip()
        for item in (row.get("score_reasons") or "").split(" ; ")
        if item.strip()
    ]

    if reasons:
        file.write("**Miksi sopii:**  \n")

        for reason in reasons[:6]:
            file.write(f"- {reason}\n")

    if row.get("notes"):
        file.write(f"\n**Omat muistiinpanot:** {row['notes']}  \n")

    url = primary_url(row)

    if url:
        file.write(f"\n[Avaa työpaikkailmoitus]({url})\n")

    file.write("\n---\n\n")


def write_output(tracker, new_ids, stats, archived_count):
    now = now_helsinki()

    new_rows = [
        tracker[job_id]
        for job_id in new_ids
        if job_id in tracker
    ]

    strong = [
        row for row in new_rows
        if int(row.get("score") or 0) >= RELEVANT_SCORE_MIN
    ]

    maybe = [
        row for row in new_rows
        if MAYBE_SCORE_MIN <= int(row.get("score") or 0) < RELEVANT_SCORE_MIN
    ]

    processes = [
        row for row in tracker.values()
        if row.get("status") in {"HAETTU", "HAASTATTELU", "TARJOUS"}
    ]

    strong.sort(key=lambda row: int(row.get("score") or 0), reverse=True)
    maybe.sort(key=lambda row: int(row.get("score") or 0), reverse=True)
    processes.sort(key=lambda row: row.get("last_seen", ""), reverse=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        file.write("# Työpaikka-agentti\n\n")
        file.write(f"**Haku suoritettu:** {now.strftime('%d.%m.%Y %H:%M')}  \n")
        file.write(f"**Uusia {RELEVANT_SCORE_MIN}+ osumia:** {len(strong)}  \n")
        file.write(f"**Uusia {MAYBE_SCORE_MIN}–{RELEVANT_SCORE_MIN - 1} osumia:** {len(maybe)}  \n")
        file.write(f"**Aktiivisia hakuprosesseja:** {len(processes)}  \n")
        file.write(f"**Tällä ajolla arkistoitu:** {archived_count}\n\n")

        file.write(
            "> Muokkaa `job_tracker.csv`-tiedostosta vain kenttiä "
            "`status`, `applied_date` ja `notes`. "
            "Kun tila on HAETTU ja applied_date jätetään tyhjäksi, "
            "päivämäärä täyttyy seuraavalla ajolla.\n\n"
        )

        file.write(f"# 🟢 Uudet vahvat osumat ({RELEVANT_SCORE_MIN}+)\n\n")

        if not strong:
            file.write(f"Ei uusia {RELEVANT_SCORE_MIN}+ osumia.\n\n")

        for row in strong:
            write_job(file, row)

        file.write(f"# 🟡 Harkitse ({MAYBE_SCORE_MIN}–{RELEVANT_SCORE_MIN - 1})\n\n")

        if not maybe:
            file.write("Ei uusia harkittavia osumia.\n\n")

        for row in maybe[:50]:
            write_job(file, row)

        file.write("# 📌 Omat hakemukset ja prosessit\n\n")

        if not processes:
            file.write("Ei merkittyjä hakuprosesseja.\n\n")

        for row in processes:
            write_job(file, row)

        file.write("# 🧪 Lähteiden tila\n\n")

        for name in sorted(stats):
            stat = stats[name]

            if stat["failed"] == 0:
                icon = "✅"
            elif stat["ok"] > 0:
                icon = "⚠️"
            else:
                icon = "❌"

            file.write(
                f"- {icon} **{name}**: "
                f"{stat['raw_jobs']} hakutulosta, "
                f"{stat['ok']} onnistui, "
                f"{stat['failed']} epäonnistui, "
                f"{stat['skipped']} ohitettiin"
            )

            if stat.get("last_error"):
                file.write(f" — {stat['last_error']}")

            file.write("\n")


def save_source_health(stats):
    payload = {
        "run_time": now_helsinki().isoformat(),
        "sources": stats,
    }

    with open(SOURCE_HEALTH_FILE, "w", encoding="utf-8") as file:
        json.dump(
            payload,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# MAIN
# ============================================================

def main():
    print("\n========== JOB AGENT V8 ==========\n")

    tracker = load_tracker()

    candidates, stats = collect_candidates()

    print(
        f"\nHakusivuilta löytyi {len(candidates)} "
        f"uniikkia URL-pohjaista ehdokasta."
    )

    enriched = enrich_candidates(candidates)

    print(
        f"\nIlmoitustekstin jälkeen jäljellä "
        f"{len(enriched)} relevanttia ehdokasta."
    )

    merged = cross_source_deduplicate(enriched)

    print(
        f"Eri sivustojen duplikaattien yhdistämisen jälkeen "
        f"{len(merged)} työpaikkaa."
    )

    tracker, new_ids = merge_into_tracker(tracker, merged)

    tracker, archived_count = archive_old_rows(tracker)

    save_tracker(tracker)
    save_relevant_jobs(tracker, new_ids)
    save_source_health(stats)
    write_output(tracker, new_ids, stats, archived_count)

    print("\n==================================")
    print(f"Uusia työpaikkoja trackerissa: {len(new_ids)}")
    print(
        f"Uusia {RELEVANT_SCORE_MIN}+ pisteen työpaikkoja: "
        f"{sum(1 for job_id in new_ids if job_id in tracker and int(tracker[job_id].get('score') or 0) >= RELEVANT_SCORE_MIN)}"
    )
    print(f"Arkistoitu tällä ajolla: {archived_count}")
    print(f"Tracker: {TRACKER_FILE.resolve()}")
    print(f"Arkisto: {ARCHIVE_FILE.resolve()}")
    print(f"Raportti: {OUTPUT_FILE.resolve()}")
    print(f"Sähköpostiin menevät: {RELEVANT_FILE.resolve()}")
    print("==================================\n")


if __name__ == "__main__":
    main()
