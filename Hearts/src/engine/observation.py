"""What a single player (or an LLM acting as one) is allowed to see (SPEC.md, section 5)."""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.contracts import CONTRACT_ORDER, GameContract

CONTRACT_RULES: dict[GameContract, str] = {
    GameContract.NO_TRICKS: "NO_TRICKS: every trick you take = 20 pts.",
    GameContract.NO_HEARTS: (
        "NO_HEARTS: every heart you take = 20 pts. "
        "You may not lead a heart while holding another suit, unless KH was played."
    ),
    GameContract.NO_QUEENS: "NO_QUEENS: every queen you take = 60 pts.",
    GameContract.NO_MEN: "NO_MEN: every king and jack you take = 30 pts.",
    GameContract.NO_KING_OF_HEARTS: (
        "NO_KING_OF_HEARTS: taking KH = 150 pts. "
        "You may not lead a heart while holding another suit, unless KH was played."
    ),
    GameContract.NO_7TH_AND_LAST: "NO_7TH_AND_LAST: taking trick 7 = 75 pts, taking the last trick = 75 pts.",
    GameContract.ROBBER: (
        "ROBBER: all penalties at once: trick 20, heart 20, queen 60, king/jack 30, KH 150 "
        "(KH totals 200), trick 7 and last trick +75. "
        "You may not lead a heart while holding another suit, unless KH was played."
    ),
}
assert set(CONTRACT_RULES) == set(CONTRACT_ORDER)


@dataclass
class PlayerObservation:
    """Public information plus the player's own hand."""

    player_id: str
    hand: list[str]
    current_trick: list[tuple[str, str]]
    trick_history: list[str]
    exposed_voids: dict[str, list[str]]
    scores: dict[str, int]  # penalties of the current deal (of the last deal when the game is over)
    legal_moves: list[str]
    total_scores: dict[str, int] = field(default_factory=dict)  # penalties of the whole match
    played_cards: list[tuple[str, str]] = field(default_factory=list)  # this deal, in play order
    contract: GameContract = GameContract.NO_TRICKS
    declarer: str = "P0"
    deal_number: int = 1
    total_deals: int = 28
    trick_number: int = 1
    total_tricks: int = 13
    current_player: str | None = None
    game_over: bool = False
    num_players: int = 4

    def to_icl_prompt(self, max_history: int = 8) -> str:
        """Compact text block (at most ``9 + max_history`` lines)."""
        if self.game_over:
            header = f"KING {self.num_players}p | You: {self.player_id} | GAME OVER"
        else:
            header = (
                f"KING {self.num_players}p | You: {self.player_id} | "
                f"Deal {self.deal_number}/{self.total_deals} {self.contract.value} "
                f"(declarer {self.declarer}) | "
                f"Trick {self.trick_number}/{self.total_tricks} | Turn: {self.current_player or '-'}"
            )
        trick = " ".join(f"{p}:{c}" for p, c in self.current_trick) or "(empty)"
        legal = " ".join(self.legal_moves) or "-"
        voids = " ".join(f"{p}:{''.join(suits) or '-'}" for p, suits in self.exposed_voids.items())
        deal_label = "Last deal" if self.game_over else "Deal pts"
        total_label = "Final totals" if self.game_over else "Total pts"

        lines = [
            header,
            f"Rule: {CONTRACT_RULES[self.contract]} Lowest total wins.",
            f"Hand: {' '.join(self.hand) or '-'}",
            f"Trick: {trick}",
            f"Legal: {legal}",
            f"Voids: {voids}",
            f"{deal_label}: " + " ".join(f"{p}={pts}" for p, pts in self.scores.items()),
            f"{total_label}: " + " ".join(f"{p}={pts}" for p, pts in self.total_scores.items()),
        ]
        history = self.trick_history
        if history:
            shown = history[-max_history:] if max_history > 0 else []
            if len(shown) < len(history):
                lines.append(f"History (last {len(shown)} of {len(history)}):")
            else:
                lines.append("History:")
            lines.extend(shown)
        else:
            lines.append("History: (none)")
        return "\n".join(lines)
