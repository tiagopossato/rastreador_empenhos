"""Localização da raiz do projeto no disco (dados versionados, `.env` e `.private`).

Com o pacote instalado em `site-packages`, a raiz não pode ser derivada do caminho
do módulo. A resolução usa, nesta ordem, `RASTREADOR_EMPENHOS_ROOT`, a árvore do
checkout/projeto detectada a partir do diretório atual e o diretório atual.
"""

import os
from pathlib import Path
from typing import Optional

_ENV_VAR = "RASTREADOR_EMPENHOS_ROOT"
_REPORTS_INDEX = Path("relatorios") / "indice_relatorios.json"
# Arquivos da raiz que não sobem de um diretório de relatórios individual.
_ROOT_MARKERS = (
    Path("README.md"),
    Path("agents.md"),
    _REPORTS_INDEX,
    _REPORTS_INDEX.with_name("index.html"),
    Path(".env.example"),
)


def _e_raiz(candidato: Path) -> bool:
    return any((candidato / marcador).exists() for marcador in _ROOT_MARKERS)


def _detectar_raiz() -> Optional[Path]:
    atual = Path.cwd().resolve()
    for candidato in (atual, *atual.parents):
        if _e_raiz(candidato):
            return candidato
    for candidato in (atual, *atual.parents):
        if (candidato / "relatorios").is_dir():
            return candidato
    return None


def encontrar_raiz_projeto() -> Path:
    ambiente = os.environ.get(_ENV_VAR)
    if ambiente:
        return Path(ambiente).expanduser().resolve()
    return _detectar_raiz() or Path.cwd().resolve()


def caminho_projeto(*partes: Path) -> Path:
    """Caminho relativo à raiz do projeto; não cria nada, apenas resolve."""
    return encontrar_raiz_projeto().joinpath(*partes)
