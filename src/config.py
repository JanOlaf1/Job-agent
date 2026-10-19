"""Profile in config/profile.json; adapter limits and role vocabulary live here."""

import json
import os
from pathlib import Path

PROFILE_PATH = Path(__file__).resolve().parents[1] / "config" / "profile.json"
def load_profile(path=PROFILE_PATH):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        for key in ("target_roles", "secondary_roles", "skills", "strong_skills", "locations", "exclude_keywords", "training_interests", "skill_watchlist"):
            if not isinstance(value.get(key), list) or any(not isinstance(s, str) or not s.strip() for s in value[key]):
                raise ValueError(f"{key} must be a list of nonempty strings")
        if not isinstance(value.get("training_digest_limit"), int) or not 1 <= value["training_digest_limit"] <= 10:
            raise ValueError("training_digest_limit must be 1–10")
        for key in ("min_relevance_score", "min_training_score"):
            if not isinstance(value.get(key), int) or not 0 <= value[key] <= 100:
                raise ValueError(f"{key} must be 0–100")
        if not isinstance(value.get("send_empty_digest"), bool):
            raise ValueError("send_empty_digest must be true or false")
        return value
    except (OSError, ValueError, AttributeError) as error:
        raise ValueError(f"Invalid profile {path}: {error}") from None


PROFILE = load_profile()


def digest_settings():
    """Read runtime overrides after .env loading, with explicit validation."""
    settings = {}
    for env, key in [("MIN_RELEVANCE_SCORE", "min_relevance_score"),
                     ("MIN_TRAINING_SCORE", "min_training_score")]:
        try:
            value = int(os.environ.get(env) or PROFILE[key])
        except (TypeError, ValueError):
            raise ValueError(f"{env}: expected an integer from 0 to 100") from None
        if not 0 <= value <= 100:
            raise ValueError(f"{env}: expected an integer from 0 to 100")
        settings[key] = value
    empty = str(os.environ.get("SEND_EMPTY_DIGEST") or PROFILE["send_empty_digest"]).lower()
    if empty not in {"true", "false"}:
        raise ValueError("SEND_EMPTY_DIGEST: expected true or false")
    settings["send_empty_digest"] = empty == "true"
    return settings

STRONG_SCORE_MIN = 65
REVIEW_SCORE_MIN = 40  # Myös vanhan trackerin 42–44 pisteen roolit näkyvät.
LOW_SCORE_MIN = 25
TIMEOUT = 20
REQUEST_DELAY = 1.0
USER_AGENT = "PersonalJobAgent/1.0"
LAURA_PAGE_SIZE = 30
LAURA_MAX_PAGES = 10
JOBLY_MAX_PAGES = 5

JOB_TERMS = PROFILE["target_roles"] + PROFILE["secondary_roles"]
UUSIMAA = PROFILE["locations"]
UNWANTED = PROFILE["exclude_keywords"]
SALES = ["sales", "myynti", "myyjä", "account manager", "account executive", "b2b",
         "business development", "customer success", "asiakkuus", "sdr", "bdr",
         "customer manager", "client manager", "asiakkuuspäällikkö", "asiakaspäällikkö",
         "myyntipäällikkö", "myyntineuvottelija", "myyntiedustaja", "myyntiasiantuntija",
         "asiakasvastaava", "ratkaisumyynti", "yritysmyynti"]
CROSSOVER = ["solution consultant", "solutions consultant", "solution advisor", "presales",
             "sales engineer", "implementation", "onboarding", "application consultant",
             "application specialist", "it consultant", "ict consultant", "technology consultant",
             "crm consultant", "power platform", "dynamics", "customer solutions",
             "technical customer success", "sovellusasiantuntija",
             "käyttöönottoasiantuntija", "ratkaisuasiantuntija", "ratkaisukonsultti",
             "sovelluskonsultti", "tekninen asiakastuki"]
SOFTWARE = ["developer", "software engineer", "software architect", "ohjelmistokehittäjä",
            "ohjelmistosuunnittelija", "programmer", "frontend", "backend", "full stack"]
IT = SOFTWARE + ["it support", "technical support", "it specialist", "it trainee", "qa",
                 "test engineer", "data", "cloud", "cybersecurity", "ict", "tietotekniikka",
                 "lähituki", "käyttötuki", "it-tuki", "tietohallinto", "ohjelmistotestaaja",
                 "testausasiantuntija", "tietoturva", "service desk", "helpdesk",
                 "järjestelmäasiantuntija", "it-asiantuntija"]
TECH = ["software", "saas", "technology", "technical", "it", "ict", "cloud", "crm",
        "power platform", "dynamics", "teknologia", "it-palvelut"]
JUNIOR = ["junior", "trainee", "graduate", "entry level", "entry-level", "early career",
          "academy", "vastavalmistunut", "harjoittelija", "no experience required"]

# Opintopolun dokumentoitu ulkoinen rajapinta; ei sijaintirajausta.
STUDY_API = "https://opintopolku.fi/konfo-backend/external"
STUDY_SUBJECTS = {
    "IT": ["information technology", "information systems", "computer science", "software",
           "programming", "tekoäly", "artificial intelligence", "data", "cybersecurity", "cloud",
           "tietojenkäsittely", "tietojenkäsittelytiede", "tietojärjestelmätiede", "tietotekniikka",
           "ohjelmointi", "digital business", "business technology"],
    "BUSINESS": ["sales", "myynti", "business", "liiketalous", "liiketoiminta", "marketing",
                 "markkinointi", "leadership", "johtaminen", "entrepreneurship", "yrittäjyys",
                 "customer experience", "kauppatieteet"],
    "SOCIAL": ["political science", "social sciences", "public administration", "public policy",
               "international relations", "governance", "valtiotieteet", "yhteiskuntatieteet",
               "politiikka", "hallintotieteet"],
}
STUDY_TERMS = PROFILE["training_interests"]
STUDY_PAGE_SIZE = 20
STUDY_MAX_PAGES = 3
STUDY_MAX_DETAILS = 100  # Muut löydöt säilyvät, mutta puuttuvat tiedot merkitään.
