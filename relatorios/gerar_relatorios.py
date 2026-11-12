import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pncp_tracker.report_registry import INDEX_PATH, ler_registros, salvar_registros
from pncp_tracker.report_html import gerar_relatorio_html


def _ler_json(caminho: Path) -> Dict[str, Any]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(dados, dict):
        raise ValueError(f"O conteúdo de {caminho} deve ser um objeto JSON.")
    return dados


def _escrever_texto(caminho: Path, conteudo: str) -> None:
    with caminho.open("w", encoding="utf-8", newline="\n") as arquivo:
        arquivo.write(conteudo)


def _numero(valor: Any) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0


def _formatar_quantidade(valor: float) -> str:
    formatado = f"{valor:,.3f}".rstrip("0").rstrip(".")
    return formatado.replace(",", "\0").replace(".", ",").replace("\0", ".")


def _formatar_moeda(valor: float) -> str:
    formatado = f"{valor:,.2f}"
    formatado = formatado.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return f"R$ {formatado}"


def _resumo_cards(dados_relatorio: Dict[str, Any]) -> List[Dict[str, Any]]:
    contagens = {"deserto": 0, "empenhado": 0, "nao_empenhado": 0, "pendente": 0}
    for item in dados_relatorio.get("itens", []):
        if item.get("status") == "resultados_homologados_indisponiveis":
            contagens["pendente"] += 1
            continue
        homologado = _numero(item.get("valor_total_homologado"))
        empenhado = _numero(item.get("valor_empenhado"))
        situacao = "deserto" if homologado == 0 else (
            "empenhado" if empenhado > 0 else "nao_empenhado"
        )
        contagens[situacao] += 1

    homologados = contagens["empenhado"] + contagens["nao_empenhado"]
    valores = [
        ("itens", "Itens", dados_relatorio.get("quantidade_itens", 0), "quantidade",
         "Itens publicados no edital"),
        ("itens_homologados", "Itens homologados", homologados, "quantidade",
         "Itens empenhados + não empenhados"),
        ("itens_empenhados", "Itens empenhados", contagens["empenhado"], "quantidade",
         "Execução acima de 0%"),
        ("itens_nao_empenhados", "Itens não empenhados", contagens["nao_empenhado"],
         "quantidade", "Execução igual a 0%, excluídos desertos"),
        ("itens_desertos", "Itens desertos", contagens["deserto"], "quantidade",
         "Valor homologado igual a R$ 0,00"),
        ("itens_resultados_pendentes", "Resultados pendentes", contagens["pendente"],
         "quantidade", "Falha ao consultar resultados no PNCP"),
        ("valor_estimado", "Valor estimado", dados_relatorio.get("valor_estimado", 0),
         "moeda", "Soma dos valores estimados por item"),
        ("valor_homologado", "Valor homologado", dados_relatorio.get("valor_homologado", 0),
         "moeda", "Soma dos resultados homologados"),
        ("empenhado_mapeado", "Empenhado mapeado",
         dados_relatorio.get("valor_empenhado_mapeado", 0), "moeda",
         "{} de {} registros com detalhamento".format(
             dados_relatorio.get("quantidade_empenhos_detalhados", 0),
             dados_relatorio.get("quantidade_registros", 0),
         )),
    ]
    cards = []
    for chave, rotulo, valor, formato, descricao in valores:
        valor_numerico = _numero(valor)
        exibicao = (
            _formatar_moeda(valor_numerico)
            if formato == "moeda"
            else _formatar_quantidade(valor_numerico)
        )
        cards.append(
            {
                "chave": chave,
                "rotulo": rotulo,
                "valor": valor,
                "exibicao": exibicao,
                "descricao": descricao,
            }
        )
    return cards


def _gerar_index_html(pasta_relatorios: Path, relatorios: List[Dict[str, Any]]) -> Path:
    linhas = []
    for relatorio in relatorios:
        arquivo_html = relatorio.get("arquivo_html")
        pasta = relatorio.get("pasta")
        if arquivo_html and pasta:
            href = quote("{}/{}".format(pasta, arquivo_html), safe="/")
            titulo = '<a class="report-link" href="{}">Edital nº {}/{}</a>'.format(
                href,
                html.escape(str(
                    (relatorio.get("chaves_integracao") or {}).get("numero_compra") or "—"
                )),
                html.escape(str(
                    (relatorio.get("chaves_integracao") or {}).get("ano_compra") or "—"
                )),
            )
        else:
            titulo = '<span class="report-link">Processo aguardando atualização</span>'
        cards = "".join(
            '<div class="metric"><span>{}</span><strong>{}</strong><small>{}</small></div>'.format(
                html.escape(str(card.get("rotulo", ""))),
                html.escape(str(card.get("exibicao", ""))),
                html.escape(str(card.get("descricao", ""))),
            )
            for card in relatorio.get("resumo_cards", [])
        ) or '<div class="metric"><span>Status</span><strong>{}</strong></div>'.format(
            html.escape(str(relatorio.get("status", "pendente")))
        )
        chaves = relatorio.get("chaves_integracao") or {}
        url_pncp = relatorio.get("url_pncp")
        link_pncp = (
            '<a href="{}" target="_blank" rel="noopener noreferrer">Abrir PNCP</a>'.format(
                html.escape(str(url_pncp), quote=True)
            )
            if url_pncp
            else "Link PNCP indisponível"
        )
        linhas.append(
            '<tr><td>{}<small>{}</small></td><td>{}</td>'
            '<td><div class="metrics">{}</div></td><td>{}</td></tr>'.format(
                titulo,
                link_pncp,
                html.escape(str(
                    relatorio.get("objeto") or "Objeto não informado no PNCP."
                )),
                cards,
                html.escape(str(
                    relatorio.get("atualizado_em")
                    or relatorio.get("status")
                    or "—"
                )),
            )
        )

    if not linhas:
        corpo_tabela = '<tr><td class="empty" colspan="4">Nenhum relatório disponível.</td></tr>'
    else:
        corpo_tabela = "\n".join(linhas)

    conteudo = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Relatórios de empenhos</title>
  <style>
    :root {{ color-scheme: light; --ink: #172033; --muted: #526078; --line: #dce3ee; --blue: #1456a0; }}
    * {{ box-sizing: border-box; }}
    body {{ font: 15px/1.5 system-ui, sans-serif; margin: 0 auto; max-width: 1500px; padding: 2rem 1rem; color: var(--ink); background: #f5f7fb; }}
    h1 {{ margin-bottom: .25rem; }}
    .intro {{ color: var(--muted); margin-top: 0; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ border-collapse: separate; border-spacing: 0 .75rem; width: 100%; min-width: 900px; }}
    th {{ text-align: left; padding: .5rem .75rem; color: var(--muted); font-size: .8rem; }}
    td {{ vertical-align: top; background: white; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 1rem .75rem; }}
    td:first-child {{ border-left: 1px solid var(--line); border-radius: .75rem 0 0 .75rem; min-width: 145px; }}
    td:last-child {{ border-right: 1px solid var(--line); border-radius: 0 .75rem .75rem 0; white-space: nowrap; min-width: 145px; }}
    .report-link {{ color: var(--blue); font-weight: 700; text-decoration: none; }}
    .report-link:hover, .report-link:focus {{ text-decoration: underline; }}
    td small {{ display: block; color: var(--muted); font-size: .75rem; margin-top: .35rem; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: .5rem; }}
    .metric {{ border: 1px solid #e8edf4; border-radius: .5rem; padding: .5rem; }}
    .metric span, .metric small {{ display: block; color: var(--muted); font-size: .7rem; }}
    .metric strong {{ display: block; margin: .15rem 0; }}
    .empty {{ text-align: center; color: var(--muted); padding: 2rem; }}
    .page-header {{ display: flex; justify-content: space-between; align-items: center; gap: 1rem; }}
    .admin-link {{ display: inline-block; padding: .55rem .85rem; border-radius: .5rem; background: var(--blue); color: white; font-weight: 600; text-decoration: none; white-space: nowrap; }}
    .admin-link:hover, .admin-link:focus {{ filter: brightness(.9); }}
    @media (max-width: 900px) {{ .metrics {{ grid-template-columns: repeat(2, minmax(110px, 1fr)); }} }}
    @media (max-width: 600px) {{ body {{ padding: 1rem .5rem; }} th, td {{ padding: .65rem .5rem; }} }}
    @media (max-width: 480px) {{ .page-header {{ align-items: flex-start; flex-direction: column; }} }}
  </style>
</head>
<body>
  <main>
    <header class="page-header">
      <h1>Relatórios de empenhos</h1>
      <!-- admin-link -->
    </header>
    <p class="intro">Resumo das compras monitoradas. Selecione um edital para abrir o relatório completo.</p>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Processo</th><th>Objeto</th><th>Resumo do pregão</th><th>Última atualização</th></tr></thead>
        <tbody>
{linhas}
        </tbody>
      </table>
    </div>
  </main>
</body>
</html>
""".format(linhas=corpo_tabela)
    caminho = pasta_relatorios / "index.html"
    _escrever_texto(caminho, conteudo)
    return caminho


def gerar_relatorios(
    pasta_relatorios: Path,
    index_path: Path = INDEX_PATH,
) -> Path:
    pasta_relatorios = Path(pasta_relatorios)
    pasta_relatorios.mkdir(parents=True, exist_ok=True)
    relatorios = ler_registros(index_path)

    for relatorio in relatorios:
        nome_pasta = relatorio.get("pasta")
        if not nome_pasta:
            relatorio["status"] = relatorio.get("status") or "pendente"
            continue
        if not isinstance(nome_pasta, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]+", nome_pasta
        ):
            raise ValueError("Nome de pasta inválido no índice: {}.".format(nome_pasta))
        pasta_relatorio = pasta_relatorios / nome_pasta
        caminho_dados_pregao = pasta_relatorio / "dados_pregao.json"
        caminho_dados = pasta_relatorio / "dados_empenhos.json"
        caminho_metadados = pasta_relatorio / "metadados.json"
        existe_arquivo_dados = any(
            caminho.exists()
            for caminho in (caminho_dados_pregao, caminho_dados, caminho_metadados)
        )
        if not all(
            caminho.is_file()
            for caminho in (caminho_dados_pregao, caminho_dados, caminho_metadados)
        ):
            if existe_arquivo_dados or relatorio.get("status") != "pendente":
                relatorio["status"] = "erro"
                relatorio["erro"] = (
                    "Dados incompletos; esperados dados_pregao.json, "
                    "dados_empenhos.json e metadados.json."
                )
            continue

        _ler_json(caminho_dados_pregao)
        dados_empenhos = _ler_json(caminho_dados)
        metadados = _ler_json(caminho_metadados)
        arquivo_html = metadados.get("arquivo_html")
        if not isinstance(arquivo_html, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]+\.html", arquivo_html
        ):
            raise ValueError("Nome do HTML inválido nos metadados de {}.".format(pasta_relatorio))

        caminho_html = pasta_relatorio / arquivo_html
        gerar_relatorio_html(
            dados_empenhos,
            caminho_html,
            gerado_em=metadados.get("atualizado_em"),
        )

        report_data = _dados_embutidos(caminho_html)
        resumo_cards = _resumo_cards(report_data)
        metadados["resumo_cards"] = resumo_cards
        _escrever_texto(caminho_metadados, json.dumps(metadados, ensure_ascii=False, indent=2) + "\n")
        relatorio.update(
            {
                "status": (
                    "erro"
                    if relatorio.get("status") == "erro"
                    else "parcial"
                    if report_data.get("erros_resultados_itens")
                    else "atualizado"
                ),
                "arquivo_html": arquivo_html,
                "url_pncp": metadados.get("url_pncp") or relatorio.get("url_pncp"),
                "atualizado_em": metadados.get("atualizado_em"),
                "chaves_integracao": metadados.get("chaves_integracao") or {},
                "objeto": report_data.get("objeto"),
                "resumo_cards": resumo_cards,
            }
        )

    salvar_registros(relatorios, index_path)
    return _gerar_index_html(pasta_relatorios, relatorios)


def _dados_embutidos(caminho_html: Path) -> Dict[str, Any]:
    conteudo = caminho_html.read_text(encoding="utf-8")
    inicio = '<script id="report-data" type="application/json">'
    fim = "</script>"
    trecho = conteudo.split(inicio, 1)
    if len(trecho) != 2 or fim not in trecho[1]:
        raise ValueError("Dados do relatório não encontrados em {}.".format(caminho_html))
    dados = json.loads(trecho[1].split(fim, 1)[0])
    if not isinstance(dados, dict):
        raise ValueError("Dados do relatório inválidos em {}.".format(caminho_html))
    return dados


def gerar_index_relatorios(pasta_relatorios: Path) -> Path:
    return gerar_relatorios(pasta_relatorios)


if __name__ == "__main__":
    reports_dir = Path(__file__).resolve().parent
    from pncp_tracker.process_lock import interprocess_lock, lock_path_for

    with interprocess_lock(lock_path_for(reports_dir / "indice_relatorios.json")):
        gerar_relatorios(reports_dir)
