
# Rastreador de Empenhos por Item — Compras Públicas Federais (PNCP)

Script em Python para automatizar o levantamento de dados de licitações federais a partir de uma URL pública do **Portal Nacional de Contratações Públicas (PNCP)** e rastrear os empenhos emitidos para cada item homologado.

---

## 📋 Visão Geral da Arquitetura

Como o ecossistema de dados abertos do Governo Federal separa o catálogo da licitação da execução orçamentária, o projeto é dividido em duas etapas:

- **Etapa 1 (Concluída):** Extração dos metadados da compra, itens licitados, vencedores e chaves de integração (UASG, número da compra e ano) via **API do PNCP**.
- **Etapa 2:** Consulta de empenhos e itens nas APIs do **PNCP** e do **Portal da Transparência**.

## 🧩 Estrutura modular do projeto

A coleta foi separada em módulos para facilitar manutenção e evolução:

```text
relatorio_compra/
├── main.py
├── README.md
├── etapa1_dados_compra.json
├── etapa2_empenhos.json
├── relatorio_compra_90026_2025.html
├── pncp_tracker/
│   ├── __init__.py
│   ├── api_client.py
│   ├── collector.py
│   ├── constants.py
│   ├── report_html.py
│   ├── url_parser.py
│   └── ...
└──
```

- `main.py`: ponto de entrada que executa as duas etapas.
- `pncp_tracker/url_parser.py`: valida e extrai parâmetros da URL do edital.
- `pncp_tracker/api_client.py`: centraliza as chamadas HTTP ao PNCP.
- `pncp_tracker/collector.py`: orquestra a coleta dos dados da compra e itens.
- `pncp_tracker/contratos_empenhos.py`: pagina a mesma API do PNCP usada pela aba Contratos/Empenhos.
- `pncp_tracker/empenhos.py`: reexporta a lógica de mapeamento de empenhos por item/fornecedor.
- `pncp_tracker/etapa2.py`: orquestra a busca e o mapeamento dos empenhos da licitação.
- `pncp_tracker/report_html.py`: gera o relatório HTML autônomo.

---

## ⚙️ Pré-requisitos

- **Python 3.8** ou superior
- Biblioteca `requests`

### Instalação

Clone o repositório e instale a dependência necessária:

```bash
git clone <url-do-seu-repositorio>
cd <nome-da-pasta>
pip install requests
```

---

## 🚀 Como Executar

1. Configure a chave da API do Portal da Transparência no `.env`.
2. Execute o script informando a URL do edital como argumento:

```bash
python main.py "https://pncp.gov.br/app/editais/10635424000186/2025/187"
```

Se executar apenas `python main.py`, o programa solicitará o link no terminal. Se nenhum link for digitado, ou se o formato for inválido, a execução será encerrada sem iniciar as consultas.

Uma única execução coleta os dados do edital, consulta os empenhos e gera `etapa1_dados_compra.json`, `etapa2_empenhos.json` e um relatório com o nome `relatorio_compra_{numero_compra}_{ano}.html` (por exemplo, `relatorio_compra_90026_2025.html`). Assim, relatórios de editais diferentes ficam preservados; ao executar novamente o mesmo edital, o arquivo correspondente é atualizado. Os arquivos JSON continuam sendo substituídos a cada execução. Os dados da etapa 1 são reutilizados na etapa 2. O HTML é um arquivo único, sem dependências externas; pode ser aberto localmente, filtrado por item/descrição/empenho e impresso ou salvo como PDF.

No topo do relatório, há contagens de itens desertos (valor homologado R$ 0,00), empenhados (execução acima de 0%) e não empenhados (execução igual a 0%, excluindo desertos). Os filtros da tabela permitem exibir cada grupo separadamente e podem ser combinados com a busca textual.

O relatório mostra valores estimados e homologados, quantidade licitada/homologada, valor empenhado por item e empenhos detalhados. A quantidade empenhada não é informada pela API; é estimada pelo valor da linha dividido pelo preço unitário homologado, com essa ressalva indicada na página.

Para evitar depender da data de assinatura/publicação do PNCP (que pode divergir bastante da emissão, inclusive em reforços), a busca dos documentos usa o endpoint do Portal da Transparência filtrado pelo CNPJ do fornecedor, ano do empenho e unidade gestora. A data de assinatura não participa da busca; se faltar CNPJ ou o ano não puder ser extraído do número do empenho, o registro fica explicitamente como não consultado.

Todas as tabelas do relatório podem ser ordenadas clicando no cabeçalho; também é possível focar um cabeçalho com Tab e alternar a ordenação com Enter ou Espaço. Um segundo clique no mesmo campo inverte a ordem. Valores numéricos, monetários e datas são ordenados pelos seus valores, e campos vazios permanecem no final. Ao ordenar os itens, cada linha de detalhes acompanha o item correspondente.

---

## 📦 Saída Gerada

Ao finalizar a execução, o script exibirá no console as chaves de integração extraídas e salvará o arquivo **`etapa1_dados_compra.json`** na raiz do projeto com a seguinte estrutura:

```json
{
  "chaves_integracao": {
    "cnpj_orgao": "00394460000141",
    "uasg_codigo": "170010",
    "uasg_nome": "SECRETARIA ESPECIAL DA RECEITA FEDERAL DO BRASIL",
    "numero_compra": "90001",
    "ano_compra": 2024,
    "modalidade_id": 6,
    "modalidade_nome": "Pregão - Eletrônico",
    "processo": "12345.000123/2024-00",
    "numero_controle_pncp": "00394460000141-1-000001/2024"
  },
  "objeto": "Descrição resumida do objeto da licitação...",
  "valor_total_estimado": 150000.00,
  "valor_total_homologado": 142500.00,
  "quantidade_itens": 10,
  "itens": [
    {
      "numeroItem": 1,
      "descricao": "Descrição detalhada do item...",
      "quantidade": 50,
      "valorUnitarioEstimado": 100.00,
      "resultadosHomologados": [
        {
          "niFornecedor": "12345678000199",
          "nomeRazaoSocialFornecedor": "EMPRESA VENCEDORA LTDA",
          "valorUnitarioHomologado": 95.00,
          "valorTotalHomologado": 4750.00
        }
      ]
    }
  ]
}
```

---

## 🔗 Fontes de Dados Utilizadas

- [Portal Nacional de Contratações Públicas (PNCP) - API de Consulta](https://pncp.gov.br)
- [Portal da Transparência - API de Dados](https://portaldatransparencia.gov.br) *(integração opcional; requer chave)*
- [Dados Abertos Compras.gov.br](https://compras.gov.br) *(previsto para Etapa 2)*

---

## ⚠️ Limitações Conhecidas

- O script atual atende exclusivamente compras **federais** vinculadas ao SIASG/Compras.gov.br.
- Links do PNCP devem seguir o padrão público `/editais/{cnpj}/{ano}/{sequencial}`.
