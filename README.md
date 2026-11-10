
# Rastreador de Empenhos por Item — Compras Públicas Federais (PNCP)

Script em Python para automatizar o levantamento de dados de licitações federais a partir de uma URL pública do **Portal Nacional de Contratações Públicas (PNCP)** e rastrear os empenhos emitidos para cada item homologado.

---

## 📋 Visão Geral da Arquitetura

Como o ecossistema de dados abertos do Governo Federal separa o catálogo da licitação da execução orçamentária, o projeto é dividido em duas etapas:

- **Etapa 1 (Concluída):** Extração dos metadados da compra, itens licitados, vencedores e chaves de integração (UASG, número da compra e ano) via **API do PNCP**.
- **Etapa 2 (Em desenvolvimento):** Cruzamento das chaves extraídas com as APIs do **Portal da Transparência** e **Compras.gov.br** para mapear as notas de empenho por item e fornecedor.

## 🧩 Estrutura modular do projeto

A coleta foi separada em módulos para facilitar manutenção e evolução:

```text
relatorio_compra/
├── main.py
├── README.md
├── etapa1_dados_compra.json
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

- `main.py`: ponto de entrada do script.
- `pncp_tracker/url_parser.py`: valida e extrai parâmetros da URL do edital.
- `pncp_tracker/api_client.py`: centraliza as chamadas HTTP ao PNCP.
- `pncp_tracker/collector.py`: orquestra a coleta dos dados da compra e itens.
- `pncp_tracker/contratos_empenhos.py`: pagina a mesma API do PNCP usada pela aba Contratos/Empenhos.
- `pncp_tracker/empenhos.py`: reexporta a lógica de mapeamento de empenhos por item/fornecedor.
- `pncp_tracker/etapa2.py`: orquestra a busca e o mapeamento dos empenhos da licitação.
- `pncp_tracker/report_html.py`: gera o relatório HTML autônomo.
- `main_etapa2.py`: entrypoint para a etapa 2.

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

## 🚀 Como Usar (Etapa 1)

1. Abra o arquivo principal do script: `main.py`.
2. Na seção `__main__`, altere a variável `link_teste` para a URL de qualquer edital federal publicado no PNCP:

```python
link_teste = "https://pncp.gov.br/app/editais/10635424000186/2025/000272"
```

3. Execute o script no terminal:

```bash
python main.py
```

---

## 🚀 Como Usar (Etapa 2)

A etapa 2 consulta a API pública do PNCP utilizada pela aba **Contratos/Empenhos**. Para cada empenho listado, usa também a chave do Portal da Transparência para buscar o detalhamento e os itens do documento. Configure `PORTAL_DADOS_API_KEY` no `.env` como descrito acima e execute:

```bash
python main_etapa2.py
```

Ao executar a etapa 2, são gerados `etapa2_empenhos.json` e `relatorio_compra.html`. O HTML é um arquivo único, sem dependências externas; pode ser aberto localmente, filtrado por item/descrição/empenho e impresso ou salvo como PDF. Ele mostra valores estimados e homologados, quantidade licitada/homologada, valor empenhado por item e empenhos detalhados. Os itens do empenho vêm diretamente do documento de despesa no Portal da Transparência. Quando a descrição inclui `Item compra: N`, o código cruza esse número e o CNPJ do fornecedor com o item N do PNCP. A quantidade empenhada não é informada pela API; é estimada pelo valor empenhado dividido pelo preço unitário homologado, com essa ressalva indicada na página. Se essa referência não existir, o empenho fica separado como pendente e não é somado a um item.

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
