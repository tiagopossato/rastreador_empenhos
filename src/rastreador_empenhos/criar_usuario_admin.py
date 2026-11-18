import os
import re
import sys
from getpass import getpass
from pathlib import Path
from typing import Callable

from .admin_web.auth import (
    hash_password,
    load_users,
    save_users,
    validate_users_path,
)
from .pncp_tracker import report_registry
from .project_root import caminho_projeto


def caminho_usuarios() -> Path:
    """Arquivo de usuários: `PNCP_ADMIN_USERS_FILE` ou `.private/usuarios.json` da raiz."""
    configurado = os.environ.get("PNCP_ADMIN_USERS_FILE")
    padrao = configurado or str(_caminho_padrao())
    return validate_users_path(Path(padrao), report_registry.REPORTS_DIR)


def _caminho_padrao() -> Path:
    return caminho_projeto(".private", "usuarios.json")


_USERNAME_PATTERN = r"[A-Za-z0-9_.-]{1,64}"


def criar_usuario(username: str, password: str, users_file: Path) -> None:
    """Valida as credenciais e grava o usuário, sem sobrescrever contas existentes."""
    if not re.fullmatch(_USERNAME_PATTERN, username):
        raise ValueError(
            "Use de 1 a 64 caracteres: letras, números, ponto, hífen ou sublinhado."
        )
    if len(password) < 8:
        raise ValueError("A senha deve ter pelo menos 8 caracteres.")
    users = load_users(users_file)
    if username in users:
        raise ValueError("Esse usuário já existe; nenhum dado foi alterado.")
    users[username] = hash_password(password)
    save_users(users, users_file)


def _erro_padrao(mensagem: str) -> None:
    print(mensagem, file=sys.stderr)


def solicitar_criacao_usuario(
    users_file: Path,
    input_fn: Callable[[str], str] = input,
    getpass_fn: Callable[[str], str] = getpass,
    output: Callable[[str], None] = print,
    error: Callable[[str], None] = _erro_padrao,
) -> bool:
    """Solicita os dados da primeira conta até criá-la; retorna False se o usuário desistir."""
    output(
        "Nenhum usuário cadastrado. Crie a primeira conta da interface administrativa."
    )
    while True:
        username = input_fn("Nome do usuário: ").strip()
        if not username:
            error("Criação cancelada: nenhum usuário foi cadastrado.")
            return False
        password = getpass_fn("Senha: ")
        confirmation = getpass_fn("Confirme a senha: ")
        if password != confirmation:
            error("As senhas não coincidem.")
            continue
        try:
            criar_usuario(username, password, users_file)
        except ValueError as exc:
            error(str(exc))
            continue
        except OSError as exc:
            error("Não foi possível salvar o usuário: {}".format(exc))
            return False
        output("Usuário '{}' criado em {}.".format(username, users_file))
        return True


def main() -> int:
    """Entry point do comando `rastreador-empenhos-criar-usuario`."""
    return run(users_file=caminho_usuarios())


def run(
    *,
    users_file: Path,
    input_fn: Callable[[str], str] = input,
    getpass_fn: Callable[[str], str] = getpass,
    output: Callable[[str], None] = print,
    error: Callable[[str], None] = _erro_padrao,
) -> int:
    username = input_fn("Nome do usuário: ").strip()

    password = getpass_fn("Senha: ")
    confirmation = getpass_fn("Confirme a senha: ")
    if password != confirmation:
        error("As senhas não coincidem.")
        return 1

    try:
        criar_usuario(username, password, users_file)
    except ValueError as exc:
        error(str(exc))
        return 1
    except OSError as exc:
        error("Não foi possível salvar o usuário: {}".format(exc))
        return 1

    output("Usuário criado em {}.".format(users_file))
    return 0


if __name__ == "__main__":
    sys.exit(main())
