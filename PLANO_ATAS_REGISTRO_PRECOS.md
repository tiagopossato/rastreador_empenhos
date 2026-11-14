# Atas de Registro de Preços (ARP): empenhos e saldos

> Documento de planejamento. Nada aqui foi implementado ainda.

## Problema

Hoje o relatório mostra, por item, a quantidade homologada e a quantidade empenhada. Ele **não** mostra as atas de registro de preços (ARP) da contratação, nem quanto cada ata já foi empenhada, nem o saldo restante da ata. Sem isso não é possível saber se a ata está esgotada, se sobrou quantidade para adesão/carona ou se um fornecedor vem sendo empenhado acima do registrado.

Este plano primeiro **analisa a viabilidade** (o que as APIs realmente entregam) e só depois propõe a implementação.

## Fatos verificados (14/11/2026, chamadas reais)

| Verificação | Resultado |
| --- | --- |
| `GET /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/atas` | **200** — não documentado; retorna `data[]` + `totalRegistros/totalPaginas`. Para `10635424000186`/`2025`/`272`: **28 atas**. |
| Campos da ata nesse endpoint | `numeroAtaRegistroPreco`, `anoAta`, `sequencialAta`, `numeroControlePNCP` (`…-1-000272/2025-000001`), `dataAssinatura`, `dataVigenciaInicio/Fim`, `cancelado`, `dataCancelamento`, `possibilidadeAdesao`, `objetoCompra`, `unidadeOrgao`, `modalidadeNome`. **Sem fornecedor e sem itens.** |
| `GET …/compras/{ano}/{seq}/atas/{sequencialAta}` | **200** — mesmo cabeçalho, mais `numeroControlePncpCompra`; **sem itens**. |
| `GET …/compras/{ano}/{seq}/atas/{n}/itens` e `…/orgaos/{cnpj}/atas/{ano}/{seq}/itens` | **404** (não existem). |
| `GET /api/consulta/v1/atas?dataInicial&dataFinal&cnpj&pagina` | **200**, porém filtrado por **vigência** e limitado a **365 dias** por consulta (422 fora disso). Para o órgão: 1.274 atas em 2025 — caro e sem vínculo direto com a compra. |
| Página pública `/app/atas/{cnpj}/{ano}/{seq}` | Abas **Órgãos/Entidades, Contratos, Arquivos, Histórico** — **não há aba de itens**; a tabela de órgãos veio vazia. |
| API Contratos.gov.br (75 caminhos) | **Nenhum** endpoint de ARP; `/api/v1/empenho/rp` é "restos a pagar", não registro de preços. |
| `numeroControlePncpAta` nos empenhos já coletados | **221 de 574** empenhos (38%) trazem o id da ata, ex.: `10635424000186-1-000343/2024-000025`. |
| Compra 2025/272 | 74 empenhos, **50 com ata**, **20 atas distintas** referenciadas (de 28 existentes) e **1 fornecedor por ata**. |

**Conclusão da análise:** o PNCP entrega o **cabeçalho da ata** (vigência, cancelamento, adesão) e o **vínculo empenho→ata** (`numeroControlePncpAta`), mas **não entrega os itens da ata**. O saldo da ata precisa ser derivado: quantidade homologada do fornecedor (que é o que a ata registra) menos as linhas de empenho que citam aquela ata.

## Fase 1 — Spike de viabilidade (antes de codar a feature)

Quatro perguntas, cada uma com critério objetivo de sucesso:

1. **Cobertura do vínculo**: em todas as 10 compras ativas, qual o percentual de empenhos com `numeroControlePncpAta` preenchido e quantas atas ficam sem nenhum empenho?
   - *Sucesso*: ≥ 60% dos empenhos com ata e ≥ 90% das atas com fornecedor identificável (via empenho).
2. **Fornecedor por ata**: confirmar que cada ata tem exatamente 1 `niFornecedor` nos empenhos. Se houver ata com 2+ fornecedores, definir regra (provável: ata substituída/retificada).
3. **Regra do saldo**: para 2025/272, comparar `saldo = homologado(fornecedor×item) − Σ linhas de empenho da ata` por item e conferir se bate com a expectativa do setor (itens 30, 24 etc.). Verificar itens em que o empenhado **excede** o homologado (sinal de adesão de outro órgão ou erro de vínculo).
4. **Atas sem empenho e atas canceladas**: as 8 atas sem empenho de 2025/272 têm saldo integral? Atas com `cancelado = true` devem sair dos totais.

Se o item 3 não fechar (divergência grande e sem explicação), a feature para no spike e o relatório continua como está, apenas com a lista de atas e links.

## Fase 2 — Implementação proposta (condicionada à Fase 1)

### Coleta (etapa 1 — `dados_pregao.json`)

- Novo módulo `pncp_tracker/atas.py`:
  - `consultar_atas_da_compra(cnpj, ano, sequencial, tamanho_pagina=50)` → lista de atas, paginando por `totalPaginas` (1 requisição na prática).
  - HTTP 404 → lista vazia (mesma semântica dos contratos); erro HTTP → `requests.RequestException`.
  - Normalização: `id` = `numeroControlePNCP`, `cancelada` = `cancelado`, vigência em ISO, `vigencia_status` calculado (`vigente` / `expirada` / `futura`).
- `report_service` grava `atas` + `coleta_atas` no `dados_pregao.json`, com `on_progress` ("Atas recebidas: N").
- Custo: 1 requisição por processo (2 no máximo). Não precisa de flag.

### Vínculo e cálculo (etapa 2 — `dados_empenhos.json`)

- Cada empenho recebe `ata_id` (de `numeroControlePncpAta`) e `ata_fornecedor`.
- Novo bloco `atas` no resultado:

```json
{
  "id": "10635424000186-1-000272/2025-000001",
  "numero": "00788", "cancelada": false,
  "vigencia_inicio": "2026-01-09", "vigencia_fim": "2027-01-08",
  "fornecedor_cnpj": "57562366000171", "fornecedor_nome": "TATSUOTECH...",
  "itens": [{"numero_item": 1, "registrado": 232, "empenhado": 65, "saldo": 167}],
  "registrado_total": 0, "empenhado_total": 0, "saldo_total": 0,
  "empenhos": ["2026NE000027", "2026NE000045"]
}
```

- Regra de cálculo (`empenho_ata.py`, pura, testável sem rede):
  - `registrado(item)` = Σ `quantidadeHomologada` dos resultados daquele fornecedor para o item.
  - `empenhado(item)` = Σ quantidades das linhas de empenho da ata (mesma conversão valor÷preço unitário já usada, agora fracionada).
  - `saldo = registrado − empenhado`; marcar `excedido: true` quando negativo.
  - Atas canceladas: calcular mas **fora dos totais**; atas sem fornecedor identificável: `fornecedor_desconhecido`.
- Consistência: a soma dos saldos das atas de um item não pode exceder o saldo do item; divergência vira aviso no relatório (não erro).

### Relatório

- Nova seção recolhida **"Atas de registro de preços"** (mesmo padrão da seção de registros PNCP): número, vigência, situação (vigente/expirada/cancelada), fornecedor, itens com registrado/empenhado/saldo e link do PNCP da ata.
- No detalhe do item: coluna **Ata** em cada linha de empenho (id/número) e, quando houver, o saldo da ata para aquele item.
- Rodapé: "Atas nesta compra", "Atas com saldo", "Atas esgotadas".
- CSV: coluna `ata`.
- Sem quebra do que existe: itens, saldos e execução continuam calculados como hoje.

### Testes

- `tests/test_atas.py`: parsing/paginação do endpoint, 404 → vazio, normalização de datas/cancelamento.
- `tests/test_empenho_ata.py`: regra de saldo com casos reais (item 30/2025-272), item excedido, ata cancelada, ata sem empenho, ata com fornecedor desconhecido.
- `tests/test_report_service.py`: `atas` persistidas no `dados_pregao.json`.
- `tests/test_consultar_e_mapear_empenhos.py`: bloco `atas` no `dados_empenhos.json` e coluna no HTML.
- Sem rede; todo HTTP por mock.

### Docs

- `agents.md`: endpoint (não documentado) com caminho/params/retorno, regra do saldo, limitações.
- `README.md`: seção de atas e como interpretar o saldo.

## Riscos e limites (a registrar no relatório)

1. **Sem itens na ata**: o saldo é derivado, não publicado — precisa do aviso "saldo calculado".
2. **38% dos empenhos sem `numeroControlePncpAta`** (alguns porque não são SRP): esses empenhos entram no item, mas não em uma ata.
3. **Fornecedor por inferência**: ata sem nenhum empenho fica sem fornecedor; se o mesmo fornecedor tiver 2 atas na mesma compra, a atribuição por empenho pode ser ambígua.
4. **Endpoint não documentado**: pode mudar; falha deve degradar para "sem dados de atas" sem quebrar o relatório (404/erro → seção oculta + aviso).
5. **Adesão de outro órgão**: empenho de carona pode citar a ata e estourar o saldo; precisa aparecer como "excedido" e não como erro.
6. **Vigência**: ata expirada/cancelada continua aparecendo (com marcação), para auditoria.

## Fora de escopo

- Buscar atas de **outros órgãos** que aderiram à mesma compra (o PNCP só lista as atas do órgão da compra).
- Itens/quantidades por adesão ("carona") — não há endpoint; só o que aparecer nos empenhos.
- Migrar o histórico já publicado: cada processo passa a ter atas na próxima atualização.

## Sequência de execução

1. Spike (itens 1–4 acima) e decisão go/no-go.
2. `atas.py` + persistência em `dados_pregao.json`.
3. `empenho_ata.py` (regra do saldo) + bloco `atas` no `dados_empenhos.json`.
4. Relatório (seção, coluna, rodapé, CSV) e docs.
5. Rodar a atualização dos 10 processos e revisar os números com o setor.
