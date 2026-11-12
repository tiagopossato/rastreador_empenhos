import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from waitress import serve

from admin_web.app import create_app


_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _configure_logging() -> Path:
    log_path = Path(
        os.environ.get(
            "PNCP_ADMIN_LOG_FILE",
            str(_PROJECT_ROOT / ".private" / "admin_web.log"),
        )
    )
    if not log_path.is_absolute():
        log_path = _PROJECT_ROOT / log_path
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


def main() -> None:
    log_path = _configure_logging()
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
