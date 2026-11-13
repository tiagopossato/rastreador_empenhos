import requests

from .constants import DEFAULT_TIMEOUT, PNCP_API_CONSULTA, PNCP_API_PNCP


def _buscar_json_robusto(urls: list[str], timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Tenta as URLs informadas e retorna o primeiro JSON válido."""
    for url in urls:
        try:
            response = requests.get(url, timeout=timeout)
            if response.status_code == 204:
                raise requests.RequestException("Endpoint PNCP respondeu 204 sem dados de compra.")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not payload:
                raise ValueError("Endpoint PNCP não retornou um cabeçalho JSON válido.")
            return payload
        except (requests.RequestException, ValueError):
            continue

    raise requests.RequestException(f"Nenhum endpoint respondeu com JSON válido: {urls}")


def buscar_dados_compra(cnpj: str, ano: str, sequencial: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Busca o cabeçalho da compra no endpoint de consulta do PNCP."""
    url = f"{PNCP_API_CONSULTA}/{cnpj}/compras/{ano}/{sequencial}"
    return _buscar_json_robusto([url], timeout=timeout)


def listar_itens(cnpj: str, ano: str, sequencial: str, pagina: int = 1, tamanho_pagina: int = 50):
    """Busca um lote de itens da compra."""
    url = f"{PNCP_API_PNCP}/{cnpj}/compras/{ano}/{sequencial}/itens"
    response = requests.get(
        url,
        params={"pagina": pagina, "tamanhoPagina": tamanho_pagina},
        timeout=DEFAULT_TIMEOUT,
    )

    if response.status_code == 204:
        return []

    response.raise_for_status()
    return response.json()


def buscar_resultados_item(cnpj: str, ano: str, sequencial: str, numero_item: int):
    """Busca os vencedores e valores homologados de um item."""
    url = f"{PNCP_API_PNCP}/{cnpj}/compras/{ano}/{sequencial}/itens/{numero_item}/resultados"
    response = requests.get(url, timeout=DEFAULT_TIMEOUT)

    if response.status_code == 204:
        return []

    response.raise_for_status()
    resultados = response.json()
    if not isinstance(resultados, list):
        raise ValueError("A resposta de resultados homologados do PNCP deve ser uma lista.")
    return resultados
