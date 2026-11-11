import html
import json
import re
from pathlib import Path
from urllib.parse import quote


_REPORT_NAME = re.compile(r"^relatorio_compra_(.+)_(\d{4})\.html$")
_REPORT_DATA = re.compile(
    r'<script id="report-data" type="application/json">(.*?)</script>',
    re.DOTALL,
)


def _dados_relatorio(caminho: Path) -> dict:
    conteudo = caminho.read_text(encoding="utf-8")
    correspondencia = _REPORT_DATA.search(conteudo)
    if not correspondencia:
        raise ValueError(f"Dados do edital não encontrados em {caminho}.")

    dados = json.loads(correspondencia.group(1))
    chaves = dados.get("chaves")
    if not isinstance(chaves, dict):
        raise ValueError(f"Chaves do edital ausentes em {caminho}.")
    return dados


def gerar_index_relatorios(pasta_relatorios: Path) -> Path:
    pasta_relatorios.mkdir(parents=True, exist_ok=True)
    relatorios = sorted(
        pasta_relatorios.glob("relatorio_compra_*.html"),
        key=lambda caminho: caminho.name.casefold(),
    )

    if relatorios:
        cartoes_lista = []
        for relatorio in relatorios:
            dados = _dados_relatorio(relatorio)
            chaves = dados["chaves"]
            numero = chaves.get("numero_compra") or "—"
            ano = chaves.get("ano_compra") or "—"
            objeto = dados.get("objeto") or "Objeto não informado no PNCP."
            cartoes_lista.append(
                '<li class="card"><a href="'
                + quote(relatorio.name)
                + '"><h2>Edital nº '
                + html.escape(str(numero))
                + "/"
                + html.escape(str(ano))
                + "</h2></a><p>"
                + html.escape(str(objeto))
                + "</p></li>"
            )
        cartoes = "\n".join(cartoes_lista)
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
    ul {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; list-style: none; padding: 0; }}
    .card {{ background: white; border: 1px solid #dce3ee; border-radius: .75rem; padding: 1.25rem; }}
    .card a {{ color: #1456a0; text-decoration: none; }}
    .card a:hover, .card a:focus {{ text-decoration: underline; }}
    h2 {{ font-size: 1.1rem; margin: 0 0 .65rem; }}
    .card p {{ margin: 0; }}
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
