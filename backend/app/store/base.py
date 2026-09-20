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

    def delete_generation(self, generation_id: str) -> None:
        """Remove one row. Raises NotFoundError if it was not there."""
        ...

    def delete_by_address(self, address: str) -> int:
        """Remove every generation for an address. Returns how many went."""
        ...

    def delete_all(self) -> int:
        """Empty the world. Returns how many rows went."""
        ...
