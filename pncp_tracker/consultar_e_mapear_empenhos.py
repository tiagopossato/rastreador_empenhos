from __future__ import annotations

from typing import Any, Dict, List, Optional

from .collector import baixar_dados_compra_pncp
from .contratos_empenhos import consultar_contratos_empenhos
from .empenho_details import enriquecer_empenhos_com_detalhes_portal
from .empenho_matcher import mapear_empenhos_por_item
from .url_parser import extrair_parametros_url


def consultar_e_mapear_empenhos(
    url_pncp: str,
    dados_compra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Busca as linhas da aba Contratos/Empenhos do PNCP e cruza pelos fornecedores."""
    if dados_compra is None:
        dados_compra = baixar_dados_compra_pncp(url_pncp)
    chaves = dados_compra.get("chaves_integracao", {})
    parametros_url = extrair_parametros_url(url_pncp)

    empenhos = consultar_contratos_empenhos(
        chaves["cnpj_orgao"],
        parametros_url["ano"],
        parametros_url["sequencial"],
    )
    empenhos_detalhados, erros_detalhamento = enriquecer_empenhos_com_detalhes_portal(empenhos)

    itens_mapeados = mapear_empenhos_por_item(dados_compra, empenhos_detalhados)
    quantidade_com_detalhes = sum(
        empenho.get("detalhesPortalTransparencia", {}).get("status") == "ok"
        for empenho in empenhos_detalhados
    )
    detalhes_nao_encontrados = sum(
        empenho.get("detalhesPortalTransparencia", {}).get("status") == "nao_encontrado"
        for empenho in empenhos_detalhados
    )
    status = "sem_registros" if not empenhos else "parcial" if erros_detalhamento or detalhes_nao_encontrados else "ok"

    return {
        "status": status,
        "mensagem": (
            "Consulta concluída; a API do PNCP não retornou contratos/empenhos para a contratação."
            if not empenhos
            else (
                f"Registros coletados do PNCP. Detalhes do Portal obtidos para {quantidade_com_detalhes} "
                f"de {len(empenhos)} registros; {detalhes_nao_encontrados} documento(s) não foram localizados."
                if status == "parcial"
                else "Registros coletados do PNCP e complementados com o detalhamento e os itens publicados no Portal da Transparência."
            )
        ),
        "fontes": ["PNCP - aba Contratos/Empenhos", "Portal da Transparência - detalhes e itens do empenho"],
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
        "empenhos": empenhos_detalhados,
        "itens_mapeados": itens_mapeados,
    }
