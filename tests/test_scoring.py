import pytest

from pipeline import config
from pipeline.models import Company, Contact, Fact, Status
from pipeline.scoring import TOTAL_WEIGHT, build_unit_model, score_all, score_company


def fact(value: object, verified: bool = True) -> Fact:
    status = Status.PUBLISHED if verified else Status.UNKNOWN
    return Fact(value=value, status=status, source_url="u", quote="q", verified=verified)


def company(cid: str = "a.de", **facts: object) -> Company:
    return Company(id=cid, name=cid, research_status="submitted", **facts)


UNITS = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
MARKET = [company(f"c{u}.de", units_managed=fact(u)) for u in UNITS]
MODEL = build_unit_model(MARKET)


def test_total_weight_matches_rulebook() -> None:
    assert TOTAL_WEIGHT == 8


def test_perfect_company_scores_94_plus_bonuses() -> None:
    c = company(
        units_managed=fact(1000),
        residential_share=fact("mainly_residential"),
        buyer_type=fact("third_party_rental"),
        software=fact("Domus"),
    )
    assert score_company(c, MODEL).lead_score == 94.0
    with_bonus = c.model_copy(update={"association": fact("VDIV"), "growth": fact("Hiring")})
    assert score_company(with_bonus, MODEL).lead_score == 100.0


def test_membership_can_only_raise_a_score() -> None:
    c = company(units_managed=fact(1000), buyer_type=fact("third_party_rental"))
    member = c.model_copy(update={"association": fact("IVD")})
    assert score_company(member, MODEL).lead_score > score_company(c, MODEL).lead_score


def test_unknown_kpis_are_left_out_not_scored_as_zero() -> None:
    small_known = company(units_managed=fact(100), buyer_type=fact("third_party_rental"))
    big_quiet = company(units_managed=fact(1000))
    result = score_company(big_quiet, MODEL)
    assert result.lead_score == 94.0 and result.completeness == pytest.approx(3 / 8)
    assert result.confidence == "Low"  # under 50% of the weight known
    assert score_company(small_known, MODEL).lead_score < result.lead_score


def test_unverified_fact_does_not_count() -> None:
    c = company(units_managed=fact(1000), software=fact("Domus", verified=False))
    assert "software" not in score_company(c, MODEL).sub_scores


def test_units_unknown_means_low_confidence_and_bands_come_from_published_only() -> None:
    c = company(residential_share=fact("mainly_residential"), buyer_type=fact("municipal"))
    result = score_company(c, MODEL)
    assert result.confidence == "Low" and result.units is None
    assert MODEL.bands == pytest.approx([220.0, 440.0, 660.0, 880.0])


def test_units_estimated_from_employees_once_the_sample_is_big_enough() -> None:
    staff = [
        company(f"s{i}.de", units_managed=fact(100 * i), employees=fact(i)) for i in range(1, 4)
    ]
    model = build_unit_model(staff)
    estimated = score_company(company(employees=fact(7)), model)
    assert (estimated.units, estimated.units_status) == (700, "estimated")
    too_few = build_unit_model(staff[: config.UNIT_ESTIMATION_MIN_SAMPLE - 1])
    assert score_company(company(employees=fact(7)), too_few).units_status == "unknown"


def test_non_property_managers_and_unresearched_are_not_scored() -> None:
    excluded = score_company(company(buyer_type=fact("not_property_manager")), MODEL)
    assert (excluded.lead_score, excluded.confidence) == (None, "Excluded")
    fresh = Company(id="x.de", name="x")
    assert score_company(fresh, MODEL).confidence == "Not researched"


def test_contact_status_counts_only_verified_contacts() -> None:
    def with_contacts(*contacts: Contact) -> Company:
        return company(contacts=list(contacts))

    verified = Contact(name="A", verified=True, email="a@x.de", email_published=True)
    unverified = Contact(name="B", verified=False, email="b@x.de", email_published=True)
    assert score_company(with_contacts(verified), MODEL).contact_status == "Named + email"
    assert score_company(with_contacts(unverified), MODEL).contact_status == "None"
    generic = company(email_general="info@x.de")
    assert score_company(generic, MODEL).contact_status == "Generic only"


def test_score_all_returns_one_score_per_company() -> None:
    scores, model = score_all(MARKET)
    assert len(scores) == len(MARKET) and model.bands
