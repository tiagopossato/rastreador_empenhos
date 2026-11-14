from __future__ import annotations

import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Set, Tuple

from .contratos_gov import coletar_dados_empenho, normalizar_numero_compra
from .portal_transparencia import (
    PortalTransparenciaBlockedError,
    consultar_contratos_por_processo,
    consultar_detalhes_documento_despesa,
    consultar_documentos_despesa_favorecido,
    consultar_empenhos_de_contrato,
    consultar_empenhos_de_licitacao,
    consultar_licitacoes_por_processo,
)

ORIGEM_CONTRATO = "portal_contrato"
ORIGEM_LICITACAO = "portal_licitacao"
ORIGEM_FAVORECIDO = "portal_favorecido"
ANOS_A_PARTIR_DA_COMPRA = 3
ORCAMENTO_DETALHAMENTOS = 60
PORTAL_WORKERS = 4

ORIGEM_ORGAN_ORIGINAL = "original"
ORIGEM_ORGAN_PROPRIA_UG = "propria_ug"
ORIGEM_ORGAN_ADESAO = "adesao_posterior"
ORIGEM_ORGAN_INDEFINIDO = "indefinido"
ORIGENS_QUE_CONSOMEM_SALDO = (ORIGEM_ORGAN_ORIGINAL, ORIGEM_ORGAN_PROPRIA_UG)


def _digitos(valor: Any) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def numero_decimal(valor: Any) -> Optional[float]:
    """Converte números no formato brasileiro (1.234,56) em float."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace("R$", "").replace("\xa0", "").replace(" ", "")
    if texto.count(",") == 1 and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(",") == 1:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _decimal(valor: Any) -> Optional[Decimal]:
    """Converte valores monetários em Decimal, preservando a precisão do texto original."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, (int, float)):
        return Decimal(str(valor))
    texto = str(valor).strip().replace("R$", "").replace("\xa0", "").replace(" ", "")
    if not texto:
        return None
    if texto.count(",") == 1:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


TOLERANCIA_QUANTIDADE = Decimal("0.01")
LIMIAR_DESCRICAO = 0.6


def quantidade_estimada(valor: Any, valor_unitario: Any) -> Optional[Tuple[int, bool]]:
    """Quantidade derivada do valor da linha dividido pelo preço unitário homologado.

    A estimativa nunca tem precisão real, então é arredondada para inteiro com Decimal
    (evita artefatos de ponto flutuante como 2,999999). O segundo elemento indica que a
    divisão não é múltipla inteira do preço unitário — sinal de que o preço efetivo difere
    do homologado e de que a quantidade é apenas aproximada.
    """
    valor_dec = _decimal(valor)
    unitario_dec = _decimal(valor_unitario)
    if valor_dec is None or unitario_dec is None or unitario_dec <= 0 or valor_dec < 0:
        return None
    razao = valor_dec / unitario_dec
    quantidade = int(razao.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if quantidade < 1:
        return None
    divergente = abs(razao - quantidade) > max(
        Decimal("0.05"), quantidade * TOLERANCIA_QUANTIDADE
    )
    return quantidade, divergente


def _norm_texto(valor: Any) -> str:
    """Texto em maiúsculas, sem acentos e sem pontuação, para comparações e regex."""
    decomposto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = decomposto.encode("ascii", "ignore").decode("ASCII").upper()
    return re.sub(r"[^A-Z0-9 ]+", " ", texto).strip()


_PREFIXO_ITEM_COMPRA = re.compile(r"\bitem\s+compra\s*:\s*\d+\s*-?\s*", re.IGNORECASE)


def _tokens(descricao: Any) -> Set[str]:
    """Palavras significativas da descrição, descartando o prefixo ``Item compra: N``."""
    texto = _PREFIXO_ITEM_COMPRA.sub(" ", str(descricao or ""))
    return {token for token in _norm_texto(texto).lower().split() if len(token) >= 3}


def _descricao_compativel(descricao_compra: Any, descricao_empenho: Any) -> Optional[bool]:
    """Compara a descrição do item da compra com a do item do empenho.

    A descrição do empenho é a descrição de catálogo do PNCP, que contém a descrição curta
    publicada no edital. Devolve ``None`` quando não há tokens suficientes para concluir.
    """
    tokens_compra = _tokens(descricao_compra)
    tokens_empenho = _tokens(descricao_empenho)
    if not tokens_compra or not tokens_empenho:
        return None
    comum = len(tokens_compra & tokens_empenho) / min(len(tokens_compra), len(tokens_empenho))
    return comum >= LIMIAR_DESCRICAO


def resumir_empenho(*valores: Any) -> str:
    """Reduz o código do empenho ao formato AAAANE999999 usado pelo PNCP."""
    for valor in valores:
        codigo = str(valor or "")
        match = re.search(r"(\d{4})\D?NE\D?(\d+)", codigo, re.IGNORECASE)
        if match:
            return f"{match.group(1)}NE{match.group(2)}".upper()
        if codigo:
            limpo = re.sub(r"[^A-Za-z0-9]", "", codigo).upper()
            if limpo:
                return limpo
    return ""


def classificar_origem_organ(
    fruto_adesao: Optional[bool],
    dados_cgov: Optional[Dict[str, Any]],
    unidade_emitente: Any,
) -> str:
    """Decide se o empenho consome o saldo da quantidade homologada."""
    if fruto_adesao is True:
        return ORIGEM_ORGAN_ADESAO
    if fruto_adesao is False:
        return ORIGEM_ORGAN_ORIGINAL
    if dados_cgov:
        chave = dados_cgov.get("chave_compra") or {}
        unidade_compra = _digitos(chave.get("unidade_compra"))
        emitente = _digitos(unidade_emitente) or _digitos(dados_cgov.get("ug_emitente"))
        if unidade_compra and emitente and unidade_compra == emitente:
            return ORIGEM_ORGAN_PROPRIA_UG
    return ORIGEM_ORGAN_INDEFINIDO


def consome_saldo(origem_organ: Optional[str]) -> bool:
    return (origem_organ or ORIGEM_ORGAN_ORIGINAL) in ORIGENS_QUE_CONSOMEM_SALDO


def _itens_por_numero(dados_compra: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    mapa: Dict[int, Dict[str, Any]] = {}
    for item in dados_compra.get("itens", []) or []:
        try:
            numero = int(item.get("numeroItem"))
        except (TypeError, ValueError):
            continue
        por_cnpj: Dict[str, Optional[float]] = {}
        for resultado in item.get("resultadosHomologados") or []:
            cnpj = _digitos(resultado.get("niFornecedor") or resultado.get("cpfCnpjFornecedor"))
            valor = numero_decimal(resultado.get("valorUnitarioHomologado"))
            if cnpj:
                por_cnpj[cnpj] = valor
        mapa[numero] = {
            "por_cnpj": por_cnpj,
            "descricao": item.get("descricao"),
        }
    return mapa


def _numero_item_descricao(descricao: Any) -> Optional[int]:
    if not descricao:
        return None
    match = re.search(r"\bitem\s+compra\s*:\s*0*(\d+)\b", str(descricao), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _itens_do_empenho(
    detalhe: Dict[str, Any],
    dados_cgov: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Itens do empenho, priorizando a quantidade real publicada na Contratos.gov.br."""
    itens: List[Dict[str, Any]] = []
    if dados_cgov:
        for item in dados_cgov.get("itens") or []:
            match = re.search(r"\d+", str(item.get("numero_item_compra") or ""))
            itens.append(
                {
                    "numero_item": int(match.group()) if match else None,
                    "valor": item.get("valor_total"),
                    "quantidade": item.get("quantidade"),
                    "descricao": item.get("descricao"),
                    "fonte": "contratos_gov",
                }
            )
    if itens:
        return itens
    for item in detalhe.get("itensEmpenho") or []:
        itens.append(
            {
                "numero_item": _numero_item_descricao(item.get("descricao")),
                "valor": numero_decimal(item.get("valorAtual")),
                "quantidade": None,
                "descricao": item.get("descricao"),
                "fonte": "portal",
            }
        )
    return itens


def _evidencias(
    detalhe: Dict[str, Any],
    dados_compra: Dict[str, Any],
    dados_cgov: Optional[Dict[str, Any]],
    processo: str,
    origem: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Avalia o vínculo do documento com a compra, do sinal mais forte ao mais fraco.

    O fornecedor homologado é apenas a semente da busca: o mesmo fornecedor empenha em
    muitas compras, então sem uma destas evidências o documento é descartado.
    """
    chaves = dados_compra.get("chaves_integracao") or {}
    if origem == ORIGEM_CONTRATO:
        return "contrato_do_processo", "alta"
    if origem == ORIGEM_LICITACAO:
        return "licitacao_do_processo", "alta"

    if dados_cgov:
        chave = dados_cgov.get("chave_compra") or {}
        unidade_compra = _digitos(chave.get("unidade_compra"))
        numero_compra = normalizar_numero_compra(chave.get("numero"))
        ano_compra = str(chave.get("ano") or "")
        if unidade_compra and numero_compra:
            mesma_compra = (
                unidade_compra == _digitos(chaves.get("uasg_codigo"))
                and numero_compra == normalizar_numero_compra(chaves.get("numero_compra"))
                and ano_compra == str(chaves.get("ano_compra") or "")
            )
            if mesma_compra:
                return "compra_identidade", "alta"
            return "outra_compra", None

    if processo and _digitos(detalhe.get("numeroProcesso")) == processo:
        return "processo", "alta"

    favorecido = _digitos(detalhe.get("codigoFavorecido"))
    if not favorecido:
        return None, None
    itens_por_numero = _itens_por_numero(dados_compra)
    for item in _itens_do_empenho(detalhe, dados_cgov):
        numero = item.get("numero_item")
        referencia = itens_por_numero.get(numero) if numero is not None else None
        if not referencia or favorecido not in referencia["por_cnpj"]:
            continue
        if _descricao_compativel(referencia.get("descricao"), item.get("descricao")):
            return "item_e_fornecedor", "alta"
        valor_unitario = referencia["por_cnpj"].get(favorecido)
        estimativa = quantidade_estimada(item.get("valor"), valor_unitario)
        if estimativa and not estimativa[1]:
            return "item_e_valor", "media"
    return None, None


def _candidato(
    codigo: Any,
    resumido: Any,
    origem: str,
    unidade_emitente: Any = None,
    prioridade: int = 1,
) -> Dict[str, Any]:
    return {
        "codigo": re.sub(r"[^A-Za-z0-9]", "", str(codigo or "")),
        "resumido": resumir_empenho(resumido, codigo),
        "origem": origem,
        "unidade_emitente": _digitos(unidade_emitente),
        "prioridade": prioridade,
    }


def _erro(origem: Optional[str], exc: Exception, **contexto: Any) -> Dict[str, str]:
    entrada = {chave: str(valor) for chave, valor in contexto.items()}
    if origem:
        entrada["origem"] = origem
    entrada["erro"] = f"{type(exc).__name__}: {exc}"
    return entrada


def _descarte(
    candidato: Dict[str, Any],
    detalhe: Dict[str, Any],
    motivo: str,
    vinculo: Optional[str] = None,
) -> Dict[str, Any]:
    """Registra um documento encontrado no fornecedor que não tem vínculo com a compra."""
    entrada: Dict[str, Any] = {
        "tipo": "descartado",
        "origem": candidato.get("origem"),
        "documento": candidato.get("codigo"),
        "numero": candidato.get("resumido"),
        "unidade": _digitos(detalhe.get("codigoUg")) or candidato.get("unidade_emitente"),
        "fornecedor": detalhe.get("codigoFavorecido"),
        "valor": numero_decimal(detalhe.get("valor")),
        "motivo": motivo,
    }
    if vinculo:
        entrada["vinculo"] = vinculo
    return entrada


def _notificar(
    on_progress: Optional[Callable[[str], None]],
    mensagem: str,
) -> None:
    if on_progress is not None:
        on_progress(mensagem)


def _coletar_por_contrato(
    processo: str,
    erros: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """Estratégia A: contratos do processo e seus documentos relacionados."""
    candidatos: List[Dict[str, Any]] = []
    for contrato in consultar_contratos_por_processo(processo):
        try:
            empenhos = consultar_empenhos_de_contrato(contrato.get("id"))
        except PortalTransparenciaBlockedError:
            raise
        except Exception as exc:
            erros.append(_erro(ORIGEM_CONTRATO, exc, contrato=contrato.get("numero")))
            continue
        for empenho in empenhos:
            candidatos.append(
                _candidato(
                    empenho.get("empenho"),
                    empenho.get("empenhoResumido"),
                    ORIGEM_CONTRATO,
                    prioridade=0,
                )
            )
    return candidatos


def _coletar_por_licitacao(
    processo: str,
    modalidade_id: Any,
    erros: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """Estratégia B: licitação do processo e seus empenhos."""
    candidatos: List[Dict[str, Any]] = []
    for licitacao in consultar_licitacoes_por_processo(processo):
        unidade = licitacao.get("unidadeGestora") or {}
        compra = licitacao.get("licitacao") or {}
        codigo_ug = unidade.get("codigo")
        numero = compra.get("numero")
        codigo_modalidade = licitacao.get("codigoModalidade") or modalidade_id
        if not (codigo_ug and numero and codigo_modalidade):
            erros.append(
                {
                    "origem": ORIGEM_LICITACAO,
                    "motivo": "Licitação sem UG, número ou modalidade para consultar empenhos.",
                    "licitacao": str(licitacao.get("id")),
                }
            )
            continue
        try:
            empenhos = consultar_empenhos_de_licitacao(codigo_ug, numero, codigo_modalidade)
        except PortalTransparenciaBlockedError:
            raise
        except Exception as exc:
            erros.append(_erro(ORIGEM_LICITACAO, exc, licitacao=licitacao.get("id")))
            continue
        for empenho in empenhos:
            candidatos.append(
                _candidato(
                    empenho.get("empenho"),
                    empenho.get("empenhoResumido"),
                    ORIGEM_LICITACAO,
                    unidade_emitente=codigo_ug,
                    prioridade=0,
                )
            )
    return candidatos


def _coletar_por_favorecido(
    dados_compra: Dict[str, Any],
    processo: str,
    anos: List[str],
    erros: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """Estratégia C: documentos dos fornecedores homologados, sem exigir o processo."""
    fornecedores = {
        _digitos(resultado.get("niFornecedor") or resultado.get("cpfCnpjFornecedor"))
        for item in dados_compra.get("itens", [])
        for resultado in item.get("resultadosHomologados", []) or []
    }
    fornecedores.discard("")
    combos = [(fornecedor, ano) for fornecedor in sorted(fornecedores) for ano in anos]

    def consultar(combo: Tuple[str, str]) -> Tuple[Tuple[str, str], List[Dict[str, Any]], Optional[Exception]]:
        fornecedor, ano = combo
        try:
            return combo, consultar_documentos_despesa_favorecido(
                fornecedor, ano, None, fase=1
            ), None
        except Exception as exc:
            return combo, [], exc

    encontrados_por_combo: List[Tuple[Tuple[str, str], List[Dict[str, Any]]]] = []
    bloqueio: Optional[Exception] = None
    with ThreadPoolExecutor(max_workers=PORTAL_WORKERS) as pool:
        for combo, documentos, exc in pool.map(consultar, combos):
            if exc is not None:
                erros.append(_erro(ORIGEM_FAVORECIDO, exc, fornecedor=combo[0], ano=combo[1]))
                if isinstance(exc, PortalTransparenciaBlockedError) and bloqueio is None:
                    bloqueio = exc
                continue
            encontrados_por_combo.append((combo, documentos))
    if bloqueio is not None:
        raise bloqueio

    candidatos: List[Dict[str, Any]] = []
    for _combo, encontrados in encontrados_por_combo:
        for documento in encontrados:
            mesmo_processo = bool(processo) and (
                _digitos(documento.get("numeroProcesso")) == processo
            )
            candidatos.append(
                _candidato(
                    documento.get("documento"),
                    documento.get("documentoResumido"),
                    ORIGEM_FAVORECIDO,
                    unidade_emitente=documento.get("codigoUg"),
                    prioridade=0 if mesmo_processo else 1,
                )
            )
    return candidatos

def _precisa_contratos_gov(
    detalhe: Dict[str, Any],
    dados_compra: Dict[str, Any],
) -> bool:
    """Consulta a Contratos.gov.br só quando o detalhe do Portal não basta para decidir ou casar."""
    if _digitos(detalhe.get("numeroProcesso")) == _digitos(
        (dados_compra.get("chaves_integracao") or {}).get("processo")
    ):
        # O processo já confirma o vínculo; a API só seria útil para quantidade real,
        # e o detalhe do Portal já traz os itens usados pelo matcher.
        if detalhe.get("itensEmpenho"):
            return False
    return True


def _detalhar_candidatos(
    candidatos: List[Dict[str, Any]],
    dados_compra: Dict[str, Any],
    erros: List[Dict[str, str]],
    detalhes_conhecidos: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Detalha cada documento uma única vez e monta registros compatíveis com o matcher."""
    chaves = dados_compra.get("chaves_integracao") or {}
    processo = _digitos(chaves.get("processo"))
    registros: List[Dict[str, Any]] = []
    conhecidos = detalhes_conhecidos if detalhes_conhecidos is not None else {}
    vistos = set()
    dados_cgov_cache: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}
    detalhamentos = 0
    bloqueado = False

    for prioridade in (0, 1):
        for candidato in candidatos:
            if candidato.get("prioridade", 1) != prioridade:
                continue
            if detalhamentos >= ORCAMENTO_DETALHAMENTOS:
                erros.append(
                    {
                        "motivo": "Orçamento de detalhamentos atingido; candidatos restantes não consultados.",
                        "consultados": str(detalhamentos),
                    }
                )
                return registros, bloqueado

            codigo = candidato["codigo"]
            if not codigo or codigo in vistos:
                continue
            vistos.add(codigo)

            if codigo in conhecidos:
                detalhe = conhecidos[codigo]
            else:
                try:
                    detalhe = consultar_detalhes_documento_despesa(codigo)
                except PortalTransparenciaBlockedError as exc:
                    erros.append(_erro(candidato["origem"], exc, documento=codigo))
                    return registros, True
                except Exception as exc:
                    erros.append(_erro(candidato["origem"], exc, documento=codigo))
                    continue
                detalhamentos += 1
                conhecidos[codigo] = detalhe

            unidade = candidato.get("unidade_emitente") or _digitos(detalhe.get("codigoUg"))
            dados_cgov: Optional[Dict[str, Any]] = None
            if unidade and candidato.get("resumido") and _precisa_contratos_gov(
                detalhe, dados_compra
            ):
                chave_cgov = (unidade, candidato["resumido"])
                if chave_cgov not in dados_cgov_cache:
                    try:
                        dados_cgov_cache[chave_cgov] = coletar_dados_empenho(
                            unidade, candidato["resumido"]
                        )
                    except Exception as exc:  # a fonte é opcional
                        dados_cgov_cache[chave_cgov] = None
                        erros.append(
                            _erro(candidato["origem"], exc, documento=codigo, fonte="contratos_gov")
                        )
                dados_cgov = dados_cgov_cache[chave_cgov]

            vinculo, confianca = _evidencias(
                detalhe, dados_compra, dados_cgov, processo, candidato["origem"]
            )
            if vinculo == "outra_compra":
                erros.append(
                    _descarte(
                        candidato,
                        detalhe,
                        "Documento descartado: pertence a outra compra.",
                        vinculo,
                    )
                )
                continue
            if vinculo is None:
                erros.append(
                    _descarte(
                        candidato,
                        detalhe,
                        "Documento descartado: nenhuma evidência de vínculo com a compra.",
                    )
                )
                continue

            origem_organ = classificar_origem_organ(None, dados_cgov, unidade)
            registro = {
                "numeroContratoEmpenho": candidato["resumido"] or codigo,
                "niFornecedor": detalhe.get("codigoFavorecido"),
                "nomeRazaoSocialFornecedor": detalhe.get("nomeFavorecido"),
                "unidadeOrgao": {
                    "codigoUnidade": detalhe.get("codigoUg") or unidade,
                    "nomeUnidade": detalhe.get("ug"),
                },
                "origem": candidato["origem"],
                "vinculo": vinculo,
                "confianca": confianca,
                "origem_organ": origem_organ,
                "consome_saldo": consome_saldo(origem_organ),
                "fruto_adesao": None,
                "detalhesPortalTransparencia": {
                    "status": "ok",
                    "codigoDocumento": codigo,
                    "detalhamento": detalhe,
                },
            }
            if dados_cgov:
                registro["dadosContratosGov"] = {
                    "chave_compra": dados_cgov.get("chave_compra"),
                    "itens": dados_cgov.get("itens"),
                }
            registros.append(registro)

    return registros, bloqueado


def buscar_empenhos_portal_para_compra(
    dados_compra: Dict[str, Any],
    on_progress: Optional[Callable[[str], None]] = None,
    detalhes_conhecidos: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Descobre empenhos no Portal, do caminho mais barato ao mais abrangente."""
    chaves = dados_compra.get("chaves_integracao") or {}
    processo_portal = str(chaves.get("processo") or "").strip()
    processo = _digitos(processo_portal)
    erros: List[Dict[str, str]] = []

    candidatos: List[Dict[str, Any]] = []
    estrategias = (
        ("A", "contratos do processo", lambda: _coletar_por_contrato(processo_portal, erros)),
        (
            "B",
            "licitação do processo",
            lambda: _coletar_por_licitacao(processo_portal, chaves.get("modalidade_id"), erros),
        ),
    )
    for rotulo, descricao, coletar in estrategias:
        if not processo_portal:
            break
        _notificar(on_progress, f"Buscando empenhos no Portal (estratégia {rotulo}: {descricao}).")
        try:
            candidatos = coletar()
        except PortalTransparenciaBlockedError as exc:
            erros.append(_erro(None, exc))
            return [], erros
        if candidatos:
            break

    if not candidatos:
        try:
            ano_compra = int(chaves.get("ano_compra"))
        except (TypeError, ValueError):
            ano_compra = None
        if ano_compra is None:
            erros.append(
                {
                    "origem": "portal",
                    "motivo": "Compra sem ano; não é possível varrer os fornecedores homologados.",
                }
            )
            return [], erros
        anos = [str(ano_compra + deslocamento) for deslocamento in range(ANOS_A_PARTIR_DA_COMPRA)]
        _notificar(
            on_progress,
            "Sem empenhos por contrato/licitação; varrendo documentos dos fornecedores homologados.",
        )
        try:
            candidatos = _coletar_por_favorecido(dados_compra, processo, anos, erros)
        except PortalTransparenciaBlockedError as exc:
            erros.append(_erro(None, exc))
            return [], erros

    registros, _bloqueado = _detalhar_candidatos(
        candidatos, dados_compra, erros, detalhes_conhecidos
    )
    return registros, erros
