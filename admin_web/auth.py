import hashlib
import hmac
import os
from pathlib import Path
import stat
from typing import Dict, Optional


_ITERATIONS = 600000


def hash_password(password: str, salt: Optional[bytes] = None) -> Dict[str, str]:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _ITERATIONS,
    )
    return {
        "salt": salt.hex(),
        "password_hash": digest.hex(),
        "iterations": _ITERATIONS,
        "algorithm": "pbkdf2_sha256",
    }


def verify_password(password: str, record: Dict[str, object]) -> bool:
    if record.get("algorithm") != "pbkdf2_sha256":
        return False
    try:
        salt = bytes.fromhex(str(record["salt"]))
        expected = bytes.fromhex(str(record["password_hash"]))
        iterations = int(record["iterations"])
    except (KeyError, TypeError, ValueError):
        return False
    if iterations < 100000 or iterations > 2000000 or not salt or not expected:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def load_users(path: Path) -> Dict[str, Dict[str, object]]:
    import json

    path = Path(path)
    if not path.exists():
        return {}
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("O arquivo de usuários deve ter permissões privadas (0600).")
    try:
        users = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Não foi possível ler o arquivo de usuários: {}".format(exc))
    if not isinstance(users, dict) or not all(
        isinstance(username, str) and isinstance(record, dict)
        for username, record in users.items()
    ):
        raise ValueError("O arquivo de usuários deve ser um objeto JSON válido.")
    return users


def validate_users_path(path: Path, reports_dir: Path) -> Path:
    path = Path(path).resolve()
    reports_dir = Path(reports_dir).resolve()
    try:
        path.relative_to(reports_dir)
    except ValueError:
        return path
    raise ValueError("O arquivo de usuários deve ficar fora da pasta publicada relatorios/.")


def save_users(users: Dict[str, Dict[str, object]], path: Path) -> None:
    import json

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.parent.chmod(0o700)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(users, file, ensure_ascii=False, indent=2)
        file.write("\n")
    if os.name != "nt":
        os.chmod(temporary, 0o600)
    temporary.replace(path)
    if os.name != "nt":
        os.chmod(path, 0o600)
