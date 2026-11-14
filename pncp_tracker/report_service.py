import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .api_client import buscar_resultados_item
from .collector import baixar_dados_compra_pncp
from .consultar_e_mapear_empenhos import (
    anexar_coleta_empenhos,
    coletar_empenhos,
    enriquecer_e_mapear_empenhos,
    montar_resultado_empenhos,
)
from .process_lock import interprocess_lock, lock_path_for
from .report_registry import (
    INDEX_PATH,
    REPORTS_DIR,
    adicionar_registro,
    atualizar_registro,
    buscar_registro,
    ler_registros,
    validar_url_pncp,
)


def _escrever_json(caminho: Path, dados: Dict[str, Any]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(caminho.name + ".tmp")
    with temporario.open("w", encoding="utf-8", newline="\n") as arquivo:
        json.dump(dados, arquivo, indent=2, ensure_ascii=False)
        arquivo.write("\n")
    temporario.replace(caminho)


def _notificar(callback: Optional[Callable[[str], None]], mensagem: str) -> None:
    if callback is not None:
        callback(mensagem)


def _ler_json(caminho: Path, descricao: str) -> Dict[str, Any]:
    """Lê um JSON persistido da pasta do relatório."""
    if not caminho.is_file():
        raise ValueError("Arquivo de {} ausente em {}.".format(descricao, caminho.parent))
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Não foi possível ler {}: {}".format(descricao, exc))
    if not isinstance(dados, dict):
        raise ValueError("O arquivo de {} não é um objeto JSON.".format(descricao))
    return dados


def _ler_snapshot_anterior(pasta_relatorio: Path) -> Optional[Dict[str, Any]]:
    """Lê o dados_pregao.json existente para permitir reutilizar a coleta quando nada mudou."""
    caminho = Path(pasta_relatorio) / "dados_pregao.json"
    if not caminho.is_file():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dados if isinstance(dados, dict) else None


def _atualizar_processo(
    url_pncp: str,
    *,
    reports_dir: Path = REPORTS_DIR,
    index_path: Path = INDEX_PATH,
    on_progress: Optional[Callable[[str], None]] = None,
    cadastrar_se_ausente: bool = True,
    buscar_empenhos_portal: Optional[bool] = None,
) -> Dict[str, Any]:
    inicio = time.monotonic()
    cnpj, ano, sequencial = validar_url_pncp(url_pncp)
    url_pncp = "https://pncp.gov.br/app/editais/{}/{}/{}".format(cnpj, ano, sequencial)
    registro = buscar_registro(url_pncp, index_path)
    if registro is None:
        if not cadastrar_se_ausente:
            raise KeyError("Processo não encontrado no índice.")
        registro = adicionar_registro(url_pncp, index_path)

    pasta = registro.get("pasta") or "processo_{}-{}-{}".format(
        cnpj, ano, int(sequencial)
    )
    if not isinstance(pasta, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", pasta):
        raise ValueError("Nome da pasta do processo inválido no índice.")
    registro = atualizar_registro(
        url_pncp,
        {"pasta": pasta, "status": "atualizando", "erro": None},
        index_path,
    )
    pasta_relatorio = Path(reports_dir) / pasta
    procurar_no_portal = (
        bool(registro.get("buscar_empenhos_portal"))
        if buscar_empenhos_portal is None
        else bool(buscar_empenhos_portal)
    )

    try:
        _notificar(on_progress, "Coletando dados do edital no PNCP.")
        dados_compra = baixar_dados_compra_pncp(
            url_pncp,
            on_progress=on_progress,
            dados_anteriores=_ler_snapshot_anterior(pasta_relatorio),
        )
        chaves_compra = dados_compra.get("chaves_integracao")
        if not isinstance(chaves_compra, dict):
            raise ValueError("Cabeçalho da compra incompleto: chaves de integração ausentes.")
        numero_compra = str(chaves_compra.get("numero_compra") or "").strip()
        ano_compra = str(chaves_compra.get("ano_compra") or "").strip()
        if not numero_compra.isdigit() or not re.fullmatch(r"\d{4}", ano_compra):
            raise ValueError(
                "Cabeçalho da compra incompleto: número e ano da compra são obrigatórios."
            )

        _notificar(on_progress, "Coletando contratos e empenhos do PNCP.")
        coleta = coletar_empenhos(
            url_pncp,
            dados_compra,
            buscar_empenhos_portal=procurar_no_portal,
            on_progress=on_progress,
        )
        anexar_coleta_empenhos(dados_compra, coleta)
        _escrever_json(pasta_relatorio / "dados_pregao.json", dados_compra)

        _notificar(on_progress, "Detalhando empenhos e relacionando aos itens homologados.")
        resultado_etapa2 = enriquecer_e_mapear_empenhos(
            dados_compra,
            on_progress=on_progress,
        )
        chaves_resultado = resultado_etapa2.get("chaves_integracao")
        if not isinstance(chaves_resultado, dict):
            raise ValueError("Cabeçalho da compra incompleto: resultado sem chaves de integração.")
        numero_resultado = str(chaves_resultado.get("numero_compra") or "").strip()
        ano_resultado = str(chaves_resultado.get("ano_compra") or "").strip()
        if not numero_resultado.isdigit() or not re.fullmatch(r"\d{4}", ano_resultado):
            raise ValueError(
                "Cabeçalho da compra incompleto: número e ano da compra são obrigatórios."
            )

        caminho_metadados = pasta_relatorio / "metadados.json"
        if caminho_metadados.exists():
            try:
                metadados = json.loads(caminho_metadados.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("Não foi possível ler os metadados do processo: {}".format(exc))
            if not isinstance(metadados, dict):
                raise ValueError("Os metadados existentes do processo não são um objeto JSON.")
        else:
            metadados = {}

        agora = datetime.now().astimezone().isoformat(timespec="seconds")
        chaves = resultado_etapa2["chaves_integracao"]
        nome_compra = re.sub(r"[^A-Za-z0-9_-]+", "-", numero_resultado).strip("-")
        ano_compra = re.sub(r"[^A-Za-z0-9_-]+", "-", ano_resultado).strip("-")
        if not nome_compra or not ano_compra:
            raise ValueError("Número ou ano inválido para nomear o relatório.")
        arquivo_html = "relatorio_compra_{}_{}.html".format(nome_compra, ano_compra)
        _escrever_json(pasta_relatorio / "dados_empenhos.json", resultado_etapa2)
        metadados.update(
            {
                "schema_version": 1,
                "url_pncp": url_pncp,
                "criado_em": metadados.get("criado_em") or agora,
                "atualizado_em": agora,
                "chaves_integracao": resultado_etapa2.get("chaves_integracao")
                or dados_compra.get("chaves_integracao", {}),
                "arquivo_html": arquivo_html,
                "ultima_duracao_segundos": round(time.monotonic() - inicio, 1),
                "buscar_empenhos_portal": procurar_no_portal,
            }
        )
        _escrever_json(caminho_metadados, metadados)

        from relatorios.gerar_relatorios import gerar_relatorios

        _notificar(on_progress, "Gerando os arquivos HTML do relatório.")
        gerar_relatorios(Path(reports_dir), index_path=Path(index_path))
        registro = buscar_registro(url_pncp, index_path)
        _notificar(on_progress, "Relatório individual e índice atualizados.")
        return {
            "registro": registro,
            "resultado_etapa2": resultado_etapa2,
            "caminho_relatorio": pasta_relatorio / arquivo_html,
            "caminho_index": Path(reports_dir) / "index.html",
        }
    except Exception as exc:
        try:
            atualizar_registro(
                url_pncp,
                {
                    "status": "erro",
                    "erro": str(exc),
                    "ultima_tentativa_em": datetime.now()
                    .astimezone()
                    .isoformat(timespec="seconds"),
                },
                index_path,
            )
        except KeyError as registry_error:
            raise RuntimeError(
                "A atualização falhou e o processo foi removido do índice: {}.".format(exc)
            ) from registry_error
        raise


def atualizar_processo(
    url_pncp: str,
    *,
    reports_dir: Path = REPORTS_DIR,
    index_path: Path = INDEX_PATH,
    on_progress: Optional[Callable[[str], None]] = None,
    cadastrar_se_ausente: bool = True,
    buscar_empenhos_portal: Optional[bool] = None,
) -> Dict[str, Any]:
    lock_path = lock_path_for(index_path)
    with interprocess_lock(lock_path):
        return _atualizar_processo(
            url_pncp,
            reports_dir=reports_dir,
            index_path=index_path,
            on_progress=on_progress,
            cadastrar_se_ausente=cadastrar_se_ausente,
            buscar_empenhos_portal=buscar_empenhos_portal,
        )


def reprocessar_itens_pendentes(
    url_pncp: str,
    *,
    reports_dir: Path = REPORTS_DIR,
    index_path: Path = INDEX_PATH,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Tenta novamente apenas os itens cujos resultados homologados falharam.

    Não consulta o Portal da Transparência: reaproveita os empenhos já detalhados e
    remonta `dados_empenhos.json` com os resultados recuperados.
    """
    cnpj, ano, sequencial = validar_url_pncp(url_pncp)
    url_pncp = "https://pncp.gov.br/app/editais/{}/{}/{}".format(cnpj, ano, sequencial)
    lock_path = lock_path_for(index_path)

    with interprocess_lock(lock_path):
        registro = buscar_registro(url_pncp, index_path)
        if registro is None:
            raise KeyError("Processo não encontrado no índice.")
        pasta = registro.get("pasta") or "processo_{}-{}-{}".format(cnpj, ano, int(sequencial))
        if not isinstance(pasta, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", pasta):
            raise ValueError("Nome da pasta do processo inválido no índice.")
        pasta_relatorio = Path(reports_dir) / pasta
        dados_compra = _ler_json(pasta_relatorio / "dados_pregao.json", "dados da coleta")
        dados_empenhos = _ler_json(
            pasta_relatorio / "dados_empenhos.json", "dados dos empenhos"
        )

        itens = dados_compra.get("itens") or []
        pendentes = [
            item for item in itens if str(item.get("erroResultadosHomologados") or "").strip()
        ]
        if not pendentes:
            return {
                "pendentes": 0,
                "recuperados": 0,
                "falhas": 0,
                "atualizado": False,
                "mensagem": "Não há itens pendentes neste processo.",
            }

        _notificar(
            on_progress,
            "Tentando novamente {} item(ns) pendente(s) no PNCP.".format(len(pendentes)),
        )
        recuperados = 0
        falhas = 0
        for item in pendentes:
            numero = item.get("numeroItem")
            try:
                item["resultadosHomologados"] = buscar_resultados_item(
                    cnpj, ano, sequencial, numero
                )
            except Exception as exc:
                falhas += 1
                item["erroResultadosHomologados"] = "{}: {}".format(type(exc).__name__, exc)
                _notificar(on_progress, "Item {} continua pendente: {}".format(numero, exc))
                continue
            item.pop("erroResultadosHomologados", None)
            recuperados += 1
            _notificar(on_progress, "Item {} recuperado.".format(numero))

        dados_compra["erros_resultados_itens"] = [
            {"numero_item": item.get("numeroItem"), "erro": item["erroResultadosHomologados"]}
            for item in itens
            if str(item.get("erroResultadosHomologados") or "").strip()
        ]
        _escrever_json(pasta_relatorio / "dados_pregao.json", dados_compra)

        coleta = dict(dados_compra.get("coleta_empenhos") or {})
        coleta["erros"] = []
        if not coleta.get("quantidade_empenhos_pncp"):
            coleta["quantidade_empenhos_pncp"] = len(dados_compra.get("empenhos") or [])
        resultado = montar_resultado_empenhos(
            dados_compra,
            list(dados_empenhos.get("empenhos") or []),
            coleta,
            list(dados_empenhos.get("erros_detalhamento") or []),
            on_progress=on_progress,
        )
        _escrever_json(pasta_relatorio / "dados_empenhos.json", resultado)

        caminho_metadados = pasta_relatorio / "metadados.json"
        metadados = _ler_json(caminho_metadados, "metadados")
        metadados["atualizado_em"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        _escrever_json(caminho_metadados, metadados)

        from relatorios.gerar_relatorios import gerar_relatorios

        gerar_relatorios(Path(reports_dir), index_path=Path(index_path))
        _notificar(on_progress, "Relatório regenerado com os itens recuperados.")
        return {
            "pendentes": len(pendentes),
            "recuperados": recuperados,
            "falhas": falhas,
            "atualizado": True,
            "mensagem": "{} de {} item(ns) pendente(s) recuperado(s).".format(
                recuperados, len(pendentes)
            ),
        }


def atualizar_todos(
    *,
    reports_dir: Path = REPORTS_DIR,
    index_path: Path = INDEX_PATH,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    lock_path = lock_path_for(index_path)
    with interprocess_lock(lock_path):
        registros = ler_registros(index_path)
        sucessos = []
        falhas = []
        for posicao, registro in enumerate(registros, start=1):
            url = registro["url_pncp"]
            _notificar(
                on_progress,
                "Atualizando processo {}/{}: {}".format(posicao, len(registros), url),
            )
            try:
                resultado = _atualizar_processo(
                    url,
                    reports_dir=reports_dir,
                    index_path=index_path,
                    on_progress=on_progress,
                    cadastrar_se_ausente=False,
                )
                sucessos.append(resultado["registro"])
            except Exception as exc:
                falhas.append({"url_pncp": url, "erro": str(exc)})
                try:
                    atualizar_registro(
                        url,
                        {
                            "status": "erro",
                            "erro": str(exc),
                            "ultima_tentativa_em": datetime.now()
                            .astimezone()
                            .isoformat(timespec="seconds"),
                        },
                        index_path,
                    )
                except KeyError:
                    _notificar(
                        on_progress,
                        "O processo foi removido da lista durante a atualização: {}".format(url),
                    )
                _notificar(on_progress, "Falha ao atualizar {}: {}".format(url, exc))

        from relatorios.gerar_relatorios import gerar_relatorios

        gerar_relatorios(Path(reports_dir), index_path=Path(index_path))
        return {"atualizados": sucessos, "falhas": falhas}
