r"""Lists the Groq models your API key can use (read-only request, nothing is generated).

    .\.venv-gui\Scripts\python.exe check_models.py

Paste the ids you want into ``groq_models.txt``. Only chat models can play Hearts; classifiers
(``prompt-guard``), speech (``whisper``, ``orpheus``) and the like are marked as such.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from controllers.groq_icl_bot import DEFAULT_API_KEY_PATH, read_api_key  # noqa: E402

NOT_CHAT = ("guard", "whisper", "orpheus", "tts", "embed")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Polish text in a Windows console
    try:
        key = read_api_key(DEFAULT_API_KEY_PATH)
    except RuntimeError as exc:
        print(exc)
        return 1
    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {key}", "User-Agent": "hearts-check-models"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            models = json.load(response)["data"]
    except Exception as exc:  # noqa: BLE001 - a diagnostic tool: show whatever went wrong
        print(f"Nie udało się pobrać listy modeli: {exc}")
        return 1
    print("Modele dostępne dla tego klucza ('+' = nadaje się do gry, '-' = nie jest modelem czatowym):\n")
    for model in sorted(models, key=lambda m: m["id"]):
        chat = not any(word in model["id"].lower() for word in NOT_CHAT)
        print(f"  {'+' if chat else '-'} {model['id']}  (kontekst {model.get('context_window')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
