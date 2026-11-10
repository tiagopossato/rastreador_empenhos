import os
from pathlib import Path
from typing import Any, Dict, List

import requests

from .constants import DEFAULT_TIMEOUT


def _carregar_arquivo_env() -> None:
    """Carrega variáveis ausentes do arquivo .env na raiz do projeto."""
    caminho_env = Path(__file__).resolve().parent.parent / ".env"
    if not caminho_env.exists():
        return

    for linha in caminho_env.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue

        nome, valor = linha.split("=", 1)
        nome = nome.strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in {"'", '"'}:
            valor = valor[1:-1]
        if nome:
            os.environ.setdefault(nome, valor)


def _api_key() -> str:
    """Lê a chave da API do .env ou do ambiente do sistema."""
    _carregar_arquivo_env()
    return os.getenv("PORTAL_DADOS_API_KEY") or os.getenv("PORTALTRANSPARENCIA_API_KEY") or ""


def _headers() -> Dict[str, str]:
    """Montagem de cabeçalhos com autenticação e user-agent."""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    api_key = _api_key()
    if api_key:
        headers["chave-api-dados"] = api_key
    return headers


def consultar_empenhos_licitacao(codigo_ug: str, numero_licitacao: str, codigo_modalidade: str, pagina: int = 1) -> List[Dict[str, Any]]:
    """Consulta empenhos de uma licitação no Portal da Transparência."""
    api_key = _api_key()
    if not api_key:
        raise PermissionError(
            "Chave da API do Portal da Transparência não configurada. "
            "Defina PORTAL_DADOS_API_KEY ou PORTALTRANSPARENCIA_API_KEY."
        )

    url = "https://api.portaldatransparencia.gov.br/api-de-dados/licitacoes/empenhos"
    response = requests.get(
        url,
        params={
            "codigoUG": codigo_ug,
            "numero": numero_licitacao,
            "codigoModalidade": codigo_modalidade,
            "pagina": pagina,
        },
        headers=_headers(),
        timeout=DEFAULT_TIMEOUT,
    )

    if response.status_code == 401:
        raise PermissionError("API do Portal da Transparência recusou a chave de autenticação.")
    response.raise_for_status()

    payload = response.json()
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "resultado" in payload and isinstance(payload["resultado"], list):
        return payload["resultado"]
    return []


def consultar_todos_empenhos_licitacao(codigo_ug: str, numero_licitacao: str, codigo_modalidade: str) -> List[Dict[str, Any]]:
    """Busca todos os empenhos da licitação nas páginas disponíveis."""
    pagina = 1
    todos: List[Dict[str, Any]] = []

    while True:
        lote = consultar_empenhos_licitacao(codigo_ug, numero_licitacao, codigo_modalidade, pagina=pagina)
        if not lote:
            break
        todos.extend(lote)
        pagina += 1

    return todos


def consultar_documentos_despesa(unidade_gestora: str, data_emissao: str, fase: int = 1) -> List[Dict[str, Any]]:
    """Lista documentos de despesa de uma UG e data, paginando até o fim."""
    api_key = _api_key()
    if not api_key:
        raise PermissionError(
            "Chave da API do Portal da Transparência não configurada. "
            "Defina PORTAL_DADOS_API_KEY ou PORTALTRANSPARENCIA_API_KEY."
        )

    url = "https://api.portaldatransparencia.gov.br/api-de-dados/despesas/documentos"
    documentos: List[Dict[str, Any]] = []
    pagina = 1

    while True:
        response = requests.get(
            url,
            params={
                "unidadeGestora": unidade_gestora,
                "dataEmissao": data_emissao,
                "fase": fase,
                "pagina": pagina,
            },
            headers=_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code == 401:
            raise PermissionError("API do Portal da Transparência recusou a chave de autenticação.")
        response.raise_for_status()
        lote = response.json()
        if not isinstance(lote, list):
            raise ValueError("Resposta inesperada ao consultar documentos de despesa.")
        if not lote:
            break
        documentos.extend(lote)
        if len(lote) < 15:
            break
        pagina += 1

    return documentos


def consultar_detalhes_documento_despesa(codigo_documento: str) -> Dict[str, Any]:
    """Busca o detalhamento do documento de despesa no Portal da Transparência."""
    api_key = _api_key()
    if not api_key:
        raise PermissionError(
            "Chave da API do Portal da Transparência não configurada. "
            "Defina PORTAL_DADOS_API_KEY ou PORTALTRANSPARENCIA_API_KEY."
        )

    base_url = "https://api.portaldatransparencia.gov.br/api-de-dados/despesas"
    headers = _headers()
    response = requests.get(
        f"{base_url}/documentos/{codigo_documento}",
        headers=headers,
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code == 401:
        raise PermissionError("API do Portal da Transparência recusou a chave de autenticação.")
    response.raise_for_status()
    documento = response.json()
    if not isinstance(documento, dict):
        raise ValueError("Resposta inesperada ao consultar o documento de despesa.")

    itens: List[Dict[str, Any]] = []
    pagina = 1
    while True:
        response_itens = requests.get(
            f"{base_url}/itens-de-empenho",
            params={"codigoDocumento": codigo_documento, "pagina": pagina},
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if response_itens.status_code == 401:
            raise PermissionError("API do Portal da Transparência recusou a chave de autenticação.")
        response_itens.raise_for_status()
        lote = response_itens.json()
        if not isinstance(lote, list):
            raise ValueError("Resposta inesperada ao consultar itens do empenho.")
        if not lote:
            break
        itens.extend(lote)
        if len(lote) < 15:
            break
        pagina += 1

    documento["itensEmpenho"] = itens
    return documento


def numero_licitacao_from_compra(numero_compra: str, ano_compra: int | str) -> str:
    """Formata o número da licitação como esperado pela API: 'NNNNNAAAA'."""
    return f"{str(numero_compra).replace('/', '').replace('-', '').strip()}{str(ano_compra).strip()}"


def codigo_modalidade_portal(modalidade_nome: str, registro_precos: bool = False) -> str:
    """Converte a modalidade PNCP para o código usado pelo Portal da Transparência."""
    modalidade = modalidade_nome.casefold()
    if "pregão" in modalidade:
        return "9999" if registro_precos else "5"

    codigos = {
        "concorrência": "3",
        "convite": "1",
        "tomada de preços": "2",
        "concurso": "20",
        "dispensa": "6",
        "inexigibilidade": "7",
    }
    for nome, codigo in codigos.items():
        if nome in modalidade:
            return codigo

    raise ValueError(f"Modalidade PNCP sem correspondência conhecida no Portal da Transparência: {modalidade_nome!r}")
