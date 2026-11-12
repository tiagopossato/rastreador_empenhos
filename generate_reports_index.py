from pathlib import Path

from relatorios.gerar_relatorios import gerar_relatorios
from pncp_tracker.process_lock import interprocess_lock, lock_path_for


if __name__ == "__main__":
    reports_dir = Path(__file__).resolve().parent / "relatorios"
    with interprocess_lock(lock_path_for(reports_dir / "indice_relatorios.json")):
        gerar_relatorios(reports_dir)
