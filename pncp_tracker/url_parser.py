import re
from typing import Tuple
from urllib.parse import urlsplit


_PNCP_PATH = re.compile(r"^/app/editais/(\d{14})/(\d{4})/(\d+)/?$")


def validar_url_pncp(url: str) -> Tuple[str, str, str]:
    url = url.strip()
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "pncp.gov.br":
        raise ValueError("Informe uma URL HTTPS do domínio pncp.gov.br.")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("A URL PNCP não deve conter credenciais, consulta ou fragmento.")
    match = _PNCP_PATH.fullmatch(parsed.path)
    if not match:
        raise ValueError(
            "URL inválida. O formato esperado é "
            "https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}."
        )
    return match.group(1), match.group(2), match.group(3)


def extrair_parametros_url(url_pncp: str) -> dict:
    """Valida e extrai os parâmetros de uma URL pública do PNCP."""
    cnpj, ano, sequencial = validar_url_pncp(url_pncp)
    return {
        "cnpj": cnpj,
        "ano": ano,
        "sequencial": sequencial,
    }
