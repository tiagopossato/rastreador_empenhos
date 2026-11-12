import sys

from pncp_tracker.report_service import atualizar_todos


def main() -> int:
    try:
        resultado = atualizar_todos(on_progress=print)
    except Exception as exc:
        print("Erro ao atualizar a lista de processos: {}".format(exc), file=sys.stderr)
        return 1

    print(
        "Atualizações concluídas: {}; falhas: {}.".format(
            len(resultado["atualizados"]),
            len(resultado["falhas"]),
        )
    )
    for falha in resultado["falhas"]:
        print(
            "Falha em {}: {}".format(falha["url_pncp"], falha["erro"]),
            file=sys.stderr,
        )
    return 1 if resultado["falhas"] else 0


if __name__ == "__main__":
    sys.exit(main())
