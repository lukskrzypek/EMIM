"""Polish names of the contracts for the UI (no Qt)."""

from __future__ import annotations

from engine.contracts import CONTRACT_ORDER, GameContract

CONTRACT_LABELS: dict[GameContract, str] = {
    GameContract.NO_TRICKS: "Bez lew",
    GameContract.NO_HEARTS: "Bez kierów",
    GameContract.NO_QUEENS: "Bez dam",
    GameContract.NO_MEN: "Bez panów",
    GameContract.NO_KING_OF_HEARTS: "Bez króla kier",
    GameContract.NO_7TH_AND_LAST: "Bez 7. i ostatniej lewy",
    GameContract.ROBBER: "Rozbójnik",
}
assert set(CONTRACT_LABELS) == set(CONTRACT_ORDER)

# The player's own penalty at which the seat plate turns to a warning colour.
WARN_POINTS = 100


def contract_label(contract: GameContract) -> str:
    return CONTRACT_LABELS[contract]
