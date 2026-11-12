# Instruções para agentes de IA

Este repositório contém a aplicação Python `rastreador_empenhos`, que coleta dados de uma compra pública no PNCP, relaciona empenhos aos itens homologados e gera um relatório HTML autônomo.

## Objetivo do projeto

- Consultar a compra, itens e resultados homologados no Portal Nacional de Contratações Públicas (PNCP).
- Buscar contratos e empenhos relacionados à compra.
- Enriquecer os empenhos usando o Portal da Transparência.
- Relacionar empenhos a itens/fornecedores homologados.
- Gerar um relatório HTML contendo a análise e os vínculos identificados.

## Estrutura principal

- `main.py`: ponto de entrada da aplicação.
- `pncp_tracker/url_parser.py`: valida a URL pública do edital.
- `pncp_tracker/api_client.py`: cliente HTTP para consultas ao PNCP.
- `pncp_tracker/collector.py`: coleta e organiza dados da compra e itens.
- `pncp_tracker/contratos_empenhos.py`: consulta registros de contratos/empenhos.
- `pncp_tracker/portal_transparencia.py`: consulta dados do Portal da Transparência.
- `pncp_tracker/empenho_details.py`: detalha documentos de empenho.
- `pncp_tracker/empenho_matcher.py`: relaciona empenhos a itens e fornecedores.
- `pncp_tracker/empenhos.py`: models e processamento de empenhos.
- `pncp_tracker/consultar_e_mapear_empenhos.py`: consulta os empenhos, enriquece com os detalhes do Portal da Transparência e mapeia os registros aos itens da compra.
- `pncp_tracker/report_html.py`: gera o relatório HTML final.
- `relatorios/gerar_relatorios.py`: regenera os HTMLs individuais e os índices JSON/HTML a partir dos dados persistidos.
- `relatorios/`: índice e pastas individuais com HTML, JSONs das duas etapas e metadados.
- `tests/`: testes automatizados.

## Configuração e requisitos

- Python 3.8 ou superior.
- Dependência: `requests`.
- Chave da API do Portal da Transparência configurada em `.env` ou variável de ambiente.

Instalação:

```bash
python -m pip install requests
```

Arquivo `.env`:

```dotenv
PORTAL_DADOS_API_KEY=sua_chave
```

Também são aceitas as variáveis `PORTAL_DADOS_API_KEY` e `PORTALTRANSPARENCIA_API_KEY`. A aplicação prioriza a primeira variável disponível e não sobrescreve valores já presentes no ambiente.

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

## Testes

Para validar alterações:

```bash
python -m unittest discover -s tests -v
```

## Regras para alterações

- Mantenha o fluxo principal de coleta e geração do relatório intacto.
- Prefira alterações pequenas e focadas no módulo relevante.
- Quando ajustar lógica de matching de empenhos, preserve a semântica de itens homologados, fornecedores e estimativa de quantidade empenhada.
- Não exponha chaves de API em logs, commits ou arquivos versionados.
- Ao alterar comportamento do HTML, valide o efeito em relação aos testes existentes e à estrutura do relatório.
- Relatórios HTML gerados em `relatorios/` são artefatos da aplicação; não os trate como fonte de código.

## Observações importantes

- O relatório final é autônomo e pode ser aberto localmente sem dependências externas.
- Registros sem vínculo confirmado a item devem continuar sendo reportados em seção separada.
- Em caso de erro HTTP 404 na API de Contratos/Empenhos do PNCP, a aplicação deve seguir normalmente e gerar o relatório sem esses registros; outros erros HTTP devem ser reportados.
- A aplicação depende de dados do Portal da Transparência com base em CNPJ do fornecedor, ano do empenho e unidade gestora.

## Checklist para contribuições

Ao editar o projeto, verifique:

1. Se a mudança impacta entrada, parsing de URL ou configuração.
2. Se a mudança afeta a coleta de empenhos, matching ou geração do relatório HTML.
3. Se os testes continuam passando.
4. Se não foram introduzidas vazamentos de dados sensíveis ou credenciais.

No momento de concluir uma alteração, execute os testes relevantes e descreva claramente o objetivo da mudança e o comportamento verificado.
