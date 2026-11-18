import html as html_lib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from .empenho_portal import quantidade_estimada


_BRAZIL_TIMEZONE = timezone(timedelta(hours=-3))
AVISO_USO_DADOS = (
    "Este é um relatório auxiliar, elaborado com dados publicados no "
    "Portal Nacional de Contratações Públicas (PNCP) e complementado, quando "
    "disponíveis, por informações do Portal da Transparência e do Contratos.gov.br. "
    "As informações exibidas nesta página não são atualizadas em tempo real: para "
    "que mudanças nas fontes apareçam, é necessária uma nova atualização do "
    "processo, feita pelo administrador ou pela rotina de atualização configurada. "
    "Observe sempre a data e o horário da última atualização exibidos para o "
    "processo. Podem ocorrer atrasos, omissões, "
    "divergências ou falhas na integração e publicação de dados entre o "
    "Contratos.gov.br — integrado ao SIAFI para emissão de notas de empenho — e o PNCP, além "
    "de limitações na coleta e no cruzamento automatizado das informações. Os "
    "resultados podem estar incompletos ou desatualizados e não substituem a "
    "consulta e conferência dos registros originais. Utilize estas informações "
    "por sua conta e risco; antes de tomar decisões importantes, confirme os dados "
    "diretamente nos sistemas e fontes oficiais pertinentes, como PNCP, "
    "Contratos.gov.br, SIAFI e Portal da Transparência. Inconsistências "
    "identificadas podem ser comunicadas para o e-mail tiago.possato@ifc.edu.br "
    "para avaliação e possíveis correções e melhorias do relatório."
)

AVISO_USO_DADOS = html_lib.escape(AVISO_USO_DADOS).replace(
    "tiago.possato@ifc.edu.br",
    '<a href="mailto:tiago.possato@ifc.edu.br">tiago.possato@ifc.edu.br</a>',
    )

def _numero(valor: Any) -> Optional[float]:
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace("R$", "").replace("\xa0", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _quantidade_empenhada(
    valor: Any,
    valor_unitario: Optional[float],
) -> Optional[float]:
    """Quantidade estimada da linha (valor ÷ preço unitário), com as casas decimais reais."""
    estimativa = quantidade_estimada(valor, valor_unitario)
    return None if estimativa is None else float(estimativa)


def _data_homologacao(valor: Any) -> Optional[str]:
    if not valor:
        return None
    texto = str(valor)
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except ValueError:
        return texto


def _url_ata(resultado: Dict[str, Any]) -> Optional[str]:
    url = resultado.get("urlAta") or resultado.get("linkAta")
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not (
            parsed.hostname == "pncp.gov.br"
            or parsed.hostname.endswith(".pncp.gov.br")
        )
    ):
        return None
    return url


def _como_dict(valor: Any) -> Dict[str, Any]:
    return valor if isinstance(valor, dict) else {}


def _chave_registro(registro: Dict[str, Any]) -> str:
    """Chave do empenho por documento completo; o número isolado se repete entre UGs."""
    detalhes = _como_dict(registro.get("detalhesPortalTransparencia"))
    codigo = re.sub(r"[^A-Za-z0-9]", "", str(detalhes.get("codigoDocumento") or ""))
    if codigo:
        return codigo
    unidade = re.sub(
        r"[^A-Za-z0-9]",
        "",
        str(_como_dict(registro.get("unidadeOrgao")).get("codigoUnidade") or ""),
    )
    numero = re.sub(r"[^A-Za-z0-9]", "", str(registro.get("numeroContratoEmpenho") or "")).upper()
    return f"{unidade}{numero}"


def _url_empenho_pncp(registro: Dict[str, Any], cnpj_orgao: Any) -> Optional[str]:
    """Página pública do contrato/empenho no PNCP (cnpj + ano + sequencial do contrato)."""
    cnpj = _como_dict(registro.get("orgaoEntidade")).get("cnpj") or cnpj_orgao
    ano = registro.get("anoContrato")
    sequencial = registro.get("sequencialContrato")
    cnpj_digitos = re.sub(r"\D", "", str(cnpj or ""))
    if not cnpj_digitos or not ano or sequencial is None:
        return None
    try:
        sequencial_numero = int(sequencial)
        ano_numero = int(ano)
    except (TypeError, ValueError):
        return None
    return "https://pncp.gov.br/app/contratos/{}/{}/{}".format(
        cnpj_digitos, ano_numero, sequencial_numero
    )


def _url_empenho_portal(codigo_documento: Any) -> Optional[str]:
    """Página do documento de despesa no Portal da Transparência."""
    codigo = re.sub(r"[^A-Za-z0-9]", "", str(codigo_documento or ""))
    if not codigo:
        return None
    return "https://portaldatransparencia.gov.br/despesas/empenho/{}".format(codigo)


def _resumir_registro_pncp(
    registro: Dict[str, Any],
    cnpj_orgao: Any = None,
) -> Dict[str, Any]:
    detalhes = _como_dict(registro.get("detalhesPortalTransparencia"))
    detalhamento = _como_dict(detalhes.get("detalhamento"))
    unidade = _como_dict(registro.get("unidadeOrgao"))
    itens_empenho = detalhamento.get("itensEmpenho") or []
    if not isinstance(itens_empenho, list):
        itens_empenho = []
    valor = _numero(detalhamento.get("valor"))
    if valor is None:
        valor = _numero(registro.get("valorGlobal"))
    if valor is None:
        valor = _numero(registro.get("valorInicial"))

    return {
        "numero": registro.get("numeroContratoEmpenho"),
        "tipo": _como_dict(registro.get("tipoContrato")).get("nome"),
        "fornecedor": detalhamento.get("nomeFavorecido")
        or registro.get("nomeRazaoSocialFornecedor"),
        "cnpj": detalhamento.get("codigoFavorecido") or registro.get("niFornecedor"),
        "unidade_codigo": detalhamento.get("codigoUg") or unidade.get("codigoUnidade"),
        "unidade_nome": detalhamento.get("ug") or unidade.get("nomeUnidade"),
        "objeto": registro.get("objetoContrato"),
        "valor": valor,
        "pncp_url": _url_empenho_pncp(registro, cnpj_orgao),
        "portal_url": _url_empenho_portal(detalhes.get("codigoDocumento")),
        "situacao": _como_dict(registro.get("situacao_empenho")).get("situacao"),
        "situacao_motivo": _como_dict(registro.get("situacao_empenho")).get("motivo"),
        "situacao_diferenca": _numero(
            _como_dict(registro.get("situacao_empenho")).get("diferenca")
        ),
        "portal_status": detalhes.get("status") or "nao_consultado",
        "portal_motivo": detalhes.get("mensagem")
        or detalhes.get("motivo")
        or detalhes.get("erro"),
        "itens_portal": [
            {
                "descricao": item.get("descricao"),
                "valor": _numero(item.get("valorAtual")),
            }
            for item in itens_empenho
            if isinstance(item, dict)
        ],
    }


def _preparar_relatorio(
    dados: Dict[str, Any],
    gerado_em: Optional[str] = None,
) -> Dict[str, Any]:
    itens: List[Dict[str, Any]] = []
    soma_empenhada = 0.0
    soma_estimada = 0.0
    soma_homologada = 0.0
    unidades_gestoras_por_empenho = {}
    origens_por_empenho = {}
    origem_organ_por_empenho = {}
    consome_saldo_por_empenho = {}
    for registro in dados.get("empenhos", []):
        detalhes_portal = _como_dict(registro.get("detalhesPortalTransparencia"))
        detalhes = _como_dict(detalhes_portal.get("detalhamento"))
        unidade_pncp = _como_dict(registro.get("unidadeOrgao"))
        chave = _chave_registro(registro)
        unidades_gestoras_por_empenho[chave] = {
            "codigo": detalhes.get("codigoUg") or unidade_pncp.get("codigoUnidade"),
            "nome": detalhes.get("ug") or unidade_pncp.get("nomeUnidade"),
        }
        origens_por_empenho[chave] = registro.get("origem") or "pncp"
        origem_organ_por_empenho[chave] = registro.get("origem_organ") or "original"
        consome_saldo_por_empenho[chave] = registro.get("consome_saldo", True)

    for item in dados.get("itens_mapeados", []):
        resultados = item.get("resultados", []) or []
        cnpjs_vencedores = {
            re.sub(r"\D", "", str(resultado.get("niFornecedor") or ""))
            for resultado in resultados
        }
        valores_unitarios = {
            re.sub(r"\D", "", str(resultado.get("niFornecedor") or "")): _numero(
                resultado.get("valorUnitarioHomologado")
            )
            for resultado in resultados
        }

        linhas_empenho = []
        total_empenhado_item = 0.0
        valor_empenhado_adesao = 0.0
        valor_empenhado_indefinido = 0.0
        quantidade_empenhada_item = 0.0
        quantidade_empenhada_adesao = 0.0
        possui_quantidade_empenhada = False
        linhas_que_consomem_saldo = 0

        for empenho_item in item.get("empenhos", []) or []:
            documento = empenho_item.get("item_despesa", {})
            chave_empenho = empenho_item.get("chave_empenho") or _chave_registro(
                {"numeroContratoEmpenho": empenho_item.get("numero_empenho")}
            )
            unidade_gestora = unidades_gestoras_por_empenho.get(chave_empenho, {})
            valor_empenhado = _numero(
                documento.get("valorAtual") or empenho_item.get("valor_empenhado")
            )
            fornecedor = re.sub(r"\D", "", str(empenho_item.get("fornecedor_cnpj") or ""))
            valor_unitario = valores_unitarios.get(fornecedor)
            quantidade_publicada = _numero(empenho_item.get("quantidade"))
            if quantidade_publicada is not None:
                quantidade = quantidade_publicada
            else:
                quantidade = _quantidade_empenhada(valor_empenhado, valor_unitario)
            consome = consome_saldo_por_empenho.get(chave_empenho, True)
            origem_organ = origem_organ_por_empenho.get(chave_empenho, "original")

            if consome:
                linhas_que_consomem_saldo += 1
                if valor_empenhado is not None:
                    total_empenhado_item += valor_empenhado
                if quantidade is not None:
                    quantidade_empenhada_item += quantidade
                    possui_quantidade_empenhada = True
            else:
                if valor_empenhado is not None:
                    if origem_organ == "adesao_posterior":
                        valor_empenhado_adesao += valor_empenhado
                    else:
                        valor_empenhado_indefinido += valor_empenhado
                if quantidade is not None:
                    quantidade_empenhada_adesao += quantidade

            linhas_empenho.append(
                {
                    "numero": empenho_item.get("numero_empenho"),
                    "data": empenho_item.get("data_emissao"),
                    "unidade_gestora_codigo": empenho_item.get("unidade_gestora_codigo")
                    or unidade_gestora.get("codigo"),
                    "unidade_gestora_nome": empenho_item.get("unidade_gestora_nome")
                    or unidade_gestora.get("nome"),
                    "fornecedor": empenho_item.get("nome_fornecedor"),
                    "valor": valor_empenhado,
                    "quantidade_estimada": quantidade,
                    "quantidade_origem": (
                        "contratos_gov"
                        if quantidade_publicada is not None
                        else empenho_item.get("quantidade_origem") or "estimada"
                    ),
                    "descricao": documento.get("descricao"),
                    "valor_unitario_homologado": valor_unitario,
                    "codigo_documento": documento.get("codigoItemEmpenho"),
                    "origem": origens_por_empenho.get(chave_empenho),
                    "origem_organ": origem_organ,
                    "consome_saldo": consome,
                    "flag_adesao_ausente": empenho_item.get("flag_adesao_ausente"),
                    "confianca": empenho_item.get("confianca"),
                }
            )

        valor_estimado = _numero(item.get("valor_total_estimado")) or 0
        valor_homologado = _numero(item.get("valor_total_homologado"))
        quantidade_licitada = _numero(item.get("quantidade_licitada"))
        quantidade_homologada = _numero(item.get("quantidade_homologada"))
        unidade = item.get("unidade_medida") or ""

        soma_estimada += valor_estimado
        if valor_homologado is not None:
            soma_homologada += valor_homologado
        soma_empenhada += total_empenhado_item

        if possui_quantidade_empenhada:
            quantidade_empenhada_estimada = round(quantidade_empenhada_item, 3)
        elif not linhas_que_consomem_saldo:
            quantidade_empenhada_estimada = 0
        else:
            quantidade_empenhada_estimada = None

        itens.append(
            {
                "numero": item.get("numero_item"),
                "descricao": item.get("descricao") or "",
                "unidade": unidade,
                "quantidade_licitada": quantidade_licitada,
                "quantidade_homologada": quantidade_homologada,
                "quantidade_empenhada_estimada": quantidade_empenhada_estimada,
                "valor_unitario_estimado": _numero(item.get("valor_unitario_estimado")),
                "valor_total_estimado": valor_estimado,
                "valor_unitario_homologado": _numero(item.get("valor_unitario_homologado")),
                "valor_total_homologado": valor_homologado,
                "valor_empenhado": total_empenhado_item,
                "valor_empenhado_adesao": valor_empenhado_adesao,
                "valor_empenhado_indefinido": valor_empenhado_indefinido,
                "quantidade_empenhada_adesao": round(quantidade_empenhada_adesao, 3),
                "resultados": [
                    {
                        "fornecedor": resultado.get("nomeRazaoSocialFornecedor"),
                        "cnpj": resultado.get("niFornecedor"),
                        "quantidade": _numero(resultado.get("quantidadeHomologada")),
                        "valor_unitario": _numero(resultado.get("valorUnitarioHomologado")),
                        "valor_total": _numero(resultado.get("valorTotalHomologado")),
                        "data_homologacao": _data_homologacao(
                            resultado.get("dataResultado")
                        ),
                        "url_ata": _url_ata(resultado),
                    }
                    for resultado in resultados
                ],
                "empenhos": linhas_empenho,
                "candidatos_sem_item": item.get("empenhos_fornecedor_sem_item_identificado", []),
                "candidatos_fornecedor_divergente": item.get(
                    "empenhos_item_sem_fornecedor_compativel", []
                ),
                "status": item.get("status"),
                "erro_resultados_homologados": item.get("erro_resultados_homologados"),
            }
        )

    itens.sort(key=lambda linha: (int(linha["numero"]) if str(linha["numero"]).isdigit() else 0))

    soma_adesao = sum(item.get("valor_empenhado_adesao") or 0 for item in itens)
    soma_indefinida = sum(item.get("valor_empenhado_indefinido") or 0 for item in itens)

    registros_por_origem = [
        registro.get("origem") or "pncp" for registro in dados.get("empenhos", [])
    ]
    quantidade_registros_pncp = dados.get("quantidade_empenhos_pncp")
    if quantidade_registros_pncp is None:
        quantidade_registros_pncp = registros_por_origem.count("pncp")
    quantidade_registros_portal = dados.get("quantidade_empenhos_portal")
    if quantidade_registros_portal is None:
        quantidade_registros_portal = sum(
            1 for origem in registros_por_origem if origem != "pncp"
        )
    registros_pncp = [
        _resumir_registro_pncp(
            registro,
            (dados.get("chaves_integracao") or {}).get("cnpj_orgao"),
        )
        for registro in dados.get("empenhos", [])
        if (registro.get("origem") or "pncp") == "pncp"
    ]

    if gerado_em:
        try:
            data_geracao = datetime.fromisoformat(gerado_em.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Data de atualização inválida nos metadados: {}.".format(gerado_em)) from exc
        if data_geracao.tzinfo is None:
            data_geracao = data_geracao.replace(tzinfo=_BRAZIL_TIMEZONE)
        gerado_em_formatado = data_geracao.astimezone(_BRAZIL_TIMEZONE).strftime("%d/%m/%Y %H:%M")
    else:
        gerado_em_formatado = datetime.now(_BRAZIL_TIMEZONE).strftime("%d/%m/%Y %H:%M")

    return {
        "status": dados.get("status"),
        "mensagem": dados.get("mensagem"),
        "chaves": dados.get("chaves_integracao", {}),
        "quantidade_registros": dados.get("quantidade_empenhos", 0),
        "quantidade_registros_pncp": quantidade_registros_pncp,
        "quantidade_registros_portal": quantidade_registros_portal,
        "registros_pncp": registros_pncp,
        "situacoes_empenhos": dados.get("situacoes_empenhos") or {},
        "quantidade_documentos_descartados": len(
            dados.get("empenhos_nao_confirmados", [])
        ),
        "quantidade_empenhos_detalhados": dados.get("quantidade_empenhos_com_detalhes", 0),
        "quantidade_itens": len(itens),
        "valor_estimado": soma_estimada,
        "valor_homologado": soma_homologada,
        "valor_empenhado_mapeado": soma_empenhada,
        "valor_empenhado_adesao": soma_adesao,
        "valor_empenhado_indefinido": soma_indefinida,
        "itens": itens,
        "erros_resultados_itens": dados.get("erros_resultados_itens", []),
        "gerado_em": gerado_em_formatado,
    }


_HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Relatório consolidado da compra</title>
<style>
:root{--ink:#172b4d;--muted:#60718a;--blue:#174ea6;--teal:#087e75;--line:#dce4ef;--bg:#f4f7fb;--white:#fff;--amber:#9a5b00;--red:#a12a26}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "Segoe UI",Arial,sans-serif}
.wrap{max-width:1500px;margin:auto;padding:28px 22px 50px}.hero{background:linear-gradient(115deg,#103c78,#176b76);color:white;border-radius:16px;padding:28px 32px;box-shadow:0 10px 24px #153d6d25}
.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:11px;opacity:.8}.hero h1{margin:6px 0 8px;font-size:clamp(24px,3vw,34px);line-height:1.2}.hero p{margin:0;max-width:980px;color:#e3efff}.meta{display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:18px;font-size:12px;color:#eaf3ff}.hero a{color:inherit;text-underline-offset:2px}.hero a:focus-visible{outline:2px solid currentColor;outline-offset:3px}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:18px 0}.card,.panel{background:var(--white);border:1px solid var(--line);border-radius:12px;box-shadow:0 2px 8px #18345608}.card{padding:16px 18px}.card .label{font-size:12px;color:var(--muted)}.card .value{font-size:22px;font-weight:700;margin:4px 0}.card .sub{font-size:11px;color:var(--muted)}
.panel{padding:18px;margin:16px 0}.panel h2{margin:0 0 12px;font-size:18px}.note{border-left:4px solid #e6a23c;background:#fff8e9;padding:12px 14px;border-radius:4px;color:#614819;margin:14px 0}
.status-filters{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.status-filters button{border:1px solid var(--line);border-radius:20px;background:white;color:var(--ink);padding:7px 12px;font:inherit;font-size:12px;cursor:pointer}.status-filters button[aria-pressed="true"]{background:var(--blue);border-color:var(--blue);color:white}.status-filters button:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
.toolbar{display:flex;gap:12px;align-items:center;margin:10px 0 14px;flex-wrap:wrap}.toolbar input{flex:1;min-width:220px;padding:10px 12px;border:1px solid #c9d4e2;border-radius:8px;font:inherit}.toolbar button{border:0;border-radius:8px;background:var(--blue);color:white;padding:10px 14px;font:inherit;cursor:pointer}.toolbar button:focus-visible{outline:2px solid var(--blue);outline-offset:2px}.retry-form{display:inline-flex;margin:0}.retry-form button{background:var(--amber)}.count{color:var(--muted);font-size:12px}
.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:9px}table{border-collapse:collapse;width:100%;min-width:1120px;background:white}th{position:sticky;top:0;background:#edf3fa;color:#314963;text-align:right;font-size:11px;text-transform:uppercase;letter-spacing:.04em;padding:11px 10px;border-bottom:1px solid var(--line);white-space:nowrap;cursor:pointer;user-select:none}th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}th:focus-visible{outline:2px solid var(--blue);outline-offset:-2px}th[aria-sort="ascending"]::after{content:" ▲";color:var(--blue)}th[aria-sort="descending"]::after{content:" ▼";color:var(--blue)}td{padding:10px;border-bottom:1px solid #e9eef4;text-align:right;vertical-align:top}tr.item-row{cursor:pointer}tr.item-row:hover{background:#f7fbff}.item-name{font-weight:600;min-width:230px}.item-name small{display:block;color:var(--muted);font-weight:400;margin-top:3px}.num{font-variant-numeric:tabular-nums;white-space:nowrap}.detail-row{display:none;background:#f8fafc}.detail-row.open{display:table-row}.detail-cell{text-align:left!important;padding:16px 20px!important}.detail-grid{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,7fr);gap:16px}.detail-box{border:1px solid var(--line);background:white;border-radius:8px;padding:12px}.detail-box h3{margin:0 0 8px;font-size:13px}.detail-box p{margin:4px 0}.detail-table{min-width:600px;font-size:12px}.detail-table th,.detail-table td{text-align:left;padding:7px}.badge{display:inline-block;border-radius:20px;padding:2px 8px;background:#e6f4f1;color:#12695e;font-size:11px}.badge.pending{background:#fff0d6;color:var(--amber)}.badge.no{background:#fbe9e8;color:var(--red)}.bar{height:5px;background:#e7edf5;border-radius:5px;margin-top:5px;overflow:hidden}.bar span{display:block;height:100%;background:var(--teal)}
.foot{color:var(--muted);font-size:11px;margin:16px 2px}.empty{text-align:center;color:var(--muted);padding:26px}.source-list{display:flex;gap:8px;flex-wrap:wrap}.source-list span{background:#edf3fa;border-radius:5px;padding:4px 8px;font-size:11px}#pncp-records-table th,#pncp-records-table td{text-align:left}#pncp-records-table td:nth-child(4){min-width:280px;overflow-wrap:anywhere}.muted{color:var(--muted);font-size:11px;margin-top:2px}details.panel>summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:18px;font-weight:700}details.panel>summary::-webkit-details-marker{display:none}details.panel>summary::before{content:"▸";color:var(--blue);font-size:14px}details.panel[open]>summary::before{content:"▾"}details.panel>summary:focus-visible{outline:2px solid var(--blue);outline-offset:3px;border-radius:4px}details.panel[open]>summary{margin-bottom:12px}.summary-count{font-size:12px;font-weight:400;color:var(--muted)}.link-cell{white-space:nowrap}.link-cell a{display:inline-block;margin:0 6px 2px 0;font-size:11px}.link-cell span{color:var(--muted);font-size:11px}
.report-footer{display:flex;flex-wrap:wrap;gap:6px 24px;margin:16px 2px;color:var(--muted);font-size:12px}
.disclaimer{background:#fff3e0;border:1px solid #e8c98e;border-left:5px solid #a56300;border-radius:8px;color:#513500;margin:24px 0 0;padding:16px 20px}.disclaimer h2{font-size:16px;margin:0 0 6px}.disclaimer p{margin:0}
@media(max-width:900px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.detail-grid{grid-template-columns:1fr}}
@media(max-width:520px){.wrap{padding:14px 10px 30px}.hero{padding:21px 18px}.cards{grid-template-columns:1fr 1fr;gap:8px}.card{padding:12px}.card .value{font-size:17px}.panel{padding:12px}.meta{display:grid;gap:4px}}
@media print{body{background:white}.wrap{max-width:none;padding:0}.hero{box-shadow:none;border-radius:0;-webkit-print-color-adjust:exact;print-color-adjust:exact}.card,.panel{box-shadow:none;break-inside:avoid}.toolbar{display:none}table{min-width:0;font-size:10px}th,td{padding:5px}.detail-row{display:table-row!important}.item-row{break-after:avoid}.panel{margin:9px 0}}
</style>
</head>
<body>
<main class="wrap">
  <header class="hero">
    <div class="eyebrow">Compras públicas · Relatório de execução</div>
    <h1 id="title">Relatório da contratação</h1>
    <p id="object"></p>
    <div class="meta"><span id="pncp"></span><span id="org"></span><span id="generated"></span><a href="../">Página inicial</a></div>
  </header>
  <section class="cards" id="cards"></section>
  <div class="note" id="collection-warning" hidden></div>
  <div class="note"><strong>Como interpretar:</strong> “Quantidade empenhada (estimada)” usa a quantidade publicada na Contratos.gov.br quando disponível; caso contrário, é calculada dividindo o valor das linhas de empenho pelo preço unitário homologado, com as casas decimais reais do resultado. Só são somadas linhas em que o número do item e o CNPJ do fornecedor correspondem ao resultado homologado. Valores/quantidades sem correspondência ficam separados como pendentes.</div>
    <div class="note"><strong>Adesão e compra compartilhada:</strong> em compras compartilhadas ou com adesão, o empenho pode ter processo e unidade gestora diferentes dos da compra. Empenhos marcados como <em>adesão posterior</em> — ou com origem de órgão <em>indefinida</em> — <strong>não</strong> reduzem a quantidade homologada nem entram na execução; eles aparecem em separado. Empenhos classificados como <em>original</em> (participante na origem) consomem o saldo normalmente.</div>
  <section class="panel">
    <h2>Itens da contratação</h2>
    <div class="status-filters" role="group" aria-label="Filtrar itens por situação de empenho">
      <button type="button" data-item-filter="todos" aria-pressed="true">Todos</button>
      <button type="button" data-item-filter="homologado" aria-pressed="false">Homologados</button>
      <button type="button" data-item-filter="empenhado" aria-pressed="false">Empenhados</button>
      <button type="button" data-item-filter="nao_empenhado" aria-pressed="false">Não empenhados</button>
      <button type="button" data-item-filter="deserto" aria-pressed="false">Desertos</button>
      <button type="button" data-item-filter="empenhado_por_adesao" aria-pressed="false">Empenho por adesão</button>
      <button type="button" data-item-filter="empenhado_origem_indefinida" aria-pressed="false">Origem indefinida</button>
      <button type="button" data-item-filter="pendente" aria-pressed="false">Resultados pendentes</button>
    </div>
    <div class="toolbar"><input id="search" type="search" placeholder="Filtrar por item, descrição, fornecedor ou empenho…" aria-label="Filtrar itens"><span class="count" id="count"></span><!-- admin-retry --><button type="button" id="download-csv">Baixar CSV completo</button></div>
    <div class="table-wrap"><table id="items-table"><thead><tr>
      <th>Item</th><th>Descrição / unidade</th><th>Qtd. licitada</th><th>Qtd. homologada</th><th>Qtd. empenhada*</th><th>Saldo do item</th><th>Estimado</th><th>Homologado</th><th>Empenhado mapeado</th><th>Execução</th>
    </tr></thead><tbody id="items"></tbody></table></div>
    <p class="foot">Clique em uma linha para abrir fornecedores e empenhos. Quantidades de unidades diferentes não são somadas em um único total.</p>
  </section>
  <details class="panel" id="pncp-records-panel" hidden>
    <summary><span class="summary-title">Registros recebidos da aba Contratos/Empenhos do PNCP</span> <span class="summary-count" id="pncp-records-count"></span></summary>
    <p class="foot">Todos os registros retornados pelo PNCP são preservados aqui. O Portal da Transparência apenas complementa os itens; a falta desse detalhamento não remove o registro PNCP nem o associa artificialmente a um item. Cada linha traz o atalho para o registro no PNCP e, quando houver, para o documento de despesa no Portal da Transparência.</p>
    <div class="table-wrap"><table id="pncp-records-table"><thead><tr>
      <th>Registro PNCP</th><th>Fornecedor</th><th>UG</th><th>Objeto publicado</th><th>Valor publicado</th><th>Situação verificada</th><th>Itens / detalhamento no Portal</th><th>Links</th>
    </tr></thead><tbody id="pncp-records"></tbody></table></div>
  </details>
  <footer class="report-footer" aria-label="Resumo dos registros">
    <span>Documentos descartados: <strong id="discarded-count"></strong></span>
    <span>Origem dos registros: <strong id="record-origins"></strong></span>
    <span>Situação dos registros: <strong id="record-situations"></strong></span>
  </footer>
  <section class="panel">
    <h2>Fontes e critérios</h2>
    <div class="source-list"><span>PNCP — dados do edital e aba Contratos/Empenhos</span><span>Portal da Transparência — detalhes e itens das notas de empenho</span><span>Contratos.gov.br — identidade da compra e quantidade dos itens</span></div>
    <p class="foot">Valores empenhados por item são calculados a partir das linhas do documento de despesa. O valor consolidado por item conta somente correspondências de número do item e fornecedor homologado.</p>
  </section>
  <aside class="disclaimer" role="note" aria-labelledby="disclaimer-title">
    <h2 id="disclaimer-title">Aviso importante</h2>
    <p>__DISCLAIMER_TEXT__</p>
  </aside>
</main>
<script id="report-data" type="application/json">__REPORT_DATA__</script>
<script>
const D=JSON.parse(document.getElementById('report-data').textContent);
const fmtMoney=n=>n==null?'—':new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(n);
const fmtQty=n=>n==null?'—':new Intl.NumberFormat('pt-BR',{maximumFractionDigits:3}).format(n);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const origemLabels={pncp:'PNCP',portal_contrato:'Portal (contrato)',portal_licitacao:'Portal (licitação)',portal_favorecido:'Portal (favorecido)'};
const origemLabel=valor=>origemLabels[valor]||(valor?String(valor):'—');
const adesaoLabels={original:'Não',propria_ug:'Não (própria UG)',adesao_posterior:'Sim (adesão posterior)',indefinido:'Indefinido'};
const adesaoLabel=e=>{
 if(e.origem_organ==='original'&&e.flag_adesao_ausente)return 'Não';
 return adesaoLabels[e.origem_organ]||(e.consome_saldo===false?'Indefinido':'—');
};
const number=n=>Number.isFinite(Number(n))?Number(n):0;
const pct=(a,b)=>b>0?Math.min(100,(a/b)*100):0;
const itemStatus=i=>{
 if(i.status==='resultados_homologados_indisponiveis')return 'pendente';
 if(number(i.valor_total_homologado)===0)return 'deserto';
 if(pct(number(i.valor_empenhado),number(i.valor_total_homologado))>0)return 'empenhado';
 const origens=new Set((i.empenhos||[]).filter(e=>e.consome_saldo===false).map(e=>e.origem_organ));
 if(origens.has('adesao_posterior'))return 'empenhado_por_adesao';
 if(origens.size)return 'empenhado_origem_indefinida';
 return 'nao_empenhado';
};
const statusLabels={deserto:'Deserto',empenhado:'Empenhado',nao_empenhado:'Não empenhado',empenhado_por_adesao:'Empenho por adesão',empenhado_origem_indefinida:'Origem indefinida',pendente:'Resultados pendentes'};
function sortableValue(text){
 const value=text.trim().replace(/\s+/g,' ');
 if(!value||value==='—')return {type:'empty',value:''};
 const date=value.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
 if(date)return {type:'number',value:Number(`${date[3]}${date[2]}${date[1]}`)};
 const isoDate=value.match(/^(\d{4})-(\d{2})-(\d{2})/);
 if(isoDate)return {type:'number',value:Number(`${isoDate[1]}${isoDate[2]}${isoDate[3]}`)};
 const numeric=value.replace(/R\$/g,'').replace(/%/g,'').replace(/\s/g,'');
 if(/^[+-]?\d[\d.,]*$/.test(numeric)){
  const normalized=numeric.includes(',')?numeric.replace(/\./g,'').replace(',','.'):numeric;
  const parsed=Number(normalized);
  if(Number.isFinite(parsed))return {type:'number',value:parsed};
 }
 return {type:'text',value};
}
function compareRows(a,b,column,direction){
 const leftCell=a.cells[column],rightCell=b.cells[column];
 const left=sortableValue(leftCell?.dataset.sortValue??leftCell?.innerText??'');
 const right=sortableValue(rightCell?.dataset.sortValue??rightCell?.innerText??'');
 let result;
 if(left.type==='empty'||right.type==='empty')return left.type===right.type?0:left.type==='empty'?1:-1;
 else if(left.type==='number'&&right.type==='number')result=left.value-right.value;
 else result=String(left.value).localeCompare(String(right.value),'pt-BR',{numeric:true,sensitivity:'base'});
 return result*direction;
}
function sortTable(table,column){
 const body=table.tBodies[0];
 if(!body)return;
 const previous=Number(table.dataset.sortColumn);
 const direction=previous===column&&table.dataset.sortDirection==='ascending'?-1:1;
 table.dataset.sortColumn=String(column);
 table.dataset.sortDirection=direction===1?'ascending':'descending';
 Array.from(table.tHead?.rows[0]?.cells||[]).forEach((header,index)=>{
  header.setAttribute('aria-sort',index===column?table.dataset.sortDirection:'none');
  header.title=`Ordenar por ${header.innerText.trim()}`;
 });
 if(table.id==='items-table'){
  const pairs=[];
  for(let index=0;index<body.rows.length;index++){
   const row=body.rows[index];
   if(!row.classList.contains('item-row'))continue;
   pairs.push([row,row.nextElementSibling]);
  }
  pairs.sort((a,b)=>compareRows(a[0],b[0],column,direction));
  pairs.forEach(pair=>pair.forEach(row=>row&&body.appendChild(row)));
  return;
 }
 Array.from(body.rows)
  .sort((a,b)=>compareRows(a,b,column,direction))
  .forEach(row=>body.appendChild(row));
}
document.addEventListener('click',event=>{
 const header=event.target.closest('th');
 const table=header?.closest('table');
 if(header&&table)sortTable(table,header.cellIndex);
});
document.addEventListener('keydown',event=>{
 if((event.key==='Enter'||event.key===' ')&&event.target.matches('th')){
  event.preventDefault();
  const header=event.target;
  const table=header.closest('table');
  if(table)sortTable(table,header.cellIndex);
 }
});
function prepareSortableHeaders(){
 document.querySelectorAll('thead th').forEach(header=>{
  header.tabIndex=0;
  header.setAttribute('role','button');
  if(!header.hasAttribute('aria-sort'))header.setAttribute('aria-sort','none');
  header.title=`Ordenar por ${header.innerText.trim()}`;
 });
}
document.getElementById('title').textContent=`Edital nº ${D.chaves.numero_compra||''}/${D.chaves.ano_compra||''}`;
document.getElementById('object').textContent=D.objeto||'Relatório consolidado dos itens e empenhos publicados.';
const pncp=document.getElementById('pncp');
const controlePncp=D.chaves.numero_controle_pncp||'';
const pncpMatch=controlePncp.match(/^(\d{14})-\d+-(\d+)\/(\d{4})$/);
if(pncpMatch){
 const link=document.createElement('a');
 link.href=`https://pncp.gov.br/app/editais/${pncpMatch[1]}/${pncpMatch[3]}/${pncpMatch[2]}`;
 link.target='_blank';
 link.rel='noopener noreferrer';
 link.textContent=`Controle PNCP: ${controlePncp}`;
 pncp.append(link);
}else{
 pncp.textContent=`Controle PNCP: ${controlePncp||'—'}`;
}
document.getElementById('org').textContent=`Unidade: ${D.chaves.uasg_codigo||'—'} ${D.chaves.uasg_nome||''} · CNPJ: ${D.chaves.cnpj_orgao||'—'}`;
document.getElementById('generated').textContent=`Gerado em ${D.gerado_em}`;
const collectionErrors=D.erros_resultados_itens||[];
if(collectionErrors.length){
 const warning=document.getElementById('collection-warning');
 warning.hidden=false;
 warning.textContent=`Aviso: não foi possível consultar os resultados homologados de ${collectionErrors.length} item(ns). Eles estão marcados como pendentes e não são contabilizados como desertos. Itens: ${collectionErrors.map(error=>error.numero_item).join(', ')}.`;
}
const committed=D.valor_empenhado_mapeado||0;
const statusCounts=D.itens.reduce((counts,item)=>{counts[itemStatus(item)]++;return counts;},{deserto:0,empenhado:0,nao_empenhado:0,empenhado_por_adesao:0,empenhado_origem_indefinida:0,pendente:0});
const cards=[
 ['Itens',''+D.quantidade_itens,'Itens publicados no edital'],
 ['Itens homologados',fmtQty(statusCounts.empenhado+statusCounts.nao_empenhado+statusCounts.empenhado_por_adesao+statusCounts.empenhado_origem_indefinida),'Itens empenhados + não empenhados'],
 ['Itens empenhados',fmtQty(statusCounts.empenhado),'Execução acima de 0% com empenho que consome a quantidade'],
 ['Itens não empenhados',fmtQty(statusCounts.nao_empenhado),'Execução igual a 0%, excluídos desertos'],
 ['Empenho por adesão',fmtQty(statusCounts.empenhado_por_adesao),'Itens com empenho apenas de adesão posterior'],
 ['Origem indefinida',fmtQty(statusCounts.empenhado_origem_indefinida),'Itens empenhados sem classificação de origem do órgão'],
 ['Itens desertos',fmtQty(statusCounts.deserto),'Valor homologado igual a R$ 0,00'],
 ['Resultados pendentes',fmtQty(statusCounts.pendente),'Falha ao consultar resultados no PNCP'],
 ['Valor estimado',fmtMoney(D.valor_estimado),'Soma dos valores estimados por item'],
 ['Valor homologado',fmtMoney(D.valor_homologado),'Soma dos resultados homologados'],
 ['Empenhado mapeado',fmtMoney(committed),`${D.quantidade_empenhos_detalhados} de ${D.quantidade_registros} registros com detalhamento`],
 ['Empenhado por adesão',fmtMoney(D.valor_empenhado_adesao||0),'Adesão posterior não consome a quantidade homologada'],
];
document.getElementById('cards').innerHTML=cards.map(c=>`<div class="card"><div class="label">${esc(c[0])}</div><div class="value">${esc(c[1])}</div><div class="sub">${esc(c[2])}</div></div>`).join('');
document.getElementById('discarded-count').textContent=fmtQty(D.quantidade_documentos_descartados||0);
document.getElementById('record-origins').textContent=`${fmtQty(D.quantidade_registros_pncp||0)} PNCP · ${fmtQty(D.quantidade_registros_portal||0)} Portal`;
const pncpRecords=D.registros_pncp||[];
document.getElementById('pncp-records-panel').hidden=!pncpRecords.length;
document.getElementById('pncp-records-count').textContent=`(${fmtQty(pncpRecords.length)} registro(s))`;
const situacaoEmpenhoLabels={normal:'Sem alteração',reforcado:'Reforçado',anulado:'Anulado parcialmente',cancelado:'Cancelado',alterado:'Retificado',nao_localizado:'Não localizado no Portal',nao_aplicavel:'Sem nota de empenho',indeterminado:'Não verificado'};
document.getElementById('pncp-records').innerHTML=pncpRecords.map(record=>{
 const items=(record.itens_portal||[]).map(item=>`<div>${esc(item.descricao||'Item sem descrição')} · ${fmtMoney(item.valor)}</div>`).join('');
 const statusLabels={ok:'Detalhamento obtido',nao_encontrado:'Detalhamento não localizado',nao_consultado:'Não consultado',erro:'Erro no detalhamento'};
 const detail=items||`<span class="muted">${esc(statusLabels[record.portal_status]||record.portal_status||'Sem detalhamento')}</span>`;
 const reason=record.portal_motivo?`<div class="muted">${esc(record.portal_motivo)}</div>`:'';
 const situacao=record.situacao||'indeterminado';
 const classeSituacao=situacao==='normal'?'':situacao==='nao_localizado'||situacao==='cancelado'||situacao==='anulado'?' badge no':' badge pending';
 const diferenca=number(record.situacao_diferenca)?`<div class="muted">Diferença: ${fmtMoney(record.situacao_diferenca)}</div>`:'';
 const situacaoHtml=`<span class="badge${classeSituacao}">${esc(situacaoEmpenhoLabels[situacao]||situacao)}</span>${record.situacao_motivo?`<div class="muted">${esc(record.situacao_motivo)}</div>`:''}${diferenca}`;
 const links=[];if(record.pncp_url)links.push(`<a href="${esc(record.pncp_url)}" target="_blank" rel="noopener noreferrer">PNCP</a>`);if(record.portal_url)links.push(`<a href="${esc(record.portal_url)}" target="_blank" rel="noopener noreferrer">Portal</a>`);const linksHtml=links.length?links.join(''):'<span>—</span>';
 return `<tr><td>${esc(record.numero||'—')}${record.tipo?`<div class="muted">${esc(record.tipo)}</div>`:''}</td><td>${esc(record.fornecedor||'—')}<div class="muted">${esc(record.cnpj||'')}</div></td><td>${esc(record.unidade_codigo||'—')}<div class="muted">${esc(record.unidade_nome||'')}</div></td><td>${esc(record.objeto||'—')}</td><td>${fmtMoney(record.valor)}</td><td>${situacaoHtml}</td><td>${detail}${reason}</td><td class="link-cell">${linksHtml}</td></tr>`;
}).join('');
window.addEventListener('beforeprint',()=>{const painel=document.getElementById('pncp-records-panel');if(painel&&!painel.hidden)painel.open=true;});
const situacoesRegistros=D.situacoes_empenhos||{};
document.getElementById('record-situations').textContent=Object.keys(situacoesRegistros).length
 ?Object.entries(situacoesRegistros).map(([chave,valor])=>`${fmtQty(valor)} ${(situacaoEmpenhoLabels[chave]||chave).toLowerCase()}`).join(' · ')
 :'—';
const tbody=document.getElementById('items');
let selectedItemFilter='todos';
function detailHtml(i){
 const suppliers=(i.resultados||[]).map(r=>`<div class="detail-box"><h3>${esc(r.fornecedor||'Fornecedor não informado')}</h3><p>CNPJ: ${esc(r.cnpj||'—')}</p><p>Data da homologação: ${esc(r.data_homologacao||'—')}</p><p>Quantidade homologada: ${fmtQty(r.quantidade)} ${esc(i.unidade)}</p><p>Preço unitário: ${fmtMoney(r.valor_unitario)} · Total: ${fmtMoney(r.valor_total)}</p>${r.url_ata?`<p><a href="${esc(r.url_ata)}" target="_blank" rel="noopener noreferrer">Ata de registro de preços</a></p>`:''}</div>`).join('')||'<div class="detail-box">Sem resultado homologado publicado.</div>';
 const emps=(i.empenhos||[]).map(e=>`<tr><td>${esc(e.numero)}</td><td>${esc(e.unidade_gestora_codigo||'—')}</td><td>${esc(e.unidade_gestora_nome||'—')}</td><td>${esc(e.data||'—')}</td><td>${esc(e.fornecedor||'—')}</td><td data-sort-value="${esc(e.valor)}">${fmtMoney(e.valor)}</td><td data-sort-value="${esc(e.quantidade_estimada)}">${fmtQty(e.quantidade_estimada)} ${esc(i.unidade)}</td><td>${esc(e.descricao||'—')}</td><td>${esc(origemLabel(e.origem))}</td><td>${esc(adesaoLabel(e))}</td><td>${e.codigo_documento?`<a href="https://portaldatransparencia.gov.br/despesas/empenho/${encodeURIComponent(e.codigo_documento)}" target="_blank" rel="noopener noreferrer">Abrir</a>`:'—'}</td></tr>`).join('');
 const candidates=[...(i.candidatos_sem_item||[]),...(i.candidatos_fornecedor_divergente||[])];
 return `<div class="detail-grid"><div><h3>Resultado(s) homologado(s)</h3>${suppliers}</div><div><h3>Empenhos vinculados ao item</h3>${emps?`<div class="table-wrap"><table class="detail-table"><thead><tr><th>Empenho</th><th>UASG</th><th>Unidade</th><th>Emissão</th><th>Fornecedor</th><th>Valor da linha</th><th>Qtd. estimada</th><th>Descrição do item no empenho</th><th>Origem</th><th>Adesão</th><th>Portal</th></tr></thead><tbody>${emps}</tbody></table></div>`:'<div class="detail-box">Nenhum empenho com item e fornecedor compatíveis.</div>'}</div></div>${candidates.length?`<div class="note"><strong>Não contabilizados:</strong> ${candidates.map(x=>esc(x.numero_empenho)).join(', ')} — sem correspondência suficiente para este item.</div>`:''}`;
}
function render(filter=document.getElementById('search').value){
 const itemsTable=document.getElementById('items-table');
 delete itemsTable.dataset.sortColumn;
 delete itemsTable.dataset.sortDirection;
 itemsTable.querySelectorAll('thead th').forEach(header=>header.setAttribute('aria-sort','none'));
 const q=filter.trim().toLocaleLowerCase('pt-BR');
 const rows=D.itens.filter(i=>{
  const status=itemStatus(i);
  const matchesStatus=selectedItemFilter==='todos'
   ||(selectedItemFilter==='homologado'?['empenhado','nao_empenhado','empenhado_por_adesao','empenhado_origem_indefinida'].includes(status):status===selectedItemFilter);
  return matchesStatus&&(!q||[i.numero,i.descricao,i.unidade,...(i.resultados||[]).flatMap(r=>[r.fornecedor,r.cnpj]),...(i.empenhos||[]).map(e=>e.numero)].join(' ').toLocaleLowerCase('pt-BR').includes(q));
 });
 document.getElementById('count').textContent=`${rows.length} de ${D.itens.length} itens`;
 tbody.innerHTML=rows.map((i,n)=>{
  const detail=`detail-${n}`, ratio=pct(number(i.valor_empenhado),number(i.valor_total_homologado));
  const saldo=i.quantidade_homologada!=null&&i.quantidade_empenhada_estimada!=null
   ?i.quantidade_homologada-i.quantidade_empenhada_estimada:null;
  const status=statusLabels[itemStatus(i)];
  return `<tr class="item-row" data-detail="${detail}" data-item-status="${itemStatus(i)}"><td class="num" data-sort-value="${esc(i.numero)}">${esc(i.numero)}</td><td class="item-name" data-sort-value="${esc(i.descricao)}">${esc(i.descricao)}<small>${esc(i.unidade||'Unidade não informada')} · ${status}</small></td><td class="num" data-sort-value="${esc(i.quantidade_licitada)}">${fmtQty(i.quantidade_licitada)}</td><td class="num" data-sort-value="${esc(i.quantidade_homologada)}">${fmtQty(i.quantidade_homologada)}</td><td class="num" data-sort-value="${esc(i.quantidade_empenhada_estimada)}">${fmtQty(i.quantidade_empenhada_estimada)}</td><td class="num" data-sort-value="${esc(saldo)}">${fmtQty(saldo)}</td><td class="num" data-sort-value="${esc(i.valor_total_estimado)}">${fmtMoney(i.valor_total_estimado)}</td><td class="num" data-sort-value="${esc(i.valor_total_homologado)}">${fmtMoney(i.valor_total_homologado)}</td><td class="num" data-sort-value="${esc(i.valor_empenhado)}">${fmtMoney(i.valor_empenhado)}<div class="bar"><span style="width:${ratio}%"></span></div></td><td class="num" data-sort-value="${i.valor_total_homologado?ratio:''}">${i.valor_total_homologado?fmtQty(ratio)+'%':'—'}</td></tr><tr class="detail-row" id="${detail}"><td colspan="10" class="detail-cell">${detailHtml(i)}</td></tr>`;
 }).join('')||'<tr><td colspan="10" class="empty">Nenhum item corresponde ao filtro.</td></tr>';
 tbody.querySelectorAll('.item-row').forEach(row=>row.addEventListener('click',()=>document.getElementById(row.dataset.detail).classList.toggle('open')));
 prepareSortableHeaders();
}
function csvCell(value){
 let text=value==null?'':String(value);
 if(typeof value==='string'&&/^[\s]*[=+\-@]/.test(value))text="'"+text;
 return `"${text.replace(/"/g,'""').replace(/\r?\n/g,' ')}"`;
}
function gerarCsv(){
 const headers=['Número do item','Descrição','Unidade','Situação','Quantidade licitada','Quantidade homologada','Quantidade empenhada estimada','Saldo do item','Valor unitário estimado','Valor total estimado','Valor unitário homologado','Valor total homologado','Valor empenhado mapeado','Execução (%)','Número do empenho','Código da Unidade Gestora emissora','Nome da Unidade Gestora emissora','Data de emissão','Fornecedor do empenho','Valor da linha do empenho','Quantidade da linha','Origem da quantidade','Descrição do item no empenho','Código do documento','Origem do registro','Adesão','Confiança','Link do Portal da Transparência'];
 const linhas=[headers];
 D.itens.forEach(item=>{
  const homologado=number(item.valor_total_homologado);
  const empenhado=number(item.valor_empenhado);
  const execucao=pct(empenhado,homologado);
  const status=itemStatus(item);
  const base=[
   item.numero,item.descricao,item.unidade,
   statusLabels[status],
   item.quantidade_licitada,item.quantidade_homologada,item.quantidade_empenhada_estimada,
   item.quantidade_homologada!=null&&item.quantidade_empenhada_estimada!=null
    ?item.quantidade_homologada-item.quantidade_empenhada_estimada:null,
   item.valor_unitario_estimado,item.valor_total_estimado,item.valor_unitario_homologado,
   item.valor_total_homologado,item.valor_empenhado,homologado?execucao:null
  ];
 const empenhos=(status==='empenhado'||status==='empenhado_por_adesao'||status==='empenhado_origem_indefinida')&&item.empenhos.length?item.empenhos:[null];
  empenhos.forEach(empenho=>{
   const origemQuantidade=empenho?(empenho.quantidade_origem||'estimada'):null;
   linhas.push([...base,
    empenho?.numero,empenho?.unidade_gestora_codigo,empenho?.unidade_gestora_nome,
    empenho?.data,empenho?.fornecedor,empenho?.valor,
    empenho?.quantidade_estimada,origemQuantidade,empenho?.descricao,empenho?.codigo_documento,
    empenho?origemLabel(empenho.origem):null,
    empenho?adesaoLabel(empenho):null,
    empenho?.confianca,
    empenho?.codigo_documento?`https://portaldatransparencia.gov.br/despesas/empenho/${encodeURIComponent(empenho.codigo_documento)}`:null
   ]);
  });
 });
 return '\uFEFF'+linhas.map(linha=>linha.map(csvCell).join(';')).join('\r\n');
}
document.getElementById('download-csv').addEventListener('click',()=>{
 const blob=new Blob([gerarCsv()],{type:'text/csv;charset=utf-8'});
 const link=document.createElement('a');
 const numero=String(D.chaves.numero_compra||'compra').replace(/[^A-Za-z0-9_-]+/g,'-');
 const ano=String(D.chaves.ano_compra||'').replace(/[^A-Za-z0-9_-]+/g,'-');
 link.href=URL.createObjectURL(blob);
 link.download=`relatorio_compra_${numero}_${ano}.csv`;
 link.click();
 setTimeout(()=>URL.revokeObjectURL(link.href),0);
});
render();
document.getElementById('search').addEventListener('input',e=>render(e.target.value));
document.querySelectorAll('[data-item-filter]').forEach(button=>button.addEventListener('click',()=>{
 selectedItemFilter=button.dataset.itemFilter;
 document.querySelectorAll('[data-item-filter]').forEach(option=>option.setAttribute('aria-pressed',String(option===button)));
 render();
}));
prepareSortableHeaders();
</script>
</body>
</html>"""


def gerar_relatorio_html(
    dados: Dict[str, Any],
    caminho_saida: Path,
    gerado_em: Optional[str] = None,
) -> Path:
    """Gera um relatório HTML autônomo, sem arquivos ou bibliotecas externas."""
    relatorio = _preparar_relatorio(dados, gerado_em=gerado_em)
    relatorio["objeto"] = dados.get("objeto")
    conteudo_json = json.dumps(relatorio, ensure_ascii=False, separators=(",", ":"))
    conteudo_json = conteudo_json.replace("</", "<\\/")
    # disclaimer_html = html_lib.escape(AVISO_USO_DADOS).replace(
    # "tiago.possato@ifc.edu.br",
    # '<a href="mailto:tiago.possato@ifc.edu.br">tiago.possato@ifc.edu.br</a>',
    # )
    html = _HTML.replace("__REPORT_DATA__", conteudo_json).replace(
        "__DISCLAIMER_TEXT__", AVISO_USO_DADOS
    )
    caminho_saida = Path(caminho_saida)
    with caminho_saida.open("w", encoding="utf-8", newline="\n") as arquivo:
        arquivo.write(html)
    return caminho_saida
