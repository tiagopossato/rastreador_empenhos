from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from .collector import baixar_dados_compra_pncp
from .contratos_empenhos import consultar_contratos_empenhos
from .empenho_details import enriquecer_empenhos_com_detalhes_portal
from .empenho_matcher import mapear_empenhos_por_item
from .empenho_portal import (
    ORIGEM_ORGAN_ORIGINAL,
    buscar_empenhos_portal_para_compra,
    classificar_origem_organ,
    consome_saldo,
    numero_decimal,
    resumir_empenho,
)
from .portal_transparencia import limpar_cache as limpar_cache_portal
from .url_parser import extrair_parametros_url

ORIGEM_PNCP = "pncp"


def _classificar_empenhos_pncp(empenhos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Marca vínculo, adesão e consumo de saldo nos registros vindos do PNCP.

    Decisão de projeto: o PNCP nem sempre envia `frutoAdesao`. A ausência da flag é tratada
    como **não adesão** — o empenho segue o fluxo normal e consome a quantidade homologada —
    em vez de ficar como origem indefinida. A ausência fica registrada para auditoria.
    """
    classificados: List[Dict[str, Any]] = []
    for empenho in empenhos:
        registro = dict(empenho)
        registro.setdefault("origem", ORIGEM_PNCP)
        registro["vinculo"] = "pncp"
        registro["confianca"] = "alta"
        unidade = (registro.get("unidadeOrgao") or {}).get("codigoUnidade")
        registro["fruto_adesao"] = registro.get("frutoAdesao")
        if registro.get("frutoAdesao") is None:
            registro["origem_organ"] = ORIGEM_ORGAN_ORIGINAL
            registro["flag_adesao_ausente"] = True
        else:
            registro["origem_organ"] = classificar_origem_organ(
                registro.get("frutoAdesao"), None, unidade
            )
        registro["consome_saldo"] = consome_saldo(registro["origem_organ"])
        classificados.append(registro)
    return classificados


def _chave_documento(valor: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(valor or ""))


def _chave_empenho(empenho: Dict[str, Any]) -> str:
    """Identifica o empenho pelo documento completo (UG+gestão+número).

    O número resumido (AAAANE999999) não é único entre unidades gestoras, por isso a
    chave usa o código do documento e, na ausência dele, prefixa a UG.
    """
    detalhes = empenho.get("detalhesPortalTransparencia") or {}
    codigo = _chave_documento(detalhes.get("codigoDocumento"))
    if codigo:
        return codigo
    unidade = _chave_documento((empenho.get("unidadeOrgao") or {}).get("codigoUnidade"))
    return f"{unidade}{resumir_empenho(empenho.get('numeroContratoEmpenho'))}"


def _detalhes_conhecidos(empenhos: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Mapeia código do documento ao detalhamento já obtido, evitando consultas repetidas."""
    mapa: Dict[str, Dict[str, Any]] = {}
    for empenho in empenhos:
        detalhes = empenho.get("detalhesPortalTransparencia") or {}
        codigo = _chave_documento(detalhes.get("codigoDocumento"))
        detalhamento = detalhes.get("detalhamento")
        if codigo and isinstance(detalhamento, dict):
            mapa[codigo] = detalhamento
    return mapa


def _chave_secundaria(empenho: Dict[str, Any]) -> str:
    """Chave UG+número, usada quando só um dos lados traz o documento completo."""
    unidade = _chave_documento((empenho.get("unidadeOrgao") or {}).get("codigoUnidade"))
    return f"{unidade}{resumir_empenho(empenho.get('numeroContratoEmpenho'))}"


def _unir_empenhos(
    empenhos_pncp: List[Dict[str, Any]],
    empenhos_portal: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int]:
    """Une as fontes sem duplicar empenhos, preservando os dados do PNCP quando existirem."""
    unidos: List[Dict[str, Any]] = []
    por_chave: Dict[str, Dict[str, Any]] = {}
    por_secundaria: Dict[str, Dict[str, Any]] = {}

    for empenho in empenhos_pncp:
        registro = dict(empenho)
        registro.setdefault("origem", ORIGEM_PNCP)
        chave = _chave_empenho(registro)
        if chave and chave in por_chave:
            continue
        unidos.append(registro)
        if chave:
            por_chave[chave] = registro
        secundaria = _chave_secundaria(registro)
        if secundaria:
            por_secundaria.setdefault(secundaria, registro)

    adicionados = 0
    for empenho in empenhos_portal:
        chave = _chave_empenho(empenho)
        existente = por_chave.get(chave) if chave else None
        if existente is None:
            existente = por_secundaria.get(_chave_secundaria(empenho))
        if existente is None:
            unidos.append(dict(empenho))
            if chave:
                por_chave[chave] = unidos[-1]
            adicionados += 1
            continue

        existente["encontrado_tambem_no_portal"] = True
        detalhes_existentes = existente.get("detalhesPortalTransparencia") or {}
        if detalhes_existentes.get("status") != "ok":
            existente["detalhesPortalTransparencia"] = empenho.get(
                "detalhesPortalTransparencia"
            )
        for campo in ("niFornecedor", "nomeRazaoSocialFornecedor"):
            if not existente.get(campo) and empenho.get(campo):
                existente[campo] = empenho[campo]
        unidade_existente = existente.get("unidadeOrgao") or {}
        unidade_portal = empenho.get("unidadeOrgao") or {}
        if not unidade_existente.get("codigoUnidade") and unidade_portal.get("codigoUnidade"):
            existente["unidadeOrgao"] = unidade_portal
        for campo in ("dadosContratosGov", "origem_organ", "consome_saldo", "confianca", "vinculo"):
            if not existente.get(campo) and empenho.get(campo):
                existente[campo] = empenho[campo]
        if existente.get("fruto_adesao") is None:
            existente["fruto_adesao"] = empenho.get("fruto_adesao")
        if empenho.get("flag_adesao_ausente"):
            existente["flag_adesao_ausente"] = True

    return unidos, adicionados


def consultar_e_mapear_empenhos(
    url_pncp: str,
    dados_compra: Optional[Dict[str, Any]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Coleta empenhos no PNCP e no Portal da Transparência e cruza com os itens homologados."""
    if dados_compra is None:
        dados_compra = baixar_dados_compra_pncp(url_pncp)
    chaves = dados_compra.get("chaves_integracao", {})
    parametros_url = extrair_parametros_url(url_pncp)
    limpar_cache_portal()

    if on_progress is not None:
        on_progress("Consultando contratos e empenhos no PNCP.")
    empenhos_pncp = consultar_contratos_empenhos(
        chaves["cnpj_orgao"],
        parametros_url["ano"],
        parametros_url["sequencial"],
    )
    if on_progress is not None:
        on_progress(
            "Registros do PNCP recebidos: {}. Consultando detalhes no Portal da Transparência.".format(
                len(empenhos_pncp)
            )
        )
    empenhos_pncp, erros_detalhamento = enriquecer_empenhos_com_detalhes_portal(empenhos_pncp)
    empenhos_pncp = _classificar_empenhos_pncp(empenhos_pncp)

    empenhos_portal, erros_busca_portal = buscar_empenhos_portal_para_compra(
        dados_compra,
        on_progress=on_progress,
        detalhes_conhecidos=_detalhes_conhecidos(empenhos_pncp),
    )
    erros_detalhamento.extend(erros_busca_portal)
    documentos_descartados = [
        erro for erro in erros_detalhamento if erro.get("tipo") == "descartado"
    ]

    if on_progress is not None:
        on_progress(
            "Portal da Transparência retornou {} empenho(s) para a compra.".format(
                len(empenhos_portal)
            )
        )
    empenhos_detalhados, quantidade_portal_exclusivos = _unir_empenhos(
        empenhos_pncp, empenhos_portal
    )

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
    fontes = []
    if empenhos_pncp:
        fontes.append("PNCP - aba Contratos/Empenhos")
    origens_portal = sorted(
        {
            empenho.get("origem")
            for empenho in empenhos_portal
            if empenho.get("origem")
        }
    )
    if origens_portal:
        fontes.append("Portal da Transparência - descoberta por processo/favorecido")
    fontes.append("Portal da Transparência - detalhes e itens do empenho")
    if any(empenho.get("dadosContratosGov") for empenho in empenhos_detalhados):
        fontes.append("Contratos.gov.br - identidade da compra e itens")

    if on_progress is not None:
        on_progress(
            "Mapeamento concluído: {} empenhos; {} detalhes obtidos; {} itens relacionados.".format(
                len(empenhos_detalhados),
                quantidade_com_detalhes,
                len(itens_mapeados),
            )
        )

    quantidade_adesao = sum(
        1
        for empenho in empenhos_detalhados
        if empenho.get("origem_organ") == "adesao_posterior"
    )
    quantidade_indefinidos = sum(
        1
        for empenho in empenhos_detalhados
        if empenho.get("origem_organ") == "indefinido"
    )
    valor_empenhado_adesao = sum(
        numero_decimal(linha.get("item_despesa", {}).get("valorAtual"))
        or numero_decimal(linha.get("valor_empenhado"))
        or 0.0
        for item in itens_mapeados
        for linha in item.get("empenhos", [])
        if linha.get("origem_organ") == "adesao_posterior"
    )

    if not empenhos_detalhados:
        mensagem = (
            "Consulta concluída; PNCP e Portal da Transparência não retornaram empenhos para a compra."
        )
    else:
        mensagem = (
            "Empenhos encontrados: {} ({} no PNCP, {} exclusivos do Portal da Transparência). "
            "Detalhamento obtido para {}; {} documento(s) não localizado(s). "
            "{} empenho(s) de adesão posterior e {} com origem de órgão indefinida."
        ).format(
            len(empenhos_detalhados),
            len(empenhos_pncp),
            quantidade_portal_exclusivos,
            quantidade_com_detalhes,
            detalhes_nao_encontrados,
            quantidade_adesao,
            quantidade_indefinidos,
        )
    if any("BlockedError" in str(erro.get("erro", "")) for erro in erros_detalhamento):
        mensagem += (
            " O Portal da Transparência bloqueou o token por limite de acesso; "
            "novas consultas ficaram suspensas até o desbloqueio."
        )
    if documentos_descartados:
        mensagem += (
            " {} documento(s) do(s) fornecedor(es) homologado(s) descartado(s) por falta de "
            "vínculo com a compra."
        ).format(len(documentos_descartados))

    return {
        "status": "parcial" if dados_compra.get("erros_resultados_itens") else status,
        "mensagem": mensagem,
        "fontes": fontes,
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
        "quantidade_empenhos_pncp": len(empenhos_pncp),
        "quantidade_empenhos_portal": quantidade_portal_exclusivos,
        "quantidade_empenhos_com_detalhes": quantidade_com_detalhes,
        "quantidade_empenhos_nao_encontrados": detalhes_nao_encontrados,
        "quantidade_empenhos_confirmados": sum(
            1 for empenho in empenhos_detalhados if empenho.get("consome_saldo", True)
        ),
        "quantidade_empenhos_adesao": quantidade_adesao,
        "quantidade_empenhos_indefinidos": quantidade_indefinidos,
        "valor_empenhado_adesao": round(valor_empenhado_adesao, 2),
        "quantidade_documentos_descartados": len(documentos_descartados),
        "empenhos_nao_confirmados": documentos_descartados,
        "erros_detalhamento": erros_detalhamento,
        "erros_resultados_itens": dados_compra.get("erros_resultados_itens", []),
        "empenhos": empenhos_detalhados,
        "itens_mapeados": itens_mapeados,
    }
