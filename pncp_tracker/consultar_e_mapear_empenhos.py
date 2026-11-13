from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .collector import baixar_dados_compra_pncp
from .contratos_empenhos import consultar_contratos_empenhos
from .empenho_details import enriquecer_empenhos_com_detalhes_portal
from .empenho_matcher import mapear_empenhos_por_item
from .empenho_portal import buscar_empenhos_portal_para_compra
from .url_parser import extrair_parametros_url


def consultar_e_mapear_empenhos(
    url_pncp: str,
    dados_compra: Optional[Dict[str, Any]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Busca as linhas da aba Contratos/Empenhos do PNCP e cruza pelos fornecedores."""
    if dados_compra is None:
        dados_compra = baixar_dados_compra_pncp(url_pncp)
    chaves = dados_compra.get("chaves_integracao", {})
    parametros_url = extrair_parametros_url(url_pncp)

    if on_progress is not None:
        on_progress("Consultando contratos e empenhos no PNCP.")
    empenhos = consultar_contratos_empenhos(
        chaves["cnpj_orgao"],
        parametros_url["ano"],
        parametros_url["sequencial"],
    )
    if on_progress is not None:
        on_progress(
            "Registros do PNCP recebidos: {}. Consultando detalhes no Portal da Transparência.".format(
                len(empenhos)
            )
        )
    empenhos_detalhados, erros_detalhamento = enriquecer_empenhos_com_detalhes_portal(empenhos)
    fonte_empenhos = "PNCP - aba Contratos/Empenhos"
    if not empenhos:
        if on_progress is not None:
            on_progress("PNCP sem registros; buscando empenhos por fornecedores homologados no Portal.")
        empenhos_detalhados, erros_fallback = buscar_empenhos_portal_para_compra(dados_compra)
        erros_detalhamento.extend(erros_fallback)
        fonte_empenhos = "Portal da Transparência - busca por fornecedores homologados"

    if on_progress is not None:
        on_progress("Relacionando empenhos aos itens e fornecedores homologados.")
    itens_mapeados = mapear_empenhos_por_item(dados_compra, empenhos_detalhados)
    quantidade_com_detalhes = sum(
        empenho.get("detalhesPortalTransparencia", {}).get("status") == "ok"
        for empenho in empenhos_detalhados
    )
    detalhes_nao_encontrados = sum(
        empenho.get("detalhesPortalTransparencia", {}).get("status") == "nao_encontrado"
        for empenho in empenhos_detalhados
    )
    status = (
        "sem_registros"
        if not empenhos_detalhados and not erros_detalhamento
        else "parcial"
        if erros_detalhamento or detalhes_nao_encontrados
        else "ok"
    )
    if on_progress is not None:
        on_progress(
            "Mapeamento concluído: {} empenhos; {} detalhes obtidos; {} itens relacionados.".format(
                len(empenhos_detalhados),
                quantidade_com_detalhes,
                len(itens_mapeados),
            )
        )

    return {
        "status": "parcial" if dados_compra.get("erros_resultados_itens") else status,
        "mensagem": (
            (
                "Consulta concluída; o PNCP não retornou registros e o Portal da Transparência "
                f"localizou {len(empenhos_detalhados)} empenho(s) por fornecedores homologados."
                if empenhos_detalhados
                else "Consulta concluída; PNCP e busca alternativa no Portal da Transparência não retornaram empenhos."
            )
            if not empenhos
            else (
                f"Registros coletados do PNCP. Detalhes do Portal obtidos para {quantidade_com_detalhes} "
                f"de {len(empenhos)} registros; {detalhes_nao_encontrados} documento(s) não foram localizados."
                if status == "parcial"
                else "Registros coletados do PNCP e complementados com o detalhamento e os itens publicados no Portal da Transparência."
            )
        ),
        "fontes": [fonte_empenhos, "Portal da Transparência - detalhes e itens do empenho"],
        "chaves_integracao": {
            "cnpj_orgao": chaves["cnpj_orgao"],
            "uasg_codigo": chaves.get("uasg_codigo"),
            "uasg_nome": chaves.get("uasg_nome"),
            "numero_compra": chaves["numero_compra"],
            "ano_compra": chaves["ano_compra"],
            "numero_controle_pncp": chaves["numero_controle_pncp"],
        },
        "objeto": dados_compra.get("objeto"),
        "quantidade_empenhos": len(empenhos_detalhados),
        "quantidade_empenhos_com_detalhes": quantidade_com_detalhes,
        "quantidade_empenhos_nao_encontrados": detalhes_nao_encontrados,
        "erros_detalhamento": erros_detalhamento,
        "erros_resultados_itens": dados_compra.get("erros_resultados_itens", []),
        "empenhos": empenhos_detalhados,
        "itens_mapeados": itens_mapeados,
    }
