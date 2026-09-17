import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.models.evidence import ChapterSnapshot, EvidenceRef, MetricSpec

FIXTURES = Path(__file__).parent / "fixtures" / "qc_contracts"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_evidence_ref_validates_source_version_and_round_trips():
    ref = EvidenceRef.model_validate(load("valid.json"))
    assert ref.model_dump(mode="json")["source_version"] == 1


def test_conflicting_source_version_is_rejected():
    with pytest.raises(ValidationError):
        EvidenceRef.model_validate(load("conflict.json"))


def test_review_does_not_verify_evidence():
    chapter = ChapterSnapshot.model_validate(load("missing-evidence.json"))
    approved = chapter.model_copy(update={"review_state": "approved"})
    assert approved.review_state == "approved"
    assert approved.evidence_state == "missing"


def test_simulation_metric_retains_simulation_origin():
    metric = MetricSpec.model_validate(load("simulation.json"))
    assert metric.value_kind == "simulated"
    assert metric.refs[0].origin_kind == "simulation"
