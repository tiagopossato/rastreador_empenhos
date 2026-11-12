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
- `pncp_tracker/empenho_matcher.py`: relaciona empenhos a itens e fornecedores.
- `pncp_tracker/empenhos.py`: models e processamento de empenhos.
- `pncp_tracker/consultar_e_mapear_empenhos.py`: consulta os empenhos, enriquece com os detalhes do Portal da Transparência e mapeia os registros aos itens da compra.
- `pncp_tracker/report_html.py`: gera o relatório HTML autônomo.
- `pncp_tracker/report_service.py`: atualiza e persiste processos individualmente ou em lote.
- `pncp_tracker/report_registry.py`: valida URLs PNCP e mantém o índice JSON como cadastro de processos ativos.
- `pncp_tracker/process_lock.py`: lock entre processos que serializa atualizações e alterações no índice.
- `relatorios/gerar_relatorios.py`: regenera os HTMLs individuais e os índices JSON/HTML a partir dos dados persistidos.
- `relatorios/`: índice (`index.html`, `indice_relatorios.json`) e pastas individuais com HTML, JSONs das duas etapas e metadados.
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
