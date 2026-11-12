from typing import Any, Dict, List

import requests

from .constants import DEFAULT_PAGE_SIZE, DEFAULT_TIMEOUT, PNCP_API_CONTRATOS


def consultar_contratos_empenhos(
    cnpj: str,
    ano: str,
    sequencial: str,
    tamanho_pagina: int = DEFAULT_PAGE_SIZE,
) -> List[Dict[str, Any]]:
    """Busca todas as linhas exibidas na aba Contratos/Empenhos do PNCP."""
    url = f"{PNCP_API_CONTRATOS}/{cnpj}/contratos/contratacao/{ano}/{sequencial}"
    pagina = 1
    total_paginas = 1
    registros: List[Dict[str, Any]] = []

    while pagina <= total_paginas:
        response = requests.get(
            url,
            params={"pagina": pagina, "tamanhoPagina": tamanho_pagina},
            timeout=DEFAULT_TIMEOUT,
        )
        if getattr(response, "status_code", None) == 404:
            return []
        response.raise_for_status()
        payload = response.json()

        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("Resposta inesperada da API de Contratos/Empenhos do PNCP.")

        registros.extend(payload["data"])
        total_paginas = int(payload.get("totalPaginas") or 0)
        if not payload["data"] or total_paginas == 0:
            break
        pagina += 1

    return registros
