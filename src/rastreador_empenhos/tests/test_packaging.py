import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

import rastreador_empenhos
from rastreador_empenhos import project_root
from rastreador_empenhos.pncp_tracker import report_registry
from rastreador_empenhos.pncp_tracker import portal_transparencia


_PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"


class PackagingTests(unittest.TestCase):
    def test_scripts_point_to_existing_callables(self):
        config = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
        scripts = config["project"]["scripts"]
        self.assertEqual(
            set(scripts),
            {
                "rastreador-empenhos",
                "rastreador-empenhos-atualizar",
                "rastreador-empenhos-criar-usuario",
                "rastreador-empenhos-gerar-indice",
                "rastreador-empenhos-admin",
            },
        )
        for modulo, funcao in (alvo.split(":") for alvo in scripts.values()):
            with self.subTest(modulo=modulo):
                import importlib

                alvo = importlib.import_module(modulo)
                self.assertTrue(callable(getattr(alvo, funcao)))

    def test_configuration_declares_src_layout_and_dependencies(self):
        config = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
        self.assertEqual(config["build-system"]["build-backend"], "setuptools.build_meta")
        self.assertEqual(config["tool"]["setuptools"]["packages"]["find"]["where"], ["src"])
        dependencias = " ".join(config["project"]["dependencies"])
        for pacote in ("requests", "Flask", "waitress"):
            self.assertIn(pacote, dependencias)
        self.assertEqual(config["project"]["dynamic"], ["version"])

    def test_version_is_available_to_the_build(self):
        self.assertRegex(rastreador_empenhos.__version__, r"^\d+\.\d+\.\d+$")


class ProjectRootTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "relatorios").mkdir()
        (self.root / "relatorios" / "indice_relatorios.json").write_text(
            '{"relatorios": []}', encoding="utf-8"
        )
        (self.root / "README.md").write_text("# teste", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_environment_variable_has_priority(self):
        with patch.dict("os.environ", {"RASTREADOR_EMPENHOS_ROOT": str(self.root)}):
            self.assertEqual(project_root.encontrar_raiz_projeto(), self.root.resolve())
            self.assertEqual(
                project_root.caminho_projeto("relatorios"),
                self.root.resolve() / "relatorios",
            )

    def test_root_is_detected_from_inside_a_report_folder(self):
        pasta_relatorio = self.root / "relatorios" / "processo_1"
        pasta_relatorio.mkdir()
        with patch.dict("os.environ", {}, clear=True), patch(
            "os.getcwd", return_value=str(pasta_relatorio)
        ):
            self.assertEqual(project_root.encontrar_raiz_projeto(), self.root.resolve())

    def test_empty_environment_variable_is_ignored(self):
        with patch.dict("os.environ", {"RASTREADOR_EMPENHOS_ROOT": ""}), patch(
            "os.getcwd", return_value=str(self.root)
        ):
            self.assertEqual(project_root.encontrar_raiz_projeto(), self.root.resolve())

    def test_modules_do_not_keep_import_time_paths(self):
        """O código instalado em site-packages não pode derivar dados de `__file__`."""
        pasta_pacote = Path(rastreador_empenhos.__file__).resolve().parent
        for arquivo in pasta_pacote.rglob("*.py"):
            if "tests" in arquivo.parts:
                continue
            with self.subTest(arquivo=arquivo.name):
                self.assertNotIn("__file__", arquivo.read_text(encoding="utf-8"))

    def test_admin_commands_share_the_same_users_file(self):
        from rastreador_empenhos import criar_usuario_admin

        with patch.dict(
            "os.environ",
            {
                "PNCP_ADMIN_USERS_FILE": str(self.root / "usuarios.json"),
                "RASTREADOR_EMPENHOS_ROOT": str(self.root),
            },
        ):
            self.assertEqual(
                criar_usuario_admin.caminho_usuarios(), (self.root / "usuarios.json").resolve()
            )

        with patch.object(
            criar_usuario_admin, "caminho_projeto", return_value=self.root / ".private" / "usuarios.json"
        ) as raiz, patch.dict(
            "os.environ", {"PNCP_ADMIN_USERS_FILE": "", "RASTREADOR_EMPENHOS_ROOT": ""}
        ), patch.object(
            criar_usuario_admin.report_registry, "REPORTS_DIR", self.root / "relatorios"
        ):
            self.assertEqual(
                criar_usuario_admin.caminho_usuarios(),
                (self.root / ".private" / "usuarios.json").resolve(),
            )
        raiz.assert_called_once_with(".private", "usuarios.json")

    def test_users_file_inside_published_folder_is_rejected(self):
        from rastreador_empenhos import criar_usuario_admin

        with patch.object(
            criar_usuario_admin.report_registry, "REPORTS_DIR", self.root / "relatorios"
        ), patch.dict(
            "os.environ",
            {
                "RASTREADOR_EMPENHOS_ROOT": str(self.root),
                "PNCP_ADMIN_USERS_FILE": str(self.root / "relatorios" / "u.json"),
            },
        ):
            with self.assertRaisesRegex(ValueError, "fora da pasta publicada"):
                criar_usuario_admin.caminho_usuarios()


class EntryPointTests(unittest.TestCase):
    def test_generate_index_runs_with_an_explicit_folder(self):
        from rastreador_empenhos.gerar_relatorios import main as gerar_main

        with tempfile.TemporaryDirectory() as temp_dir:
            pasta = Path(temp_dir) / "relatorios"
            pasta.mkdir()
            (pasta / "indice_relatorios.json").write_text(
                '{"relatorios": []}', encoding="utf-8"
            )
            with patch("builtins.print"):
                self.assertEqual(gerar_main([str(pasta)]), 0)
            self.assertTrue((pasta / "index.html").is_file())

    def test_generate_index_module_delegates_to_the_generator(self):
        from rastreador_empenhos import generate_reports_index

        self.assertEqual(
            generate_reports_index.main.__module__, "rastreador_empenhos.gerar_relatorios"
        )

    def test_generate_index_uses_the_detected_project_root(self):
        from rastreador_empenhos import gerar_relatorios

        raiz = Path(tempfile.gettempdir()) / "raiz_inexistente_para_teste"
        with patch.object(
            gerar_relatorios, "_resolve_folder", return_value=raiz
        ), patch.object(
            gerar_relatorios, "gerar_relatorios", return_value=raiz / "index.html"
        ) as gerar, patch.object(gerar_relatorios, "interprocess_lock"), patch(
            "builtins.print"
        ):
            self.assertEqual(gerar_relatorios.main([]), 0)

        gerar.assert_called_once_with(raiz, index_path=raiz / "indice_relatorios.json")

    def test_update_reports_returns_nonzero_when_a_process_fails(self):
        from rastreador_empenhos import atualizar_relatorios

        resultado = {
            "atualizados": [],
            "falhas": [{"url_pncp": "https://pncp.gov.br/x", "erro": "timeout"}],
        }
        with patch.object(
            atualizar_relatorios, "atualizar_todos", return_value=resultado
        ), patch("builtins.print"):
            self.assertEqual(atualizar_relatorios.main(), 1)


if __name__ == "__main__":
    unittest.main()
