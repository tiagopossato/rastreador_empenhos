import html
import re
from pathlib import Path
from urllib.parse import quote


_REPORT_NAME = re.compile(r"^relatorio_compra_(.+)_(\d{4})\.html$")


def _titulo_relatorio(nome_arquivo: str) -> str:
    correspondencia = _REPORT_NAME.match(nome_arquivo)
    if correspondencia:
        numero, ano = correspondencia.groups()
        return f"Compra {numero} — {ano}"
    return nome_arquivo


def gerar_index_relatorios(pasta_relatorios: Path) -> Path:
    pasta_relatorios.mkdir(parents=True, exist_ok=True)
    relatorios = sorted(
        pasta_relatorios.glob("relatorio_compra_*.html"),
        key=lambda caminho: caminho.name.casefold(),
    )

    if relatorios:
        cartoes = "\n".join(
            (
                '<li class="card"><a href="'
                + quote(relatorio.name)
                + '">'
                + html.escape(_titulo_relatorio(relatorio.name))
                + "</a></li>"
            )
            for relatorio in relatorios
        )
    else:
        cartoes = '<li class="empty">Nenhum relatório disponível.</li>'

    conteudo = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Relatórios de empenhos</title>
  <style>
    body {{ font: 16px/1.5 system-ui, sans-serif; margin: 0 auto; max-width: 960px; padding: 2rem 1rem; color: #172033; background: #f5f7fb; }}
    h1 {{ margin-bottom: .25rem; }}
    p {{ color: #526078; }}
    ul {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 1rem; list-style: none; padding: 0; }}
    .card {{ background: white; border: 1px solid #dce3ee; border-radius: .75rem; padding: 1.25rem; }}
    a {{ color: #1456a0; font-weight: 650; text-decoration: none; }}
    a:hover, a:focus {{ text-decoration: underline; }}
    .empty {{ color: #526078; padding: 1rem 0; }}
  </style>
</head>
<body>
  <main>
    <h1>Relatórios de empenhos</h1>
    <p>Selecione uma compra para consultar o relatório completo.</p>
    <ul>
{cartoes}
    </ul>
  </main>
</body>
</html>
"""
    caminho_index = pasta_relatorios / "index.html"
    caminho_index.write_text(conteudo, encoding="utf-8")
    return caminho_index


if __name__ == "__main__":
    gerar_index_relatorios(Path(__file__).resolve().parent / "relatorios")
