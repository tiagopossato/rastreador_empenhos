import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .collector import baixar_dados_compra_pncp
from .consultar_e_mapear_empenhos import consultar_e_mapear_empenhos
from .process_lock import interprocess_lock
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


def _atualizar_processo(
    url_pncp: str,
    *,
    reports_dir: Path = REPORTS_DIR,
    index_path: Path = INDEX_PATH,
    on_progress: Optional[Callable[[str], None]] = None,
    cadastrar_se_ausente: bool = True,
) -> Dict[str, Any]:
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

    try:
        _notificar(on_progress, "Coletando dados do edital no PNCP.")
        dados_compra = baixar_dados_compra_pncp(
            url_pncp,
            on_progress=on_progress,
        )

        _notificar(on_progress, "Consultando e mapeando contratos e empenhos.")
        resultado_etapa2 = consultar_e_mapear_empenhos(
            url_pncp,
            dados_compra=dados_compra,
            on_progress=on_progress,
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
        nome_compra = re.sub(
            r"[^A-Za-z0-9_-]+",
            "-",
            str(chaves["numero_compra"]).strip(),
        ).strip("-")
        ano_compra = re.sub(
            r"[^A-Za-z0-9_-]+",
            "-",
            str(chaves["ano_compra"]).strip(),
        ).strip("-")
        if not nome_compra or not ano_compra:
            raise ValueError("Número ou ano inválido para nomear o relatório.")
        arquivo_html = "relatorio_compra_{}_{}.html".format(nome_compra, ano_compra)
        _escrever_json(pasta_relatorio / "dados_pregao.json", dados_compra)
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
) -> Dict[str, Any]:
    lock_path = Path(index_path).parent.parent / ".private" / "report_update.lock"
    with interprocess_lock(lock_path):
        return _atualizar_processo(
            url_pncp,
            reports_dir=reports_dir,
            index_path=index_path,
            on_progress=on_progress,
            cadastrar_se_ausente=cadastrar_se_ausente,
        )


def atualizar_todos(
    *,
    reports_dir: Path = REPORTS_DIR,
    index_path: Path = INDEX_PATH,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
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
            resultado = atualizar_processo(
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

    lock_path = Path(index_path).parent.parent / ".private" / "report_update.lock"
    with interprocess_lock(lock_path):
        gerar_relatorios(Path(reports_dir), index_path=Path(index_path))
    return {"atualizados": sucessos, "falhas": falhas}
