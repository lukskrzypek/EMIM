"""Description of ``evaluation.params.Params`` for an editor: fields, sections and hints.

Read from the dataclass and from the comments in its source, so a new parameter in
``params.py`` shows up in the dialog without touching the GUI.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, fields, replace

from evaluation.params import Params

_FIELD_RE = re.compile(r"^\s+(\w+):\s*(float|int)\s*=\s*[^#\n]+?(?:#\s*(.*))?$")
_SECTION_RE = re.compile(r"^\s*#\s*---\s*(.+?)\s*---\s*$")
_CONTINUATION_RE = re.compile(r"^\s+#\s*(.*)$")


@dataclass(frozen=True)
class ParamField:
    name: str
    kind: type  # float or int
    default: float
    section: str
    hint: str


def param_fields() -> list[ParamField]:
    """Every tunable of ``Params`` in source order."""
    defaults = Params()
    types = {f.name: f.type for f in fields(Params)}
    section, hints, sections, order = "Parametry", {}, {}, []
    last: str | None = None
    for line in inspect.getsource(Params).splitlines():
        if (m := _SECTION_RE.match(line)) is not None:
            section, last = m.group(1), None
        elif (m := _FIELD_RE.match(line)) is not None:
            name = m.group(1)
            order.append(name)
            sections[name] = section
            hints[name] = (m.group(3) or "").strip()
            last = name
        elif last is not None and (m := _CONTINUATION_RE.match(line)) is not None:
            hints[last] = f"{hints[last]} {m.group(1).strip()}".strip()
        else:
            last = None
    result = []
    for name in order:
        if name not in types:
            continue
        kind = int if types[name] in (int, "int") else float
        result.append(ParamField(name, kind, getattr(defaults, name), sections[name], hints[name]))
    return result


def with_values(base: Params, values: dict[str, float]) -> Params:
    """Copy of ``base`` with the given fields replaced (unknown names are ignored)."""
    known = {f.name: f for f in param_fields()}
    clean = {n: known[n].kind(v) for n, v in values.items() if n in known}
    return replace(base, **clean)


def is_default(params: Params | None) -> bool:
    return params is None or params == Params()
