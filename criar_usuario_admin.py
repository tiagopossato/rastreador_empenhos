import os
import re
import sys
from getpass import getpass
from pathlib import Path

from admin_web.auth import hash_password, load_users, save_users, validate_users_path
from pncp_tracker.report_registry import REPORTS_DIR


_PROJECT_ROOT = Path(__file__).resolve().parent
_USERS_FILE = Path(
    os.environ.get(
        "PNCP_ADMIN_USERS_FILE",
        str(_PROJECT_ROOT / ".private" / "usuarios.json"),
    )
)


def main() -> int:
    username = input("Nome do usuário: ").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username):
        print("Use de 1 a 64 caracteres: letras, números, ponto, hífen ou sublinhado.", file=sys.stderr)
        return 1

    password = getpass("Senha: ")
    confirmation = getpass("Confirme a senha: ")
    if len(password) < 8:
        print("A senha deve ter pelo menos 8 caracteres.", file=sys.stderr)
        return 1
    if password != confirmation:
        print("As senhas não coincidem.", file=sys.stderr)
        return 1

    try:
        users_file = validate_users_path(_USERS_FILE, REPORTS_DIR)
        users = load_users(users_file)
        if username in users:
            print("Esse usuário já existe; nenhum dado foi alterado.", file=sys.stderr)
            return 1
        users[username] = hash_password(password)
        save_users(users, users_file)
    except (OSError, ValueError) as exc:
        print("Não foi possível salvar o usuário: {}".format(exc), file=sys.stderr)
        return 1

    print("Usuário criado em {}.".format(_USERS_FILE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
