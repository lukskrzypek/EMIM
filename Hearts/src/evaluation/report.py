"""Jakość botów: ocena każdego ruchu z logu i średnie per model (bez I/O poza czytaniem logu)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from .context import InvalidState
from .evaluator import evaluate_move, verdict_for
from .trajectories import LoadResult, load_moves

VERDICTS = ("optymalne", "poprawne", "wątpliwe", "niepoprawne")
VERDICT_HEADERS = ("optym.", "popraw.", "wątpl.", "niepop.")
FORCED_SCENARIO = "only_move"  # jedyna legalna karta: nie świadczy o jakości gry
# Ruchy bez realnego wyboru: pokazywane jako optymalne, ale pomijane w statystykach.
NON_DECISION_SCENARIOS = frozenset({FORCED_SCENARIO, "nothing_left"})  # nothing_left: brak kar do wzięcia


@dataclass
class ModelQuality:
    """Statystyki jednego modelu (albo kontrolera, np. ``human``)."""

    model: str
    moves: int = 0                                  # wszystkie ocenione ruchy
    forced: int = 0                                 # ruchy bez wyboru (jedna legalna karta, brak kar)
    illegal: int = 0                                # ruchy, których ewaluator uznał za nielegalne
    correctness_sum: float = 0.0                    # tylko ruchy z wyborem
    aggressiveness_sum: float = 0.0
    aggressiveness_n: int = 0
    verdicts: Counter[str] = field(default_factory=Counter)
    scenarios: dict[str, list[float]] = field(default_factory=dict)  # scenariusz -> poprawności

    @property
    def decisions(self) -> int:
        """Ruchy z realnym wyborem (bez wymuszonych)."""
        return self.moves - self.forced - self.illegal

    @property
    def correctness(self) -> float | None:
        """Średnia poprawność (0-100) po ruchach z wyborem."""
        return self.correctness_sum / self.decisions if self.decisions else None

    @property
    def aggressiveness(self) -> float | None:
        return self.aggressiveness_sum / self.aggressiveness_n if self.aggressiveness_n else None


@dataclass
class QualityReport:
    models: dict[str, ModelQuality] = field(default_factory=dict)
    records: int = 0
    ignored: Counter[str] = field(default_factory=Counter)
    skipped: Counter[str] = field(default_factory=Counter)
    ignored_models: tuple[str, ...] = ()


def build_report(load: LoadResult, ignored_models: Collection[str] = ()) -> QualityReport:
    report = QualityReport(
        records=load.records,
        ignored=Counter(load.ignored),
        skipped=Counter(load.skipped),
        ignored_models=tuple(ignored_models),
    )
    for move in load.moves:
        try:
            evaluation = evaluate_move(move.state, move.chosen)
        except InvalidState as exc:
            report.skipped[f"nieprawidłowy stan ({exc})"] += 1
            continue
        stats = report.models.setdefault(move.model, ModelQuality(move.model))
        stats.moves += 1
        if not evaluation.legal or evaluation.correctness is None:
            stats.illegal += 1
            continue
        if evaluation.scenario in NON_DECISION_SCENARIOS:
            stats.forced += 1
            continue
        stats.correctness_sum += evaluation.correctness
        stats.verdicts[verdict_for(evaluation.correctness)] += 1
        stats.scenarios.setdefault(evaluation.scenario or "?", []).append(evaluation.correctness)
        if evaluation.aggressiveness is not None:
            stats.aggressiveness_sum += evaluation.aggressiveness
            stats.aggressiveness_n += 1
    return report


def evaluate_log(path: str | Path, ignored_models: Collection[str] = ()) -> QualityReport:
    """Oceń wszystkie ruchy z ``path``, pomijając modele z ``ignored_models``."""
    return build_report(load_moves(path, ignored_models), ignored_models)


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def format_report(report: QualityReport) -> str:
    lines = ["Ocena jakości ruchów botów", "=" * 64]
    ignored_total = sum(report.ignored.values())
    if report.ignored_models:
        lines.append(
            f"Ignorowani: {', '.join(report.ignored_models)} (pominięto {ignored_total} ruchów)"
        )
    lines.append(f"Rekordów w logu: {report.records}")
    for reason, count in sorted(report.skipped.items()):
        lines.append(f"Pominięto {count} rekordów: {reason}")

    ranked = sorted(
        report.models.values(),
        key=lambda m: (-(m.correctness if m.correctness is not None else -1.0), m.model),
    )
    if not ranked:
        lines.append("\nBrak ruchów do oceny.")
        return "\n".join(lines)

    lines.append("")
    lines.append(
        f"{'Model':<28} {'Ruchy':>6} {'Wybory':>7} {'Poprawn.':>9} {'Agresyw.':>9}  "
        + "  ".join(f"{label:>7}" for label in VERDICT_HEADERS)
    )
    for m in ranked:
        shares = [
            f"{100 * m.verdicts[v] / m.decisions:6.0f}%" if m.decisions else f"{'-':>7}"
            for v in VERDICTS
        ]
        lines.append(
            f"{m.model:<28} {m.moves:>6} {m.decisions:>7} {_fmt(m.correctness):>9} "
            f"{_fmt(m.aggressiveness):>9}  " + "  ".join(shares)
        )
    lines.append("")
    lines.append("Poprawność i agresywność: skala 0-100, liczone tylko z ruchów z wyborem")
    lines.append("(bez ruchów wymuszonych - jedna legalna karta albo brak kar do wzięcia).")
    lines.append("Kolumny 'optym.' ... 'niepop.' to")
    lines.append("odsetek ruchów z danym werdyktem (>=90 optymalne, >=70 poprawne, >=40 wątpliwe).")
    for m in ranked:
        if not m.scenarios:
            continue
        lines.append(f"\n{m.model} - według scenariusza (liczba ruchów, średnia poprawność):")
        for name, values in sorted(m.scenarios.items()):
            lines.append(f"  {name:<14} {len(values):>5}  {sum(values) / len(values):5.1f}")
        if m.forced or m.illegal:
            lines.append(f"  (wymuszone: {m.forced}, nielegalne: {m.illegal})")
    return "\n".join(lines)
