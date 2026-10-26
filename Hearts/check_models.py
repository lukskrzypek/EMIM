r"""Lists the models your API key can use (read-only request, nothing is generated).

    .\.venv-gui\Scripts\python.exe check_models.py           # Groq (default)
    .\.venv-gui\Scripts\python.exe check_models.py openai

Paste the ids you want into ``groq_models.txt`` or ``openai_models.txt``. Only chat models can
play Hearts; classifiers (``prompt-guard``), speech (``whisper``, ``orpheus``, ``tts``), images
(``dall-e``) and the like are marked as such.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from controllers.ai_bot import DEFAULT_PROVIDER, PROVIDERS, read_api_key  # noqa: E402

MODELS_URLS = {
    "groq": "https://api.groq.com/openai/v1/models",
    "openai": "https://api.openai.com/v1/models",
}
NOT_CHAT = ("guard", "whisper", "orpheus", "tts", "embed", "dall-e", "moderation", "image", "audio",
            "realtime", "transcribe")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Polish text in a Windows console
    args = sys.argv[1:] if argv is None else argv
    provider = (args[0] if args else DEFAULT_PROVIDER).lower()
    if provider not in PROVIDERS:
        print(f"Nieznany dostawca '{provider}'. Dostępne: {', '.join(PROVIDERS)}.")
        return 1
    info = PROVIDERS[provider]
    try:
        key = read_api_key(info.key_path, provider)
    except RuntimeError as exc:
        print(exc)
        return 1
    request = urllib.request.Request(
        MODELS_URLS[provider],
        headers={"Authorization": f"Bearer {key}", "User-Agent": "hearts-check-models"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            models = json.load(response)["data"]
    except Exception as exc:  # noqa: BLE001 - a diagnostic tool: show whatever went wrong
        print(f"Nie udało się pobrać listy modeli: {exc}")
        return 1
    print(
        f"Modele {info.label} dostępne dla tego klucza "
        "('+' = nadaje się do gry, '-' = nie jest modelem czatowym):\n"
    )
    for model in sorted(models, key=lambda m: m["id"]):
        chat = not any(word in model["id"].lower() for word in NOT_CHAT)
        context = model.get("context_window")
        suffix = f"  (kontekst {context})" if context else ""
        print(f"  {'+' if chat else '-'} {model['id']}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
