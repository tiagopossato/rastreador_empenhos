# Rastreador de Empenhos por Item — Compras Públicas Federais (PNCP)

**Acesse os relatórios publicados:** [https://tiagopossato.github.io/rastreador_empenhos/](https://tiagopossato.github.io/rastreador_empenhos/)

Aplicação Python que coleta dados de compras no Portal Nacional de Contratações Públicas (PNCP), relaciona empenhos aos itens homologados e gera relatórios HTML autônomos. Inclui uma CLI, atualização em lote para cron e uma interface administrativa privada.

## Como funciona

1. **Coleta da compra e dos empenhos:** consulta no PNCP os dados do edital, seus itens, os resultados homologados e a lista de empenhos da aba Contratos/Empenhos. Opcionalmente — e somente quando solicitado — também descobre no Portal da Transparência empenhos que não constam dessa aba, inclusive de adesões e compras compartilhadas, cujo processo e unidade gestora podem ser diferentes. Todo esse conjunto é salvo em `dados_pregao.json`.
2. **Detalhamento e verificação:** consulta cada empenho em `/despesas/documentos-por-favorecido`, obtém o documento e seus itens e compara os valores com o registro do PNCP para identificar empenho cancelado, anulado, reforçado ou retificado. O resultado é salvo em `dados_empenhos.json`.
3. **Mapeamento e relatório:** relaciona as linhas de empenho aos itens por número do item e fornecedor homologado e gera o relatório HTML.

O PNCP fornece valores de empenho, mas não necessariamente a quantidade física empenhada. Quando a API pública Contratos.gov.br identifica o empenho, a quantidade real do item é usada; caso contrário, e havendo preço unitário homologado, a quantidade é estimada dividindo o valor da linha pelo preço unitário, mantendo as casas decimais reais do resultado (até três casas).

Empenhos decorrentes de adesão posterior — ou, quando vindos apenas do Portal, com origem de órgão não determinada — não consomem a quantidade homologada e aparecem em colunas e cards próprios; apenas empenhos originais, inclusive de órgãos participantes na origem, entram no saldo e na execução do item. Se o PNCP não enviar o campo `frutoAdesao`, o empenho é tratado como **não adesão** e segue o fluxo normal; a ausência fica sinalizada para auditoria.

## Estrutura do projeto

```text
rastreador_empenhos/
├── pyproject.toml
├── README.md
├── requirements.txt
├── src/
│   └── rastreador_empenhos/
│       ├── __init__.py
│       ├── project_root.py
│       ├── cli.py
│       ├── atualizar_relatorios.py
│       ├── criar_usuario_admin.py
│       ├── generate_reports_index.py
│       ├── gerar_relatorios.py
│       ├── admin_web/
│       │   ├── app.py
│       │   ├── auth.py
│       │   ├── serve.py
│       │   └── templates/
│       ├── pncp_tracker/
│       │   ├── api_client.py
│       │   ├── collector.py
│       │   ├── constants.py
│       │   ├── contratos_empenhos.py
│       │   ├── contratos_gov.py
│       │   ├── empenho_details.py
│       │   ├── empenho_matcher.py
│       │   ├── empenho_portal.py
│       │   ├── empenhos.py
│       │   ├── consultar_e_mapear_empenhos.py
│       │   ├── portal_transparencia.py
│       │   ├── report_html.py
│       │   ├── process_lock.py
│       │   ├── report_registry.py
│       │   ├── report_service.py
│       │   └── url_parser.py
│       └── tests/
└── relatorios/
    ├── index.html
    ├── indice_relatorios.json
    └── <id_do_processo>/
        ├── relatorio_compra_<numero>_<ano>.html
        ├── dados_pregao.json
        ├── dados_empenhos.json
        └── metadados.json
```

- `rastreador_empenhos/cli.py`: comando `rastreador-empenhos`; delega coleta e persistência ao serviço compartilhado.
- `rastreador_empenhos/atualizar_relatorios.py`: comando `rastreador-empenhos-atualizar`; atualiza todos os processos ativos do índice, para uso manual ou por cron.
- `rastreador_empenhos/criar_usuario_admin.py`: comando `rastreador-empenhos-criar-usuario`; cria credenciais locais para a interface administrativa.
- `rastreador_empenhos/admin_web/`: comando `rastreador-empenhos-admin`; aplicação privada Flask servida por Waitress.
- `rastreador_empenhos/gerar_relatorios.py` e `generate_reports_index.py`: comando `rastreador-empenhos-gerar-indice`; regenera os HTMLs individuais e os índices sem consultar as APIs.
- `rastreador_empenhos/project_root.py`: localiza a raiz do projeto (`.env`, `.private/` e `relatorios/`) quando o pacote é executado a partir de uma instalação.
- `rastreador_empenhos/pncp_tracker/url_parser.py`: valida e extrai os parâmetros da URL pública do edital.
- `rastreador_empenhos/pncp_tracker/api_client.py` e `collector.py`: consultam e organizam os dados da compra, itens e resultados no PNCP.
- `rastreador_empenhos/pncp_tracker/contratos_empenhos.py`: consulta os registros da aba Contratos/Empenhos do PNCP.
- `rastreador_empenhos/pncp_tracker/portal_transparencia.py` e `empenho_details.py`: consultam e enriquecem os empenhos com detalhes do Portal da Transparência.
- `rastreador_empenhos/pncp_tracker/empenho_portal.py`: descobre empenhos no Portal da Transparência por contrato, licitação ou fornecedor homologado, aceitando processo/UG divergentes quando há evidência de vínculo.
- `rastreador_empenhos/pncp_tracker/contratos_gov.py`: cliente público da API Contratos.gov.br para confirmar a compra de cada empenho e obter a quantidade real dos itens.
- `rastreador_empenhos/pncp_tracker/empenho_matcher.py` e `empenhos.py`: relacionam empenhos aos itens e fornecedores homologados.
- `rastreador_empenhos/pncp_tracker/consultar_e_mapear_empenhos.py`: consulta os empenhos, enriquece com detalhes do Portal da Transparência e mapeia os registros aos itens da compra.
- `rastreador_empenhos/pncp_tracker/report_html.py`: prepara os dados e gera o relatório HTML.
- `rastreador_empenhos/pncp_tracker/report_service.py`: executa e persiste uma atualização individual ou em lote.
- `rastreador_empenhos/pncp_tracker/report_registry.py`: valida URLs e mantém a lista ativa no índice JSON.
- `rastreador_empenhos/tests/`: testes automatizados do projeto.

## Instalação

O projeto segue o layout `src/` e declara as dependências, os pacotes e os comandos em `pyproject.toml` (PEP 621, backend `setuptools`).

```bash
python -m pip install -r requirements.txt
```

Para instalar como ferramenta CLI isolada, sem alterar o ambiente global:

```bash
pipx install .
```

```powershell
pipx install -e .
```

Os cinco comandos abaixo passam a ficar disponíveis no `PATH`:

```text
rastreador-empenhos                 # CLI principal
rastreador-empenhos-atualizar       # atualização em lote (cron)
rastreador-empenhos-criar-usuario   # criação de usuário da interface administrativa
rastreador-empenhos-gerar-indice    # regenera os relatórios e índices a partir dos JSONs
rastreador-empenhos-admin           # servidor administrativo Waitress
```

## Requisitos e configuração

- Python 3.10 ou superior.
- Dependências declaradas em `pyproject.toml` (`requests`, Flask e Waitress), replicadas em `requirements.txt`.
- Chave da API do Portal da Transparência para consultar o detalhamento dos documentos de despesa.

Instale as dependências:

```bash
python -m pip install -r requirements.txt
```

Ou instale o próprio projeto (que já resolve as dependências):

```bash
pipx install .
```

O `.env`, `.private/` e `relatorios/` são procurados na **raiz do projeto**: a variável `RASTREADOR_EMPENHOS_ROOT` tem prioridade; sem ela, a raiz é detectada a partir do diretório atual (subindo até encontrar `relatorios/indice_relatorios.json`, `README.md` ou `.env.example`). Execute os comandos dentro do repositório — `cd rastreador_empenhos && rastreador-empenhos ...` — ou defina `RASTREADOR_EMPENHOS_ROOT` antes de chamar os comandos de outro diretório.

Configure a chave em um arquivo `.env` na raiz do projeto:

```dotenv
PORTAL_DADOS_API_KEY=sua_chave
```

Também são aceitas as variáveis `PORTAL_DADOS_API_KEY` e `PORTALTRANSPARENCIA_API_KEY` definidas no ambiente do sistema. Valores do ambiente não são sobrescritos pelo `.env`; a aplicação consulta primeiro `PORTAL_DADOS_API_KEY` e, se estiver ausente ou vazio, `PORTALTRANSPARENCIA_API_KEY`. Não compartilhe nem versione sua chave.

## Executar

Passe a URL pública do edital como argumento:

```bash
rastreador-empenhos "https://pncp.gov.br/app/editais/10635424000186/2025/187"
```

Sem `pipx`, a forma equivalente é `python -m rastreador_empenhos.cli "https://..."`.

Se a URL for omitida, o programa a solicitará no terminal. Uma URL vazia ou fora do formato `/editais/{cnpj}/{ano}/{sequencial}` é rejeitada antes das consultas.

Por padrão, a atualização usa apenas a aba Contratos/Empenhos do PNCP, considerando que ela traz os empenhos daquela licitação. Para também procurar no Portal da Transparência empenhos que não estejam registrados no PNCP, use a flag:

```bash
rastreador-empenhos "https://pncp.gov.br/app/editais/10635424000186/2025/187" --buscar-empenhos-portal
```

A busca adicional consulta o Portal por contrato, licitação e fornecedores homologados, o que aumenta o tempo de execução e o consumo de requisições (o endpoint por favorecido é restrito a 180 requisições por minuto; exceder o limite suspende o token por 8 horas). A flag vale apenas para a execução corrente e não altera o modo gravado no cadastro do processo. Em qualquer modo, os empenhos publicados no PNCP continuam sendo detalhados no Portal para identificar os itens da despesa.

Todos os registros retornados pela aba Contratos/Empenhos do PNCP permanecem no relatório, em uma seção recolhida com situação verificada e links para o PNCP e para o Portal da Transparência de cada empenho, mesmo quando o Portal não localiza o detalhamento. Nesses casos, o registro é exibido na seção de registros PNCP, mas não é atribuído a um item nem incluído nos totais por item sem os dados correspondentes do Portal.

Quando a consulta dos resultados homologados de um item falha (por exemplo, timeout no PNCP), o item fica como **resultado pendente** e, ao abrir o relatório pelo servidor administrativo autenticado, aparece o botão **Tentar novamente N item(ns) pendente(s)**. Ele refaz apenas os itens que falharam, reaproveita os empenhos já detalhados e regenera o relatório — sem repetir a coleta inteira nem consultar novamente o Portal da Transparência. No GitHub Pages o botão não aparece.

Os dados das duas etapas são preservados na pasta individual do relatório, sem opção de remoção automática. Se a API de Contratos/Empenhos do PNCP retornar HTTP 404 indicando que não há contratos publicados para a compra, a execução continua e gera o relatório sem esses registros. Outros erros HTTP são reportados.

## Relatório HTML

O arquivo gerado é autônomo, não depende de bibliotecas ou arquivos externos e pode ser aberto localmente, impresso ou salvo como PDF. O cabeçalho inclui um link para o edital no PNCP.

Na seção **Itens da contratação**, a tabela apresenta quantidades licitadas, homologadas e empenhadas estimadas, além do saldo do item. O saldo é calculado como:

```text
saldo = quantidade homologada - quantidade empenhada estimada
```

Quando não há empenhos vinculados ao item, a quantidade empenhada é zero e o saldo corresponde à quantidade homologada. Se houver empenho, mas não for possível estimar sua quantidade, o saldo aparece como `—`. As quantidades são exibidas na unidade do item e não são somadas entre unidades diferentes.

As linhas podem ser expandidas para consultar resultados homologados e empenhos vinculados. Em telas largas, os empenhos ocupam aproximadamente 70% da área de detalhes e os resultados homologados, 30%; em telas menores, as seções ficam empilhadas. Documentos do fornecedor sem vínculo comprovado não são exibidos no HTML nem incluídos nos totais; permanecem em `dados_empenhos.json` para auditoria.

Os filtros de situação podem ser combinados com a busca textual. Os cards apresentam as contagens de itens — total, homologados, empenhados, não empenhados, desertos e resultados pendentes — seguidas dos valores financeiros. Se o PNCP falhar ao consultar resultados homologados, o item fica marcado como pendente, não como deserto; o relatório exibe um aviso e o índice identifica a atualização como parcial. As tabelas podem ser ordenadas clicando nos cabeçalhos; também é possível focar um cabeçalho com Tab e alternar a ordenação com Enter ou Espaço. Ao ordenar os itens, suas linhas de detalhes acompanham cada item.

O botão **Baixar CSV completo** exporta todos os itens, independentemente dos filtros ativos. O arquivo inclui as colunas da tabela, inclusive o saldo, e os dados adicionais das linhas de empenho. Itens com empenhos vinculados geram uma linha por empenho; itens sem empenho vinculado geram uma linha. O CSV usa ponto e vírgula como separador e codificação UTF-8 com BOM para compatibilidade com planilhas.

## Arquivos gerados e testes

Cada processo tem sua própria pasta em `relatorios/<id_do_processo>/` (pastas preexistentes mantêm o nome atual); o identificador de novas pastas deriva da URL PNCP. A pasta contém:

- `relatorio_compra_{numero_compra}_{ano}.html`: relatório autônomo, regenerável sem rede;
- `dados_pregao.json`: dados coletados do edital e itens na primeira etapa;
- `dados_empenhos.json`: dados enriquecidos e mapeados da segunda etapa;
- `metadados.json`: URL PNCP, chaves da compra, datas de criação e atualização e resumo derivado dos cards do relatório.

Na raiz de `relatorios/` ficam `index.html`, `indice_relatorios.json`, `gerar_relatorios.py` e as pastas de cada compra. `indice_relatorios.json` é também o cadastro dos processos ativos: cada URL PNCP é única, e processos recém-cadastrados ficam pendentes até a primeira atualização. Remover da lista ativa preserva os arquivos históricos da pasta. O índice HTML apresenta uma linha por processo, com o objeto e os indicadores dos cards individuais.

O índice e cada relatório individual exibem, ao final da página, um aviso sempre visível sobre responsabilidade de uso, fontes e limitações de integração. Os dados não são atualizados em tempo real: é necessária uma nova atualização do processo pelo administrador ou pela rotina configurada, e a data exibida deve ser observada. O aviso também orienta a conferência nos sistemas oficiais antes de decisões importantes e permite comunicar inconsistências a `tiago.possato@ifc.edu.br`.

## Atualização automática e interface administrativa

Atualize manualmente todos os processos ativos:

```bash
rastreador-empenhos-atualizar
```

O comando tenta todos os processos mesmo se algum falhar e retorna código de saída diferente de zero se houver falhas, para que o cron possa registrá-las. Exemplo de crontab (ajuste os caminhos e a frequência):

```cron
0 3 * * * cd /opt/rastreador_empenhos && /home/usuario/.local/bin/rastreador-empenhos-atualizar >> /var/log/rastreador-empenhos.log 2>&1
```

A interface administrativa permite cadastrar URLs PNCP, remover processos da lista ativa sem apagar os dados históricos, definir por processo se a atualização deve procurar empenhos não registrados no PNCP e iniciar a atualização de um processo ou de todos. A coluna **Procurar empenhos não registrados no PNCP** guarda essa escolha em `indice_relatorios.json`; o modo selecionado é aplicado nas próximas atualizações do processo, inclusive nas disparadas pelo cron, e fica registrado em `metadados.json`. As tarefas iniciadas pela interface rodam em segundo plano; o painel exibe seu resultado enquanto o serviço estiver ativo. Um lock local serializa atualizações iniciadas pela interface, pela CLI e pelo cron. Execute uma única instância Waitress para manter o painel de tarefas consistente; o status em memória é perdido se o serviço reiniciar durante uma tarefa.

O arquivo privado de usuários fica por padrão em `.private/usuarios.json` (ignorado pelo Git e fora da pasta publicada). Crie a primeira conta de forma interativa (o próprio servidor administrativo também solicita essa conta quando ainda não existe nenhuma):

```bash
rastreador-empenhos-criar-usuario
```

As senhas são armazenadas apenas como hashes PBKDF2 salgados. Defina uma chave de sessão forte no ambiente do serviço; não a versione. No PowerShell (Windows), execute:

```powershell
$env:PNCP_ADMIN_SESSION_SECRET = (python -c "import secrets; print(secrets.token_urlsafe(48))")
```

No Bash (Linux/macOS), use:

```bash
export PNCP_ADMIN_SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

Opcionalmente, configure `PNCP_ADMIN_USERS_FILE` para apontar o arquivo privado de usuários. Inicie o servidor WSGI na máquina privada, na mesma sessão em que definiu a chave:

```bash
rastreador-empenhos-admin
```

Se o arquivo de usuários estiver vazio ou não existir, o servidor solicita antes da inicialização os dados da primeira conta — nome de usuário, senha e confirmação — e só sobe depois que ela é criada. Cancelar a criação (nome de usuário vazio, `Ctrl+C` ou entrada indisponível) encerra a execução sem iniciar a interface.

Na raiz do servidor administrativo (`http://127.0.0.1:8000/`) é exibido o `relatorios/index.html`, com o botão **Administração**. Os links do índice também servem os relatórios HTML individuais no mesmo endereço; os arquivos JSON não são expostos por essas rotas. O botão abre a tela de login em outra aba; após autenticar, essa aba segue para `/admin`. O GitHub Pages continua servindo apenas os relatórios estáticos; para que o botão funcione, acesse o índice pelo servidor administrativo, não pelo GitHub Pages.

O andamento das atualizações iniciadas no painel é exibido no terminal onde o servidor está rodando e gravado em `.private/admin_web.log` (com rotação automática). O log informa etapas da coleta, páginas e itens do PNCP, consulta de empenhos e geração dos relatórios. Configure `PNCP_ADMIN_LOG_FILE` para usar outro caminho de log. O login bloqueia temporariamente novas tentativas após cinco falhas do mesmo usuário e IP em dez minutos; esse contador é mantido em memória por instância do servidor.

Por padrão, Waitress escuta em `127.0.0.1:8000`. Publique o servidor somente atrás de um reverse proxy com HTTPS e controle de acesso de rede; não o exponha diretamente à internet. `PNCP_ADMIN_HOST` e `PNCP_ADMIN_PORT` configuram o endereço de escuta. Para teste local sem HTTPS, `PNCP_ADMIN_COOKIE_SECURE=0` desativa a flag Secure do cookie; não use essa opção em produção. O painel, login e status das tarefas usam `Cache-Control: no-store`; o índice e relatórios HTML públicos permitem cache por 60 segundos.

Atualizações concorrentes compartilham um lock em `.private/report_update.lock`. A espera tem limite de 300 segundos; se o lock continuar ocupado, a operação falha explicitamente em vez de aguardar indefinidamente.

Para recriar os relatórios individuais e os dois índices, sem consultar as APIs:

```bash
rastreador-empenhos-gerar-indice
```

## Publicação no GitHub Pages

O workflow `.github/workflows/pages.yml` regenera os relatórios individuais e os índices a partir do cadastro e dos JSONs versionados (`python -m pip install .` seguido de `rastreador-empenhos-gerar-indice`), e publica o conteúdo de `relatorios/` no GitHub Pages em cada push para `main`. Também é possível iniciar a publicação manualmente pela aba **Actions**.

Para publicar, configure a fonte do GitHub Pages como **GitHub Actions** em **Settings → Pages**. O workflow publica os relatórios HTML que estão versionados; a coleta de novas compras continua sendo feita localmente. Para incluir um novo relatório no site, gere-o e envie o arquivo para o repositório.

O mesmo gerador pode ser executado pelo atalho na raiz do projeto:

```bash
rastreador-empenhos-gerar-indice
```

Para executar os testes, instale o projeto em modo editável (`pipx install -e .` ou `python -m pip install -e .`) e rode:

```bash
python -m unittest rastreador_empenhos.tests.suite -v
```

## Fontes e limitações

- [Portal Nacional de Contratações Públicas (PNCP)](https://pncp.gov.br) — dados da compra, itens, resultados homologados e registros de contratos/empenhos.
- [Portal da Transparência](https://portaldatransparencia.gov.br) — detalhes dos documentos e itens das notas de empenho; requer chave de API.

O script atende compras federais vinculadas ao SIASG/Compras.gov.br. A busca dos documentos no Portal da Transparência usa o CNPJ do fornecedor, o ano do empenho e a unidade gestora; não depende da data de assinatura/publicação do PNCP. Se faltar algum dado necessário, o registro é identificado como não consultado ou não localizado; falhas da API são reportadas como erros.
