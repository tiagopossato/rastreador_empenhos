from pathlib import Path

from relatorios.gerar_relatorios import gerar_index_relatorios, gerar_relatorios


if __name__ == "__main__":
    gerar_relatorios(Path(__file__).resolve().parent / "relatorios")
