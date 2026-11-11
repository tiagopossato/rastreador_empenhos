# Rastreador de Empenhos por Item — Compras Públicas Federais (PNCP)

Aplicação Python de linha de comando que coleta dados de uma compra no Portal Nacional de Contratações Públicas (PNCP), relaciona empenhos aos itens homologados e gera um relatório HTML autônomo.

## Como funciona

1. **Coleta da compra:** consulta no PNCP os dados do edital, seus itens e resultados homologados.
2. **Consulta de empenhos:** busca contratos/empenhos publicados para a compra no PNCP e complementa os documentos com detalhes e itens da despesa no Portal da Transparência.
3. **Mapeamento e relatório:** relaciona as linhas de empenho aos itens por número do item e fornecedor homologado e gera o relatório HTML.

O PNCP fornece valores de empenho, mas não necessariamente a quantidade física empenhada. Quando há preço unitário homologado, a quantidade empenhada é estimada dividindo o valor da linha pelo preço unitário. O relatório identifica essa estimativa e mantém registros sem correspondência confirmada em uma seção separada.

## Estrutura do projeto

```text
rastreador_empenhos/
├── main.py
├── README.md
├── generate_reports_index.py
├── pncp_tracker/
│   ├── api_client.py
│   ├── collector.py
│   ├── constants.py
│   ├── contratos_empenhos.py
│   ├── empenho_details.py
│   ├── empenho_matcher.py
│   ├── empenhos.py
│   ├── consultar_e_mapear_empenhos.py
│   ├── portal_transparencia.py
│   ├── report_html.py
│   └── url_parser.py
├── relatorios/
└── tests/
```

- `main.py`: ponto de entrada; executa as consultas e salva o relatório.
- `pncp_tracker/url_parser.py`: valida e extrai os parâmetros da URL pública do edital.
- `pncp_tracker/api_client.py` e `collector.py`: consultam e organizam os dados da compra, itens e resultados no PNCP.
- `pncp_tracker/contratos_empenhos.py`: consulta os registros da aba Contratos/Empenhos do PNCP.
- `pncp_tracker/portal_transparencia.py` e `empenho_details.py`: consultam e enriquecem os empenhos com detalhes do Portal da Transparência.
- `pncp_tracker/empenho_matcher.py` e `empenhos.py`: relacionam empenhos aos itens e fornecedores homologados.
- `pncp_tracker/consultar_e_mapear_empenhos.py`: consulta os empenhos, enriquece com detalhes do Portal da Transparência e mapeia os registros aos itens da compra.
- `pncp_tracker/report_html.py`: prepara os dados e gera o relatório HTML.
- `generate_reports_index.py`: gera o índice HTML dos relatórios existentes em `relatorios/`.
- `tests/`: testes automatizados do projeto.

## Requisitos e configuração

- Python 3.8 ou superior.
- Dependência Python `requests`.
- Chave da API do Portal da Transparência para consultar o detalhamento dos documentos de despesa.

Instale a dependência:

```bash
python -m pip install requests
```

Configure a chave em um arquivo `.env` na raiz do projeto:

```dotenv
PORTAL_DADOS_API_KEY=sua_chave
```

Também são aceitas as variáveis `PORTAL_DADOS_API_KEY` e `PORTALTRANSPARENCIA_API_KEY` definidas no ambiente do sistema. Valores do ambiente não são sobrescritos pelo `.env`; a aplicação consulta primeiro `PORTAL_DADOS_API_KEY` e, se estiver ausente ou vazio, `PORTALTRANSPARENCIA_API_KEY`. Não compartilhe nem versione sua chave.

## Executar

Passe a URL pública do edital como argumento:

```bash
python main.py "https://pncp.gov.br/app/editais/10635424000186/2025/187"
```

Se a URL for omitida, o programa a solicitará no terminal. Uma URL vazia ou fora do formato `/editais/{cnpj}/{ano}/{sequencial}` é rejeitada antes das consultas.

Por padrão, depois que o relatório é gerado com sucesso, os arquivos intermediários `etapa1_dados_compra.json` e `etapa2_empenhos.json` são removidos. Para mantê-los:

```bash
python main.py "https://pncp.gov.br/app/editais/10635424000186/2025/187" --manter-json
```

O alias `--manterJSON` também é aceito. Se a API de Contratos/Empenhos do PNCP retornar HTTP 404 indicando que não há contratos publicados para a compra, a execução continua e gera o relatório sem esses registros. Outros erros HTTP são reportados.

## Relatório HTML

O arquivo gerado é autônomo, não depende de bibliotecas ou arquivos externos e pode ser aberto localmente, impresso ou salvo como PDF. O cabeçalho inclui um link para o edital no PNCP.

Na seção **Itens da contratação**, a tabela apresenta quantidades licitadas, homologadas e empenhadas estimadas, além do saldo do item. O saldo é calculado como:

```text
saldo = quantidade homologada - quantidade empenhada estimada
```

Se uma dessas quantidades estiver indisponível, o saldo aparece como `—`. As quantidades são exibidas na unidade do item e não são somadas entre unidades diferentes.

As linhas podem ser expandidas para consultar resultados homologados e empenhos vinculados. Em telas largas, os empenhos ocupam aproximadamente 70% da área de detalhes e os resultados homologados, 30%; em telas menores, as seções ficam empilhadas. Registros que não puderam ser vinculados a um item aparecem na seção **Registros sem vínculo confirmado a item**.

Os filtros de situação podem ser combinados com a busca textual. Os cards apresentam as contagens de itens — total, homologados, empenhados, não empenhados e desertos — seguidas dos valores financeiros. As tabelas podem ser ordenadas clicando nos cabeçalhos; também é possível focar um cabeçalho com Tab e alternar a ordenação com Enter ou Espaço. Ao ordenar os itens, suas linhas de detalhes acompanham cada item.

O botão **Baixar CSV completo** exporta todos os itens, independentemente dos filtros ativos. O arquivo inclui as colunas da tabela, inclusive o saldo, e os dados adicionais das linhas de empenho. Itens com empenhos vinculados geram uma linha por empenho; itens sem empenho vinculado geram uma linha. O CSV usa ponto e vírgula como separador e codificação UTF-8 com BOM para compatibilidade com planilhas.

## Arquivos gerados e testes

O relatório é salvo em `relatorios/relatorio_compra_{numero_compra}_{ano}.html`, por exemplo, `relatorios/relatorio_compra_90026_2025.html`. Relatórios de compras diferentes são preservados; uma nova execução da mesma compra atualiza o arquivo correspondente. Após gerar o relatório, a aplicação também atualiza `relatorios/index.html` com links para os relatórios existentes.

## Publicação no GitHub Pages

O workflow `.github/workflows/pages.yml` gera `relatorios/index.html` com cards para os relatórios presentes e publica o conteúdo de `relatorios/` no GitHub Pages em cada push para `main`. Também é possível iniciar a publicação manualmente pela aba **Actions**.

Para publicar, configure a fonte do GitHub Pages como **GitHub Actions** em **Settings → Pages**. O workflow publica os relatórios HTML que estão versionados; a coleta de novas compras continua sendo feita localmente. Para incluir um novo relatório no site, gere-o e envie o arquivo para o repositório.

Para gerar ou atualizar o índice localmente:

```bash
python generate_reports_index.py
```

Para executar os testes:

```bash
python -m unittest discover -s tests -v
```

## Fontes e limitações

- [Portal Nacional de Contratações Públicas (PNCP)](https://pncp.gov.br) — dados da compra, itens, resultados homologados e registros de contratos/empenhos.
- [Portal da Transparência](https://portaldatransparencia.gov.br) — detalhes dos documentos e itens das notas de empenho; requer chave de API.

O script atende compras federais vinculadas ao SIASG/Compras.gov.br. A busca dos documentos no Portal da Transparência usa o CNPJ do fornecedor, o ano do empenho e a unidade gestora; não depende da data de assinatura/publicação do PNCP. Se faltar algum dado necessário, o registro é identificado como não consultado ou não localizado; falhas da API são reportadas como erros.
