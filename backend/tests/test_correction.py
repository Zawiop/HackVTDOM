"""Step 09: a human correction is recorded as manually-verified, not laundered."""
from __future__ import annotations

import pytest

from app.models import Correction


def test_correction_flips_state_and_updates_transform(store, sample_payload):
    saved = store.save_generation(sample_payload)
    assert saved.confidence_state == "auto-high"

    fixed = store.apply_correction(
        saved.id, Correction(rotationDegrees=227.5, scale=1.95)
    )

    assert fixed.confidence_state == "manually-verified"
    assert fixed.placement["confidence"] == "manually-verified", "both fields stay in sync"
    assert fixed.placement["rotationDegrees"] == pytest.approx(227.5)
    assert fixed.placement["scale"] == pytest.approx(1.95)


def test_correction_persists_across_a_reread(store, sample_payload):
    saved = store.save_generation(sample_payload)
    store.apply_correction(saved.id, Correction(scale=2.5))
    assert store.get_generation(saved.id).placement["scale"] == pytest.approx(2.5)


def test_partial_correction_leaves_other_fields_alone(store, sample_payload):
    saved = store.save_generation(sample_payload)
    fixed = store.apply_correction(saved.id, Correction(scale=2.0))

    assert fixed.placement["rotationDegrees"] == pytest.approx(47.5), "untouched"
    assert len(fixed.placement["scoredRotationCandidates"]) == 4, "scores survive"


def test_correction_keeps_position_nudge(store, sample_payload):
    saved = store.save_generation(sample_payload)
    fixed = store.apply_correction(saved.id, Correction(position=[37.23, -80.42, 0.0]))
    assert fixed.placement["position"] == [37.23, -80.42, 0.0]


def test_correction_does_not_create_a_new_row(store, sample_payload):
    """A correction edits the flagged row in place — it is not a new generation."""
    saved = store.save_generation(sample_payload)
    store.apply_correction(saved.id, Correction(scale=2.0))
    history = store.get_history_for_address(sample_payload.address)
    assert len(history) == 1
    assert history[0].id == saved.id
