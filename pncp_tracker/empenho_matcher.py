from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def _normalizar_cnpj(valor: Any) -> str:
    """Remove pontuação e mantém apenas os dígitos do CNPJ."""
    if valor is None:
        return ""
    return str(valor).replace(".", "").replace("/", "").replace("-", "").strip()


def _numero_item_empenho(descricao: Any) -> Optional[int]:
    """Extrai o número do item de compra descrito no item do empenho."""
    if not descricao:
        return None
    match = re.search(r"\bitem\s+compra\s*:\s*0*(\d+)\b", str(descricao), re.IGNORECASE)
    return int(match.group(1)) if match else None


def mapear_empenhos_por_item(dados_compra: Dict[str, Any], empenhos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Relaciona empenhos ao item PNCP pelo número de item indicado no documento de despesa."""
    itens = dados_compra.get("itens", [])
    itens_origem = {str(item.get("numeroItem")): item for item in itens}
    empenhos_por_item: Dict[int, List[Dict[str, Any]]] = {}
    empenhos_sem_item_por_fornecedor: Dict[str, List[Dict[str, Any]]] = {}

    for empenho in empenhos:
        numero_empenho = empenho.get("numeroContratoEmpenho")
        detalhes = empenho.get("detalhesPortalTransparencia", {}).get("detalhamento", {})
        itens_despesa = detalhes.get("itensEmpenho", [])
        fornecedor = _normalizar_cnpj(
            detalhes.get("codigoFavorecido") or empenho.get("niFornecedor")
        )
        possui_item_identificado = False

        for item_despesa in itens_despesa:
            numero_item = _numero_item_empenho(item_despesa.get("descricao"))
            if numero_item is None:
                continue
            possui_item_identificado = True
            empenhos_por_item.setdefault(numero_item, []).append(
                {
                    "numero_empenho": numero_empenho,
                    "data_emissao": detalhes.get("data"),
                    "valor_empenhado": item_despesa.get("valorAtual"),
                    "fornecedor_cnpj": fornecedor,
                    "nome_fornecedor": detalhes.get("nomeFavorecido") or empenho.get("nomeRazaoSocialFornecedor"),
                    "item_despesa": item_despesa,
                }
            )

        if not possui_item_identificado and fornecedor:
            empenhos_sem_item_por_fornecedor.setdefault(fornecedor, []).append(
                {
                    "numero_empenho": numero_empenho,
                    "data_emissao": detalhes.get("data"),
                    "valor_empenhado": detalhes.get("valor"),
                }
            )

    resultados: List[Dict[str, Any]] = []
    for item in itens:
        numero_item = item.get("numeroItem")
        try:
            chave_item = int(numero_item)
        except (TypeError, ValueError):
            chave_item = -1

        resultados_item = item.get("resultadosHomologados", []) or []
        cnpjs_vencedores = {
            _normalizar_cnpj(resultado.get("niFornecedor") or resultado.get("cpfCnpjFornecedor"))
            for resultado in resultados_item
        }
        cnpjs_vencedores.discard("")
        empenhos_sem_item = [
            empenho
            for cnpj in cnpjs_vencedores
            for empenho in empenhos_sem_item_por_fornecedor.get(cnpj, [])
        ]
        empenhos_do_numero_item = empenhos_por_item.get(chave_item, [])
        empenhos_vinculados = [
            empenho for empenho in empenhos_do_numero_item
            if empenho["fornecedor_cnpj"] in cnpjs_vencedores
        ]
        empenhos_fornecedor_divergente = [
            empenho for empenho in empenhos_do_numero_item
            if empenho["fornecedor_cnpj"] not in cnpjs_vencedores
        ]
        item_origem = itens_origem.get(str(numero_item), {})
        quantidade_homologada = sum(
            float(resultado.get("quantidadeHomologada") or 0)
            for resultado in resultados_item
        )
        valor_total_homologado = sum(
            float(resultado.get("valorTotalHomologado") or 0)
            for resultado in resultados_item
        )

        item_match = {
            "numero_item": numero_item,
            "descricao": item.get("descricao"),
            "unidade_medida": item_origem.get("unidadeMedida"),
            "quantidade_licitada": item_origem.get("quantidade"),
            "quantidade_homologada": quantidade_homologada,
            "valor_unitario_estimado": item_origem.get("valorUnitarioEstimado"),
            "valor_total_estimado": item_origem.get("valorTotal") or item_origem.get("valorTotalEstimado"),
            "valor_unitario_homologado": (
                valor_total_homologado / quantidade_homologada
                if quantidade_homologada
                else None
            ),
            "valor_total_homologado": valor_total_homologado,
            "resultados": resultados_item,
            "empenhos": empenhos_vinculados,
            "empenhos_item_sem_fornecedor_compativel": empenhos_fornecedor_divergente,
            "empenhos_fornecedor_sem_item_identificado": empenhos_sem_item,
            "status": (
                "mapeado_por_numero_item"
                if empenhos_vinculados
                else "item_identificado_fornecedor_divergente"
                if empenhos_fornecedor_divergente
                else "empenhos_do_fornecedor_sem_item_identificado"
                if empenhos_sem_item
                else "sem_empenho_mapeado"
            ),
        }

        resultados.append(item_match)

    return resultados
