"""Modo de desenvolvimento (sparescreen --dev).

- Mudou um .py: o agente é reiniciado sozinho.
- Mudou algo em web/ (ou o agente reiniciou): a página no celular recarrega sozinha.

Funciona com dois processos: este supervisor, que vigia os arquivos, e o agente
de verdade como processo filho. A página percebe a mudança pela "versão" que
vai junto com os dados (campo `dev`).
"""

import os
import subprocess
import sys
import time
from pathlib import Path

PACKAGE = Path(__file__).parent
CHILD_ENV = "SPARESCREEN_DEV_CHILD"
RESTART_ENV = "SPARESCREEN_DEV_RESTART"


def _python_mtimes():
    return {p: p.stat().st_mtime for p in PACKAGE.rglob("*.py")}


class DevSource:
    """Versão do código: muda quando o agente reinicia ou um arquivo da página muda."""

    name = "dev"

    def __init__(self):
        self.started = time.time()

    def read(self):
        web = max((p.stat().st_mtime for p in (PACKAGE / "web").iterdir()), default=0)
        return f"{self.started:.0f}-{web:.3f}"


def is_child():
    return bool(os.environ.get(CHILD_ENV))


def is_restart():
    return bool(os.environ.get(RESTART_ENV))


def supervise(argv):
    """Roda o agente num processo filho e reinicia quando um .py muda."""
    env = dict(os.environ, **{CHILD_ENV: "1"})
    snapshot = _python_mtimes()
    child = None
    print("[dev] modo dev: o agente reinicia quando um .py muda e a página recarrega sozinha.", flush=True)
    try:
        while True:
            if child is None:
                child = subprocess.Popen([sys.executable, "-m", "sparescreen", *argv], env=env)
                env[RESTART_ENV] = "1"  # nos próximos reinícios, não reabre a página no celular
            time.sleep(1)
            current = _python_mtimes()
            if current != snapshot:
                snapshot = current
                print("[dev] código Python mudou, reiniciando o agente...", flush=True)
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=10)
                child = None
            elif child.poll() is not None and not getattr(child, "_reported", False):
                # Provavelmente um erro no código: espera a próxima alteração para tentar de novo.
                child._reported = True
                print("[dev] o agente parou. Corrija o erro acima e salve; ele volta sozinho.", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
