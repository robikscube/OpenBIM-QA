from pathlib import Path

import pytest

from openbim_qa.models import Door


@pytest.fixture
def fixture_dir():
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def fingerprints():
    return {f"source_{name}_sha256": digit * 64 for name, digit in (("model", "a"), ("schedule", "b"), ("mapping", "c"))}


@pytest.fixture
def door_factory():
    def make(entity_id=1, door_id="001", rating="60", **kwargs):
        defaults = dict(ifc_global_id=f"guid-{entity_id}", identity_source="IfcDoor.Tag",
                        rating_source=f"instance#{entity_id}:Pset_DoorCommon.FireRating", rating_property_found=True)
        defaults.update(kwargs)
        return Door(entity_id, door_id=door_id, raw_rating=rating, **defaults)
    return make
