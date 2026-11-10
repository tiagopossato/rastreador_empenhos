import json
from pathlib import Path
import sys

from pncp_tracker.etapa2 import processar_etapa2
from pncp_tracker.report_html import gerar_relatorio_html


def main() -> None:
    url_pncp = "https://pncp.gov.br/app/editais/10635424000186/2025/000272"

    try:
        resultado = processar_etapa2(url_pncp)
        caminho_saida = Path(__file__).resolve().parent / "etapa2_empenhos.json"
        caminho_saida.write_text(
            json.dumps(resultado, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        caminho_relatorio = gerar_relatorio_html(
            resultado,
            Path(__file__).resolve().parent / "relatorio_compra.html",
        )
        print(f"Status: {resultado['status']}")
        print(resultado.get("mensagem", ""))
        print(f"Empenhos encontrados: {resultado.get('quantidade_empenhos', 0)}")
        print(f"Resultado salvo em: {caminho_saida}")
        print(f"Relatório HTML salvo em: {caminho_relatorio}")
    except Exception as exc:
        print(f"Erro na etapa 2: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
