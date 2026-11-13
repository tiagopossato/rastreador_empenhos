from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .portal_transparencia import (
    PortalTransparenciaBlockedError,
    consultar_detalhes_documento_despesa,
    consultar_documentos_despesa_favorecido,
)


def _digitos(valor: Any) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def buscar_empenhos_portal_para_compra(
    dados_compra: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Busca, entre os fornecedores homologados, empenhos da compra ausentes no PNCP."""
    chaves = dados_compra.get("chaves_integracao") or {}
    processo = _digitos(chaves.get("processo"))
    ano_compra = int(chaves.get("ano_compra"))
    anos = [str(ano_compra + deslocamento) for deslocamento in range(3)]
    fornecedores = {
        _digitos(resultado.get("niFornecedor") or resultado.get("cpfCnpjFornecedor"))
        for item in dados_compra.get("itens", [])
        for resultado in item.get("resultadosHomologados", []) or []
    }
    fornecedores.discard("")
    documentos: Dict[str, Dict[str, Any]] = {}
    erros: List[Dict[str, str]] = []

    for fornecedor in fornecedores:
        for ano in anos:
            try:
                encontrados = consultar_documentos_despesa_favorecido(
                    fornecedor, ano, None, fase=1
                )
            except Exception as exc:
                erros.append({
                    "fornecedor": fornecedor,
                    "ano": ano,
                    "erro": f"{type(exc).__name__}: {exc}",
                })
                if isinstance(exc, PortalTransparenciaBlockedError):
                    return [], erros
                continue
            for documento in encontrados:
                if _digitos(documento.get("numeroProcesso")) != processo or not processo:
                    continue
                codigo = str(documento.get("documento") or "")
                numero = str(documento.get("documentoResumido") or "")
                if codigo and numero and "NE" in numero:
                    documentos[numero] = documento

    registros: List[Dict[str, Any]] = []
    for numero, documento in documentos.items():
        codigo = str(documento["documento"])
        registro = {
            "numeroContratoEmpenho": numero,
            "niFornecedor": documento.get("codigoPessoa") or documento.get("codigoFavorecido"),
            "nomeRazaoSocialFornecedor": documento.get("nomeFavorecido"),
            "unidadeOrgao": {},
        }
        try:
            detalhe = consultar_detalhes_documento_despesa(codigo)
            processo_detalhe = _digitos(detalhe.get("numeroProcesso"))
            if processo_detalhe and processo_detalhe != processo:
                continue
            registro["niFornecedor"] = (
                detalhe.get("codigoFavorecido") or registro["niFornecedor"]
            )
            registro["nomeRazaoSocialFornecedor"] = (
                detalhe.get("nomeFavorecido") or registro["nomeRazaoSocialFornecedor"]
            )
            registro["detalhesPortalTransparencia"] = {
                "status": "ok",
                "codigoDocumento": codigo,
                "detalhamento": detalhe,
            }
        except Exception as exc:
            registro["detalhesPortalTransparencia"] = {
                "status": "erro",
                "codigoDocumento": codigo,
                "erro": f"{type(exc).__name__}: {exc}",
            }
            erros.append({"numero_empenho": numero, "codigo_documento": codigo,
                          "erro": f"{type(exc).__name__}: {exc}"})
            if isinstance(exc, PortalTransparenciaBlockedError):
                break
        registros.append(registro)
    return registros, erros
