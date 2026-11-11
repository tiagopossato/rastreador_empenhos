import re
from typing import Any, Dict, List, Tuple

from .portal_transparencia import (
    consultar_detalhes_documento_despesa,
    consultar_documentos_despesa_favorecido,
)


def enriquecer_empenhos_com_detalhes_portal(
    empenhos_pncp: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Adiciona detalhes e itens do Portal aos registros PNCP identificados como NE."""
    grupos: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    enriquecidos = [dict(empenho) for empenho in empenhos_pncp]
    erros: List[Dict[str, str]] = []

    for empenho in enriquecidos:
        numero = str(empenho.get("numeroContratoEmpenho") or "")
        unidade = str((empenho.get("unidadeOrgao") or {}).get("codigoUnidade") or "")
        data_assinatura = str(empenho.get("dataAssinatura") or "")
        if "NE" not in numero or not unidade:
            empenho["detalhesPortalTransparencia"] = {
                "status": "nao_consultado",
                "motivo": "Registro sem identificador de empenho ou unidade gestora.",
            }
            continue
        fornecedor = re.sub(r"\D", "", str(empenho.get("niFornecedor") or ""))
        if not fornecedor:
            empenho["detalhesPortalTransparencia"] = {
                "status": "nao_consultado",
                "motivo": "Registro sem CNPJ do fornecedor para consulta por favorecido.",
            }
            continue
        ano_empenho = re.match(r"^(\d{4})NE", numero, re.IGNORECASE)
        if not ano_empenho:
            empenho["detalhesPortalTransparencia"] = {
                "status": "nao_consultado",
                "motivo": "Não foi possível extrair o ano do número do empenho.",
            }
            continue
        ano = ano_empenho.group(1)
        grupos.setdefault((unidade, fornecedor, ano), []).append(empenho)

    documentos_por_grupo: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for grupo in grupos:
        unidade, fornecedor, ano = grupo
        try:
            documentos_por_grupo[grupo] = consultar_documentos_despesa_favorecido(
                fornecedor,
                ano,
                unidade,
                fase=1,
            )
        except Exception as exc:
            documentos_por_grupo[grupo] = []
            erros.append(
                {
                    "unidade_gestora": unidade,
                    "fornecedor": fornecedor,
                    "ano": ano,
                    "erro": f"{type(exc).__name__}: {exc}",
                }
            )

    for grupo, registros in grupos.items():
        documentos = documentos_por_grupo[grupo]
        por_numero = {
            str(documento.get("documentoResumido") or ""): documento
            for documento in documentos
        }
        for empenho in registros:
            numero = str(empenho.get("numeroContratoEmpenho") or "")
            documento = por_numero.get(numero)
            if documento is None:
                empenho["detalhesPortalTransparencia"] = {
                    "status": "nao_encontrado",
                    "mensagem": "Documento não localizado para o favorecido, ano e UG informados.",
                }
                continue

            codigo_documento = str(documento["documento"])
            try:
                empenho["detalhesPortalTransparencia"] = {
                    "status": "ok",
                    "codigoDocumento": codigo_documento,
                    "detalhamento": consultar_detalhes_documento_despesa(codigo_documento),
                }
            except Exception as exc:
                empenho["detalhesPortalTransparencia"] = {
                    "status": "erro",
                    "codigoDocumento": codigo_documento,
                    "erro": f"{type(exc).__name__}: {exc}",
                }
                erros.append(
                    {
                        "numero_empenho": numero,
                        "codigo_documento": codigo_documento,
                        "erro":                         f"{type(exc).__name__}: {exc}",
                    }
                )

    return enriquecidos, erros
