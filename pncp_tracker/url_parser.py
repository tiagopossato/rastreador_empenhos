import re


def extrair_parametros_url(url_pncp: str) -> dict:
    """Extrai CNPJ, Ano e Sequencial de uma URL pública do PNCP."""
    padrao = r"/editais/(\d{14})/(\d{4})/(\d+)"
    match = re.search(padrao, url_pncp)

    if not match:
        raise ValueError("URL inválida. O formato esperado contém '/editais/{cnpj}/{ano}/{sequencial}'.")

    return {
        "cnpj": match.group(1),
        "ano": match.group(2),
        "sequencial": match.group(3),
    }
