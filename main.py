import argparse
import sys
from typing import Optional, Sequence

from pncp_tracker.report_registry import validar_url_pncp
from pncp_tracker.report_service import atualizar_processo


def _obter_url_pncp(url: Optional[str], input_fn=input) -> str:
    if not url:
        url = input_fn("Informe o link do edital no PNCP: ")
    if not url or not url.strip():
        raise ValueError("Nenhum link do PNCP foi informado; execução cancelada.")
    url = url.strip()
    validar_url_pncp(url)
    return url


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Gera ou atualiza o relatório de um edital do PNCP."
    )
    parser.add_argument(
        "url_pncp",
        nargs="?",
        help="Link do edital no PNCP. Se omitido, será solicitado no terminal.",
    )
    try:
        args = parser.parse_args(argv)
        url_pncp = _obter_url_pncp(args.url_pncp)
    except (ValueError, EOFError) as exc:
        parser.error(str(exc))

    try:
        resultado = atualizar_processo(url_pncp, on_progress=print)
    except Exception as exc:
        print("Erro ao atualizar o processo: {}".format(exc), file=sys.stderr)
        sys.exit(1)

    dados = resultado["resultado_etapa2"]
    print("Status: {}".format(dados.get("status", "desconhecido")))
    print(dados.get("mensagem", ""))
    print("Empenhos encontrados: {}".format(dados.get("quantidade_empenhos", 0)))
    print("Relatório HTML salvo em: {}".format(resultado["caminho_relatorio"]))
    print("Índice HTML atualizado em: {}".format(resultado["caminho_index"]))


if __name__ == "__main__":
    main()
