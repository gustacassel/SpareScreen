# SpareScreen

Ferramenta aberta e gratuita que transforma um celular antigo (ou qualquer aparelho
com navegador) num painel do PC: hardware, o que está rodando e uso do Claude Code.
Visão, fases e pesquisa em [IDEIA.md](IDEIA.md); uso em [README.md](README.md).

## Diretriz principal: genérico, nunca "o PC de alguém"

Esta ferramenta é para qualquer pessoa, em qualquer PC e com qualquer aparelho.
O PC e o celular de quem desenvolve são só ambientes de teste.

- **Nada específico de uma máquina no código ou nos padrões.** Não supor modelo de
  placa-mãe, ordem de conectores ("Fan 1 é a CPU"), marca de GPU, quantidade de núcleos,
  letras de disco, nome de usuário, caminhos locais ou o aparelho de teste.
- **Descobrir em tempo de execução.** Mostrar o que o sistema daquela pessoa informar.
  Se um dado não existir, esconder a linha ou mostrar "sem dados"; nunca inventar.
- **Personalização é do usuário, não do código.** Nomes de ventoinhas, qual ventoinha
  aparece no card da CPU, tema, telas etc. ficam na config de cada pessoa
  (`~/.sparescreen/config.json`, editável pela tela de configurações), com padrão neutro.
- **Exemplos na documentação** podem citar um hardware real, mas sempre como exemplo.

## Outros princípios

- **Multiplataforma (Windows, Linux, macOS).** Recurso que só existe num sistema precisa
  degradar sem erro nos outros e estar documentado no README (o que funciona onde).
- **Qualquer aparelho com navegador.** A página (`sparescreen/web/`) roda em navegadores
  antigos: alvo mínimo Chrome 49 / iOS 10 (variáveis CSS, URLSearchParams, EventSource).
  Nada de `gap` em flexbox, `inset`, `aspect-ratio`, optional chaining, `?.`, `??`,
  módulos ES ou outras sintaxes recentes. Testar em retrato e paisagem (360x640).
- **Gratuito e aberto.** Só dependências livres e gratuitas; nada que exija conta ou pagamento.
- **Local e privado.** Os dados ficam na rede local; nada é enviado para fora.
- **Formatos internos de terceiros** (ex.: arquivos do Claude Code) são lidos de forma
  tolerante: campos ausentes não podem derrubar o agente.

## Desenvolvimento

- `sparescreen --dev`: reinicia o agente quando um `.py` muda e recarrega a página sozinha.
- Código e comentários seguem o estilo existente: identificadores em inglês,
  comentários, mensagens e interface em português.
