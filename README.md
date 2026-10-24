# SpareScreen

Use aquele celular antigo da gaveta como um painel do seu computador.
O PC roda um agente em Python que coleta os dados e serve uma página;
o celular só abre essa página no navegador.

A página tem três telas, que se alternam sozinhas (ou com um toque):

- **Hardware:** uso, temperatura, consumo e clock de CPU e GPU, uso de cada núcleo,
  VRAM, RAM e arquivo de paginação.
- **Claude:** janelas de uso de 5 horas e semanal, tokens do Fable na semana,
  tokens de hoje e as sessões abertas (com quais estão trabalhando).
- **PC:** o jogo aberto (e há quanto tempo), o programa em foco, os programas mais
  pesados, as ventoinhas, a rede, o espaço dos discos e a temperatura deles.

Quando uma sessão do Claude termina, a página pula para a tela do Claude, mostra um
aviso com o nome da sessão e toca um "plim" (o som só funciona depois do primeiro
toque na tela, regra dos navegadores).
Funciona em Windows, Linux e macOS, com qualquer aparelho que tenha navegador.
Código aberto e gratuito (licença MIT). Ideias e próximos passos em [IDEIA.md](IDEIA.md).

## Como rodar

Precisa de [Git](https://git-scm.com/) e de [Python](https://www.python.org/) 3.9 ou mais novo.
Baixe o projeto e entre na pasta:

```bash
git clone https://github.com/gustacassel/SpareScreen.git
```

```bash
cd SpareScreen
```

Crie um ambiente Python só para ele:

```bash
python -m venv .venv
```

Ative o ambiente (Windows: `.venv\Scripts\activate`; Linux/macOS: `source .venv/bin/activate`) e instale:

```bash
pip install -e .
```

```bash
sparescreen
```

Dá para ligar o celular de dois jeitos: pelo Wi-Fi ou pelo cabo USB.

### Pelo Wi-Fi

O agente mostra o endereço para abrir no celular, algo como `http://192.168.0.10:8765`.
O celular precisa estar na mesma rede Wi-Fi que o PC.

### Pelo cabo USB

Funciona sem Wi-Fi, e o celular já fica carregando. Usa o `adb reverse`, então
o celular acessa o agente em `http://localhost:8765` pelo cabo.

1. Instale o `adb` (Android Platform Tools) no PC:
   - Windows: `winget install Google.PlatformTools`
   - macOS: `brew install --cask android-platform-tools`
   - Linux (Debian/Ubuntu): `sudo apt install adb`
2. No celular, ative a Depuração USB:
   *Configurações > Sobre o telefone > Informações do software*, toque 7 vezes em
   *Número de compilação*; depois *Opções do desenvolvedor > Depuração USB*.
3. Rode o `sparescreen` e ligue o cabo. Na primeira vez, aceite o aviso
   "Permitir depuração USB?" no celular (marque "Sempre permitir").
4. A página abre sozinha no navegador do celular. Se tirar e ligar o cabo de novo,
   ela volta sozinha.

Se o agente não achar o `adb`, use `--adb CAMINHO`. No Windows, alguns Samsung
precisam do driver USB da Samsung se o celular não aparecer.

### Opções

| Opção | Padrão | O que faz |
|---|---|---|
| `--port` | `8765` | Porta HTTP |
| `--host` | `0.0.0.0` | Endereço de escuta. Só USB: use `127.0.0.1` e nada fica exposto na rede |
| `--interval` | `1` | Segundos entre leituras |
| `--no-usb` | | Não procura celulares no USB |
| `--adb` | procura sozinho | Caminho do `adb` |
| `--no-open` | | Não abre a página no celular ao conectar |
| `--stay-awake` | | Liga no celular a opção de manter a tela acesa enquanto estiver no USB (fica gravada no celular) |
| `--dev` | | Modo de desenvolvimento (veja abaixo) |

## No celular

1. Abra o endereço no navegador (no USB isso é automático).
2. Toque na tela para entrar em tela cheia. Cada toque passa para a próxima tela
   (ou fecha um aviso aberto).
3. Toque longo (segurar ~1 segundo) troca o tema.
4. A engrenagem no canto de cima abre as **configurações**: tema, quais telas entram
   no rodízio, de quanto em quanto tempo trocar, avisos do Claude e som. Tudo fica
   salvo no PC (`~/.sparescreen/config.json`), então sobrevive a recarregar a página.
5. Para a tela não apagar: use `--stay-awake` no USB, ou deixe o celular
   carregando e ative *Opções do desenvolvedor > Permanecer ativo*.

Para testes, dá para forçar pelo endereço: `…:8765/?tela=pc` fica só numa tela
(`hardware`, `claude` ou `pc`) e `…:8765/?tema=neon` força um tema.

## Jogo e programas

- **Jogo aberto:** qualquer programa rodando de dentro das pastas de jogos das lojas
  (Steam `steamapps/common`, Epic Games, GOG, Xbox, Riot, EA, Ubisoft, Battle.net).
  O nome mostrado é o da pasta do jogo. Jogos instalados em outro lugar não aparecem.
- **Em foco:** o programa da janela ativa (só Windows, por enquanto).
- **Mais pesados:** programas somados por executável (todas as abas do Chrome contam
  como um), ordenados por CPU. A % é do processador inteiro.
- FPS ainda não: no Windows isso exige ferramentas como o PresentMon.

## Temperaturas e ventoinhas

- **GPU:** por enquanto só NVIDIA, pelo `nvidia-smi` que já vem com o driver.
  AMD e Intel ainda não aparecem.
- **CPU no Windows:** o Windows só libera esse sensor para programas com driver próprio.
  O painel lê do [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor):
  1. Instale: `winget install LibreHardwareMonitor.LibreHardwareMonitor`
  2. Abra como administrador.
  3. Ligue *Options > Remote Web Server > Run* (porta 8085, o padrão).
  4. Para não precisar lembrar: ligue também *Options > Start Minimized*,
     *Minimize To Tray* e *Run On Windows Startup*.
  O LibreHardwareMonitor também entrega as **ventoinhas** (rpm) e a temperatura dos
  **discos**. As ventoinhas da placa-mãe aparecem como "Fan 1", "Fan 2"... (o número
  do conector); as que estão em 0 rpm são escondidas, porque costumam ser conectores vazios.
  A da GPU aparece como "parada" quando a placa desliga o fan em repouso.
  Como cada placa liga as coisas num conector diferente, o painel não tenta adivinhar
  qual é qual. Em *configurações* você pode dar nomes a elas (ex.: "Fan 2" → "Radiador")
  e escolher qual aparece no card da CPU (por padrão, nenhuma).
- **CPU no Linux:** vem direto do sistema (`k10temp`/`coretemp`), e as ventoinhas de `hwmon`.
- **macOS:** ainda sem temperatura.

## Limites do Claude (5 horas e semanal)

O Claude Code só entrega esses números para a **status line** dele, então o painel
traz um comando de status line que grava os limites num arquivo
(`~/.sparescreen/claude-limits.json`) que o agente lê. Em `~/.claude/settings.json`:

```json
"statusLine": {
  "type": "command",
  "command": "CAMINHO/DO/PROJETO/.venv/Scripts/sparescreen-statusline.exe"
}
```

(No Linux/macOS: `.venv/bin/sparescreen-statusline`.) A status line também mostra o
modelo, o contexto usado e os limites na barra do próprio Claude Code.

Limitações:

- Só funciona nos planos Pro e Max, e os números só atualizam enquanto houver
  uma sessão do Claude Code aberta **no terminal**. O app desktop não roda status line.
- A semanal específica do Fable não vem na status line. No lugar, o painel mostra
  quantos tokens o Fable usou dentro da janela semanal, contados no histórico
  do Claude Code deste PC (uso no claude.ai ou em outros PCs fica de fora).

## Desenvolvendo

Rode com `sparescreen --dev`. O agente se reinicia sozinho quando um arquivo `.py` muda,
e a página no celular recarrega sozinha quando algo em `sparescreen/web/` muda ou o
agente reinicia. Não precisa tocar no celular.

A página é uma moldura (`index.html`) que fica em tela cheia e carrega o painel
(`app.html`) por dentro. Só o painel recarrega, então o celular não sai da tela cheia.

## Problemas comuns

- **O celular não abre a página (Windows):** na primeira execução o Windows pergunta
  se o Python pode receber conexões. Permita em *redes privadas*. Se a rede Wi-Fi
  estiver marcada como *pública*, mude para *privada* ou libere a porta 8765 no firewall.
- **Privacidade no Wi-Fi:** qualquer aparelho na mesma rede consegue abrir a página
  e ver os nomes das sessões do Claude. Em rede que não é sua, use só o USB
  com `--host 127.0.0.1`.
- **Ponto vermelho no canto de cima:** o celular perdeu a conexão com o agente.
  A página reconecta sozinha quando o agente volta.

## Como funciona

- `sparescreen/sources.py`: uso de CPU e RAM via `psutil`.
- `sparescreen/sensors.py`: temperaturas, ventoinhas, discos e GPU (`nvidia-smi`, LibreHardwareMonitor, hwmon).
- `sparescreen/claude.py`: lê `~/.claude` (ou `CLAUDE_CONFIG_DIR`). As sessões abertas vêm
  de `sessions/*.json`; os tokens vêm dos históricos `projects/**/*.jsonl` dos
  últimos 8 dias, lidos só no trecho novo a cada 5 segundos e somados em blocos de
  15 minutos. São formatos internos do Claude Code e podem mudar entre versões.
- `sparescreen/statusline.py`: a status line que grava os limites para o agente.
- `sparescreen/server.py`: servidor HTTP da biblioteca padrão. A página recebe os dados
  por Server-Sent Events em `/events`, uma vez por segundo.
- `sparescreen/usb.py`: a cada 3 segundos olha `adb devices`, aplica o `adb reverse`
  nos celulares conectados e abre a página neles.
- `sparescreen/activity.py`: jogo aberto, programa em foco e programas mais pesados.
- `sparescreen/config.py`: as preferências salvas em `~/.sparescreen/config.json` (POST `/config`).
- `sparescreen/dev.py`: o modo `--dev` (supervisor que reinicia o agente e a versão do código).
- `sparescreen/hwinfo.py`: nomes curtos da CPU, GPU e memória.
- `sparescreen/web/`: a página (HTML, CSS e JS simples, pensados para navegadores antigos).
  `index.html` é só a moldura; o painel está em `app.html`, `app.js` e `style.css`.

## Licença

[MIT](LICENSE): pode usar, copiar, modificar e distribuir à vontade, inclusive em
projetos comerciais, desde que mantenha o aviso de licença.
