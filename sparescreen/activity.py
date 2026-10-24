"""O que está rodando no PC: jogo aberto, programa em foco e os processos mais pesados.

Jogo é detectado pelo caminho do executável: tudo que roda de dentro das pastas
de biblioteca das lojas (Steam, Epic, GOG, Xbox, Riot, EA, Ubisoft...). O nome
do jogo é o da pasta, que nessas lojas costuma ser o nome bonito.
"""

import ctypes
import os
import re
import sys
import time

import psutil

# (trecho do caminho, em minúsculas e com "/") -> o nome do jogo é a pasta logo depois
GAME_DIRS = (
    "/steamapps/common/",
    "/epic games/",
    "/gog galaxy/games/",
    "/gog games/",
    "/xboxgames/",
    "/riot games/",
    "/ea games/",
    "/ubisoft game launcher/games/",
    "/battle.net/games/",
)
# Pastas que ficam dentro desses lugares, mas não são jogos.
NOT_GAMES = {"launcher", "directxredist", "steamworks shared", "riot client", "epic online services"}
# Processos auxiliares que rodam da pasta do jogo.
HELPERS = re.compile(r"crash|report|easyanticheat|battleye|unitycrashhandler|redist|setup|launcher", re.I)


def game_name(exe):
    path = (exe or "").replace("\\", "/").lower()
    for marker in GAME_DIRS:
        start = path.find(marker)
        if start < 0:
            continue
        rest = exe.replace("\\", "/")[start + len(marker):]
        folder = rest.split("/", 1)[0]
        if folder and folder.lower() not in NOT_GAMES:
            return folder
    return None


# ---- Nome amigável do programa (Windows: "Descrição do arquivo" do .exe) -----

_descriptions = {}


def _file_description(exe):
    """'C:/.../chrome.exe' -> 'Google Chrome', lendo o recurso de versão do executável."""
    version = ctypes.windll.version
    size = version.GetFileVersionInfoSizeW(exe, None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(exe, 0, size, buf):
        return None
    ptr, length = ctypes.c_void_p(), ctypes.c_uint()
    if not version.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)) \
            or length.value < 4:
        return None
    lang, codepage = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
    key = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileDescription"
    if not version.VerQueryValueW(buf, key, ctypes.byref(ptr), ctypes.byref(length)) or not length.value:
        return None
    return ctypes.wstring_at(ptr.value, length.value).rstrip("\x00").strip() or None


def friendly_name(name, exe):
    key = exe or name
    if key not in _descriptions:
        desc = None
        if sys.platform == "win32" and exe:
            try:
                desc = _file_description(exe)
            except (OSError, AttributeError, ValueError):
                desc = None
        _descriptions[key] = desc or os.path.splitext(name or "?")[0]
    return _descriptions[key]


def foreground_pid():
    """PID da janela em foco (só Windows, por enquanto)."""
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


class ActivitySource:
    """Jogo aberto, programa em foco e top processos (somados por programa)."""

    name = "activity"
    IGNORE = {"system idle process", "idle", "system", "registry", "memory compression"}

    def __init__(self, refresh=3, top=4):
        self.refresh = refresh
        self.top = top
        self.cores = psutil.cpu_count() or 1
        self._at = 0
        self._cache = {"game": None, "focus": None, "top": []}

    def read(self):
        if time.time() - self._at < self.refresh:
            return self._cache
        self._at = time.time()

        focus_pid = foreground_pid()
        programs = {}  # exe (ou nome) -> totais
        game = None
        focus = None
        for proc in psutil.process_iter(["name", "exe", "memory_info", "create_time"]):
            info = proc.info
            name = info["name"] or ""
            if name.lower() in self.IGNORE or proc.pid == 0:
                continue
            try:
                cpu = proc.cpu_percent(None) / self.cores  # 1ª leitura de cada processo volta 0
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            mem = info["memory_info"].rss if info["memory_info"] else 0
            exe = info["exe"]
            key = exe or name
            prog = programs.setdefault(key, {"name": name, "exe": exe, "cpu": 0.0, "mem": 0, "since": None})
            prog["cpu"] += cpu
            prog["mem"] += mem
            if info["create_time"] and (prog["since"] is None or info["create_time"] < prog["since"]):
                prog["since"] = info["create_time"]

            title = game_name(exe)
            if title and not HELPERS.search(name):
                if game is None or mem > game["_mem"]:
                    game = {"name": title, "_mem": mem, "_key": key}
            if proc.pid == focus_pid:
                focus = key

        if game:
            prog = programs[game.pop("_key")]
            game.pop("_mem")
            game.update(cpu=round(prog["cpu"], 1), mem=prog["mem"], since=prog["since"])

        def describe(prog):
            return {
                "name": friendly_name(prog["name"], prog["exe"]),
                "cpu": round(prog["cpu"], 1),
                "mem": prog["mem"],
            }

        heavy = sorted(programs.values(), key=lambda p: (p["cpu"], p["mem"]), reverse=True)
        self._cache = {
            "game": game,
            "focus": describe(programs[focus]) if focus in programs else None,
            "top": [describe(p) for p in heavy[:self.top]],
        }
        return self._cache
