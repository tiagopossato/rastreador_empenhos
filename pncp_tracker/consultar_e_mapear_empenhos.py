from __future__ import annotations

import re
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Tuple

from .collector import baixar_dados_compra_pncp
from .contratos_empenhos import consultar_contratos_empenhos
from .empenho_details import (
    classificar_situacao_empenho,
    enriquecer_empenhos_com_detalhes_portal,
)
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

SITUACOES_EMPENHO = {
    "normal": "sem alteração",
    "reforcado": "reforçado(s)",
    "anulado": "anulado(s) parcialmente",
    "cancelado": "cancelado(s)",
    "alterado": "retificado(s)",
    "nao_localizado": "não localizado(s) no Portal",
    "nao_aplicavel": "sem nota de empenho",
    "indeterminado": "não verificado(s)",
}


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


def _descobrir_empenhos_portal(
    dados_compra: Dict[str, Any],
    empenhos_pncp: List[Dict[str, Any]],
    buscar_empenhos_portal: bool,
    on_progress: Optional[Callable[[str], None]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Procura empenhos fora da aba Contratos/Empenhos do PNCP somente quando solicitado."""
    if not buscar_empenhos_portal:
        if on_progress is not None:
            on_progress(
                "Busca por empenhos não registrados no PNCP desativada; "
                "usando a aba Contratos/Empenhos do PNCP."
            )
        return [], []
    return buscar_empenhos_portal_para_compra(
        dados_compra,
        on_progress=on_progress,
        detalhes_conhecidos=_detalhes_conhecidos(empenhos_pncp),
    )


def _notificar(callback: Optional[Callable[[str], None]], mensagem: str) -> None:
    if callback is not None:
        callback(mensagem)


def coletar_empenhos(
    url_pncp: str,
    dados_compra: Dict[str, Any],
    *,
    buscar_empenhos_portal: bool = False,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Etapa 1: coleta a aba Contratos/Empenhos do PNCP e, se solicitado, o Portal.

    O resultado é gravado em `dados_pregao.json` junto com o cabeçalho, os itens e os
    resultados homologados: nada do Portal da Transparência é consultado aqui além da
    descoberta opcional de empenhos por fornecedor.
    """
    chaves = dados_compra.get("chaves_integracao", {}) or {}
    parametros_url = extrair_parametros_url(url_pncp)
    limpar_cache_portal()

    _notificar(on_progress, "Consultando contratos e empenhos no PNCP.")
    empenhos_pncp = consultar_contratos_empenhos(
        chaves["cnpj_orgao"],
        parametros_url["ano"],
        parametros_url["sequencial"],
    )
    _notificar(
        on_progress,
        "Registros do PNCP recebidos: {}.".format(len(empenhos_pncp)),
    )
    empenhos_pncp = _classificar_empenhos_pncp(empenhos_pncp)

    empenhos_portal, erros_portal = _descobrir_empenhos_portal(
        dados_compra,
        empenhos_pncp,
        buscar_empenhos_portal,
        on_progress,
    )
    if buscar_empenhos_portal:
        _notificar(
            on_progress,
            "Portal da Transparência retornou {} empenho(s) para a compra.".format(
                len(empenhos_portal)
            ),
        )
    empenhos, quantidade_portal = _unir_empenhos(empenhos_pncp, empenhos_portal)
    return {
        "empenhos": empenhos,
        "busca_portal_realizada": bool(buscar_empenhos_portal),
        "quantidade_empenhos_pncp": len(empenhos_pncp),
        "quantidade_empenhos_portal": quantidade_portal,
        "erros": erros_portal,
    }


def anexar_coleta_empenhos(
    dados_compra: Dict[str, Any],
    coleta: Dict[str, Any],
) -> Dict[str, Any]:
    """Anexa ao snapshot da etapa 1 os empenhos coletados (conteúdo de dados_pregao.json)."""
    dados_compra["empenhos"] = list(coleta.get("empenhos") or [])
    dados_compra["coleta_empenhos"] = {
        "busca_portal_realizada": bool(coleta.get("busca_portal_realizada")),
        "quantidade_empenhos_pncp": int(coleta.get("quantidade_empenhos_pncp") or 0),
        "quantidade_empenhos_portal": int(coleta.get("quantidade_empenhos_portal") or 0),
        "erros": list(coleta.get("erros") or []),
    }
    return dados_compra


def enriquecer_e_mapear_empenhos(
    dados_compra: Dict[str, Any],
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Etapa 2: detalha cada empenho no Portal, classifica a situação e cruza com os itens."""
    coleta = dados_compra.get("coleta_empenhos") or {}
    empenhos_coletados = list(dados_compra.get("empenhos") or [])

    _notificar(
        on_progress,
        "Consultando detalhes de {} empenho(s) no Portal da Transparência.".format(
            len(empenhos_coletados)
        ),
    )
    empenhos_detalhados, erros_detalhamento = enriquecer_empenhos_com_detalhes_portal(
        empenhos_coletados
    )
    erros_detalhamento.extend(coleta.get("erros") or [])
    return montar_resultado_empenhos(
        dados_compra,
        empenhos_detalhados,
        coleta,
        erros_detalhamento,
        on_progress=on_progress,
    )


def montar_resultado_empenhos(
    dados_compra: Dict[str, Any],
    empenhos_detalhados: List[Dict[str, Any]],
    coleta: Optional[Dict[str, Any]] = None,
    erros_detalhamento: Optional[List[Dict[str, str]]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Monta o `dados_empenhos.json` a partir dos registros já detalhados.

    Separado do detalhamento para permitir remontar o resultado sem novas chamadas ao
    Portal — usado pela nova tentativa de itens pendentes.
    """
    coleta = coleta or {}
    erros_detalhamento = list(erros_detalhamento or [])
    chaves = dados_compra.get("chaves_integracao", {})
    quantidade_pncp = int(coleta.get("quantidade_empenhos_pncp") or 0)
    quantidade_portal_exclusivos = int(coleta.get("quantidade_empenhos_portal") or 0)
    busca_portal_realizada = bool(coleta.get("busca_portal_realizada"))
    documentos_descartados = [
        erro for erro in erros_detalhamento if erro.get("tipo") == "descartado"
    ]

    empenhos_detalhados = [
        {
            **empenho,
            "situacao_empenho": classificar_situacao_empenho(empenho),
        }
        for empenho in empenhos_detalhados
    ]

    _notificar(on_progress, "Relacionando empenhos aos itens e fornecedores homologados.")
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
    if quantidade_pncp:
        fontes.append("PNCP - aba Contratos/Empenhos")
    if quantidade_portal_exclusivos:
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
    situacoes = Counter(
        (empenho.get("situacao_empenho") or {}).get("situacao") or "indeterminado"
        for empenho in empenhos_detalhados
    )

    if not empenhos_detalhados:
        if busca_portal_realizada:
            mensagem = (
                "Consulta concluída; PNCP e Portal da Transparência não retornaram empenhos para a compra."
            )
        else:
            mensagem = (
                "Consulta concluída; a aba Contratos/Empenhos do PNCP não retornou empenhos "
                "para a compra."
            )
    else:
        mensagem = (
            "Empenhos encontrados: {} ({} no PNCP, {} exclusivos do Portal da Transparência). "
            "Detalhamento obtido para {}; {} documento(s) não localizado(s). "
            "{} empenho(s) de adesão posterior e {} com origem de órgão indefinida."
        ).format(
            len(empenhos_detalhados),
            quantidade_pncp,
            quantidade_portal_exclusivos,
            quantidade_com_detalhes,
            detalhes_nao_encontrados,
            quantidade_adesao,
            quantidade_indefinidos,
        )
        if situacoes:
            mensagem += " Situação dos registros: {}.".format(
                "; ".join(
                    "{} {}".format(quantidade, SITUACOES_EMPENHO.get(situacao, situacao))
                    for situacao, quantidade in sorted(situacoes.items())
                )
            )
    if not busca_portal_realizada:
        mensagem += " Busca por empenhos não registrados no PNCP não executada."
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
        "quantidade_empenhos_pncp": quantidade_pncp,
        "quantidade_empenhos_portal": quantidade_portal_exclusivos,
        "busca_portal_realizada": busca_portal_realizada,
        "situacoes_empenhos": dict(situacoes),
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


def consultar_e_mapear_empenhos(
    url_pncp: str,
    dados_compra: Optional[Dict[str, Any]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    *,
    buscar_empenhos_portal: bool = False,
) -> Dict[str, Any]:
    """Executa a coleta (etapa 1) quando necessário e o detalhamento/mapeamento (etapa 2).

    Quando o snapshot da etapa 1 já traz os empenhos — caso do fluxo do `report_service`,
    que grava `dados_pregao.json` antes de detalhar — nenhuma coleta é repetida.
    """
    if dados_compra is None:
        dados_compra = baixar_dados_compra_pncp(url_pncp)
    if not isinstance(dados_compra.get("empenhos"), list) or not isinstance(
        dados_compra.get("coleta_empenhos"), dict
    ):
        coleta = coletar_empenhos(
            url_pncp,
            dados_compra,
            buscar_empenhos_portal=buscar_empenhos_portal,
            on_progress=on_progress,
        )
        anexar_coleta_empenhos(dados_compra, coleta)
    return enriquecer_e_mapear_empenhos(dados_compra, on_progress=on_progress)
