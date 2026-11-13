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
- `pncp_tracker/empenho_details.py`: detalha documentos de empenho.
- `pncp_tracker/empenho_portal.py`: busca empenhos alternativos no Portal quando o PNCP não retorna registros.
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
| 5–7 | `/api-de-dados/despesas/...` | `api-docs-transparencia.json` |

Ordem executada por `atualizar_processo`: as etapas 1–3 pertencem a `baixar_dados_compra_pncp` (resultado em `dados_pregao.json`); as etapas 4–7 pertencem a `consultar_e_mapear_empenhos` (resultado em `dados_empenhos.json`), que no fluxo principal reaproveita o cabeçalho da etapa 1 e não a repete.

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

   **Fallback quando o PNCP não retorna nenhum registro:** a aplicação consulta o mesmo endpoint uma vez por CNPJ distinto dos fornecedores homologados, usando `codigoPessoa`, `fase=1`, `ano` da compra e `pagina`, sem enviar `ug`. Só são aceitos documentos com `numeroProcesso` igual ao processo da compra (comparação pelos dígitos); documentos sem processo não são aceitos nesta etapa.

6. **Detalhamento do documento (Portal da Transparência)** — `documentoPorCodigo` em `api-docs-transparencia.json`; para cada empenho cujo documento foi localizado:
   `https://api.portaldatransparencia.gov.br/api-de-dados/despesas/documentos/{codigo}`
   - **Parâmetros:** `codigo` no caminho (código do registro: unidade gestora + gestão + número do documento); sem query string. Usa os mesmos cabeçalhos de autenticação.
   - **Retorno esperado:** objeto JSON `DespesasPorDocumentoDTO` (não lista) com os dados usados no relatório, como `data`, `valor`, `codigoUg`, `ug`, `codigoFavorecido` e `nomeFavorecido`. Sucesso grava `status: ok` e o documento em `detalhesPortalTransparencia.detalhamento`; falha grava `status: erro` e o erro em `erros_detalhamento`, sem interromper os demais empenhos.

7. **Itens do empenho (Portal da Transparência)** — `itensDeEmpenho` em `api-docs-transparencia.json`; chamada imediatamente após o detalhamento do mesmo documento:
   `https://api.portaldatransparencia.gov.br/api-de-dados/despesas/itens-de-empenho`
   - **Parâmetros de query:** `codigoDocumento` (código do empenho: unidade gestora + gestão + número do documento) e `pagina` (começa em 1). Usa os mesmos cabeçalhos de autenticação.
   - **Retorno esperado:** lista JSON de `DetalhamentoDoGastoDTO`, com campos como `descricao`, `valorAtual`, `codigoItemEmpenho` e `sequencial`. A paginação para em lista vazia ou com menos de 15 elementos; a lista agregada é anexada ao documento como `itensEmpenho`. Falha aqui invalida o detalhamento inteiro e resulta em `status: erro` para o empenho.

**Fallback de descoberta (Portal da Transparência):** executado somente se a etapa 4 retornar zero empenhos. Para cada fornecedor homologado distinto, a etapa 5 é repetida sem `ug` para o ano da compra e os dois anos subsequentes; cada documento candidato é então consultado nas etapas 6–7. O detalhe é descartado se declarar processo diferente; se não repetir o número do processo, prevalece a correspondência já validada na resposta da etapa 5. Os registros são deduplicados por `documentoResumido` e recebem a mesma estrutura de detalhes usada pelo matcher (`numeroContratoEmpenho`, `niFornecedor` e `detalhesPortalTransparencia.detalhamento`). A correspondência com itens continua usando `Item compra: NNNNN` e fornecedor, sem alterar a regra do matcher. A busca é limitada a esses três anos e à fase Empenho; não consulta outros anos nem fornecedores não homologados. Erros por fornecedor/ano/documento são incluídos em `erros_detalhamento`. Se o PNCP retornar qualquer registro, o fallback não é executado.

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

## Testes

Para validar alterações:

```bash
python -m unittest discover -s tests -v
```

- `test_api_client.py`, `test_collector.py`: cliente PNCP e paginação da coleta.
- `test_admin_web.py`, `test_admin_auth.py`: rotas, CSRF, hashing e criação de usuários.
- `test_report_service.py`, `test_report_registry.py`, `test_process_lock.py`: atualização, índice e concorrência.
- `test_generate_reports_index.py`, `test_consultar_e_mapear_empenhos.py`: geração dos HTMLs e regras de matching.

Os testes não acessam a rede; todo acesso HTTP é substituído por `unittest.mock`. Ao tocar em `collector`, `api_client` ou `report_service`, mantenha essa regra.

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
- Ao alterar chamadas externas, confira caminhos e parâmetros em `api-docs-pnpc.json` e `api-docs-transparencia.json`; os endpoints do PNCP não documentados (itens, resultados e contratos por contratação) usam a base `/api/pncp/v1` e só podem ser validados por chamada real.

## Observações importantes

- O relatório final é autônomo e pode ser aberto localmente sem dependências externas.
- Registros sem vínculo confirmado a item devem continuar sendo reportados em seção separada.
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
