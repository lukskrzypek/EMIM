"""One line of the lobby: who sits on seat ``Pn``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from controllers.groq_icl_bot import DEFAULT_MODEL, USER_GUIDELINES
from gui.config import GUIDELINES_MAX_CHARS, NAME_MAX_CHARS, SMART_SAMPLES
from gui.core.controllers_factory import availability_problem
from gui.core.model_catalog import FALLBACK_MODELS
from gui.core.seat_config import SEAT_LABELS, SeatConfig, SeatKind, clean_guidelines, clean_name

ALIAS_TIP = (
    "Nazwa odróżnia dwa boty tego samego modelu (max 10 znaków: litery, cyfry, - i _). "
    "Puste pole: pamięć w logs/memory_<model>.txt. Z nazwą: logs/memory_<model>_<nazwa>.txt. "
    "Ten sam model na kilku miejscach wymaga różnych nazw (najwyżej jedno miejsce może jej nie mieć)."
)
SAMPLES_TIP = (
    "Monte Carlo: ile razy bot losuje, jak mogą wyglądać ukryte ręce rywali, i rozgrywa dla każdej "
    "legalnej karty końcówkę rozdania. Wybiera kartę z najmniejszą średnią liczbą punktów karnych. "
    "0 = same heurystyki; więcej = trafniej, ale wolniej."
)


def model_key(model: str) -> str:
    return model.strip().casefold()


class SeatRow(QWidget):
    changed = Signal()
    becameGroq = Signal(object)  # this SeatRow, when its kind has just been switched to Groq

    def __init__(
        self,
        index: int,
        default_kind: SeatKind,
        models: Sequence[str] = FALLBACK_MODELS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.player_id = f"P{index}"

        self.name = QLabel(self.player_id)
        self.name.setMinimumWidth(28)
        self.kind = QComboBox()
        for kind, label in SEAT_LABELS.items():
            self.kind.addItem(label, kind)
        self.kind.setCurrentIndex(list(SEAT_LABELS).index(default_kind))

        self.model = QComboBox()
        self.model.addItems(list(models))  # a closed list: new models go to groq_models.txt
        self.model.setMinimumWidth(190)
        self.model.setToolTip("Model Groq z listy w groq_models.txt")
        self.alias_label = QLabel("nazwa:")
        self.alias_label.setToolTip(ALIAS_TIP)
        self.alias = QLineEdit()
        self.alias.setMaxLength(NAME_MAX_CHARS)
        self.alias.setFixedWidth(96)
        self.alias.setPlaceholderText("opcjonalnie")
        self.alias.setToolTip(ALIAS_TIP)
        self.alias.setValidator(  # only what is safe in a file name
            QRegularExpressionValidator(
                QRegularExpression(
                    r"[\w-]*", QRegularExpression.PatternOption.UseUnicodePropertiesOption
                )
            )
        )
        self.samples_label = QLabel("losowania MC:")
        self.samples_label.setToolTip(SAMPLES_TIP)
        self.samples = QSpinBox()
        self.samples.setRange(0, 500)
        self.samples.setValue(SMART_SAMPLES)
        self.samples.setToolTip(SAMPLES_TIP)
        self.samples_hint = QLabel("symulacje na ruch: więcej = dokładniej, ale dłużej liczy")
        self.samples_hint.setObjectName("muted")
        self.samples_hint.setToolTip(SAMPLES_TIP)
        self.note = QLabel()
        self.note.setObjectName("warning")

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        for widget in (
            self.name, self.kind, self.model, self.alias_label, self.alias,
            self.samples_label, self.samples, self.samples_hint, self.note,
        ):
            top.addWidget(widget)
        top.addStretch(1)

        # Extra system-prompt line for GroqICLBot (its USER_GUIDELINES constant is the default).
        self.guidelines_label = QLabel(
            f"wytyczne startowe (najlepiej po angielsku, max {GUIDELINES_MAX_CHARS} znaków):"
        )
        self.guidelines_label.setObjectName("muted")
        self.guidelines = QLineEdit()
        self.guidelines.setMaxLength(GUIDELINES_MAX_CHARS)
        self.guidelines.setPlaceholderText(
            f"domyślnie: {USER_GUIDELINES}" if USER_GUIDELINES.strip()
            else "np. Avoid taking hearts; dump the Queen of Spades early."
        )
        self.guidelines.setToolTip(
            "Dodatkowa instrukcja dopisywana do promptu systemowego bota. "
            "Puste pole = domyślne wytyczne bota (USER_GUIDELINES)."
        )
        self.guidelines_count = QLabel()
        self.guidelines_count.setObjectName("muted")
        bottom = QHBoxLayout()
        bottom.setContentsMargins(34, 0, 0, 0)
        for widget in (self.guidelines_label, self.guidelines, self.guidelines_count):
            bottom.addWidget(widget)
        bottom.setStretch(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addLayout(bottom)

        self._was_groq = default_kind is SeatKind.GROQ
        self.kind.currentIndexChanged.connect(self._on_change)
        self.model.currentTextChanged.connect(self._on_text)
        self.samples.valueChanged.connect(self._on_value)
        self.guidelines.textChanged.connect(self._on_text)
        self.alias.textChanged.connect(self._on_text)
        self._on_change()

    @property
    def seat_kind(self) -> SeatKind:
        return SeatKind(self.kind.currentData())  # Qt hands the str value back, not the Enum

    def config(self) -> SeatConfig:
        return SeatConfig(
            kind=self.seat_kind,
            groq_model=self.model.currentText().strip() or DEFAULT_MODEL,
            smart_samples=self.samples.value(),
            groq_guidelines=clean_guidelines(self.guidelines.text()),
            groq_name=clean_name(self.alias.text()),
        )

    def apply(self, seat: SeatConfig) -> None:
        """Show ``seat`` (restoring saved choices)."""
        self.kind.setCurrentIndex(list(SEAT_LABELS).index(seat.kind))
        self.select_model(seat.groq_model)
        self.samples.setValue(seat.smart_samples)
        self.guidelines.setText(seat.groq_guidelines)
        self.alias.setText(seat.groq_name)

    @property
    def is_groq(self) -> bool:
        return self.seat_kind is SeatKind.GROQ

    @property
    def model_name(self) -> str:
        return self.config().groq_model

    @property
    def seat_name(self) -> str:
        return self.config().groq_name

    def model_names(self) -> list[str]:
        return [self.model.itemText(i) for i in range(self.model.count())]

    def select_model(self, name: str) -> bool:
        """Select ``name`` from the list (any case); ``False`` and no change when it is not there."""
        index = self.model.findText(name.strip(), Qt.MatchFlag.MatchFixedString)
        if index < 0:
            return False
        self.model.setCurrentIndex(index)
        return True

    def set_models(self, models: Sequence[str]) -> None:
        """Replace the list (the file changed), keeping the current choice when it survives."""
        models = list(models)
        if models == self.model_names():
            return
        current = self.model.currentText()
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems(models)
        self.model.blockSignals(False)
        if not self.select_model(current):
            self.model.setCurrentIndex(0)
        self._on_change()

    def pick_free_model(self, taken: Mapping[str, str]) -> None:
        """Select the first listed model that nobody else plays (no-op when all are taken)."""
        for name in self.model_names():
            if model_key(name) not in taken:
                self.select_model(name)
                return

    def problem(self) -> str | None:
        return availability_problem(self.config())

    def refresh(self) -> None:
        self._on_change()

    def _on_value(self, _value: int) -> None:
        self._on_change()

    def _on_text(self, _text: str) -> None:
        self._on_change()

    def _on_change(self) -> None:
        kind = self.seat_kind
        groq = kind is SeatKind.GROQ
        smart = kind is SeatKind.SMART
        for widget in (
            self.model, self.alias_label, self.alias,
            self.guidelines_label, self.guidelines, self.guidelines_count,
        ):
            widget.setVisible(groq)
        for widget in (self.samples_label, self.samples, self.samples_hint):
            widget.setVisible(smart)
        self.guidelines_count.setText(f"{len(self.guidelines.text())}/{GUIDELINES_MAX_CHARS}")
        problem = self.problem()
        self.note.setText(f"⚠ {problem}" if problem else "")
        if groq and not self._was_groq:
            self._was_groq = True
            self.becameGroq.emit(self)
        self._was_groq = groq
        self.changed.emit()
