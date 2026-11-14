import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from .api_client import buscar_dados_compra, buscar_resultados_item, listar_itens
from .constants import DEFAULT_PAGE_SIZE
from .url_parser import extrair_parametros_url

MAX_WORKERS_RESULTADOS = 6


def _chave_cache(controle: Any, atualizacao: Any) -> str:
    """Identifica o snapshot da compra para reutilizar a coleta quando nada mudou."""
    if not controle or not atualizacao:
        return ""
    return f"{controle}|{atualizacao}"


def _buscar_resultados(
    cnpj: str,
    ano: str,
    sequencial: str,
    itens: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Consulta os resultados homologados em paralelo, preservando a ordem dos itens."""
    itens_com_numero = [item for item in itens if item.get("numeroItem") is not None]

    def consultar(item: Dict[str, Any]) -> Dict[str, Any]:
        numero = item.get("numeroItem")
        try:
            item["resultadosHomologados"] = buscar_resultados_item(cnpj, ano, sequencial, numero)
        except Exception as exc:
            item["resultadosHomologados"] = []
            item["erroResultadosHomologados"] = "{}: {}".format(type(exc).__name__, exc)
        return item

    if not itens_com_numero:
        return itens
    with ThreadPoolExecutor(max_workers=MAX_WORKERS_RESULTADOS) as pool:
        list(pool.map(consultar, itens_com_numero))
    return itens


def baixar_dados_compra_pncp(
    url_pncp: str,
    on_progress: Optional[Callable[[str], None]] = None,
    dados_anteriores: Optional[Dict[str, Any]] = None,
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

    controle = dados_compra.get("numeroControlePNCP")
    atualizacao = dados_compra.get("dataAtualizacaoGlobal")
    chave_cache = _chave_cache(controle, atualizacao)
    if (
        dados_anteriores
        and chave_cache
        and dados_anteriores.get("chave_cache") == chave_cache
        and isinstance(dados_anteriores.get("itens"), list)
    ):
        if on_progress is not None:
            on_progress(
                "PNCP sem alteração desde a última execução; reutilizando itens e resultados já coletados."
            )
        reutilizado = dict(dados_anteriores)
        reutilizado["cache_reutilizado"] = True
        return reutilizado

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

        quantidade_com_numero = sum(
            1 for item in lote_itens if item.get("numeroItem") is not None
        )
        if on_progress is not None:
            on_progress(
                "Página {}: consultando resultados homologados de {} item(ns) em paralelo.".format(
                    pagina, quantidade_com_numero
                )
            )
        _buscar_resultados(cnpj, ano, sequencial, lote_itens)

        for item in lote_itens:
            if item.get("erroResultadosHomologados"):
                erro = {
                    "numero_item": item.get("numeroItem"),
                    "erro": item["erroResultadosHomologados"],
                }
                erros_resultados_itens.append(erro)
                if on_progress is not None:
                    on_progress(
                        "Falha ao consultar resultados homologados do item {}: {}".format(
                            erro["numero_item"], erro["erro"]
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
        "data_atualizacao_global": atualizacao,
        "chave_cache": chave_cache,
    }
