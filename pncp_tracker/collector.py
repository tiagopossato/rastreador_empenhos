import re
from typing import Callable, Optional

from .api_client import buscar_dados_compra, buscar_resultados_item, listar_itens
from .constants import DEFAULT_PAGE_SIZE
from .url_parser import extrair_parametros_url


def baixar_dados_compra_pncp(
    url_pncp: str,
    on_progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """Consulta os dados gerais da compra, os itens e os resultados homologados."""
    params = extrair_parametros_url(url_pncp)
    cnpj = params["cnpj"]
    ano = params["ano"]
    sequencial = params["sequencial"]

    dados_compra = buscar_dados_compra(cnpj, ano, sequencial)
    if not isinstance(dados_compra, dict):
        raise ValueError("Resposta inválida ao consultar o cabeçalho da compra no PNCP.")
    numero_compra = str(dados_compra.get("numeroCompra") or "").strip()
    ano_compra = str(dados_compra.get("anoCompra") or "").strip()
    if not numero_compra.isdigit() or not re.fullmatch(r"\d{4}", ano_compra):
        raise ValueError(
            "Cabeçalho da compra incompleto: número e ano da compra são obrigatórios."
        )
    itens_completos = []
    erros_resultados_itens = []
    pagina = 1

    while True:
        if on_progress is not None:
            on_progress("Consultando página {} de itens no PNCP.".format(pagina))
        lote_itens = listar_itens(cnpj, ano, sequencial, pagina=pagina, tamanho_pagina=DEFAULT_PAGE_SIZE)

        if not lote_itens:
            if on_progress is not None and pagina == 1:
                on_progress("O PNCP não retornou itens para esta compra.")
            break

        for indice, item in enumerate(lote_itens, start=1):
            num_item = item.get("numeroItem")
            if num_item is None:
                itens_completos.append(item)
                continue

            if on_progress is not None and (indice == 1 or indice % 10 == 0 or indice == len(lote_itens)):
                on_progress(
                    "Página {}: consultando resultados homologados do item {} de {}.".format(
                        pagina, indice, len(lote_itens)
                    )
                )
            try:
                item["resultadosHomologados"] = buscar_resultados_item(cnpj, ano, sequencial, num_item)
            except Exception as exc:
                item["resultadosHomologados"] = []
                erro = {
                    "numero_item": num_item,
                    "erro": "{}: {}".format(type(exc).__name__, exc),
                }
                item["erroResultadosHomologados"] = erro["erro"]
                erros_resultados_itens.append(erro)
                if on_progress is not None:
                    on_progress(
                        "Falha ao consultar resultados homologados do item {}: {}".format(
                            num_item, erro["erro"]
                        )
                    )

            itens_completos.append(item)

        if on_progress is not None:
            on_progress(
                "Página {} concluída: {} itens coletados.".format(
                    pagina, len(itens_completos)
                )
            )
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
        "erros_resultados_itens": erros_resultados_itens,
    }
