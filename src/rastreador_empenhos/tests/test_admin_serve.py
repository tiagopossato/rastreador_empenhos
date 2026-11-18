import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import rastreador_empenhos.admin_web.serve as serve_module
from rastreador_empenhos.admin_web.auth import hash_password, load_users, save_users, verify_password
from rastreador_empenhos.admin_web.serve import garantir_usuario_inicial
from rastreador_empenhos.criar_usuario_admin import solicitar_criacao_usuario


class FirstUserCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.users_file = Path(self.temp_dir.name) / "usuarios.json"
        self.output = io.StringIO()
        self.errors = io.StringIO()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_existing_user_skips_the_prompt(self):
        save_users({"operador": hash_password("senha-valida")}, self.users_file)
        solicitacoes = []

        garantir_usuario_inicial(
            self.users_file, lambda arquivo: solicitacoes.append(arquivo) or True
        )

        self.assertEqual(solicitacoes, [])

    def test_missing_user_is_created_through_the_prompt(self):
        def input_fn(_prompt):
            return "primeiro"

        def getpass_fn(_prompt):
            return "senha-valida"

        with patch("builtins.print"):
            criada = solicitar_criacao_usuario(
                self.users_file,
                input_fn=input_fn,
                getpass_fn=getpass_fn,
                output=self.output.write,
                error=self.errors.write,
            )

        self.assertTrue(criada)
        registro = load_users(self.users_file)["primeiro"]
        self.assertTrue(verify_password("senha-valida", registro))
        self.assertNotIn("senha-valida", self.users_file.read_text(encoding="utf-8"))

    def test_prompt_repeats_until_a_valid_password_is_informed(self):
        usuarios = iter(["primeiro", "primeiro"])
        senhas = iter(["curta", "curta", "senha-valida", "senha-valida"])

        criada = solicitar_criacao_usuario(
            self.users_file,
            input_fn=lambda _prompt: next(usuarios),
            getpass_fn=lambda _prompt: next(senhas),
            output=self.output.write,
            error=self.errors.write,
        )

        self.assertTrue(criada)
        self.assertIn("pelo menos 8 caracteres", self.errors.getvalue())
        self.assertIn("primeiro", load_users(self.users_file))

    def test_declining_stops_the_server_startup(self):
        with self.assertRaises(SystemExit):
            garantir_usuario_inicial(
                self.users_file, lambda arquivo: False
            )

        self.assertFalse(self.users_file.exists())

    def test_prompt_cancelled_by_empty_username_creates_no_file(self):
        criada = solicitar_criacao_usuario(
            self.users_file,
            input_fn=lambda _prompt: "  ",
            getpass_fn=lambda _prompt: "senha-valida",
            output=self.output.write,
            error=self.errors.write,
        )

        self.assertFalse(criada)
        self.assertFalse(self.users_file.exists())

    def _solicitar(self):
        return solicitar_criacao_usuario(
            self.users_file,
            input_fn=lambda _prompt: "primeiro",
            getpass_fn=lambda _prompt: "senha-valida",
            output=self.output.write,
            error=self.errors.write,
        )

    def test_missing_user_is_created_through_the_prompt(self):
        self.assertTrue(self._solicitar())
        registro = load_users(self.users_file)["primeiro"]
        self.assertTrue(verify_password("senha-valida", registro))
        self.assertNotIn("senha-valida", self.users_file.read_text(encoding="utf-8"))

    def test_startup_prompts_and_creates_the_first_user(self):
        with patch.object(
            serve_module, "solicitar_criacao_usuario", side_effect=lambda arquivo: (
                solicitar_criacao_usuario(
                    arquivo,
                    input_fn=lambda _prompt: "primeiro",
                    getpass_fn=lambda _prompt: "senha-valida",
                    output=self.output.write,
                    error=self.errors.write,
                )
            )
        ) as solicitacao:
            garantir_usuario_inicial(self.users_file)

        solicitacao.assert_called_once_with(self.users_file)
        self.assertTrue(verify_password("senha-valida", load_users(self.users_file)["primeiro"]))

    def test_main_checks_the_user_before_serving(self):
        chamadas = []
        with patch.object(serve_module, "_configure_logging", return_value=Path("log")), patch.object(
            serve_module,
            "create_app",
            side_effect=lambda: chamadas.append("app") or object(),
        ), patch.object(
            serve_module, "serve", side_effect=lambda app, host, port: chamadas.append("serve")
        ), patch.object(
            serve_module, "caminho_usuarios", return_value=self.users_file
        ) as caminho, patch.object(
            serve_module, "solicitar_criacao_usuario", return_value=False
        ) as criacao:
            with self.assertRaises(SystemExit):
                serve_module.main()

        caminho.assert_called_once_with()
        criacao.assert_called_once_with(self.users_file)
        self.assertEqual(chamadas, [])


if __name__ == "__main__":
    unittest.main()
