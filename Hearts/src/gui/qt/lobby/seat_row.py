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

from controllers.ai_bot import DEFAULT_PROVIDER, PROVIDERS, USER_GUIDELINES
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
    # This SeatRow, when it has just become an AI seat or its provider was switched.
    becameAI = Signal(object)

    def __init__(
        self,
        index: int,
        default_kind: SeatKind,
        models: Mapping[str, Sequence[str]] = FALLBACK_MODELS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.player_id = f"P{index}"
        self._models = {pid: list(models.get(pid, ())) for pid in PROVIDERS}

        self.name = QLabel(self.player_id)
        self.name.setMinimumWidth(28)
        self.kind = QComboBox()
        for kind, label in SEAT_LABELS.items():
            self.kind.addItem(label, kind)
        self.kind.setCurrentIndex(list(SEAT_LABELS).index(default_kind))

        self.provider = QComboBox()
        for info in PROVIDERS.values():
            self.provider.addItem(info.label, info.id)
        self.provider.setToolTip("Które API obsługuje tego bota (każde ma własny klucz i listę modeli)")
        self.model = QComboBox()
        self.model.setMinimumWidth(190)
        self._fill_models()  # a closed list: new models go to <provider>_models.txt
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
            self.name, self.kind, self.provider, self.model, self.alias_label, self.alias,
            self.samples_label, self.samples, self.samples_hint, self.note,
        ):
            top.addWidget(widget)
        top.addStretch(1)

        # Extra system-prompt line for AIBot (its USER_GUIDELINES constant is the default).
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

        self._was_ai = default_kind is SeatKind.AI
        self.kind.currentIndexChanged.connect(self._on_change)
        self.provider.currentIndexChanged.connect(self._on_provider)
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
            ai_model=self.model.currentText().strip() or PROVIDERS[self.provider_id].default_model,
            smart_samples=self.samples.value(),
            ai_guidelines=clean_guidelines(self.guidelines.text()),
            ai_name=clean_name(self.alias.text()),
            ai_provider=self.provider_id,
        )

    @property
    def provider_id(self) -> str:
        return str(self.provider.currentData() or DEFAULT_PROVIDER)

    def apply(self, seat: SeatConfig) -> None:
        """Show ``seat`` (restoring saved choices)."""
        self.kind.setCurrentIndex(list(SEAT_LABELS).index(seat.kind))
        self.provider.blockSignals(True)  # the model list is filled once, below
        index = self.provider.findData(seat.ai_provider)
        self.provider.setCurrentIndex(max(index, 0))
        self.provider.blockSignals(False)
        self._fill_models(keep=seat.ai_model)
        self.samples.setValue(seat.smart_samples)
        self.guidelines.setText(seat.ai_guidelines)
        self.alias.setText(seat.ai_name)
        self._on_change()  # the model list was filled with signals blocked

    @property
    def is_ai(self) -> bool:
        return self.seat_kind is SeatKind.AI

    @property
    def model_name(self) -> str:
        return self.config().ai_model

    @property
    def seat_name(self) -> str:
        return self.config().ai_name

    def model_names(self) -> list[str]:
        return [self.model.itemText(i) for i in range(self.model.count())]

    def select_model(self, name: str) -> bool:
        """Select ``name`` from the list (any case); ``False`` and no change when it is not there."""
        index = self.model.findText(name.strip(), Qt.MatchFlag.MatchFixedString)
        if index < 0:
            return False
        self.model.setCurrentIndex(index)
        return True

    def _fill_models(self, keep: str = "") -> None:
        """Show the model list of the chosen provider, keeping ``keep`` selected when it is there."""
        provider = self.provider_id
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems(self._models[provider])
        self.model.blockSignals(False)
        if not (keep and self.select_model(keep)):
            self.model.setCurrentIndex(0)
        self.model.setToolTip(f"Model z listy w {PROVIDERS[provider].models_path.name}")

    def set_models(self, models: Mapping[str, Sequence[str]]) -> None:
        """Replace the lists (a file changed), keeping the current choice when it survives."""
        new = {pid: list(models.get(pid, ())) for pid in PROVIDERS}
        if new == self._models:
            return
        self._models = new
        self._fill_models(keep=self.model.currentText())
        self._on_change()

    def _on_provider(self, _index: int) -> None:
        self._fill_models()
        self._on_change()
        if self.is_ai:
            self.becameAI.emit(self)  # lets the lobby move off a model another seat already plays

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
        ai = kind is SeatKind.AI
        smart = kind is SeatKind.SMART
        for widget in (
            self.provider, self.model, self.alias_label, self.alias,
            self.guidelines_label, self.guidelines, self.guidelines_count,
        ):
            widget.setVisible(ai)
        for widget in (self.samples_label, self.samples, self.samples_hint):
            widget.setVisible(smart)
        self.guidelines_count.setText(f"{len(self.guidelines.text())}/{GUIDELINES_MAX_CHARS}")
        problem = self.problem()
        self.note.setText(f"⚠ {problem}" if problem else "")
        if ai and not self._was_ai:
            self._was_ai = True
            self.becameAI.emit(self)
        self._was_ai = ai
        self.changed.emit()
