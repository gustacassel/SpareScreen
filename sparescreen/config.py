"""Preferências da página, salvas no PC em ~/.sparescreen/config.json.

A tela de configurações no celular manda as mudanças por POST /config; o agente
valida, grava e devolve a configuração junto com os dados (campo `config`).
"""

import json
import os
import threading
from pathlib import Path

THEMES = ("grafite", "oled", "terracota", "neon", "terminal", "claro")
SCREENS = ("hardware", "claude", "pc")
ROTATE = (0, 10, 20, 30, 60)  # segundos; 0 = não troca sozinho

DEFAULTS = {
    "theme": "grafite",
    "screens": list(SCREENS),
    "rotate": 20,
    "notify": True,
    "sound": True,
    "fan_names": {},  # nome original -> nome dado pelo usuário (ex.: "Fan 2" -> "Radiador")
    "cpu_fan": None,  # qual ventoinha aparece no card da CPU (escolha do usuário; nenhuma por padrão)
}

CONFIG_FILE = Path.home() / ".sparescreen" / "config.json"


def clean(data):
    """Fica só com as chaves e valores válidos; o resto é ignorado."""
    if not isinstance(data, dict):
        return {}
    out = {}
    if data.get("theme") in THEMES:
        out["theme"] = data["theme"]
    if isinstance(data.get("screens"), list):
        screens = [s for s in SCREENS if s in data["screens"]]
        if screens:  # pelo menos uma tela
            out["screens"] = screens
    if data.get("rotate") in ROTATE:
        out["rotate"] = data["rotate"]
    for key in ("notify", "sound"):
        if isinstance(data.get(key), bool):
            out[key] = data[key]
    if "cpu_fan" in data and (data["cpu_fan"] is None or isinstance(data["cpu_fan"], str)):
        out["cpu_fan"] = data["cpu_fan"][:20] if data["cpu_fan"] else None
    names = data.get("fan_names")
    if isinstance(names, dict):  # nome vazio = volta ao nome original
        out["fan_names"] = {
            str(fan)[:20]: name.strip()[:16]
            for fan, name in names.items()
            if isinstance(name, str) and name.strip()
        }
    return out


class ConfigStore:
    """Também serve de fonte de dados: a página recebe a config a cada leitura."""

    name = "config"

    def __init__(self, path=CONFIG_FILE):
        self.path = path
        self._lock = threading.Lock()
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        self._config = {**DEFAULTS, **clean(saved)}

    def read(self):
        with self._lock:
            return dict(self._config)

    def update(self, changes):
        with self._lock:
            self._config.update(clean(changes))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._config, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            return dict(self._config)
