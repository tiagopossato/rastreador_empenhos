import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

from waitress import serve

from ..criar_usuario_admin import caminho_usuarios, solicitar_criacao_usuario
from ..project_root import caminho_projeto
from .app import create_app
from .auth import load_users


def _configure_logging() -> Path:
    log_path = Path(
        os.environ.get(
            "PNCP_ADMIN_LOG_FILE",
            str(caminho_projeto(".private", "admin_web.log")),
        )
    )
    if not log_path.is_absolute():
        log_path = caminho_projeto() / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            str(log_path),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        ),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )
    return log_path


def garantir_usuario_inicial(
    users_file: Optional[Path] = None,
    solicitar_criacao: Optional[Callable[[Path], bool]] = None,
) -> None:
    """Interrompe a inicialização enquanto não existir ao menos um usuário cadastrado."""
    users_file = Path(users_file) if users_file is not None else caminho_usuarios()
    try:
        if load_users(users_file):
            return
    except ValueError as exc:
        raise SystemExit("Não foi possível ler o arquivo de usuários: {}".format(exc))

    logging.getLogger(__name__).warning(
        "Nenhum usuário cadastrado em %s; solicitando a criação da primeira conta.",
        users_file,
    )
    criacao = solicitar_criacao or solicitar_criacao_usuario
    try:
        criada = criacao(users_file)
    except (EOFError, KeyboardInterrupt):
        criada = False
    if not criada:
        raise SystemExit(
            "Nenhum usuário cadastrado em {}; a interface administrativa não foi "
            "iniciada.".format(users_file)
        )


def main() -> None:
    log_path = _configure_logging()
    garantir_usuario_inicial()
    host = os.environ.get("PNCP_ADMIN_HOST", "127.0.0.1")
    port = int(os.environ.get("PNCP_ADMIN_PORT", "8000"))
    logging.getLogger(__name__).info(
        "Interface administrativa iniciada em http://%s:%s. Arquivo de log: %s",
        host,
        port,
        log_path,
    )
    serve(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
