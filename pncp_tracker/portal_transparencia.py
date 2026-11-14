from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import requests

from .constants import DEFAULT_TIMEOUT

PORTAL_BASE_URL = "https://api.portaldatransparencia.gov.br/api-de-dados"
_PORTAL_RESTRITO = "/despesas/documentos-por-favorecido"
_rate_limit_lock = threading.Lock()
_last_request_at = 0.0
_portal_blocked = False
_portal_blocked_until = 0.0

_CACHE_TTL = 1800.0
_cache_lock = threading.Lock()
_cache_favorecido: Dict[tuple, tuple] = {}

_TENTATIVAS_HTTP = 2
_session = requests.Session()
_session.mount("https://", requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8))
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
_env_lock = threading.Lock()
_env_carregado = False


def _http_get(url: str, **kwargs: Any) -> requests.Response:
    """Ponto único de HTTP do Portal: sessão com pool de conexões (e alvo dos testes)."""
    return _session.get(url, **kwargs)


def limpar_cache() -> None:
    """Zera o cache de consultas por favorecido (chamado no início de cada coleta)."""
    with _cache_lock:
        _cache_favorecido.clear()


class PortalTransparenciaBlockedError(PermissionError):
    """Raised when the Portal suspends or blocks the API token."""


def _intervalo_minimo(url: str) -> float:
    hora = datetime.now().hour
    limite_geral = 700 if hora < 6 else 400
    limite = min(limite_geral, 180) if _PORTAL_RESTRITO in url else limite_geral
    return 60 / limite + 0.01


def _aguardar_intervalo(url: str) -> None:
    """Respeita o limite de taxa, compartilhado entre todas as threads do processo."""
    global _last_request_at, _portal_blocked, _portal_blocked_until
    with _rate_limit_lock:
        agora = time.monotonic()
        if _portal_blocked:
            if agora < _portal_blocked_until:
                raise PortalTransparenciaBlockedError(
                    "O token do Portal da Transparência foi bloqueado; novas chamadas foram interrompidas."
                )
            _portal_blocked = False
        espera = _intervalo_minimo(url) - (agora - _last_request_at)
        if _last_request_at and espera > 0:
            time.sleep(espera)
        _last_request_at = time.monotonic()


def _get(url: str, **kwargs: Any) -> requests.Response:
    global _portal_blocked, _portal_blocked_until
    response = None
    for tentativa in range(1, _TENTATIVAS_HTTP + 1):
        _aguardar_intervalo(url)
        try:
            response = _http_get(url, **kwargs)
            break
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if tentativa == _TENTATIVAS_HTTP:
                raise

    texto = str(getattr(response, "text", "") or "").casefold()
    mensagem_bloqueio = (
        "limite de acesso à api de dados foi atingido",
        "token suspenso",
        "usuário bloqueado",
        "usuario bloqueado",
    )
    if response.status_code == 429 or any(msg in texto for msg in mensagem_bloqueio):
        with _rate_limit_lock:
            _portal_blocked = True
            _portal_blocked_until = time.monotonic() + 8 * 60 * 60
        raise PortalTransparenciaBlockedError(
            "O Portal da Transparência bloqueou o token por limite de acesso. "
            "As chamadas foram interrompidas para evitar novas requisições."
        )
    return response


def _ler_variaveis_env() -> Dict[str, str]:
    """Lê as variáveis do arquivo .env da raiz do projeto (sem tocar no ambiente)."""
    if not _ENV_FILE.exists():
        return {}

    variaveis: Dict[str, str] = {}
    for linha in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue

        nome, valor = linha.split("=", 1)
        nome = nome.strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in {"'", '"'}:
            valor = valor[1:-1]
        if nome:
            variaveis[nome] = valor
    return variaveis


def _carregar_arquivo_env() -> None:
    """Carrega variáveis ausentes do .env uma vez, com segurança entre threads.

    O carregamento é preguiçoso e disparado na primeira consulta. Sem o lock, duas threads
    do enriquecimento paralelo podiam ver `_env_carregado` já marcado antes de o ambiente
    ser preenchido e concluir que a chave não existia.
    """
    global _env_carregado
    if _env_carregado:
        return
    with _env_lock:
        if _env_carregado:
            return
        for nome, valor in _ler_variaveis_env().items():
            os.environ.setdefault(nome, valor)
        _env_carregado = True


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


def _exigir_chave() -> None:
    if not _api_key():
        raise PermissionError(
            "Chave da API do Portal da Transparência não configurada. "
            "Defina PORTAL_DADOS_API_KEY ou PORTALTRANSPARENCIA_API_KEY."
        )


def _json(response: requests.Response, esperado: type, mensagem: str) -> Any:
    if response.status_code == 401:
        raise PermissionError("API do Portal da Transparência recusou a chave de autenticação.")
    response.raise_for_status()
    try:
        dados = response.json()
    except ValueError as exc:
        raise ValueError(f"{mensagem}: resposta não é JSON válido.") from exc
    if not isinstance(dados, esperado):
        raise ValueError(mensagem)
    return dados


def _consultar_paginado(
    url: str,
    parametros: Dict[str, Any],
    *,
    tamanho_minimo_pagina: int = 15,
) -> List[Dict[str, Any]]:
    """Agrega as páginas de um endpoint do Portal até a primeira página curta.

    A paginação é sequencial de propósito: o endpoint restrito está limitado a 180 req/min,
    então paralelizar páginas só adiciona requisições sem reduzir o tempo (a taxa é o teto).
    """
    _exigir_chave()
    headers = _headers()
    resultados: List[Dict[str, Any]] = []
    pagina = 1

    while True:
        response = _get(
            url,
            params={**parametros, "pagina": pagina},
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        lote = _json(response, list, f"Resposta inesperada ao consultar {url}")
        resultados.extend(lote)
        if len(lote) < tamanho_minimo_pagina:
            break
        pagina += 1

    return resultados


def consultar_documentos_despesa_favorecido(
    codigo_pessoa: str,
    ano: int | str,
    unidade_gestora: str | None,
    fase: int = 1,
) -> List[Dict[str, Any]]:
    """Lista documentos por favorecido, ano e, opcionalmente, unidade gestora.

    O resultado é cacheado por (favorecido, ano, UG, fase) durante a coleta, porque o mesmo
    fornecedor costuma ser consultado pelo enriquecimento e pela varredura de fornecedores.
    """
    chave = (str(codigo_pessoa), str(ano), str(unidade_gestora or ""), int(fase))
    with _cache_lock:
        entrada = _cache_favorecido.get(chave)
        if entrada and (time.monotonic() - entrada[0]) < _CACHE_TTL:
            return [dict(documento) for documento in entrada[1]]

    parametros: Dict[str, Any] = {
        "codigoPessoa": codigo_pessoa,
        "fase": fase,
        "ano": ano,
    }
    if unidade_gestora:
        parametros["ug"] = unidade_gestora
    documentos = _consultar_paginado(
        f"{PORTAL_BASE_URL}/despesas/documentos-por-favorecido",
        parametros,
    )

    with _cache_lock:
        _cache_favorecido[chave] = (time.monotonic(), documentos)
    return [dict(documento) for documento in documentos]


def consultar_contratos_por_processo(processo: str) -> List[Dict[str, Any]]:
    """Lista os contratos federais registrados com o número de processo informado."""
    return _consultar_paginado(
        f"{PORTAL_BASE_URL}/contratos/processo",
        {"processo": processo},
    )


def consultar_empenhos_de_contrato(id_contrato: Any) -> List[Dict[str, Any]]:
    """Lista os empenhos relacionados a um contrato do Portal."""
    return _consultar_paginado(
        f"{PORTAL_BASE_URL}/contratos/documentos-relacionados",
        {"id": id_contrato},
    )


def consultar_licitacoes_por_processo(processo: str) -> List[Dict[str, Any]]:
    """Lista as licitações federais registradas com o número de processo informado."""
    return _consultar_paginado(
        f"{PORTAL_BASE_URL}/licitacoes/por-processo",
        {"processo": processo},
    )


def consultar_empenhos_de_licitacao(
    codigo_ug: str,
    numero: str,
    codigo_modalidade: Any,
) -> List[Dict[str, Any]]:
    """Lista os empenhos de uma licitação identificada por UG, número e modalidade."""
    return _consultar_paginado(
        f"{PORTAL_BASE_URL}/licitacoes/empenhos",
        {
            "codigoUG": codigo_ug,
            "numero": numero,
            "codigoModalidade": codigo_modalidade,
        },
    )


def consultar_detalhes_documento_despesa(codigo_documento: str) -> Dict[str, Any]:
    """Busca o detalhamento do documento de despesa e seus itens no Portal."""
    _exigir_chave()
    base_url = f"{PORTAL_BASE_URL}/despesas"
    headers = _headers()

    response = _get(
        f"{base_url}/documentos/{codigo_documento}",
        headers=headers,
        timeout=DEFAULT_TIMEOUT,
    )
    documento = _json(
        response,
        dict,
        "Resposta inesperada ao consultar o documento de despesa.",
    )
    documento["itensEmpenho"] = _consultar_paginado(
        f"{base_url}/itens-de-empenho",
        {"codigoDocumento": codigo_documento},
    )
    return documento
