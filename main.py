import json
import sys
from pathlib import Path

from pncp_tracker.collector import baixar_dados_compra_pncp
from pncp_tracker.etapa2 import processar_etapa2
from pncp_tracker.report_html import gerar_relatorio_html


def main() -> None:
    url_pncp = "https://pncp.gov.br/app/editais/10635424000186/2025/187"
    pasta_projeto = Path(__file__).resolve().parent

    try:
        print("=== ETAPA 1: COLETA DO PNCP ===")
        dados_compra = baixar_dados_compra_pncp(url_pncp)

        print("\n=== CHAVES EXTRAÍDAS PARA BUSCA DE EMPENHOS ===")
        print(json.dumps(dados_compra["chaves_integracao"], indent=2, ensure_ascii=False))

        print(f"\nTotal de itens baixados: {dados_compra['quantidade_itens']}")
        if dados_compra["itens"]:
            primeiro_item = dados_compra["itens"][0]
            print(f"Exemplo Item 1: {primeiro_item.get('descricao', '')[:80]}...")

        caminho_etapa1 = pasta_projeto / "etapa1_dados_compra.json"
        caminho_etapa1.write_text(
            json.dumps(dados_compra, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Dados da etapa 1 salvos em: {caminho_etapa1}")

        print("\n=== ETAPA 2: EMPENHOS E RELATÓRIO ===")
        resultado_etapa2 = processar_etapa2(url_pncp, dados_compra=dados_compra)
        caminho_etapa2 = pasta_projeto / "etapa2_empenhos.json"
        caminho_etapa2.write_text(
            json.dumps(resultado_etapa2, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        caminho_relatorio = gerar_relatorio_html(
            resultado_etapa2,
            pasta_projeto / "relatorio_compra.html",
        )

        print(f"Status: {resultado_etapa2['status']}")
        print(resultado_etapa2.get("mensagem", ""))
        print(f"Empenhos encontrados: {resultado_etapa2.get('quantidade_empenhos', 0)}")
        print(f"Dados da etapa 2 salvos em: {caminho_etapa2}")
        print(f"Relatório HTML salvo em: {caminho_relatorio}")

    except Exception as exc:
        print(f"Erro ao processar as etapas da compra: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
