# Instruções para agentes de IA

Este repositório contém a aplicação Python `rastreador_empenhos`, que coleta dados de uma compra pública no PNCP, relaciona empenhos aos itens homologados e gera um relatório HTML autônomo.

## Objetivo do projeto

- Consultar a compra, itens e resultados homologados no Portal Nacional de Contratações Públicas (PNCP).
- Buscar contratos e empenhos relacionados à compra.
- Enriquecer os empenhos usando o Portal da Transparência.
- Relacionar empenhos a itens/fornecedores homologados.
- Gerar um relatório HTML contendo a análise e os vínculos identificados.

## Estrutura principal

- `main.py`: ponto de entrada da CLI; valida a URL e delega ao serviço compartilhado.
- `atualizar_relatorios.py`: atualiza todos os processos ativos para uso pelo cron.
- `criar_usuario_admin.py`: cria uma conta local para a interface administrativa.
- `generate_reports_index.py`: atalho legado para regenerar os relatórios publicados.
- `admin_web/`: aplicação administrativa privada Flask/Waitress (`app.py`, `auth.py`, `serve.py`, `templates/`).
- `pncp_tracker/url_parser.py`: extrai os parâmetros da URL pública do edital.
- `pncp_tracker/api_client.py`: cliente HTTP para consultas ao PNCP.
- `pncp_tracker/collector.py`: coleta e organiza dados da compra e itens.
- `pncp_tracker/contratos_empenhos.py`: consulta registros de contratos/empenhos.
- `pncp_tracker/portal_transparencia.py`: consulta dados do Portal da Transparência.
- `pncp_tracker/contratos_gov.py`: cliente público da API Contratos.gov.br; resolve a identidade da compra de um empenho e a quantidade real dos itens.
- `pncp_tracker/empenho_details.py`: detalha documentos de empenho.
- `pncp_tracker/empenho_portal.py`: descobre empenhos no Portal da Transparência (contrato, licitação e favorecido) quando o PNCP não os lista.
- `pncp_tracker/empenho_matcher.py`: relaciona empenhos a itens e fornecedores.
- `pncp_tracker/empenhos.py`: models e processamento de empenhos.
- `pncp_tracker/consultar_e_mapear_empenhos.py`: consulta os empenhos, enriquece com os detalhes do Portal da Transparência e mapeia os registros aos itens da compra.
- `pncp_tracker/report_html.py`: gera o relatório HTML autônomo.
- `pncp_tracker/report_service.py`: atualiza e persiste processos individualmente ou em lote.
- `pncp_tracker/report_registry.py`: valida URLs PNCP e mantém o índice JSON como cadastro de processos ativos.
- `pncp_tracker/process_lock.py`: lock entre processos que serializa atualizações e alterações no índice.
- `relatorios/gerar_relatorios.py`: regenera os HTMLs individuais e os índices JSON/HTML a partir dos dados persistidos.
- `relatorios/`: índice (`index.html`, `indice_relatorios.json`) e pastas individuais com HTML, JSONs das duas etapas e metadados.
- `api-docs-pnpc.json`: especificação OpenAPI 3.0.1 da API PNCP Consulta (12 caminhos e 23 schemas); documenta o cabeçalho da compra, mas não os endpoints de itens, resultados e contratos por contratação usados pelo projeto.
- `api-docs-transparencia.json`: especificação OpenAPI 3.0.1 da API do Portal da Transparência (109 caminhos e 106 schemas).
- `api-docs-contratos.json`: especificação OpenAPI 3.0.1 da API Contratos.gov.br (servidor `https://contratos.comprasnet.gov.br`, 75 caminhos). Usada apenas nos endpoints **públicos** descritos mais adiante; os que exigem `bearerAuth` (JWT), como `POST /api/v1/comprasnet/compras/impedimentos` e `GET /api/v1/contrato/empenho/consultar/{id}`, **não** são usados pelo projeto.
- `.private/`: usuários, log e lock; ignorado pelo Git e nunca publicado.
- `tests/`: testes automatizados.


## Configuração e requisitos

- Python 3.10 ou superior. O código usa anotações PEP 604 (`int | str`) e `list[str]` avaliadas em tempo de execução, portanto 3.8 e 3.9 não funcionam, apesar do que versões anteriores deste arquivo indicavam.
- Dependências: `requests`, `Flask>=2.3,<3.0` e `waitress>=2.1,<3.0` (ver `requirements.txt`).
- Chave da API do Portal da Transparência configurada em `.env` ou variável de ambiente.
- Não há linter ou formatador configurado no repositório; a validação é feita pela suíte de testes e por `python -m compileall`.

Instalação:

```bash
python -m pip install -r requirements.txt
```

Variáveis reconhecidas:

| Variável | Uso |
| --- | --- |
| `PORTAL_DADOS_API_KEY` / `PORTALTRANSPARENCIA_API_KEY` | Chave do Portal da Transparência. |
| `PNCP_ADMIN_SESSION_SECRET` | Obrigatória para iniciar a interface administrativa. |
| `PNCP_ADMIN_USERS_FILE` | Caminho alternativo do arquivo de usuários. |
| `PNCP_ADMIN_HOST` / `PNCP_ADMIN_PORT` | Endereço de escuta do Waitress (padrão `127.0.0.1:8000`). |
| `PNCP_ADMIN_COOKIE_SECURE` | `0` desativa a flag Secure do cookie (somente teste local). |
| `PNCP_ADMIN_LOG_FILE` | Caminho do log do servidor (padrão `.private/admin_web.log`). |

Arquivo `.env`:

```dotenv
PORTAL_DADOS_API_KEY=sua_chave
```

A aplicação prioriza `PORTAL_DADOS_API_KEY` e não sobrescreve valores já presentes no ambiente.

## Como executar

```bash
python main.py "https://pncp.gov.br/app/editais/10635424000186/2025/187"
```

A URL pode também ser informada interativamente quando omitida na linha de comando. A aplicação rejeita URLs vazias ou fora do formato `/editais/{cnpj}/{ano}/{sequencial}` antes de iniciar as consultas.

## APIs externas: sequência, parâmetros e retorno

Todo o fluxo usa HTTP GET, sem corpo de requisição. `{cnpj}`, `{ano}` e `{sequencial}` vêm da URL pública `/app/editais/{cnpj}/{ano}/{sequencial}`, validada por `url_parser` (CNPJ com 14 dígitos, ano com 4 e sequencial numérico). O timeout padrão é 30 s (`DEFAULT_TIMEOUT`) e o tamanho de página do PNCP é 50 (`DEFAULT_PAGE_SIZE`).

As especificações OpenAPI 3.0.1 estão no repositório:

- [api-docs-pnpc.json](./api-docs-pnpc.json): API PNCP Consulta, servidor relativo `/api/consulta` (em produção, `https://pncp.gov.br/api/consulta`), 12 caminhos e 23 schemas. Cobre o cabeçalho da compra (`consultarCompra`); **não cobre** os endpoints de itens, resultados e contratos por contratação usados nas etapas 2–4. A spec declara `bearerAuth` (JWT), mas as chamadas atuais do projeto não enviam autenticação ao PNCP.
- [api-docs-transparencia.json](./api-docs-transparencia.json): Portal da Transparência, servidor `https://api.portaldatransparencia.gov.br`, 109 caminhos e 106 schemas. Cobre as etapas 5–7; a autenticação é `apiKey` no cabeçalho `chave-api-dados`.

| Etapa | Endpoint usado | Documentado em |
| --- | --- | --- |
| 1 | `/api/consulta/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}` | `api-docs-pnpc.json` (`consultarCompra`) |
| 2 | `/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens` | não |
| 3 | `/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{numeroItem}/resultados` | não |
| 4 | `/api/pncp/v1/orgaos/{cnpj}/contratos/contratacao/{ano}/{sequencial}` | não |
| 4b | `/api-de-dados/contratos/processo` + `/api-de-dados/contratos/documentos-relacionados` | `api-docs-transparencia.json` |
| 4c | `/api-de-dados/licitacoes/por-processo` + `/api-de-dados/licitacoes/empenhos` | `api-docs-transparencia.json` |
| 5–7 | `/api-de-dados/despesas/...` | `api-docs-transparencia.json` |

Ordem executada por `atualizar_processo`: as etapas 1–3 pertencem a `baixar_dados_compra_pncp` (resultado em `dados_pregao.json`); as etapas 4, 4b/4c e 5–7 pertencem a `consultar_e_mapear_empenhos` (resultado em `dados_empenhos.json`), que no fluxo principal reaproveita o cabeçalho da etapa 1 e não a repete.

1. **Cabeçalho da compra (PNCP)** — `consultarCompra` em `api-docs-pnpc.json`; o código usa somente o endpoint oficial:
   - `https://pncp.gov.br/api/consulta/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}` — responde 200; é o único caminho usado para o cabeçalho.
   - **Parâmetros:** `cnpj` (string), `ano` (inteiro) e `sequencial` (inteiro) no caminho; sem query string. A spec também define as respostas 204, 400, 401, 422 e 500.
   - **Retorno esperado:** objeto JSON `RecuperarCompraDTO`. `numeroCompra` (somente dígitos) e `anoCompra` (4 dígitos) são obrigatórios; sem eles a coleta para com "Cabeçalho da compra incompleto". Também são aproveitados, quando presentes, `unidadeOrgao.codigoUnidade`, `unidadeOrgao.nomeUnidade`, `modalidadeId`, `modalidadeNome`, `processo`, `numeroControlePNCP`, `srp`, `objetoCompra`, `valorTotalEstimado` e `valorTotalHomologado`.
   - **Falhas:** como há uma única URL, HTTP 204, erro HTTP, JSON inválido ou corpo que não seja objeto encerram a atualização com `requests.RequestException`. O 204 é convertido em erro por `_buscar_json_robusto`.

2. **Itens da compra (PNCP)** — endpoint não documentado em `api-docs-pnpc.json`, na base `/api/pncp/v1`: `https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens`
   - **Parâmetros de query:** `pagina` (começa em 1) e `tamanhoPagina` (50).
   - **Retorno esperado:** lista JSON de itens, preservada campo a campo. HTTP 204 equivale a lista vazia. A paginação para na primeira página vazia ou com menos de 50 itens; páginas cheias avançam `pagina`. Itens sem `numeroItem` são mantidos sem consulta de resultados. Erro HTTP nesta chamada não é tratado: aborta a atualização.

3. **Resultados homologados (PNCP)** — endpoint não documentado em `api-docs-pnpc.json`, na base `/api/pncp/v1`; uma chamada por item com `numeroItem`, ainda dentro da página corrente: `https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{numeroItem}/resultados`
   - **Parâmetros:** `numeroItem` no caminho; sem query string.
   - **Retorno esperado:** lista JSON, anexada ao item em `resultadosHomologados` (fornecedor, quantidade e valores homologados). HTTP 204 equivale a lista vazia; corpo que não seja lista gera `ValueError`. Qualquer erro é registrado em `erros_resultados_itens` e em `erroResultadosHomologados` do item, que segue com `resultadosHomologados = []` sem interromper os demais itens.

4. **Contratos e empenhos da contratação (PNCP)** — endpoint não documentado em `api-docs-pnpc.json`: `https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/contratos/contratacao/{ano}/{sequencial}`
   - **Parâmetros de query:** `pagina` (começa em 1) e `tamanhoPagina` (50).
   - **Retorno esperado:** objeto JSON com `data` (lista de registros) e `totalPaginas` (inteiro), no formato de `PaginaRetornoRecuperarContratoDTO` da spec (`data`, `totalRegistros`, `totalPaginas`, `numeroPagina`, `paginasRestantes`, `empty`). As páginas são agregadas enquanto `pagina <= totalPaginas`; a leitura para se `data` vier vazia ou `totalPaginas` for zero. Formato diferente disso gera `ValueError`.
   - **Falhas:** HTTP 404 é tratado como ausência de registros (`[]`); outros erros HTTP abortam a atualização.

**Nota (verificada em 2026-11-13):** o cabeçalho usa `/api/consulta/v1`; itens, resultados e contratos usam `/api/pncp/v1`. Nenhum desses três recursos está documentado em `api-docs-pnpc.json`, e `/api/consulta/v1` responde 404 para eles mesmo quando há dados.

5. **Documentos de despesa por favorecido (Portal da Transparência)** — `documentosPorFavorecido` em `api-docs-transparencia.json`; após a etapa 4, consulta os documentos dos empenhos elegíveis, agrupados por unidade gestora, CNPJ do fornecedor e ano:
   `https://api.portaldatransparencia.gov.br/api-de-dados/despesas/documentos-por-favorecido`
   - **Elegibilidade:** o registro precisa conter `NE` em `numeroContratoEmpenho`, ter `unidadeOrgao.codigoUnidade` e `niFornecedor` preenchidos e um ano extraível do número (regex `^(\d{4})NE`). Registros fora disso recebem `status: nao_consultado` e não geram chamada.
   - **Parâmetros de query (conforme a spec):** `codigoPessoa` (obrigatório; CPF, CNPJ ou código SIAFI), `fase` (obrigatório; 1 = Empenho, 2 = Liquidação, 3 = Pagamento), `ano` (obrigatório; ano de emissão), `ug` (opcional; código da unidade gestora), `gestao` (opcional), `ordenacaoResultado` (opcional; 1 a 4) e `pagina` (obrigatório; começa em 1). O código envia `codigoPessoa`, `fase=1`, `ano`, `ug` e `pagina`; `gestao` e `ordenacaoResultado` não são usados.
   - **Cabeçalhos:** `chave-api-dados` com a chave lida de `PORTAL_DADOS_API_KEY` ou `PORTALTRANSPARENCIA_API_KEY`, inclusive de `.env`; também envia `Accept: application/json` e `User-Agent`. A spec declara segurança `apiKey` nesse cabeçalho.
   - **Retorno esperado:** lista JSON de `DespesasPorDocumentoDTO`; a paginação para em lista vazia ou com menos de 15 elementos. O vínculo com o empenho usa `documentoResumido`, e `documento` fornece o código usado na etapa 6. A spec documenta também as respostas 400, 401 e 500.
   - **Falhas:** chave ausente ou HTTP 401 geram `PermissionError`; erro em um grupo deixa a lista daquele grupo vazia e entra em `erros_detalhamento`, sem interromper o relatório. Empenho sem documento correspondente recebe `status: nao_encontrado`.

   **Uso na descoberta (estratégia C):** quando as estratégias A e B não retornam empenhos, a aplicação consulta o mesmo endpoint uma vez por CNPJ distinto dos fornecedores homologados, usando `codigoPessoa`, `fase=1`, `ano` da compra (e os dois anos seguintes) e `pagina`, sem enviar `ug`. Só são aceitos documentos com `numeroProcesso` igual ao processo da compra (comparação pelos dígitos).

6. **Detalhamento do documento (Portal da Transparência)** — `documentoPorCodigo` em `api-docs-transparencia.json`; para cada empenho cujo documento foi localizado:
   `https://api.portaldatransparencia.gov.br/api-de-dados/despesas/documentos/{codigo}`
   - **Parâmetros:** `codigo` no caminho (código do registro: unidade gestora + gestão + número do documento); sem query string. Usa os mesmos cabeçalhos de autenticação.
   - **Retorno esperado:** objeto JSON `DespesasPorDocumentoDTO` (não lista) com os dados usados no relatório, como `data`, `valor`, `codigoUg`, `ug`, `codigoFavorecido` e `nomeFavorecido`. Sucesso grava `status: ok` e o documento em `detalhesPortalTransparencia.detalhamento`; falha grava `status: erro` e o erro em `erros_detalhamento`, sem interromper os demais empenhos.

7. **Itens do empenho (Portal da Transparência)** — `itensDeEmpenho` em `api-docs-transparencia.json`; chamada imediatamente após o detalhamento do mesmo documento:
   `https://api.portaldatransparencia.gov.br/api-de-dados/despesas/itens-de-empenho`
   - **Parâmetros de query:** `codigoDocumento` (código do empenho: unidade gestora + gestão + número do documento) e `pagina` (começa em 1). Usa os mesmos cabeçalhos de autenticação.
   - **Retorno esperado:** lista JSON de `DetalhamentoDoGastoDTO`, com campos como `descricao`, `valorAtual`, `codigoItemEmpenho` e `sequencial`. A paginação para em lista vazia ou com menos de 15 elementos; a lista agregada é anexada ao documento como `itensEmpenho`. Falha aqui invalida o detalhamento inteiro e resulta em `status: erro` para o empenho.

**Descoberta de empenhos no Portal da Transparência (cascata A → B → C):** o PNCP continua sendo a fonte primária, mas a descoberta no Portal roda **sempre**, não apenas quando o PNCP vem vazio. Isso garante que um empenho ausente do PNCP apareça no relatório mesmo que outros já tenham sido retornados. A busca segue uma cascata do caminho mais barato para o mais abrangente. O processo da compra **não** é filtro obrigatório: em compras compartilhadas e adesões o empenho tem processo e UG próprios.

- **A — contrato do processo:** `GET /contratos/processo?processo=` → para cada contrato, `GET /contratos/documentos-relacionados?id=`. Retorna `ContratoDTO[]` e depois `EmpenhoComprasDTO[]` (`empenho`, `empenhoResumido`, `dataEmissao`, `observacao`, `valor`).
- **B — licitação do processo:** `GET /licitacoes/por-processo?processo=` → `GET /licitacoes/empenhos?codigoUG&numero&codigoModalidade`. Usa `unidadeGestora.codigo`, `licitacao.numero` e `codigoModalidade` (ou `modalidade_id` da compra) e retorna `EmpenhoComprasDTO[]`. Licitação sem esses campos é apenas registrada em `erros_detalhamento`.
- **C — fornecedores homologados:** executada somente se A e B não retornarem empenhos. Repete a etapa 5 sem `ug` para cada CNPJ homologado distinto, no ano da compra e nos dois anos subsequentes. Documentos cujo `numeroProcesso` coincide com o da compra entram na faixa de prioridade alta e são detalhados primeiro. O fornecedor é apenas **semente de descoberta**: cada documento só entra no relatório se comprovar uma das evidências objetivas descritas adiante; os demais são descartados e listados em `empenhos_nao_confirmados`.

Cada estratégia pode falhar isoladamente sem interromper as seguintes; o bloqueio do token interrompe a cascata e o resultado fica parcial. Cada documento é detalhado uma única vez (etapas 6–7) e o detalhe é reaproveitado entre estratégias e entre registros do PNCP via cache da execução. Há orçamento de 60 detalhamentos por execução (`ORCAMENTO_DETALHAMENTOS`); o excedente é registrado em `erros_detalhamento`.

**Deduplicação e reaproveitamento de consultas:** fornecedores são deduplicados por CNPJ (um fornecedor que vence vários itens é consultado uma vez por ano, não por item) e o enriquecimento agrupa por (UG, fornecedor, ano). Medição em 2025/282: 330 resultados homologados → 45 fornecedores distintos → 135 combinações na varredura; 111 empenhos → 83 consultas no enriquecimento. As consultas por favorecido são cacheadas por (favorecido, ano, UG, fase) durante a execução (TTL de 30 min, cache limpo no início de cada coleta), evitando repetição entre estratégias.

O enriquecimento continua consultando **com `ug`**: a mesma consulta sem `ug` retorna de 25 a 77 documentos contra 1 a 3 com `ug`, então ampliar o escopo para tentar reaproveitar o cache piora o tempo total. O cache só aproveita chamadas idênticas.

**Limite de taxa domina a varredura:** na compra 2025/282 a estratégia C gerou **719 requisições** e levou **247 s** — praticamente 719 × 0,343 s, ou seja, o teto de 180 req/min do endpoint restrito. Como o tempo é limitado pela taxa, paralelizar fornecedores já está aplicado e não reduz o total; paralelizar páginas piorou o resultado (833 requisições e 286 s), por isso a paginação permanece sequencial. Para reduzir o tempo é necessário reduzir requisições (cache persistente entre execuções ou menos anos/fornecedores), não aumentar concorrência.

**Identidade da compra na Contratos.gov.br (evidência primária de vínculo):** para cada documento candidato, `contratos_gov.coletar_dados_empenho(ug_emitente, numero_empenho)` consulta dois endpoints **públicos** da API Contratos.gov.br:

- `GET /api/contrato/ugorigem/{codigo_uasg}/numeroano/{numero}` — resolve o empenho pela UG emitente e número e devolve `unidade_compra`, `licitacao_numero`, `codigo_modalidade`, `processo`, `informacao_complementar` e `id`. A UG emitente é obrigatória: com a UG errada a resposta é uma lista vazia.
- `GET /api/contrato/{id}/itens` — devolve `numero_item_compra`, `quantidade`, `valorunitario` e `valortotal` do empenho, permitindo usar a **quantidade real** em vez da estimativa por divisão.

A compra é identificada por `unidade_compra` + `licitacao_numero` + `codigo_modalidade` (ou pelo formato compacto de `informacao_complementar`, `UG(6)+modalidade(2)+número(5)+ano(4)`). Quando essa identidade coincide com `uasg_codigo`, `numero_compra` e `ano_compra` da compra, o vínculo é `compra_identidade` com confiança alta; quando aponta para outra licitação, o documento é descartado como “pertence a outra compra”. Se a API não responder, o fluxo cai nas evidências por item/fornecedor/valor, sem interromper o relatório.

**Evidências de vínculo (em ordem de força):** o fornecedor homologado é apenas a **semente** da busca — o mesmo CNPJ empenha em muitas compras, então nenhum documento é aceito só por isso. Um documento é aceito apenas com uma destas evidências objetivas:

| Evidência (`vinculo`) | Regra | Confiança |
| --- | --- | --- |
| `contrato_do_processo` | veio da estratégia A (contratos do processo) | alta |
| `licitacao_do_processo` | veio da estratégia B (licitação do processo) | alta |
| `compra_identidade` | Contratos.gov.br: `unidade_compra` + `licitacao_numero` + `codigo_modalidade` + ano iguais aos da compra | alta |
| `processo` | `numeroProcesso` do documento igual ao processo da compra | alta |
| `item_e_fornecedor` | `Item compra: NNNNN` cujo item PNCP tem resultado do mesmo CNPJ **e** cuja descrição é compatível com a do item da compra (≥ 60% de tokens em comum) | alta |
| `item_e_valor` | item do mesmo CNPJ **e** `valor ÷ preço unitário homologado` é múltiplo inteiro (tolerância de 1%) | média |

Sem qualquer evidência o documento é **descartado** e registrado em `erros_detalhamento` com `tipo: "descartado"`, além de `numero`, `unidade`, `fornecedor`, `valor` e `motivo`. A antiga evidência `fornecedor_e_valor` (apenas o CNPJ ser vencedor de algum item) foi **removida**: na compra 2026/197 ela aceitou 40 documentos de outros órgãos e zerou a confiabilidade do relatório.

**Decisão de projeto registrada:** o campo `observacao` do Portal da Transparência **não** é usado como parâmetro em nenhuma decisão — é texto livre, opcional e subjetivo. Toda evidência vem de campo estruturado (identidade da compra, processo, número do item, descrição de catálogo e preço unitário homologado).

**Calibração da compatibilidade de descrição:** a descrição do item do empenho é a descrição de catálogo do PNCP (`Item compra: 00019 - ÁCIDO INDOL-3-BUTÍRICO, …`), que contém a descrição curta do edital. Comparando tokens (≥ 3 caracteres, normalizados sem acento) em 1.446 linhas de empenho dos relatórios existentes, todos os casos legítimos ficaram em 1,0 e as 37 linhas do caso falso de 2026/197 ficaram entre 0,00 e 0,27 — por isso o limiar de 0,6 (`LIMIAR_DESCRICAO`).

**Quantidade estimada é sempre inteira:** quando a Contratos.gov.br não publica a quantidade, ela é calculada como `valor ÷ preço unitário homologado` e **arredondada para inteiro** com `Decimal` (evita artefatos como `2,999999`), por `empenho_portal.quantidade_estimada`. A função devolve também um indicador de divergência quando a divisão não é múltipla inteira do preço unitário (`|razão − inteiro| > max(0,05; 1% × inteiro)`); nesse caso a linha aparece com “≈” e `quantidade_divergente = true`. Quantidades publicadas na Contratos.gov.br continuam como vieram.

**Adesão e consumo de saldo:** o cabeçalho da compra **não** traz flag de adesão (apenas `srp`), e a Contratos.gov.br também não distingue participante de adesão posterior — nos dois casos `unidade_compra` difere da UG emitente. A única fonte exata é `frutoAdesao` do PNCP (`RecuperarContratoDTO`). Cada registro recebe `origem_organ`:

| Situação | `origem_organ` | `consome_saldo` |
| --- | --- | --- |
| `frutoAdesao = true` no PNCP | `adesao_posterior` | não |
| `frutoAdesao = false` no PNCP (inclui participante na origem) | `original` | sim |
| `frutoAdesao` ausente no PNCP | `original` (com `flag_adesao_ausente = true`) | sim |
| Empenho só do Portal, `unidade_compra == UG emitente` | `propria_ug` | sim |
| Empenho só do Portal, `unidade_compra != UG emitente` ou sem dados | `indefinido` | não |

**Decisão de projeto registrada:** a ausência de `frutoAdesao` em um empenho **vindo do PNCP** é tratada como **não adesão**. O empenho segue o fluxo normal, consome a quantidade homologada e **não** é classificado como origem indefinida; a ausência fica registrada em `flag_adesao_ausente` apenas para auditoria. O estado indefinido permanece restrito a empenhos descobertos **somente** no Portal da Transparência, cuja origem não pode ser conhecida.

Adesão posterior e indefinido **não** reduzem a quantidade homologada: vão para `valor_empenhado_adesao` / `valor_empenhado_indefinido` e não entram na execução. O relatório ganha os estados `empenhado_por_adesao` e `empenhado_origem_indefinida` para itens cujo único empenho é, respectivamente, de adesão posterior ou de origem não determinada. Essa regra evita execução acima de 100% por carona, ao custo de subestimar a execução quando a origem é desconhecida — por isso os valores ficam em colunas e cards separados.

**Limitação conhecida do PNCP:** o campo `frutoAdesao` não vem em todos os registros. Na compra 2025/282, 71 empenhos vieram com `false`, 5 com `true` e 35 **sem o campo**, todos do mesmo tipo (`Empenho`), categoria e ano — a omissão depende do sistema publicador do órgão. Por decisão de projeto, esses 35 são tratados como **não adesão** (`original`, com `flag_adesao_ausente`), e não como origem indefinida.

Os registros recebem também `origem` (`pncp`, `portal_contrato`, `portal_licitacao`, `portal_favorecido`), `vinculo` e `confianca`, e o resultado é unido e deduplicado por número resumido do empenho (`AAAANE999999`): os campos do PNCP são preservados e, quando o mesmo empenho também aparece no Portal, ele recebe `encontrado_tambem_no_portal`. A correspondência com itens continua usando `Item compra: NNNNN` e fornecedor, sem alterar a regra do matcher. `dados_empenhos.json` expõe `quantidade_empenhos_pncp`, `quantidade_empenhos_portal`, `quantidade_empenhos_confirmados`, `quantidade_empenhos_adesao`, `quantidade_empenhos_indefinidos`, `valor_empenhado_adesao`, `quantidade_documentos_descartados` e `empenhos_nao_confirmados` (documentos do fornecedor sem vínculo com a compra, com motivo, para auditoria).

**Limites de acesso do Portal da Transparência:** respeite os limites publicados para cada token: até 700 requisições/minuto entre 00:00–06:00, até 400 requisições/minuto nos demais horários e, para endpoints restritos, até 180 requisições/minuto. O endpoint `despesas/documentos-por-favorecido` usado nas etapas 5 e no fallback é restrito. A lista completa de endpoints restritos também inclui `bolsa-familia-disponivel-por-cpf-ou-nis`, `bolsa-familia-por-municipio`, `bolsa-familia-sacado-por-nis`, `auxilio-emergencial-beneficiario-por-municipio`, `auxilio-emergencial-por-cpf-ou-nis`, `auxilio-emergencial-por-municipio` e `seguro-defeso-codigo`. Excesso suspende o token por 8 horas. `portal_transparencia.py` aplica intervalos mínimos entre chamadas no processo: 180/min para o endpoint restrito e os limites globais informados para os demais. O controle em memória coordena threads desse processo, não processos independentes; não execute instâncias concorrentes com o mesmo token sem um limitador compartilhado.

Se a API retornar HTTP 429 ou uma resposta textual informando bloqueio/limite atingido (inclusive HTTP 200 sem JSON), marque o token como bloqueado e não faça novas chamadas durante as 8 horas de suspensão. Não repita rapidamente para outros fornecedores, anos ou documentos. A execução deve terminar com erro/resultado parcial explicando que o token foi bloqueado; após o prazo, uma nova execução pode retomar as consultas. Não faça retries automáticos que possam prolongar o bloqueio.

As respostas geram `dados_pregao.json` (cabeçalho e itens com resultados) e `dados_empenhos.json` (registros PNCP enriquecidos e mapeados); a geração dos HTMLs não faz chamadas externas. A chave da API nunca deve aparecer em parâmetros de URL, logs ou relatórios.

Os JSONs das etapas são preservados na pasta do relatório junto com o HTML e os metadados. Para regenerar os HTMLs e índices sem consultar as APIs:

```bash
python relatorios/gerar_relatorios.py
```

O índice `relatorios/index.html` resume cada processo em uma linha; `relatorios/indice_relatorios.json` contém os mesmos dados em formato estruturado.

O índice JSON é o cadastro ativo. Use `python atualizar_relatorios.py` para atualizar todos os processos via cron. A interface em `admin_web/` permite cadastrar URLs, remover processos sem apagar arquivos históricos e iniciar atualizações; usuários são criados com `python criar_usuario_admin.py`. Não versione o arquivo `.private/usuarios.json` nem `PNCP_ADMIN_SESSION_SECRET`; mantenha a interface atrás de HTTPS e acesso de rede restrito.

Inicie a interface com:

```bash
export PNCP_ADMIN_SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"   # Bash
$env:PNCP_ADMIN_SESSION_SECRET = (python -c "import secrets; print(secrets.token_urlsafe(48))")      # PowerShell
python -m admin_web.serve
```

Rotas da interface:

- `/`: serve `relatorios/index.html` substituindo o marcador `<!-- admin-link -->` pelo botão **Administração**. O marcador é obrigatório; sem ele a rota responde 500. O GitHub Pages publica o marcador sem substituição, portanto o botão só funciona no servidor administrativo.
- `/login`: formulário de autenticação; após o login redireciona para `/admin`.
- `/admin`: painel protegido com o CRUD de processos e as ações de atualização.
- `/<pasta>/<arquivo>.html`: entrega os relatórios individuais; arquivos não `.html` (JSONs, metadados) respondem 404.

O andamento das atualizações do painel é enviado ao log via `on_progress`. `report_service` repassa as mensagens ao coletor e ao mapeador, que devem informar páginas, itens e totais. Ao criar uma nova etapa de coleta, chame `on_progress` em vez de imprimir diretamente, para que CLI, cron e servidor compartilhem o mesmo canal.

**Painel de progresso:** `pncp_tracker/report_progress.py` (`ProgressoTracker`) interpreta as mensagens de `on_progress` e expõe etapa, percentual com pisos por fase (coleta 0,05; empenhos 0,45; relatório 0,90; concluído 1,0), estatísticas (páginas, itens, empenhos do PNCP, exclusivos do Portal, mapeados, processo *i* de *n*), tempo decorrido, segundos restantes e previsão de conclusão em UTC−3. A previsão usa `ultima_duracao_segundos` do `metadados.json` do processo quando existe; sem histórico, extrapola pelo percentual (só a partir de 8%). O painel consulta `/processes/jobs/<id>` a cada 2 s e desabilita os botões de atualização enquanto houver job ativo; `JobRegistry.create` recusa um segundo job na mesma instância e as rotas exibem “Já existe uma atualização em andamento.”. A trava entre processos continua sendo `process_lock`.

**Relatório HTML — documentos descartados:** documentos sem vínculo comprovado com a compra não são exibidos no HTML e não entram em totais, itens, saldo ou CSV. Permanecem somente em `empenhos_nao_confirmados` no `dados_empenhos.json` para auditoria.

## Testes

Para validar alterações:

```bash
python -m unittest discover -s tests -v
```

- `test_api_client.py`, `test_collector.py`: cliente PNCP e paginação da coleta.
- `test_admin_web.py`, `test_admin_auth.py`: rotas, CSRF, hashing e criação de usuários.
- `test_report_service.py`, `test_report_registry.py`, `test_process_lock.py`: atualização, índice e concorrência.
- `test_generate_reports_index.py`, `test_consultar_e_mapear_empenhos.py`: geração dos HTMLs, regras de matching, evidências de vínculo e classificação de adesão.

Os testes não acessam a rede; todo acesso HTTP é substituído por `unittest.mock`. Ao tocar em `collector`, `api_client`, `contratos_gov` ou `report_service`, mantenha essa regra.

## Regras para alterações

- Mantenha o fluxo principal de coleta e geração do relatório intacto.
- Prefira alterações pequenas e focadas no módulo relevante.
- Quando ajustar lógica de matching de empenhos, preserve a semântica de itens homologados, fornecedores e estimativa de quantidade empenhada.
- Não exponha chaves de API em logs, commits ou arquivos versionados.
- Ao alterar comportamento do HTML, valide o efeito em relação aos testes existentes e à estrutura do relatório.
- Relatórios HTML gerados em `relatorios/` são artefatos da aplicação; não os trate como fonte de código.
- Nunca grave usuários, logs, locks ou chaves dentro de `relatorios/`: essa pasta é publicada. Use `.private/`.
- Preserve o marcador `<!-- admin-link -->` no HTML gerado pelo índice; o servidor administrativo depende dele.
- Use o callback `on_progress` para mensagens de acompanhamento; não introduza `print` no fluxo de coleta.
- Ao corrigir um item de "Riscos e problemas conhecidos", remova ou atualize a entrada correspondente.
- Ao alterar chamadas externas, confira caminhos e parâmetros em `api-docs-pnpc.json`, `api-docs-transparencia.json` e `api-docs-contratos.json`; os endpoints do PNCP não documentados (itens, resultados e contratos por contratação) usam a base `/api/pncp/v1` e só podem ser validados por chamada real.
- A API Contratos.gov.br só deve ser usada nos endpoints públicos; não introduza credenciais JWT no projeto para contornar isso.
- Preserve a regra de saldo: apenas `original` e `propria_ug` consomem a quantidade homologada.
- Nunca use o campo `observacao` do Portal da Transparência como evidência de vínculo ou como parâmetro de decisão: é texto livre, opcional e subjetivo. Use identidade da compra, processo, número do item, descrição de catálogo e preço unitário homologado.
- A quantidade empenhada estimada deve ser sempre inteira, calculada com `Decimal` (`empenho_portal.quantidade_estimada`), e marcada como divergente quando a divisão pelo preço unitário não for múltipla inteira.

## Observações importantes

- O relatório final é autônomo e pode ser aberto localmente sem dependências externas.
- O PNCP é a fonte primária, mas a descoberta no Portal da Transparência roda sempre, para incluir empenhos que o PNCP não lista.
- A Contratos.gov.br é consultada sem autenticação apenas para identidade da compra e quantidade dos itens; falha nela não interrompe a atualização.
- Adesão posterior e empenho de origem indefinida não consomem a quantidade homologada e são exibidos separadamente.
- Decisão de projeto: empenho vindo do PNCP sem `frutoAdesao` é tratado como não adesão (fluxo normal), nunca como origem indefinida.
- Registros sem vínculo confirmado a item **não** são exibidos em seção própria no HTML (decisão de projeto: a seção "Registros sem vínculo confirmado a item" foi removida); eles continuam nos JSONs da pasta do processo.
- Em caso de erro HTTP 404 na API de Contratos/Empenhos do PNCP, a aplicação deve seguir normalmente e gerar o relatório sem esses registros; outros erros HTTP devem ser reportados.
- A aplicação depende de dados do Portal da Transparência com base em CNPJ do fornecedor, ano do empenho e unidade gestora.
- O fuso do carimbo de geração do relatório é fixo em UTC−3 (horário de Brasília), independente do fuso do servidor.

## Limitações operacionais conhecidas

- O estado das tarefas administrativas é isolado por instância da aplicação, mas permanece em memória; reiniciar o servidor durante uma tarefa perde o histórico exibido no painel.
- O limite de tentativas de login também é mantido em memória por instância e é reiniciado quando o servidor reinicia.

## Checklist para contribuições

Ao editar o projeto, verifique:

1. Se a mudança impacta entrada, parsing de URL ou configuração.
2. Se a mudança afeta a coleta de empenhos, matching ou geração do relatório HTML.
3. Se os testes continuam passando.
4. Se não foram introduzidas vazamentos de dados sensíveis ou credenciais.

No momento de concluir uma alteração, execute os testes relevantes e descreva claramente o objetivo da mudança e o comportamento verificado.
