import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from .portal_transparencia import (
    PortalTransparenciaBlockedError,
    consultar_detalhes_documento_despesa,
    consultar_documentos_despesa_favorecido,
)

PORTAL_WORKERS = 4
TOLERANCIA_VALOR = 0.01


def _normalizar_numero_empenho(valor: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(valor or "")).upper()


def _valor_monetario(valor: Any) -> Optional[float]:
    """Converte valores do PNCP (float) e do Portal ("65,00") para número."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).replace("R$", "").strip()
    if not texto:
        return None
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def classificar_situacao_empenho(registro: Dict[str, Any]) -> Dict[str, Any]:
    """Compara o empenho publicado no PNCP com o documento atual do Portal.

    O PNCP informa o valor inicial, o valor global e o número de retificações; o Portal
    informa o valor vigente do documento. A diferença entre eles revela reforço, anulação
    ou cancelamento, e `numeroRetificacao` revela retificação sem mudança de valor.
    """
    detalhes = registro.get("detalhesPortalTransparencia") or {}
    detalhamento = detalhes.get("detalhamento") or {}
    valor_pncp = _valor_monetario(registro.get("valorGlobal"))
    if valor_pncp is None:
        valor_pncp = _valor_monetario(registro.get("valorInicial"))
    valor_inicial = _valor_monetario(registro.get("valorInicial"))
    valor_portal = _valor_monetario(detalhamento.get("valor"))
    try:
        retificacoes = int(registro.get("numeroRetificacao") or 0)
    except (TypeError, ValueError):
        retificacoes = 0

    diferenca: Optional[float] = None
    if valor_pncp is not None and valor_portal is not None:
        diferenca = round(valor_portal - valor_pncp, 2)

    status = detalhes.get("status")
    numero = str(registro.get("numeroContratoEmpenho") or "").upper()
    if "NE" not in numero:
        situacao = "nao_aplicavel"
        motivo = "Registro não é nota de empenho; não há documento de despesa a comparar."
    elif status == "nao_encontrado":
        situacao = "nao_localizado"
        motivo = (
            "Empenho publicado no PNCP não localizado no Portal da Transparência; "
            "pode indicar cancelamento ou anulação não publicada no PNCP."
        )
    elif status != "ok":
        situacao = "indeterminado"
        motivo = (
            detalhes.get("motivo")
            or detalhes.get("mensagem")
            or detalhes.get("erro")
            or "Detalhamento do Portal da Transparência indisponível."
        )
    elif valor_portal is not None and abs(valor_portal) <= TOLERANCIA_VALOR:
        situacao = "cancelado"
        motivo = "Documento do Portal com valor zerado."
    elif diferenca is not None and abs(diferenca) > TOLERANCIA_VALOR:
        if diferenca < 0:
            situacao = "anulado"
            motivo = "Valor do Portal menor que o valor global publicado no PNCP."
        else:
            situacao = "reforcado"
            motivo = "Valor do Portal maior que o valor global publicado no PNCP."
    elif (
        valor_pncp is not None
        and valor_inicial is not None
        and abs(valor_pncp - valor_inicial) > TOLERANCIA_VALOR
    ):
        if valor_pncp > valor_inicial:
            situacao = "reforcado"
            motivo = "Valor global do PNCP maior que o valor inicial."
        else:
            situacao = "anulado"
            motivo = "Valor global do PNCP menor que o valor inicial."
    elif retificacoes > 0:
        situacao = "alterado"
        motivo = "Registro com {} retificação(ões) no PNCP.".format(retificacoes)
    else:
        situacao = "normal"
        motivo = "Valores do PNCP e do Portal coincidem."

    return {
        "situacao": situacao,
        "motivo": motivo,
        "valor_inicial_pncp": valor_inicial,
        "valor_pncp": valor_pncp,
        "valor_portal": valor_portal,
        "diferenca": diferenca,
        "retificacoes": retificacoes,
    }


def enriquecer_empenhos_com_detalhes_portal(
    empenhos_pncp: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Adiciona detalhes e itens do Portal aos registros PNCP identificados como NE."""
    grupos: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    enriquecidos = [dict(empenho) for empenho in empenhos_pncp]
    erros: List[Dict[str, str]] = []

    for empenho in enriquecidos:
        detalhes_atuais = empenho.get("detalhesPortalTransparencia") or {}
        if detalhes_atuais.get("status") == "ok" and isinstance(
            detalhes_atuais.get("detalhamento"), dict
        ):
            continue
        numero = str(empenho.get("numeroContratoEmpenho") or "")
        unidade = str((empenho.get("unidadeOrgao") or {}).get("codigoUnidade") or "")
        if "NE" not in numero or not unidade:
            empenho["detalhesPortalTransparencia"] = {
                "status": "nao_consultado",
                "motivo": "Registro sem identificador de empenho ou unidade gestora.",
            }
            continue
        fornecedor = re.sub(r"\D", "", str(empenho.get("niFornecedor") or ""))
        if not fornecedor:
            empenho["detalhesPortalTransparencia"] = {
                "status": "nao_consultado",
                "motivo": "Registro sem CNPJ do fornecedor para consulta por favorecido.",
            }
            continue
        ano_empenho = re.match(r"^(\d{4})NE", numero, re.IGNORECASE)
        if not ano_empenho:
            empenho["detalhesPortalTransparencia"] = {
                "status": "nao_consultado",
                "motivo": "Não foi possível extrair o ano do número do empenho.",
            }
            continue
        ano = ano_empenho.group(1)
        grupos.setdefault((unidade, fornecedor, ano), []).append(empenho)

    documentos_por_grupo: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    grupos_com_erro: set[Tuple[str, str, str]] = set()
    bloqueio_portal = False

    def consultar_grupo(grupo: Tuple[str, str, str]):
        unidade, fornecedor, ano = grupo
        try:
            return grupo, consultar_documentos_despesa_favorecido(
                fornecedor, ano, unidade, fase=1
            ), None
        except Exception as exc:
            return grupo, [], exc

    if grupos:
        with ThreadPoolExecutor(max_workers=PORTAL_WORKERS) as pool:
            for grupo, documentos, exc in pool.map(consultar_grupo, list(grupos)):
                documentos_por_grupo[grupo] = documentos
                if exc is not None:
                    grupos_com_erro.add(grupo)
                    if isinstance(exc, PortalTransparenciaBlockedError):
                        bloqueio_portal = True
                    unidade, fornecedor, ano = grupo
                    erros.append(
                        {
                            "unidade_gestora": unidade,
                            "fornecedor": fornecedor,
                            "ano": ano,
                            "erro": f"{type(exc).__name__}: {exc}",
                        }
                    )

    pendentes: List[Tuple[Dict[str, Any], str, str]] = []
    pendentes_sem_ug: Dict[Tuple[str, str], List[Tuple[Dict[str, Any], str, str]]] = {}
    for grupo, registros in grupos.items():
        documentos = documentos_por_grupo[grupo]
        por_numero = {
            _normalizar_numero_empenho(documento.get("documentoResumido")): documento
            for documento in documentos
        }
        for empenho in registros:
            numero = str(empenho.get("numeroContratoEmpenho") or "")
            documento = por_numero.get(_normalizar_numero_empenho(numero))
            if documento is None:
                if grupo not in grupos_com_erro and not bloqueio_portal:
                    _, fornecedor, ano = grupo
                    pendentes_sem_ug.setdefault((fornecedor, ano), []).append(
                        (empenho, numero, grupo[0])
                    )
                elif bloqueio_portal and grupo not in grupos_com_erro:
                    empenho["detalhesPortalTransparencia"] = {
                        "status": "nao_consultado",
                        "mensagem": (
                            "Consulta interrompida porque o token do Portal foi bloqueado."
                        ),
                    }
                else:
                    empenho["detalhesPortalTransparencia"] = {
                        "status": "nao_encontrado",
                        "mensagem": (
                            "Documento não localizado para o favorecido, ano e UG informados."
                        ),
                    }
                continue
            pendentes.append((empenho, numero, str(documento["documento"])))

    itens_sem_ug = list(pendentes_sem_ug.items())
    for posicao, ((fornecedor, ano), registros) in enumerate(itens_sem_ug):
        if bloqueio_portal:
            for _, registros_nao_consultados in itens_sem_ug[posicao:]:
                for empenho, _, _ in registros_nao_consultados:
                    empenho["detalhesPortalTransparencia"] = {
                        "status": "nao_consultado",
                        "mensagem": (
                            "Consulta interrompida porque o token do Portal foi bloqueado."
                        ),
                    }
            break
        try:
            documentos = consultar_documentos_despesa_favorecido(
                fornecedor, ano, None, fase=1
            )
        except Exception as exc:
            erros.append(
                {
                    "unidade_gestora": "",
                    "fornecedor": fornecedor,
                    "ano": ano,
                    "erro": f"{type(exc).__name__}: {exc}",
                }
            )
            for empenho, _, _ in registros:
                empenho["detalhesPortalTransparencia"] = {
                    "status": (
                        "nao_consultado"
                        if isinstance(exc, PortalTransparenciaBlockedError)
                        else "nao_encontrado"
                    ),
                    "mensagem": (
                        "Consulta interrompida porque o token do Portal foi bloqueado."
                        if isinstance(exc, PortalTransparenciaBlockedError)
                        else (
                            "Documento não localizado na consulta com UG; "
                            "a consulta sem UG falhou."
                        )
                    ),
                }
            if isinstance(exc, PortalTransparenciaBlockedError):
                bloqueio_portal = True
            continue

        por_numero: Dict[str, List[Dict[str, Any]]] = {}
        for documento in documentos:
            chave = _normalizar_numero_empenho(documento.get("documentoResumido"))
            if chave:
                por_numero.setdefault(chave, []).append(documento)

        for empenho, numero, unidade in registros:
            candidatos = por_numero.get(_normalizar_numero_empenho(numero), [])
            unidade_normalizada = re.sub(r"\D", "", unidade)
            mesma_unidade = [
                documento
                for documento in candidatos
                if re.sub(r"\D", "", str(documento.get("codigoUg") or ""))
                == unidade_normalizada
            ]
            if len(mesma_unidade) == 1:
                documento = mesma_unidade[0]
            elif len(candidatos) == 1:
                documento = candidatos[0]
            else:
                documento = None

            if documento is None:
                mensagem = (
                    "Documento não localizado para o favorecido, ano e número do PNCP."
                    if not candidatos
                    else "Mais de um documento corresponde ao número do PNCP; UG não identificada."
                )
                empenho["detalhesPortalTransparencia"] = {
                    "status": "nao_encontrado",
                    "mensagem": mensagem,
                }
                continue
            pendentes.append((empenho, numero, str(documento["documento"])))

    if bloqueio_portal:
        for empenho, _, _ in pendentes:
            empenho["detalhesPortalTransparencia"] = {
                "status": "nao_consultado",
                "mensagem": "Consulta interrompida porque o token do Portal foi bloqueado.",
            }
        pendentes.clear()

    def detalhar(item: Tuple[Dict[str, Any], str, str]):
        empenho, numero, codigo_documento = item
        try:
            return item, consultar_detalhes_documento_despesa(codigo_documento), None
        except Exception as exc:
            return item, None, exc

    if pendentes:
        with ThreadPoolExecutor(max_workers=PORTAL_WORKERS) as pool:
            for (empenho, numero, codigo_documento), detalhamento, exc in pool.map(
                detalhar, pendentes
            ):
                if exc is None:
                    empenho["detalhesPortalTransparencia"] = {
                        "status": "ok",
                        "codigoDocumento": codigo_documento,
                        "detalhamento": detalhamento,
                    }
                    continue
                empenho["detalhesPortalTransparencia"] = {
                    "status": "erro",
                    "codigoDocumento": codigo_documento,
                    "erro": f"{type(exc).__name__}: {exc}",
                }
                erros.append(
                    {
                        "numero_empenho": numero,
                        "codigo_documento": codigo_documento,
                        "erro":                         f"{type(exc).__name__}: {exc}",
                    }
                )

    return enriquecidos, erros
