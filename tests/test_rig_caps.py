"""Model list and capability parsing — the source of the rig setup UI."""

from __future__ import annotations

import pytest

from catnector.rig import dump_caps, list_models

pytestmark = pytest.mark.hamlib


def test_model_list_is_parsed_completely():
    models = list_models()
    assert len(models) > 200
    by_number = {m.model: m for m in models}
    assert by_number[1].label == "Hamlib Dummy"


def test_a_model_with_no_name_still_has_a_usable_label():
    """FLRig's row leaves the model column empty; it must not render blank."""
    flrig = next(m for m in list_models() if m.model == 4)
    assert flrig.label.strip() == "FLRig"


def test_labels_never_expose_raw_model_numbers():
    assert all(m.label and not m.label.isdigit() for m in list_models())


def test_serial_rig_capabilities_drive_the_settings_form():
    caps = dump_caps(1035)  # Yaesu FT-991
    assert caps.name == "FT-991"
    assert caps.is_serial and caps.needs_device
    assert 9600 in caps.serial_speeds
    assert caps.can_set_freq and caps.can_set_mode
    assert caps.can_get_ptt  # enables the PTT guard for this rig


def test_network_rigs_are_ordinary_entries_not_special_cases():
    """flrig and Flex are just picker entries — docs/PLANNING.md §8.1."""
    for model in (4, 2036):
        caps = dump_caps(model)
        assert caps.is_network
        assert not caps.needs_device
