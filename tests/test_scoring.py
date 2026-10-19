import pytest
from src.scoring import classify_score, score_job


@pytest.mark.parametrize("title,description,minimum,maximum", [
    ("Junior Software Developer", "Python React", 65, 100),
    ("Senior Software Developer", "Python React, 5 years of professional development experience", 0, 24),
    ("Software Developer", "Requires 3 years of software development experience", 0, 24),
    ("Solutions Consultant", "CRM customer success SaaS", 65, 100),
    ("Customer Solutions Specialist", "Implementation of SaaS for B2B customers", 65, 100),
    ("Digital Advisor", "SaaS implementation and customer requirements", 65, 100),
    ("Software Developer", "Python React; suitable for recent graduates", 65, 100),
    ("Account Manager", "B2B sales prospecting CRM", 65, 100),
    ("Driver", "Customer service B2B", 0, 24),
    ("Junior QA Engineer", "software testing", 40, 100),
])
def test_profile_fit(title, description, minimum, maximum):
    job = score_job(dict(title=title, description=description, location="Helsinki"))
    assert minimum <= job["score"] <= maximum
    assert job["score_reasons"]


@pytest.mark.parametrize("location", ["Helsinki", "Espoo", "Uusimaa", "Remote Finland", ""])
def test_accepted_or_unknown_locations(location):
    assert score_job(dict(title="Account Manager", location=location))["classification"] != "REJECTED"


def test_wrong_geography_and_synonyms():
    assert score_job(dict(title="Junior Software Developer", location="Berlin"))["score"] < 40
    a = score_job(dict(title="Account Manager", description="sales", location="Helsinki"))
    b = score_job(dict(title="Account Manager", description="sales sales myynti B2B", location="Helsinki"))
    assert a["score"] == b["score"]
    assert classify_score(44) == "REVIEW"
    assert "java," not in score_job(dict(title="Junior Developer", description="JavaScript"))["score_reasons"].lower()


@pytest.mark.parametrize("location,description", [("Berlin", "On site SaaS B2B"), ("Remote", "US only SaaS B2B")])
def test_wrong_location_cannot_be_rescued_by_strong_commercial_fit(location, description):
    assert score_job(dict(title="Solutions Consultant", location=location, description=description))["classification"] == "REJECTED"


def test_english_pronoun_it_is_not_a_technology_signal():
    job = score_job(dict(title="Account Manager", description="It is a sales role. We make it easy."))
    assert job["category"] == "MYYNTI"


@pytest.mark.parametrize("title", ["Myyjä, Silmäasema Lohja", "Myyjä K-Supermarket Postitalo", "Myyjä Finlayson Pop Up"])
def test_live_retail_examples_are_not_emailed(title):
    assert score_job(dict(title=title, location="Helsinki"))["score"] < 40


def test_generic_sales_title_with_real_b2b_context_remains_strong():
    assert score_job(dict(title="Myyjä", description="B2B ratkaisumyynti", location="Espoo"))["classification"] == "STRONG"
