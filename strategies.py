"""
strategies.py
-------------
Ranking strategies for the list of PondCandidate objects that
pond_finder.find_pond_candidates() returns.

Design pattern (CSD: Design Patterns -- Strategy):
pond_finder.py already scores/orders candidates internally by catchment
area while it searches the grid (that ordering is baked into *which*
top-N candidates survive, for performance -- see pond_finder.py's
docstring). This module is a separate, swappable *presentation-layer*
re-ranking step: given the same top-N candidates, a village officer may
instead want "flattest first" (easiest to excavate) or "closest to
existing structures" in a future version. Each concern is one small
class implementing the same interface, so app.py can pick a strategy by
name from a request parameter without any of these classes knowing
about Flask, and without touching the search algorithm in pond_finder.py.

Adding a new ranking rule later means adding one class here and one
entry in STRATEGIES -- nothing else in the codebase changes.
"""

from abc import ABC, abstractmethod

from pond_finder import PondCandidate


class RankingStrategy(ABC):
    """Common interface every ranking strategy must implement."""

    name: str = "base"

    @abstractmethod
    def rank(self, candidates: list[PondCandidate]) -> list[PondCandidate]:
        """Return candidates re-ordered best-first. Must not mutate input."""


class CatchmentAreaStrategy(RankingStrategy):
    """Default: largest contributing catchment area first (most runoff)."""

    name = "catchment"

    def rank(self, candidates: list[PondCandidate]) -> list[PondCandidate]:
        return sorted(candidates, key=lambda c: c.catchment_area_m2, reverse=True)


class FlatnessStrategy(RankingStrategy):
    """Flattest site first (smallest elevation range) -- cheapest to dig."""

    name = "flatness"

    def rank(self, candidates: list[PondCandidate]) -> list[PondCandidate]:
        return sorted(candidates, key=lambda c: c.elevation_range_m)


class BalancedStrategy(RankingStrategy):
    """
    Compromise ranking: normalizes catchment area and flatness onto a
    0..1 scale each and ranks by their average, so a site doesn't have
    to be the single best on one axis to rank well overall.
    """

    name = "balanced"

    def rank(self, candidates: list[PondCandidate]) -> list[PondCandidate]:
        if not candidates:
            return []

        areas = [c.catchment_area_m2 for c in candidates]
        ranges = [c.elevation_range_m for c in candidates]
        area_min, area_max = min(areas), max(areas)
        range_min, range_max = min(ranges), max(ranges)

        def score(c: PondCandidate) -> float:
            area_norm = (
                (c.catchment_area_m2 - area_min) / (area_max - area_min)
                if area_max > area_min else 1.0
            )
            flat_norm = (
                1.0 - (c.elevation_range_m - range_min) / (range_max - range_min)
                if range_max > range_min else 1.0
            )
            return (area_norm + flat_norm) / 2.0

        return sorted(candidates, key=score, reverse=True)


# Factory (CSD: Design Patterns -- Factory): callers ask for a strategy
# by name and never need to know the concrete class behind it.
STRATEGIES: dict[str, type[RankingStrategy]] = {
    CatchmentAreaStrategy.name: CatchmentAreaStrategy,
    FlatnessStrategy.name: FlatnessStrategy,
    BalancedStrategy.name: BalancedStrategy,
}


def get_strategy(name: str | None) -> RankingStrategy:
    """Look up a ranking strategy by name, defaulting to catchment-area."""
    key = (name or CatchmentAreaStrategy.name).lower()
    try:
        return STRATEGIES[key]()
    except KeyError:
        valid = ", ".join(sorted(STRATEGIES))
        raise ValueError(f"Unknown ranking strategy '{name}'. Valid options: {valid}")
