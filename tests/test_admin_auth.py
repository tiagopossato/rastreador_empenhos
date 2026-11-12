import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import criar_usuario_admin
from admin_web.auth import (
    hash_password,
    load_users,
    save_users,
    validate_users_path,
    verify_password,
)


class PasswordTests(unittest.TestCase):
    def test_hash_records_the_algorithm_and_iterations(self):
        record = hash_password("senha-de-teste")

        self.assertEqual(record["algorithm"], "pbkdf2_sha256")
        self.assertGreaterEqual(record["iterations"], 100000)
        self.assertTrue(verify_password("senha-de-teste", record))

    def test_short_salt_or_hash_is_rejected(self):
        record = hash_password("senha-de-teste")
        record["password_hash"] = ""

        self.assertFalse(verify_password("senha-de-teste", record))

    def test_unknown_algorithm_is_rejected(self):
        record = hash_password("senha-de-teste")
        record["algorithm"] = "md5"

        self.assertFalse(verify_password("senha-de-teste", record))

    def test_weak_iteration_count_is_rejected(self):
        record = hash_password("senha-de-teste")
        record["iterations"] = 1000

        self.assertFalse(verify_password("senha-de-teste", record))

    def test_malformed_record_is_rejected_without_raising(self):
        self.assertFalse(verify_password("senha-de-teste", {"algorithm": "pbkdf2_sha256"}))
        self.assertFalse(
            verify_password(
                "senha-de-teste",
                {"algorithm": "pbkdf2_sha256", "salt": "zz", "password_hash": "zz", "iterations": "x"},
            )
        )


class UserFileTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.reports_dir = self.root / "relatorios"
        self.reports_dir.mkdir()
        self.users_path = self.root / "usuarios.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_file_is_treated_as_an_empty_database(self):
        self.assertEqual(load_users(self.users_path), {})

    def test_round_trip_preserves_users(self):
        save_users({"admin": hash_password("senha-de-teste")}, self.users_path)

        carregado = load_users(self.users_path)

        self.assertEqual(list(carregado), ["admin"])
        self.assertTrue(verify_password("senha-de-teste", carregado["admin"]))

    def test_invalid_json_is_reported(self):
        self.users_path.write_text("{invalido", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "arquivo de usuários"):
            load_users(self.users_path)

    def test_non_object_payload_is_reported(self):
        self.users_path.write_text("[1, 2]", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "objeto JSON"):
            load_users(self.users_path)

    def test_user_file_inside_the_published_directory_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "fora da pasta publicada"):
            validate_users_path(self.reports_dir / "usuarios.json", self.reports_dir)

    def test_saved_file_contains_only_hashes(self):
        save_users({"admin": hash_password("senha-de-teste")}, self.users_path)

        conteudo = self.users_path.read_text(encoding="utf-8")

        self.assertNotIn("senha-de-teste", conteudo)
        self.assertIn("password_hash", json.loads(conteudo)["admin"])


class UserCreationScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.users_file = Path(self.temp_dir.name) / "usuarios.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _executar(self, usuario, senhas):
        with patch.object(criar_usuario_admin, "_USERS_FILE", self.users_file), patch(
            "builtins.input", return_value=usuario
        ), patch("criar_usuario_admin.getpass", side_effect=senhas):
            return criar_usuario_admin.main()

    def test_rejects_invalid_username_without_creating_a_file(self):
        with patch("sys.stderr"):
            self.assertEqual(self._executar("usuário inválido", ["senha-longa", "senha-longa"]), 1)

        self.assertFalse(self.users_file.exists())

    def test_rejects_short_password_without_creating_a_file(self):
        with patch("sys.stderr"):
            self.assertEqual(self._executar("operador", ["curta", "curta"]), 1)

        self.assertFalse(self.users_file.exists())

    def test_rejects_password_confirmation_mismatch(self):
        with patch("sys.stderr"):
            self.assertEqual(self._executar("operador", ["senha-longa", "outra-senha"]), 1)

        self.assertFalse(self.users_file.exists())

    def test_does_not_overwrite_an_existing_user(self):
        save_users({"operador": hash_password("senha-original")}, self.users_file)

        with patch("sys.stderr"):
            self.assertEqual(self._executar("operador", ["senha-nova-1", "senha-nova-1"]), 1)

        registro = json.loads(self.users_file.read_text(encoding="utf-8"))["operador"]
        self.assertTrue(verify_password("senha-original", registro))
        self.assertFalse(verify_password("senha-nova-1", registro))


if __name__ == "__main__":
    unittest.main()
