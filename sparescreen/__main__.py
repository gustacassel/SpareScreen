"""Ponto de entrada: python -m sparescreen"""

import argparse
import socket
import sys

from . import dev
from .config import ConfigStore
from .server import serve
from .sources import default_sources
from .usb import UsbBridge, find_adb


def lan_ip():
    """IP desta máquina na rede local (o que o celular deve usar)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # não envia nada, só escolhe a interface
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main():
    parser = argparse.ArgumentParser(prog="sparescreen", description="SpareScreen: um celular antigo como painel do PC.")
    parser.add_argument("--host", default="0.0.0.0", help="endereço de escuta (padrão: todas as interfaces)")
    parser.add_argument("--port", type=int, default=8765, help="porta HTTP (padrão: 8765)")
    parser.add_argument("--interval", type=float, default=1.0, help="segundos entre leituras (padrão: 1)")
    usb = parser.add_argument_group("USB")
    usb.add_argument("--no-usb", action="store_true", help="não procurar celulares no USB")
    usb.add_argument("--adb", help="caminho do adb, se não estiver no PATH")
    usb.add_argument("--no-open", action="store_true", help="não abrir a página sozinha no celular ao conectar")
    usb.add_argument("--stay-awake", action="store_true",
                     help="liga no celular a opção de manter a tela acesa enquanto estiver no USB")
    parser.add_argument("--dev", action="store_true",
                        help="modo de desenvolvimento: reinicia ao mudar o código e recarrega a página")
    args = parser.parse_args()

    # Quando a saída vai para arquivo/pipe, o Windows usaria cp1252 e quebraria os acentos.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.dev and not dev.is_child():
        dev.supervise(sys.argv[1:])
        return

    config = ConfigStore()
    sources = default_sources() + [config]
    if args.dev:
        sources.append(dev.DevSource())
    server = serve(args.host, args.port, sources, args.interval, config)
    print(f"SpareScreen rodando na porta {args.port}.")
    if args.host in ("0.0.0.0", "::"):
        print(f"  Wi-Fi: no celular, abra http://{lan_ip()}:{args.port}")

    if not args.no_usb:
        adb = find_adb(args.adb)
        if adb:
            print("  USB:   ligue o celular no cabo (com Depuração USB ativa) e a página abre sozinha.")
            open_page = not args.no_open and not dev.is_restart()
            UsbBridge(adb, args.port, open_page=open_page, stay_awake=args.stay_awake).start()
        else:
            print("  USB:   adb não encontrado. Instale o Android Platform Tools para usar o cabo (veja o README).")
    print("Ctrl+C para sair.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
