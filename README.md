# Rastreador de Empenhos por Item — Compras Públicas Federais (PNCP)

[![GitHub Pages](https://img.shields.io/badge/relatórios-online-blue)](https://tiagopossato.github.io/rastreador_empenhos/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)

Aplicação em Python para monitoramento e auditoria de compras públicas homologadas no **Portal Nacional de Contratações Públicas (PNCP)**. A ferramenta coleta dados de editais, itens e fornecedores vencedores, relaciona notas de empenho emitidas (via PNCP, Portal da Transparência e Contratos.gov.br) e gera relatórios HTML autônomos com o saldo executado e remanescente por item.

O projeto inclui linha de comando (CLI), rotinas de atualização em lote via cron e uma interface web administrativa privada para gestão de processos monitorados.

---

## Acesso Rápido

- 🌐 **Relatórios Públicos Publicados:** [https://tiagopossato.github.io/rastreador_empenhos/](https://tiagopossato.github.io/rastreador_empenhos/)
- 📖 **Documentação Técnica Interna e Fluxograma:** consulte [`src/rastreador_empenhos/README.md`](file:///c:/Users/tiago/Documents/rastreador_empenhos/src/rastreador_empenhos/README.md).

---

## Como Funciona (Visão Geral)

1. **Coleta do Edital e Itens (PNCP):** Obtém dados gerais da contratação, relação completa de itens licitados, fornecedores homologados e registros publicados na aba Contratos/Empenhos do PNCP.
2. **Detalhamento das Notas de Empenho:** Consulta as despesas por favorecido e documentos detalhados no Portal da Transparência e na API Contratos.gov.br para obter quantidades físicas reais e identificar a situação de cada empenho (regular, reforço, anulação ou cancelamento).
3. **Mapeamento e Cálculo de Saldos:** Associa cada empenho ao respectivo item homologado, distinguindo compras originais de adesões (caronas), e calcula:
   $$\text{Saldo do Item} = \text{Quantidade Homologada} - \sum \text{Quantidade Empenhada Original}$$
4. **Geração de Relatórios:** Produz relatórios HTML autônomos (sem dependências externas), tabelas com busca e filtros dinâmicos, exportação em CSV e índices consolidados.

---

## Requisitos do Sistema

- **Python 3.10 ou superior**.
- **Chave de API do Portal da Transparência** (gratuita, obtida em [portaldatransparencia.gov.br/api-de-dados/cadastrar-chave](https://portaldatransparencia.gov.br/api-de-dados/cadastrar-chave)).

---

## Instalação

### Opção 1: Como ferramenta CLI isolada via `pipx` (Recomendado)

Garante que os comandos fiquem disponíveis no `PATH` sem conflitos de dependências:

```bash
pipx install .
```

Para desenvolvimento local com atualização automática das alterações:

```bash
pipx install -e .
```

### Opção 2: Via ambiente virtual (`venv`) e `pip`

```bash
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
python -m pip install -e .
```

Após a instalação, os seguintes comandos CLI ficam disponíveis:

| Comando | Descrição |
|---|---|
| `rastreador-empenhos` | CLI principal para rastrear e atualizar um processo específico. |
| `rastreador-empenhos-atualizar` | Atualiza em lote todos os processos cadastrados (ideal para cron). |
| `rastreador-empenhos-gerar-indice` | Regenera índices e HTMLs locais a partir dos JSONs sem chamar as APIs. |
| `rastreador-empenhos-criar-usuario` | Cria credenciais de acesso local para a interface web administrativa. |
| `rastreador-empenhos-admin` | Inicia o servidor administrativo Waitress (privado). |

---

## Configuração do Ambiente

Crie um arquivo `.env` na raiz do repositório:

```dotenv
PORTAL_DADOS_API_KEY=sua_chave_aqui
```

Também é aceita a variável de ambiente `PORTALTRANSPARENCIA_API_KEY`.

> **Resolução da raiz do projeto:** O sistema busca automaticamente arquivos como `.env`, pasta `.private/` e `relatorios/` a partir da raiz do repositório. Para definir um caminho fixo explicitamente, use a variável `RASTREADOR_EMPENHOS_ROOT=/caminho/do/projeto`.

---

## Como Executar

### 1. Rastrear um processo individualmente

Informe a URL pública do edital no PNCP:

```bash
rastreador-empenhos "https://pncp.gov.br/app/editais/10635424000186/2025/187"
```

*(Se omitir a URL, ela será solicitada interativamente no terminal).*

#### Descoberta ampla no Portal da Transparência (`--buscar-empenhos-portal`)

Por padrão, a ferramenta consome os empenhos listados na aba Contratos/Empenhos do PNCP. Caso deseje que o rastreador faça uma busca ativa complementar no Portal da Transparência (por contrato, licitação e CNPJ de fornecedores homologados):

```bash
rastreador-empenhos "https://pncp.gov.br/app/editais/10635424000186/2025/187" --buscar-empenhos-portal
```

### 2. Atualizar todos os processos cadastrados (Rotina Automática / Cron)

```bash
rastreador-empenhos-atualizar
```

Exemplo de agendamento no `crontab` do Linux (execução diária às 03:00):

```cron
0 3 * * * cd /opt/rastreador_empenhos && /usr/local/bin/rastreador-empenhos-atualizar >> /var/log/rastreador-empenhos.log 2>&1
```

### 3. Regenerar relatórios sem bater nas APIs externas

Se você alterou os templates HTML ou quer reconstruir o índice a partir dos JSONs já salvos em disco:

```bash
rastreador-empenhos-gerar-indice
```

---

## Painel Administrativo Privado

A aplicação conta com um painel web privado em Flask servido via Waitress para cadastrar novos editais, alternar a busca ampla e acionar atualizações em segundo plano.

1. **Crie o primeiro usuário administrador:**
   ```bash
   rastreador-empenhos-criar-usuario
   ```
   *(As senhas são protegidas com hash PBKDF2 salgado em `.private/usuarios.json`).*

2. **Defina a chave de sessão secreta:**
   - PowerShell (Windows):
     ```powershell
     $env:PNCP_ADMIN_SESSION_SECRET = (python -c "import secrets; print(secrets.token_urlsafe(48))")
     ```
   - Bash (Linux/macOS):
     ```bash
     export PNCP_ADMIN_SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
     ```

3. **Inicie o servidor:**
   ```bash
   rastreador-empenhos-admin
   ```
   Acesse no navegador: `http://127.0.0.1:8000/`.

> **Segurança:** O servidor Waitress escuta por padrão em `127.0.0.1:8000`. Não o exponha diretamente à internet sem um proxy reverso com HTTPS e restrição de acesso.

---

## Estrutura de Arquivos e Dados

```text
rastreador_empenhos/
├── pyproject.toml              # Metadados do pacote, scripts CLI e dependências
├── requirements.txt            # Dependências com travas de versão
├── README.md                   # Esta documentação macro
├── src/
│   └── rastreador_empenhos/    # Código-fonte principal (src-layout)
│       └── README.md           # Documentação técnica e fluxograma detalhado
└── relatorios/                 # Artefatos públicos e dados persistidos
    ├── index.html              # Índice geral público
    ├── indice_relatorios.json  # Cadastro e metadados consolidados dos processos
    └── <id_do_processo>/       # Diretório individual de cada contratação
        ├── relatorio_compra_<num>_<ano>.html
        ├── dados_pregao.json   # Snapshot bruto da compra e itens do PNCP
        ├── dados_empenhos.json # Snapshot enriquecido dos empenhos e mapeamentos
        └── metadados.json      # Resumo estatístico e datas de atualização
```

---

## Testes Automatizados

Para executar toda a suíte de testes unitários e de integração:

```bash
python -m unittest rastreador_empenhos.tests.suite -v
```

---

## Licença e Fontes

- **Fontes Oficiais:** [PNCP](https://pncp.gov.br), [Portal da Transparência](https://portaldatransparencia.gov.br) e [Contratos.gov.br](https://contratos.comprasnet.gov.br).
- Relatórios estáticos e código para finalidade de auditoria cívica e transparência pública.
- Dúvidas e inconsistências em relatórios podem ser comunicadas via repositório ou pelo e-mail institucional indicado no rodapé dos relatórios.
