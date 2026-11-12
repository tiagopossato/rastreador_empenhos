import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from generate_reports_index import gerar_relatorios
from pncp_tracker.collector import baixar_dados_compra_pncp
from pncp_tracker.consultar_e_mapear_empenhos import consultar_e_mapear_empenhos
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


def _escrever_json(caminho: Path, dados: dict) -> None:
    with caminho.open("w", encoding="utf-8", newline="\n") as arquivo:
        json.dump(dados, arquivo, indent=2, ensure_ascii=False)
        arquivo.write("\n")


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Gera relatório de edital e empenhos do PNCP.")
    parser.add_argument(
        "url_pncp",
        nargs="?",
        help="Link do edital no PNCP. Se omitido, será solicitado no terminal.",
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

        pasta_relatorios = pasta_projeto / "relatorios"
        nome_arquivo_relatorio = _nome_arquivo_relatorio(
            dados_compra["chaves_integracao"]
        )
        pasta_relatorio = pasta_relatorios / Path(nome_arquivo_relatorio).stem
        pasta_relatorio.mkdir(parents=True, exist_ok=True)

        caminho_etapa1 = pasta_relatorio / "dados_pregao.json"
        _escrever_json(caminho_etapa1, dados_compra)
        print(f"Dados da etapa 1 salvos em: {caminho_etapa1}")

        print("\n=== ETAPA 2: EMPENHOS E RELATÓRIO ===")
        resultado_etapa2 = consultar_e_mapear_empenhos(url_pncp, dados_compra=dados_compra)
        caminho_etapa2 = pasta_relatorio / "dados_empenhos.json"
        _escrever_json(caminho_etapa2, resultado_etapa2)
        caminho_metadados = pasta_relatorio / "metadados.json"
        if caminho_metadados.exists():
            metadados = json.loads(caminho_metadados.read_text(encoding="utf-8"))
            if not isinstance(metadados, dict):
                raise ValueError("Os metadados existentes do relatório são inválidos.")
        else:
            metadados = {}

        agora = datetime.now().astimezone().isoformat(timespec="seconds")
        metadados.update(
            {
                "schema_version": 1,
                "url_pncp": url_pncp,
                "criado_em": metadados.get("criado_em") or agora,
                "atualizado_em": agora,
                "chaves_integracao": resultado_etapa2.get("chaves_integracao")
                or dados_compra.get("chaves_integracao", {}),
                "arquivo_html": nome_arquivo_relatorio,
            }
        )
        _escrever_json(caminho_metadados, metadados)

        caminho_index = gerar_relatorios(pasta_relatorios)
        caminho_relatorio = pasta_relatorio / nome_arquivo_relatorio

        print(f"Status: {resultado_etapa2['status']}")
        print(resultado_etapa2.get("mensagem", ""))
        print(f"Empenhos encontrados: {resultado_etapa2.get('quantidade_empenhos', 0)}")
        print(f"Relatório HTML salvo em: {caminho_relatorio}")
        print(f"Índice HTML atualizado em: {caminho_index}")

    except Exception as exc:
        print(f"Erro ao processar as etapas da compra: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
