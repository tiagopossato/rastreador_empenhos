from .api_client import buscar_dados_compra, buscar_resultados_item, listar_itens
from .constants import DEFAULT_PAGE_SIZE
from .url_parser import extrair_parametros_url


def baixar_dados_compra_pncp(url_pncp: str) -> dict:
    """Consulta os dados gerais da compra, os itens e os resultados homologados."""
    params = extrair_parametros_url(url_pncp)
    cnpj = params["cnpj"]
    ano = params["ano"]
    sequencial = params["sequencial"]

    dados_compra = buscar_dados_compra(cnpj, ano, sequencial)
    itens_completos = []
    pagina = 1

    while True:
        lote_itens = listar_itens(cnpj, ano, sequencial, pagina=pagina, tamanho_pagina=DEFAULT_PAGE_SIZE)

        if not lote_itens:
            break

        for item in lote_itens:
            num_item = item.get("numeroItem")
            if num_item is None:
                itens_completos.append(item)
                continue

            try:
                item["resultadosHomologados"] = buscar_resultados_item(cnpj, ano, sequencial, num_item)
            except Exception:
                item["resultadosHomologados"] = []

            itens_completos.append(item)

        if len(lote_itens) < DEFAULT_PAGE_SIZE:
            break

        pagina += 1

    return {
        "chaves_integracao": {
            "cnpj_orgao": cnpj,
            "uasg_codigo": (dados_compra.get("unidadeOrgao") or {}).get("codigoUnidade"),
            "uasg_nome": (dados_compra.get("unidadeOrgao") or {}).get("nomeUnidade"),
            "numero_compra": dados_compra.get("numeroCompra"),
            "ano_compra": dados_compra.get("anoCompra"),
            "modalidade_id": dados_compra.get("modalidadeId"),
            "modalidade_nome": dados_compra.get("modalidadeNome"),
            "processo": dados_compra.get("processo"),
            "numero_controle_pncp": dados_compra.get("numeroControlePNCP"),
        },
        "srp": dados_compra.get("srp"),
        "objeto": dados_compra.get("objetoCompra"),
        "valor_total_estimado": dados_compra.get("valorTotalEstimado"),
        "valor_total_homologado": dados_compra.get("valorTotalHomologado"),
        "quantidade_itens": len(itens_completos),
        "itens": itens_completos,
    }
