import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .url_parser import validar_url_pncp
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = _PROJECT_ROOT / "relatorios"
INDEX_PATH = REPORTS_DIR / "indice_relatorios.json"


def chave_url_pncp(url: str) -> str:
    cnpj, ano, sequencial = validar_url_pncp(url)
    return "{}/{}/{}".format(cnpj, ano, int(sequencial))


def _id_processo(url: str) -> str:
    cnpj, ano, sequencial = validar_url_pncp(url)
    return "{}-{}-{}".format(cnpj, ano, int(sequencial))


def _ler_indice(caminho: Path) -> Dict[str, Any]:
    if not caminho.exists():
        return {"schema_version": 2, "quantidade_relatorios": 0, "relatorios": []}
    try:
        indice = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Não foi possível ler o índice de relatórios {}: {}".format(caminho, exc))
    if not isinstance(indice, dict) or not isinstance(indice.get("relatorios"), list):
        raise ValueError("O índice de relatórios deve conter a lista 'relatorios'.")

    registros = []
    chaves = set()
    for entrada in indice["relatorios"]:
        if not isinstance(entrada, dict) or not entrada.get("url_pncp"):
            raise ValueError("Cada processo do índice deve conter uma URL PNCP.")
        registro = dict(entrada)
        chave = chave_url_pncp(str(registro["url_pncp"]))
        if chave in chaves:
            raise ValueError("O índice contém URLs PNCP duplicadas: {}.".format(chave))
        chaves.add(chave)
        registro["id"] = _id_processo(str(registro["url_pncp"]))
        registro.setdefault("status", "atualizado" if registro.get("pasta") else "pendente")
        registros.append(registro)

    indice["schema_version"] = 2
    indice["relatorios"] = registros
    indice["quantidade_relatorios"] = len(registros)
    return indice


def ler_registros(caminho: Path = INDEX_PATH) -> List[Dict[str, Any]]:
    return _ler_indice(Path(caminho))["relatorios"]


def salvar_registros(registros: List[Dict[str, Any]], caminho: Path = INDEX_PATH) -> None:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    indice = {
        "schema_version": 2,
        "quantidade_relatorios": len(registros),
        "relatorios": registros,
    }
    temporario = caminho.with_name(caminho.name + ".tmp")
    with temporario.open("w", encoding="utf-8", newline="\n") as arquivo:
        json.dump(indice, arquivo, ensure_ascii=False, indent=2)
        arquivo.write("\n")
    temporario.replace(caminho)


def buscar_registro(url: str, caminho: Path = INDEX_PATH) -> Optional[Dict[str, Any]]:
    chave = chave_url_pncp(url)
    for registro in ler_registros(caminho):
        if chave_url_pncp(registro["url_pncp"]) == chave:
            return registro
    return None


def adicionar_registro(url: str, caminho: Path = INDEX_PATH) -> Dict[str, Any]:
    cnpj, ano, sequencial = validar_url_pncp(url)
    url = "https://pncp.gov.br/app/editais/{}/{}/{}".format(cnpj, ano, sequencial)
    registros = ler_registros(caminho)
    chave = chave_url_pncp(url)
    if any(chave_url_pncp(registro["url_pncp"]) == chave for registro in registros):
        raise ValueError("Este processo PNCP já está cadastrado.")

    registro = {
        "id": _id_processo(url),
        "url_pncp": url,
        "pasta": None,
        "status": "pendente",
        "atualizado_em": None,
        "chaves_integracao": {},
        "objeto": None,
        "resumo_cards": [],
    }
    registros.append(registro)
    salvar_registros(registros, caminho)
    return registro


def remover_registro(process_id: str, caminho: Path = INDEX_PATH) -> Dict[str, Any]:
    registros = ler_registros(caminho)
    for index, registro in enumerate(registros):
        if registro["id"] == process_id:
            removido = registros.pop(index)
            salvar_registros(registros, caminho)
            return removido
    raise KeyError("Processo não encontrado no índice.")


def atualizar_registro(
    url: str,
    atualizacao: Dict[str, Any],
    caminho: Path = INDEX_PATH,
) -> Dict[str, Any]:
    chave = chave_url_pncp(url)
    registros = ler_registros(caminho)
    for indice, registro in enumerate(registros):
        if chave_url_pncp(registro["url_pncp"]) == chave:
            registro.update(atualizacao)
            registro["id"] = _id_processo(registro["url_pncp"])
            registros[indice] = registro
            salvar_registros(registros, caminho)
            return registro
    raise KeyError("Processo não encontrado no índice.")
