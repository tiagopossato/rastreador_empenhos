from datetime import datetime
from typing import Any, Dict, List, Tuple

from .portal_transparencia import consultar_detalhes_documento_despesa, consultar_documentos_despesa


def _data_portal(data: str) -> str:
    """Converte a data ISO da API do PNCP para DD/MM/AAAA."""
    return datetime.strptime(data[:10], "%Y-%m-%d").strftime("%d/%m/%Y")


def enriquecer_empenhos_com_detalhes_portal(
    empenhos_pncp: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Adiciona detalhes e itens do Portal aos registros PNCP identificados como NE."""
    grupos: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    enriquecidos = [dict(empenho) for empenho in empenhos_pncp]
    erros: List[Dict[str, str]] = []

    for empenho in enriquecidos:
        numero = str(empenho.get("numeroContratoEmpenho") or "")
        unidade = str((empenho.get("unidadeOrgao") or {}).get("codigoUnidade") or "")
        data_assinatura = str(empenho.get("dataAssinatura") or "")
        if "NE" not in numero or not unidade or not data_assinatura:
            empenho["detalhesPortalTransparencia"] = {
                "status": "nao_consultado",
                "motivo": "Registro sem identificador de empenho, unidade ou data de emissão.",
            }
            continue
        grupos.setdefault((unidade, _data_portal(data_assinatura)), []).append(empenho)

    documentos_por_grupo: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for grupo in grupos:
        unidade, data_emissao = grupo
        try:
            documentos_por_grupo[grupo] = consultar_documentos_despesa(unidade, data_emissao, fase=1)
        except Exception as exc:
            documentos_por_grupo[grupo] = []
            erros.append(
                {
                    "unidade_gestora": unidade,
                    "data_emissao": data_emissao,
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
                    "mensagem": "Documento não localizado para a UG e data informadas.",
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
                        "erro": f"{type(exc).__name__}: {exc}",
                    }
                )

    return enriquecidos, erros
