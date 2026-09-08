"""Manual / in-memory sources: the guaranteed fallback and the test double."""

from __future__ import annotations

from legm.integrations.base import ExternalPick


class ManualSource:
    """Picks the user typed in; exists so every code path has a DraftSource."""

    name = "manual"

    def __init__(self, picks: list[ExternalPick] | None = None):
        self._picks = list(picks or [])

    def add(self, pick: ExternalPick) -> None:
        self._picks.append(pick)

    def poll(self) -> list[ExternalPick]:
        return list(self._picks)
