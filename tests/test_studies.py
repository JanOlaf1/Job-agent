import json
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo
import pytest

from src.study_search import application_info, normalize_study, score_study, search_studies, study_type
from src.tracker import load_tracker, merge_studies, save_tracker
from src.study_search import STUDY_FIELDS


def study(title="Information Systems", **kwargs):
    return dict(study_id="1", title=title, location="Oulu", remote_type="UNKNOWN", study_type="MASTER / YAMK",
                urls="https://opintopolku.fi/konfo/fi/toteutus/1", **kwargs)


@pytest.mark.parametrize("title", ["Information Technology", "Sales Management", "Business Development",
                                   "Political Science", "Social Sciences", "Valtiotieteet"])
def test_subjects_and_physical_study_outside_uusimaa(title):
    assert score_study(study(title))["classification"] in {"STRONG", "REVIEW"}


def test_irrelevant_and_doctoral_rejected_online_highlighted():
    assert score_study(study("Mechanic vocational programme"))["classification"] == "REJECTED"
    doctoral = dict(study("Information Technology"), study_type="DOCTORAL")
    assert score_study(doctoral)["classification"] == "REJECTED"
    offline = score_study(study())
    online = score_study(dict(study(), remote_type="ONLINE"))
    assert online["score"] > offline["score"]
    assert study_type("Information Systems, Bachelor and Master of Science", "yo", {}) == "BACHELOR + MASTER"


def test_study_new_once_deadline_changed_once_and_notes_survive(tmp_path):
    tracker = {}
    row = score_study(study(deadline="2026-10-01T15:00", application_status="OPEN"))
    assert len(merge_studies(tracker, [row, row])) == 1
    tracker["1"]["notes"] = "Check prerequisites"
    path = tmp_path / "study.csv"
    save_tracker(path, tracker, STUDY_FIELDS)
    tracker = load_tracker(path, "study_id")
    assert tracker["1"]["deadline"] == "2026-10-01T15:00"
    assert merge_studies(tracker, [row]) == []
    changed = dict(row, deadline="2026-10-15T15:00")
    assert len(merge_studies(tracker, [changed])) == 1
    assert merge_studies(tracker, [changed]) == []
    assert tracker["1"]["notes"] == "Check prerequisites"
    assert merge_studies(tracker, [dict(changed, detail_ok=False, deadline="", application_status="UNKNOWN")]) == []
    assert tracker["1"]["deadline"] == "2026-10-15T15:00"


def test_api_fields_scope_remote_and_precise_deadline():
    hit = {"nimi": {"en": "Information Systems"}, "koulutustyyppi": "kk-opintojakso"}
    offering = {"toteutusOid": "1", "oppilaitosNimi": {"fi": "Oulun yliopisto"}, "kunnat": [{"nimi": {"fi": "Oulu"}}]}
    details = {"metadata": {"isAvoinKorkeakoulutus": True, "opintojenLaajuusNumero": 5,
                            "opintojenLaajuusyksikko": {"nimi": {"en": "ECTS"}},
                            "opetus": {"opetustapa": [{"nimi": {"fi": "Verkko-opetus"}}]},
                            "hakuaika": {"alkaa": "2020-01-01T08:00", "paattyy": "2099-10-15T15:00"}}}
    row = normalize_study(hit, offering, details)
    assert row["remote_type"] == "ONLINE"
    assert row["scope"] == "5 ECTS"
    assert "COURSE" in row["study_type"]
    assert row["deadline"] == "2099-10-15T15:00"
    assert row["application_status"] == "OPEN"
    assert normalize_study(hit, offering)["remote_type"] == "UNKNOWN"


def test_application_uses_current_round_not_old_deadline():
    periods = [{"alkaa": "2025-01-01", "paattyy": "2025-02-01"},
               {"alkaa": "2026-09-01", "paattyy": "2026-09-30T15:00"}]
    now = datetime(2026, 9, 24, tzinfo=ZoneInfo("Europe/Helsinki"))
    assert application_info(periods, now) == ("OPEN", "2026-09-30T15:00")


def test_actual_external_route_pagination_and_no_location_filter(monkeypatch):
    monkeypatch.setattr("src.study_search.time.sleep", lambda _: None)
    monkeypatch.setattr("src.study_search.STUDY_PAGE_SIZE", 1)
    session = MagicMock()
    hit = {"nimi": {"en": "Sales Management"}, "toteutukset": [{"toteutusOid": "1"}]}
    responses = []
    for data in [{"hits": [hit], "total": 2}, {"hits": [hit], "total": 2}, {"oid": "1", "metadata": {}}]:
        response = MagicMock(status_code=200, text=json.dumps(data))
        response.json.return_value = data
        responses.append(response)
    session.get.side_effect = responses
    rows, health = search_studies(["sales"], session)
    assert len(rows) == 1
    assert health["Opintopolku"]["status"] == "HEALTHY"
    calls = [c.args[0] for c in session.get.call_args_list]
    assert "/external/search/toteutukset-koulutuksittain" in calls[0]
    assert "page=2" in calls[1]
    assert all("sijainti=" not in url for url in calls)


def test_verified_price_and_season_fields_do_not_invent_exact_start_day():
    details = {"metadata": {"opetus": {"maksut": [{"maksullisuustyyppi": "maksuton"}]}},
               "hakukohteet": [{"paateltyAlkamiskausi": {"kausiUri": "kausi_s#1", "vuosi": "2026"},
                                "paateltyAlkamisajankohta": {"pvm": "2026-08-01", "alkamiskausityyppi": "alkamiskausi ja -vuosi"}}]}
    row = normalize_study({"nimi": "Python"}, {"toteutusOid": "1"}, details)
    assert row["price"] == "Maksuton"
    assert row["start_date"] == "Syksy 2026"
    empty = normalize_study({"nimi": "Python"}, {"toteutusOid": "1"})
    assert empty["price"].startswith("UNKNOWN")


def test_malformed_detail_does_not_abort_other_studies(monkeypatch):
    monkeypatch.setattr("src.study_search.time.sleep", lambda _: None)
    session = MagicMock()
    data = [{"hits": [{"nimi": "Python", "toteutukset": [{"toteutusOid": "1"}, {"toteutusOid": "2"}]}], "total": 1},
            {"oid": "1", "metadata": {"opetus": {"opetustapa": 5}}}, {"oid": "2", "metadata": {}}]
    responses = []
    for item in data:
        response = MagicMock(status_code=200, text=json.dumps(item))
        response.json.return_value = item
        responses.append(response)
    session.get.side_effect = responses
    rows, health = search_studies(["Python"], session)
    assert len(rows) == 2
    assert health["Opintopolku"]["status"] == "PARTIAL"
    assert health["Opintopolku"]["detail_ok"] == 1
