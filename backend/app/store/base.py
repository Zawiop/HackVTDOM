"""Storage protocol shared by the Supabase and SQLite backends."""
from __future__ import annotations

from typing import Protocol

from ..models import Correction, Generation, GenerationCreate


class GenerationStore(Protocol):
    backend_name: str

    def health(self) -> dict: ...

    def save_generation(self, payload: GenerationCreate) -> Generation:
        """Insert one row. Never upserts by address — see step 11."""
        ...

    def get_generation(self, generation_id: str) -> Generation: ...

    def list_generations(self) -> list[Generation]:
        """Every row, for the step 12 map layer."""
        ...

    def get_history_for_address(self, address: str) -> list[Generation]:
        """All rows for one address, oldest first: Reality -> Flooded -> ..."""
        ...

    def apply_correction(self, generation_id: str, correction: Correction) -> Generation:
        """Step 09: write corrected transform back, flip to manually-verified."""
        ...
