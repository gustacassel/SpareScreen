"""Status line do Claude Code que repassa os limites de uso para o painel.

Configurada em ~/.claude/settings.json ("statusLine"). O Claude Code roda este
comando a cada atualização e manda os dados da sessão em JSON pelo stdin; o
campo `rate_limits` (janelas de 5 h e semanal) só existe nos planos Pro/Max.
Gravamos esse campo num arquivo que o agente do painel lê.
"""

import json
import os
import sys
import time
from pathlib import Path

LIMITS_FILE = Path.home() / ".sparescreen" / "claude-limits.json"


def save_limits(limits):
    LIMITS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LIMITS_FILE.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"updated_at": time.time(), "rate_limits": limits}), encoding="utf-8")
    os.replace(tmp, LIMITS_FILE)  # troca atômica: o agente nunca lê um arquivo pela metade


def load_limits():
    try:
        return json.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def status_text(data):
    parts = [(data.get("model") or {}).get("display_name") or "Claude"]
    ctx = (data.get("context_window") or {}).get("used_percentage")
    if ctx is not None:
        parts.append(f"ctx {ctx:.0f}%")
    limits = data.get("rate_limits") or {}
    for key, label in (("five_hour", "5h"), ("seven_day", "semana")):
        pct = (limits.get(key) or {}).get("used_percentage")
        if pct is not None:
            parts.append(f"{label} {pct:.0f}%")
    return " · ".join(parts)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except ValueError:
        data = {}
    if data.get("rate_limits"):
        try:
            save_limits(data["rate_limits"])
        except OSError:
            pass  # a status line nunca pode falhar por causa do painel
    print(status_text(data))


if __name__ == "__main__":
    main()
