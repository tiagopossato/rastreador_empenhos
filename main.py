import json

from pncp_tracker.collector import baixar_dados_compra_pncp


def main() -> None:
    link_teste = "https://pncp.gov.br/app/editais/10635424000186/2025/000272"

    try:
        dados = baixar_dados_compra_pncp(link_teste)

        print("\n=== CHAVES EXTRAÍDAS PARA BUSCA DE EMPENHOS ===")
        print(json.dumps(dados["chaves_integracao"], indent=2, ensure_ascii=False))

        print(f"\nTotal de itens baixados: {dados['quantidade_itens']}")
        if dados["itens"]:
            primeiro_item = dados["itens"][0]
            print(f"Exemplo Item 1: {primeiro_item.get('descricao', '')[:80]}...")

        with open("etapa1_dados_compra.json", "w", encoding="utf-8") as arq:
            json.dump(dados, arq, indent=2, ensure_ascii=False)

        print("\nArquivo 'etapa1_dados_compra.json' salvo com sucesso.")

    except Exception as exc:
        print(f"Erro ao processar compra: {exc}")


if __name__ == "__main__":
    main()

