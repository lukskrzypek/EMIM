"""Editor for the evaluator's tunable numbers (``evaluation.params.Params``)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from evaluation.params import Params
from gui.core.params_schema import ParamField, param_fields, with_values


def _editor(field: ParamField, value: float) -> QDoubleSpinBox | QSpinBox:
    if field.kind is int:
        box = QSpinBox()
        box.setRange(0, 1000)
        box.setValue(int(value))
    else:
        box = QDoubleSpinBox()
        box.setRange(0.0, 1000.0)
        box.setDecimals(2)
        box.setSingleStep(0.05 if field.default <= 1 else 1.0)
        box.setValue(float(value))
    box.setToolTip(field.hint or field.name)
    box.setMinimumWidth(90)
    return box


class ParamsDialog(QDialog):
    def __init__(self, current: Params | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Parametry oceny")
        self.resize(640, 640)
        self._base = current if current is not None else Params()
        self.fields = param_fields()
        self.editors: dict[str, QDoubleSpinBox | QSpinBox] = {}

        note = QLabel(
            "Zmiany dotyczą ocen na żywo w tej sesji. Raport z logu zawsze liczy parametrami "
            "domyślnymi, więc przy własnych wartościach oba wyniki mogą się różnić."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        sections: dict[str, QFormLayout] = {}
        for field in self.fields:
            form = sections.get(field.section)
            if form is None:
                group = QGroupBox(field.section)
                form = QFormLayout(group)
                sections[field.section] = form
                inner_layout.addWidget(group)
            editor = _editor(field, getattr(self._base, field.name))
            self.editors[field.name] = editor
            label = QLabel(field.name)
            label.setToolTip(field.hint)
            hint = QLabel(field.hint)
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            cell = QVBoxLayout()
            cell.setSpacing(2)
            cell.addWidget(editor)
            cell.addWidget(hint)
            form.addRow(label, cell)
        inner_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        restore = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        restore.setText("Przywróć domyślne")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Anuluj")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        restore.clicked.connect(self.restore_defaults)

        layout = QVBoxLayout(self)
        layout.addWidget(note)
        layout.addWidget(scroll, 1)
        layout.addWidget(buttons)

    def restore_defaults(self) -> None:
        for field in self.fields:
            self.editors[field.name].setValue(field.default)

    def params(self) -> Params:
        return with_values(self._base, {name: box.value() for name, box in self.editors.items()})
