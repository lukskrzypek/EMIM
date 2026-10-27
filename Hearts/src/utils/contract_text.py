"""Polish names of the contracts for the UI (no Qt)."""

from __future__ import annotations

from engine.contracts import CONTRACT_ORDER, DEALS_PER_GAME, GameContract

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


def session_heading(deal_number: int, total_deals: int) -> str:
    """``Rozdanie 3/7``, or ``Gra 2/5 · Rozdanie 3/7`` when several games are played."""
    game = (deal_number - 1) // DEALS_PER_GAME + 1
    games = max(total_deals // DEALS_PER_GAME, 1)
    rnd = (deal_number - 1) % DEALS_PER_GAME + 1
    deal = f"Rozdanie {rnd}/{DEALS_PER_GAME}"
    if games == 1:
        return deal
    return f"Gra {game}/{games} · {deal}"
