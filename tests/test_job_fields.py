"""Vehicles by VIN, customers by name AND phone, insurance by name, and one rule for job fields: they follow the
job's current estimate version unless a person typed them in."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from db.models import Customer, InsuranceCompany, Job, Vehicle
from db.save import set_field
from db.session import init_db, make_engine
from fakes import VIN_A, make
from fakes import upload as _upload


@pytest.fixture
def s(tmp_path):
    with init_db(make_engine(f"sqlite:///{tmp_path / 'f.db'}"))() as s:
        s.files_dir = tmp_path / "files"
        yield s


def job(s, **kw):
    kind, job_id = _upload(s, make(**kw), s.files_dir)
    assert kind == "job"
    return s.get(Job, job_id)


def count(s, model):
    return s.scalar(select(func.count()).select_from(model))


# ---------------------------------------------------------------- vehicles

def test_jobs_on_the_same_vin_share_one_vehicle(s):
    a = job(s, vin=VIN_A, claim="CL-1", mileage="50,100")
    b = job(s, vin=VIN_A, claim="CL-2", mileage="61,000")  # same car, another claim: another job
    assert a.id != b.id and a.vehicle_id == b.vehicle_id and count(s, Vehicle) == 1
    assert (a.mileage_in, b.mileage_in) == ("50,100", "61,000")  # mileage belongs to the job


def test_no_vin_is_a_new_vehicle(s):
    a = job(s, ro="1", vin="")
    b = job(s, ro="2", vin="")
    assert a.vehicle_id != b.vehicle_id


# ---------------------------------------------------------------- customers

def test_same_name_and_phone_is_the_same_customer(s):
    a = job(s, ro="1", customer="DOE, JANE", phone="(573) 555-0101")
    b = job(s, ro="2", customer="doe,  jane", phone="573.555.0101")
    assert a.customer_id == b.customer_id


@pytest.mark.parametrize("phone_a,phone_b", [("(573) 555-0101", ""), ("", "(573) 555-0101"), ("", ""),
                                             ("(573) 555-0101", "(573) 555-0199"), ("N/A", "")])
def test_name_alone_is_never_the_same_customer(s, phone_a, phone_b):
    a = job(s, ro="1", customer="DOE, JANE", phone=phone_a)
    b = job(s, ro="2", customer="DOE, JANE", phone=phone_b)
    assert a.customer_id != b.customer_id


def test_a_supplement_without_a_phone_keeps_the_jobs_customer(s):
    a = job(s, ro="1", customer="DOE, JANE")
    b = job(s, ro="1", customer="DOE,  Jane", supplement_no=1)
    assert a.id == b.id and count(s, Customer) == 1


def test_a_new_owner_on_the_current_version_becomes_the_customer(s):
    a = job(s, ro="1", customer="DOE, JANE")
    job(s, ro="1", customer="ROE, RAY", supplement_no=1)
    assert a.customer.name == "ROE, RAY"


# ---------------------------------------------------------------- insurance

def test_insurance_matched_by_name_ignoring_case_and_spacing(s):
    a = job(s, ro="1", insurance="State  Farm")
    b = job(s, ro="2", insurance="STATE FARM")
    assert a.insurance_id == b.insurance_id and a.insurance.name == "State  Farm" and count(s, InsuranceCompany) == 1


# ---------------------------------------------------------------- job fields follow the current version

def test_fields_follow_the_current_version(s):
    a = job(s, ro="1", claim="CL-1", vin=VIN_A, adjuster="AMY", estimator="ED", loss_date="8/1/2026",
            deductible="500.00", mileage="50,100", insurance="Acme Ins")
    job(s, ro="1", claim="CL-1", vin=VIN_A, adjuster="BOB", estimator="EVE", loss_date="8/2/2026",
        deductible="$1,000.00 - Not Waived", mileage="50,180", insurance="Zenith", supplement_no=1)
    assert (a.adjuster, a.estimator, a.loss_date, a.deductible, a.mileage_in, a.insurance.name) == (
        "BOB", "EVE", date(2026, 8, 2), Decimal("1000.00"), "50,180", "Zenith")


def test_an_older_version_uploaded_later_does_not_take_over(s):
    a = job(s, ro="1", adjuster="BOB", supplement_no=1, printed="2026-09-05T10:00:00")
    job(s, ro="1", adjuster="AMY", supplement_no=0, printed="2026-09-01T10:00:00")
    assert a.adjuster == "BOB" and a.current_document.supplement_no == 1


def test_a_value_the_current_version_does_not_print_is_kept(s):
    a = job(s, ro="1", adjuster="AMY", mileage="50,100")
    job(s, ro="1", adjuster="", mileage="", supplement_no=1)
    assert (a.adjuster, a.mileage_in) == ("AMY", "50,100")


@pytest.mark.parametrize("field,typed", [("ro_number", "7001"), ("claim_no", "TYPED-1"), ("adjuster", "TYPED")])
def test_a_field_typed_by_hand_is_never_overwritten(s, field, typed):
    a = job(s, ro="1", claim="CL-1", vin=VIN_A, adjuster="AMY")
    set_field(s, a, field, typed, job_id=a.id, action="manual")
    s.flush()
    # the next version prints RO 1, claim CL-1 and adjuster BOB; it still matches this job (by RO # or claim # + VIN)
    b = job(s, ro="1", claim="CL-1", vin=VIN_A, adjuster="BOB", supplement_no=1)
    assert b.id == a.id and getattr(a, field) == typed
