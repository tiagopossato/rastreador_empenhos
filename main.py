import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional, Sequence

from pncp_tracker.collector import baixar_dados_compra_pncp
from pncp_tracker.etapa2 import processar_etapa2
from pncp_tracker.report_html import gerar_relatorio_html
from pncp_tracker.url_parser import extrair_parametros_url


def _nome_arquivo_relatorio(chaves_integracao: dict) -> str:
    numero_compra = re.sub(
        r"[^A-Za-z0-9_-]+",
        "-",
        str(chaves_integracao["numero_compra"]).strip(),
    ).strip("-")
    ano_compra = re.sub(
        r"[^A-Za-z0-9_-]+",
        "-",
        str(chaves_integracao["ano_compra"]).strip(),
    ).strip("-")
    if not numero_compra or not ano_compra:
        raise ValueError("Número ou ano da compra inválido para nomear o relatório.")
    return f"relatorio_compra_{numero_compra}_{ano_compra}.html"


def _obter_url_pncp(url: Optional[str], input_fn=input) -> str:
    if not url:
        url = input_fn("Informe o link do edital no PNCP: ")
    url = url.strip()
    if not url:
        raise ValueError("Nenhum link do PNCP foi informado; execução cancelada.")
    extrair_parametros_url(url)
    return url


def _finalizar_jsons(caminhos_json: Sequence[Path], manter_json: bool) -> None:
    if manter_json:
        for caminho in caminhos_json:
            print(f"JSON mantido: {caminho}")
        return

    for caminho in caminhos_json:
        caminho.unlink()
    print("Arquivos JSON temporários removidos.")


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Gera relatório de edital e empenhos do PNCP.")
    parser.add_argument(
        "url_pncp",
        nargs="?",
        help="Link do edital no PNCP. Se omitido, será solicitado no terminal.",
    )
    parser.add_argument(
        "--manter-json",
        "--manterJSON",
        dest="manter_json",
        action="store_true",
        help="Preserva os arquivos JSON da coleta após gerar o relatório.",
    )
    args = parser.parse_args(argv)
    try:
        url_pncp = _obter_url_pncp(args.url_pncp)
    except (ValueError, EOFError) as exc:
        parser.error(str(exc))

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
            pasta_projeto
            / _nome_arquivo_relatorio(resultado_etapa2["chaves_integracao"]),
        )
        _finalizar_jsons((caminho_etapa1, caminho_etapa2), args.manter_json)

        print(f"Status: {resultado_etapa2['status']}")
        print(resultado_etapa2.get("mensagem", ""))
        print(f"Empenhos encontrados: {resultado_etapa2.get('quantidade_empenhos', 0)}")
        print(f"Relatório HTML salvo em: {caminho_relatorio}")

    except Exception as exc:
        print(f"Erro ao processar as etapas da compra: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
