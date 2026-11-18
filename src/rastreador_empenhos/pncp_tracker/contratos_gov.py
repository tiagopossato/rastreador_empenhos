from __future__ import annotations

import re
import threading
from typing import Any, Dict, List, Optional

import requests

from .constants import DEFAULT_TIMEOUT
from .rate_limit import CONTRATOS_GOV_LIMITER

CONTRATOS_GOV_BASE_URL = "https://contratos.comprasnet.gov.br"

_cache: Dict[str, Any] = {}
_cache_lock = threading.Lock()

def _digitos(valor: Any) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def _numero(valor: Any) -> Optional[float]:
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace("R$", "").replace("\xa0", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def normalizar_numero_compra(valor: Any) -> str:
    """Compara números de compra sem zeros à esquerda (00404 == 404)."""
    digitos = _digitos(valor)
    return digitos.lstrip("0") or digitos


def _requisitar(caminho: str) -> Any:
    """GET tolerante a falhas; devolve None em qualquer erro, sem interromper o relatório."""
    with _cache_lock:
        if caminho in _cache:
            return _cache[caminho]

    CONTRATOS_GOV_LIMITER.aguardar()
    try:
        response = requests.get(
            f"{CONTRATOS_GOV_BASE_URL}{caminho}",
            headers={"Accept": "application/json"},
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code >= 500 or response.status_code == 429:
            return None
        if response.status_code != 200:
            with _cache_lock:
                _cache[caminho] = None
            return None
        dados = response.json()
    except (requests.RequestException, ValueError):
        return None

    with _cache_lock:
        _cache[caminho] = dados
    return dados


def chave_compra(registro: Dict[str, Any]) -> Dict[str, str]:
    """Extrai a identidade da compra a partir do registro de contrato/empenho."""
    unidade_compra = _digitos(registro.get("unidade_compra"))
    modalidade = _digitos(registro.get("codigo_modalidade"))
    numero = ""
    ano = ""
    licitacao = str(registro.get("licitacao_numero") or "")
    partes = re.findall(r"\d+", licitacao)
    if len(partes) >= 2:
        numero = normalizar_numero_compra(partes[0])
        ano = partes[1]
    elif len(partes) == 1:
        numero = normalizar_numero_compra(partes[0])

    if not (unidade_compra and numero and ano):
        compacta = _digitos(registro.get("informacao_complementar"))
        match = re.match(r"^(\d{6})(\d{2})(\d{5})(\d{4})", compacta)
        if match:
            unidade_compra = unidade_compra or match.group(1)
            modalidade = modalidade or match.group(2)
            numero = numero or normalizar_numero_compra(match.group(3))
            ano = ano or match.group(4)

    return {
        "unidade_compra": unidade_compra,
        "modalidade": modalidade,
        "numero": numero,
        "ano": ano,
    }


def consultar_empenho_por_ug_numero(
    unidade_gestora: Any,
    numero_empenho: Any,
) -> Optional[Dict[str, Any]]:
    """Busca o empenho pela UG emitente e pelo número, retornando o primeiro registro."""
    ug = _digitos(unidade_gestora)
    numero = re.sub(r"[^A-Za-z0-9]", "", str(numero_empenho or ""))
    if not ug or not numero:
        return None
    dados = _requisitar(f"/api/contrato/ugorigem/{ug}/numeroano/{numero}")
    if isinstance(dados, dict):
        return dados
    if isinstance(dados, list) and dados and isinstance(dados[0], dict):
        return dados[0]
    return None


def consultar_itens(id_contrato: Any) -> List[Dict[str, Any]]:
    """Lista os itens de um contrato ou empenho pelo seu identificador."""
    identificador = _digitos(id_contrato)
    if not identificador:
        return []
    dados = _requisitar(f"/api/contrato/{identificador}/itens")
    return [item for item in dados if isinstance(item, dict)] if isinstance(dados, list) else []


def _procurar_codigo_unidade(no: Any) -> str:
    """Localiza o código da unidade gestora de origem dentro do contratante."""
    if isinstance(no, dict):
        for chave in ("unidade_gestora_origem", "unidade_gestora"):
            valor = no.get(chave)
            if isinstance(valor, dict) and valor.get("codigo"):
                return _digitos(valor.get("codigo"))
        for valor in no.values():
            encontrado = _procurar_codigo_unidade(valor)
            if encontrado:
                return encontrado
    elif isinstance(no, list):
        for valor in no:
            encontrado = _procurar_codigo_unidade(valor)
            if encontrado:
                return encontrado
    return ""


def coletar_dados_empenho(
    unidade_gestora: Any,
    numero_empenho: Any,
) -> Optional[Dict[str, Any]]:
    """Reúne identidade da compra, itens e valores do empenho na Contratos.gov.br."""
    registro = consultar_empenho_por_ug_numero(unidade_gestora, numero_empenho)
    if registro is None:
        return None
    itens = consultar_itens(registro.get("id"))
    return {
        "id": registro.get("id"),
        "numero": registro.get("numero"),
        "tipo": registro.get("tipo"),
        "unidade_compra": registro.get("unidade_compra"),
        "ug_emitente": _procurar_codigo_unidade(registro.get("contratante"))
        or _digitos(registro.get("unidade_origem_codigo"))
        or _digitos(registro.get("unidade_codigo")),
        "chave_compra": chave_compra(registro),
        "valor_global": _numero(registro.get("valor_global")),
        "itens": [
            {
                "numero_item_compra": item.get("numero_item_compra"),
                "quantidade": _numero(item.get("quantidade")),
                "valor_unitario": _numero(item.get("valorunitario")),
                "valor_total": _numero(item.get("valortotal")),
                "descricao": item.get("catmatseritem_id"),
                "descricao_complementar": item.get("descricao_complementar"),
            }
            for item in itens
        ],
    }
