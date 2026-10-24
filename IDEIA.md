# SpareScreen: celular antigo como painel do PC

Usar um celular antigo (ou qualquer aparelho com navegador) ligado ao computador por
USB ou Wi-Fi como um display auxiliar programável: uso do Claude Code, CPU/GPU (uso e
temperatura), fotos, texto passando, relógio etc.

**Objetivos:** rodar em qualquer sistema (Windows, Linux, macOS), ser código aberto e
gratuito, funcionar com qualquer celular ou aparelho, e ser **genérico**: nada amarrado
ao PC ou ao celular de quem desenvolve (veja a diretriz em [CLAUDE.md](CLAUDE.md)).

## O que já existe (pesquisa em 24/10/2026)

| Projeto | O que faz | Por que não resolve tudo |
|---|---|---|
| Remote System Monitor (Trigone) | App Android + servidor no PC mostrando sensores via Wi-Fi | Servidor só Windows, fechado, com anúncios; só hardware |
| AIDA64 RemoteSensor / Remote Panel | AIDA64 serve uma página com sensores; o celular abre no navegador ou via app por ADB | Pago, só Windows, só hardware |
| HWMonitor PRO (CPUID) | Monitora máquinas pela rede, inclusive no Android | Pago, focado em hardware |
| zvocrljen/HWMonitor (GitHub) | App Android + serviço no PC com OpenHardwareMonitor, USB ou Wi-Fi | Só Windows, só hardware |
| turing-smart-screen-python | Monitor de sistema com temas para telinhas USB baratas (Turing/XuanFang) | Multiplataforma, mas para hardware específico, não celular. Boa referência de temas |
| Clawdmeter, ClaudeGauge, TokenMonitor | Mostram uso do Claude Code em placas ESP32 com tela | Exigem comprar/montar hardware |
| Dashkiosk, kiFOSSk, Fully Kiosk | Navegador em tela cheia (kiosk) para Android | Só mostram uma página; não coletam nada do PC |
| spacedesk, Duet, linux-second-screen | Celular como segundo monitor (extensão da área de trabalho) | Outra proposta: espelha/estende a tela, não é um painel de widgets |

**Conclusão:** as peças existem separadas, mas não achei uma ferramenta aberta,
multiplataforma, que junte widgets genéricos (hardware + Claude + foto + texto)
num celular antigo, por USB e sem app obrigatório. Esse é o espaço do projeto.

## Esboço da arquitetura

```
 PC (Windows/Linux/macOS)                         Celular antigo
 ┌──────────────────────────────┐                 ┌─────────────────────┐
 │ agente                        │  HTTP +         │ navegador em tela   │
 │  ├─ fontes de dados (plugins) │  WebSocket      │ cheia (ou app kiosk │
 │  │   hardware, claude, foto,  │ ──────────────► │ simples depois)     │
 │  │   texto, relógio...        │  USB: adb       │                     │
 │  ├─ layout (JSON/tema)        │  reverse        │ renderiza widgets   │
 │  └─ servidor web + UI         │  Wi-Fi: IP:porta│                     │
 └──────────────────────────────┘                 └─────────────────────┘
```

- **Agente no PC**: coleta dados e serve uma página web com os widgets.
  Envia atualizações por Server-Sent Events (só PC → celular, sem dependência
  extra; WebSocket fica para quando o celular precisar mandar comandos).
- **Celular**: no começo, nenhum app próprio. Só abre a página no navegador.
  - **USB**: o agente roda `adb reverse tcp:PORTA tcp:PORTA` e o celular abre
    `http://localhost:PORTA`. Funciona igual nos três sistemas e não precisa de root.
    Bônus: `localhost` conta como contexto seguro, então a Wake Lock API
    (manter a tela ligada) funciona.
  - **Wi-Fi**: abre `http://IP-do-PC:PORTA`. Para a tela não apagar, usar a opção
    de desenvolvedor "Permanecer ativo" (com o celular carregando).
- **Layout/temas**: um arquivo descrevendo a grade e os widgets, editável à mão
  e, mais tarde, por uma tela de configuração no PC.

### Fontes de dados (widgets) iniciais

- **Hardware**: uso de CPU/RAM/disco/rede (fácil em qualquer SO).
  Temperaturas são a parte difícil:
  - Windows: LibreHardwareMonitor (precisa de admin).
  - Linux: `/sys/class/hwmon` / lm-sensors.
  - macOS: limitado, sobretudo em Apple Silicon.
  - GPU NVIDIA: NVML / `nvidia-smi` (multiplataforma).
- **Claude Code**: ler os logs locais em `~/.claude/projects/**/*.jsonl`
  (mesma ideia do `ccusage`) para tokens, custo estimado, sessões ativas.
- **Foto / slideshow**, **texto passando**, **relógio/clima**.

## Aparelhos antigos

- Alvo mínimo da página: Chrome 49 / iOS 10 (navegadores de ~2016 em diante).
- Aparelho de teste atual: Galaxy J5 Prime (Android 8.0, navegador anterior ao
  Chrome 84: sem `gap` em flexbox, sem Wake Lock). Serve de teste, não de alvo.
- Consequência: HTML/CSS/JS conservador e testes em retrato e paisagem.

## Fases sugeridas

1. ✅ **MVP**: agente que serve a página + widgets de CPU/RAM e relógio, via Wi-Fi.
   Testado no J5 Prime: o navegador dele é anterior ao Chrome 84 (sem `gap` em
   flexbox, sem Wake Lock), então a página precisa de CSS/JS bem conservador.
2. ✅ USB automático com `adb reverse` (o agente detecta o celular, configura e abre a página).
3. ✅ Widget do Claude Code: tokens de hoje e sessões abertas (trabalhando/parada).
   Ideias para depois: gráfico de tokens por hora, janela de 5 h, custo estimado.
   O USB está pronto, mas ainda não foi testado no J5 (falta um cabo micro-USB de dados).
4. ✅ Telas separadas (hardware e Claude), que giram sozinhas ou com um toque.
   ✅ Temperaturas: GPU via `nvidia-smi`, CPU via LibreHardwareMonitor (Windows) e hwmon (Linux).
   ✅ Limites de 5 h e semanal via status line do Claude Code (só sessões no terminal).
   ✅ Nomes das peças, ícones, 6 temas (toque longo troca), aviso quando uma sessão do Claude termina.
   ✅ Modo `--dev`: reinicia o agente e recarrega a página sozinho, sem sair da tela cheia.
   ✅ Tela de configurações (tema, telas, troca, avisos, som), salva no PC.
   ✅ Tela PC: jogo aberto, programa em foco, mais pesados, ventoinhas, rede e discos.
   ✅ Nomes personalizados para as ventoinhas, clocks de CPU/GPU, núcleos em grade.
   Falta: foto e texto passando, gráficos de histórico, FPS (veja também as lacunas abaixo).
5. Opcional: app Android mínimo (WebView kiosk, minSdk 23) para abrir sozinho,
   tela cheia e tela sempre ligada.

## Revisão contra os objetivos (24/10/2026)

**Atende:** agente em Windows/Linux/macOS; qualquer aparelho com navegador pelo Wi-Fi;
só dependências livres e gratuitas; peças descobertas em tempo de execução;
personalização salva na config de cada pessoa.

**Corrigido nesta revisão:** o card da CPU supunha que "Fan 1" era o cooler (verdade
só em algumas placas); agora o usuário escolhe nas configurações (padrão: nenhuma).

**Lacunas, em ordem de prioridade:**

1. ✅ **Licença e repositório.** MIT, em github.com/gustacassel/SpareScreen.
2. **GPU AMD e Intel.** Hoje só NVIDIA (`nvidia-smi`). No Windows o LibreHardwareMonitor
   já lê AMD/Intel; no Linux, `amdgpu`/`i915` via hwmon/sysfs.
3. **Segurança na rede local.** Qualquer um no Wi-Fi vê sessões e processos e muda a
   config. Ideia: código de pareamento/token, ou só USB por padrão.
4. **Instalação para quem não programa.** Hoje exige Python + venv. Ideia: executável
   por sistema (PyInstaller) e iniciar com o sistema.
5. **Claude genérico.** Trocar "Fable · semana" por "tokens da semana por modelo";
   status line que convive com uma status line que a pessoa já tenha.
6. **macOS e Linux completos.** Temperatura/ventoinhas no macOS; "programa em foco" no Linux.
7. **Idioma.** Interface só em português; avaliar inglês para o repositório público.
8. **Testar aparelhos de verdade:** iPhone/iPad pelo Wi-Fi, Android bem antigo,
   tablet; USB com cabo de dados.

## Para pensar no futuro

- **Tela marcando (burn-in).** Painel fixo por horas, com as mesmas cores no mesmo
  lugar, pode marcar a tela, como acontecia com o "always on display" dos celulares.
  É sério em telas **AMOLED/OLED** (muitos Samsung antigos); em **LCD** o risco é
  menor (no máximo retenção temporária), mas a luz de fundo também envelhece.
  Ideias para contornar:
  - Mover o conteúdo alguns pixels de tempos em tempos (pixel shift), invisível para quem olha.
  - O rodízio de telas já ajuda; evitar elementos claros e fixos (barra de cima, títulos).
  - Tema escuro por padrão em OLED, brilho menor e "modo noite" que apaga ou só mostra
    um relógio que anda pela tela.
  - Desligar/escurecer quando o PC estiver ocioso ou bloqueado.
  - Opção na config para ativar/desativar, já que depende do tipo de tela.

## Decisões

- ✅ Linguagem do agente: Python (psutil, protótipo rápido, multiplataforma).
- ✅ Nome: SpareScreen.
- ✅ Licença: MIT.
- ✅ Distribuição: só pelo GitHub (clonar e rodar); sem publicar no PyPI por enquanto.
- Em aberto: idioma da interface.

## Fontes

- https://www.pcgamesn.com/android/remote-system-monitor
- https://www.tomsguide.com/computing/i-turned-an-old-phone-into-a-system-monitor-for-my-computer-and-the-results-blew-me-away
- https://forum.manjaro.org/t/remote-system-monitor-trigone-pitikapp-remote-dashboard-for-manjaro-android-temps-and-stats-dashboard/143613
- https://forums.aida64.com/topic/2636-remotesensor-lcd-for-smartphones-and-tablets/
- https://forums.aida64.com/topic/2776-display-pc-sensor-values-on-android-device-connected-via-usb-odospace-remote-panel/page/4
- https://cpuid.com/softwares/hwmonitor-pro-android.html
- https://github.com/zvocrljen/HWMonitor
- https://github.com/mathoudebine/turing-smart-screen-python
- https://www.cnx-software.com/2026/05/14/clawdmeter-a-diy-esp32-s3-desk-dashboard-for-claude-code-token-usage-monitoring/
- https://www.hackster.io/dorofino/claudegauge-real-time-ai-usage-monitor-on-esp32-s3-with-a-a82d4b
- https://www.cnx-software.com/2026/08/07/token-monitor-an-esp32-s3-desktop-display-that-tracks-ai-coding-assistant-usage/
- https://dashkiosk.readthedocs.io/en/v2.5.0/android.html
- https://f-droid.org/en/packages/com.shinydiscoballsdev.kifossk/
- https://gittrend.io/repo/brunodles/linux-second-screen
- https://blog.grio.com/2015/07/android-tip-adb-reverse.html
- https://en.wikipedia.org/wiki/Samsung_Galaxy_J5_Prime
- https://9to5google.com/2025/06/26/google-chrome-android-versions-no-longer-supported-2025/
