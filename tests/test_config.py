"""clinic.yaml validation.

A clinic operator edits this file. Every mistake they can plausibly make must
produce a clear error at setup time rather than a broken conversation later.
"""

from __future__ import annotations

import textwrap

import pytest
import yaml

from clinic_bot.clinic_config import ConfigError, load_clinic_config

BASE = {
    "clinic": {
        "name": "Test Clinic",
        "phone": "+919000000000",
        "address": "Somewhere",
        "timezone": "Asia/Kolkata",
        "hours": {"open": "09:00", "close": "18:00", "days": ["mon", "tue"]},
    },
    "payment": {"upi_id": "test@okbank", "upi_name": "Test Clinic", "advance_amount": 200},
    "services": [
        {"code": "consultation", "name": "Consultation", "fee_from": 300, "duration_minutes": 30}
    ],
    "doctors": [
        {
            "code": "dr_a",
            "name": "Dr. A",
            "services": ["consultation"],
            "working_days": ["mon", "tue"],
        }
    ],
}


def write(tmp_path, data, name="clinic.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def mutate(**overrides):
    import copy

    data = copy.deepcopy(BASE)
    for key, value in overrides.items():
        data[key] = value
    return data


def test_the_shipped_config_is_valid():
    cfg = load_clinic_config("config/clinic.yaml")
    assert cfg.clinic.name
    assert cfg.services and cfg.doctors


def test_a_minimal_valid_config_loads(tmp_path):
    cfg = load_clinic_config(write(tmp_path, BASE))
    assert cfg.clinic.name == "Test Clinic"
    assert cfg.booking.slot_minutes == 30, "defaults should fill in"


def test_missing_file_names_the_fix(tmp_path):
    with pytest.raises(ConfigError, match="setup.py"):
        load_clinic_config(tmp_path / "nope.yaml")


def test_invalid_yaml_is_reported_clearly(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("clinic: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_clinic_config(path)


def test_doctor_referencing_an_unknown_service_is_caught(tmp_path):
    data = mutate(
        doctors=[
            {
                "code": "dr_a",
                "name": "Dr. A",
                "services": ["consultation", "typo_service"],
                "working_days": ["mon"],
            }
        ]
    )
    with pytest.raises(ConfigError, match="typo_service"):
        load_clinic_config(write(tmp_path, data))


def test_service_with_no_doctor_is_caught(tmp_path):
    """An unbookable service would be a dead end for the patient."""
    data = mutate(
        services=[
            {"code": "consultation", "name": "Consultation", "fee_from": 300},
            {"code": "orphan", "name": "Orphan Service", "fee_from": 500},
        ]
    )
    with pytest.raises(ConfigError, match="orphan"):
        load_clinic_config(write(tmp_path, data))


def test_duplicate_service_codes_are_caught(tmp_path):
    data = mutate(
        services=[
            {"code": "consultation", "name": "One", "fee_from": 300},
            {"code": "consultation", "name": "Two", "fee_from": 400},
        ]
    )
    with pytest.raises(ConfigError, match="duplicate service code"):
        load_clinic_config(write(tmp_path, data))


def test_overlong_service_name_is_caught(tmp_path):
    """WhatsApp truncates list rows past 24 characters."""
    data = mutate(
        services=[
            {
                "code": "consultation",
                "name": "An Extremely Long Treatment Name That Will Not Fit",
                "fee_from": 300,
            }
        ]
    )
    with pytest.raises(ConfigError, match="24"):
        load_clinic_config(write(tmp_path, data))


def test_bad_upi_id_is_caught(tmp_path):
    for bad in ("9000000000", "notavpa", "@bank", "name@"):
        data = mutate(payment={**BASE["payment"], "upi_id": bad})
        with pytest.raises(ConfigError, match="upi_id"):
            load_clinic_config(write(tmp_path, data, name=f"{abs(hash(bad))}.yaml"))


def test_phone_without_country_code_is_caught(tmp_path):
    data = mutate(clinic={**BASE["clinic"], "phone": "9000000000"})
    with pytest.raises(ConfigError, match="international format"):
        load_clinic_config(write(tmp_path, data))


def test_closing_before_opening_is_caught(tmp_path):
    data = mutate(
        clinic={
            **BASE["clinic"],
            "hours": {"open": "18:00", "close": "09:00", "days": ["mon"]},
        }
    )
    with pytest.raises(ConfigError):
        load_clinic_config(write(tmp_path, data))


def test_unknown_weekday_is_caught(tmp_path):
    data = mutate(
        clinic={
            **BASE["clinic"],
            "hours": {"open": "09:00", "close": "18:00", "days": ["mon", "funday"]},
        }
    )
    with pytest.raises(ConfigError, match="funday"):
        load_clinic_config(write(tmp_path, data))


def test_malformed_time_is_caught(tmp_path):
    data = mutate(
        clinic={
            **BASE["clinic"],
            "hours": {"open": "9am", "close": "18:00", "days": ["mon"]},
        }
    )
    with pytest.raises(ConfigError):
        load_clinic_config(write(tmp_path, data))


def test_empty_services_or_doctors_is_caught(tmp_path):
    with pytest.raises(ConfigError):
        load_clinic_config(write(tmp_path, mutate(services=[]), name="a.yaml"))
    with pytest.raises(ConfigError):
        load_clinic_config(write(tmp_path, mutate(doctors=[]), name="b.yaml"))


def test_doctor_with_no_working_days_is_caught(tmp_path):
    data = mutate(
        doctors=[
            {"code": "dr_a", "name": "Dr. A", "services": ["consultation"], "working_days": []}
        ]
    )
    with pytest.raises(ConfigError):
        load_clinic_config(write(tmp_path, data))


def test_break_outside_or_inverted_is_caught(tmp_path):
    data = mutate(
        clinic={
            **BASE["clinic"],
            "hours": {
                "open": "09:00",
                "close": "18:00",
                "days": ["mon"],
                "break": {"start": "14:30", "end": "13:30"},
            },
        }
    )
    with pytest.raises(ConfigError):
        load_clinic_config(write(tmp_path, data))


def test_top_level_must_be_a_mapping(tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text(textwrap.dedent("- a\n- b\n"), encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_clinic_config(path)
