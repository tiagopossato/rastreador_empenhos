from pathlib import Path

from relatorios.gerar_relatorios import gerar_index_relatorios, gerar_relatorios
from pncp_tracker.process_lock import interprocess_lock


if __name__ == "__main__":
    reports_dir = Path(__file__).resolve().parent / "relatorios"
    lock_path = reports_dir.parent / ".private" / "report_update.lock"
    with interprocess_lock(lock_path):
        gerar_relatorios(reports_dir)
