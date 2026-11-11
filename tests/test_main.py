import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main as main_module
from main import _nome_arquivo_relatorio, _obter_url_pncp


class MainTests(unittest.TestCase):
    def test_pncp_url_is_taken_from_argument(self):
        url = "https://pncp.gov.br/app/editais/10635424000186/2025/187"
        self.assertEqual(_obter_url_pncp(url), url)

    def test_missing_url_is_requested_from_input(self):
        url = "https://pncp.gov.br/app/editais/10635424000186/2025/187"
        prompts = []

        def fake_input(prompt):
            prompts.append(prompt)
            return url

        self.assertEqual(_obter_url_pncp(None, fake_input), url)
        self.assertEqual(len(prompts), 1)

    def test_empty_input_aborts_before_processing(self):
        with self.assertRaisesRegex(ValueError, "Nenhum link"):
            _obter_url_pncp(None, lambda _prompt: "  ")

    def test_invalid_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "URL inválida"):
            _obter_url_pncp("https://example.com")

    def test_report_filename_includes_purchase_number_and_year(self):
        self.assertEqual(
            _nome_arquivo_relatorio(
                {"numero_compra": "90026", "ano_compra": 2025}
            ),
            "relatorio_compra_90026_2025.html",
        )

    def test_report_filename_sanitizes_path_separators(self):
        self.assertEqual(
            _nome_arquivo_relatorio(
                {"numero_compra": "90026/2025", "ano_compra": 2025}
            ),
            "relatorio_compra_90026-2025_2025.html",
        )

    def _run_main_in_temp_project(self, arguments):
        project = Path(self.temp_dir.name)
        purchase = {
            "chaves_integracao": {
                "numero_compra": "90026",
                "ano_compra": 2025,
            },
            "quantidade_itens": 0,
            "itens": [],
        }
        result = {
            "chaves_integracao": purchase["chaves_integracao"],
            "status": "ok",
            "quantidade_empenhos": 0,
        }

        def generate_report(_data, path):
            Path(path).write_text("<html></html>", encoding="utf-8")
            return Path(path)

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(main_module, "__file__", str(project / "main.py")))
            stack.enter_context(
                patch.object(main_module, "baixar_dados_compra_pncp", return_value=purchase)
            )
            stack.enter_context(patch.object(main_module, "consultar_e_mapear_empenhos", return_value=result))
            stack.enter_context(
                patch.object(main_module, "gerar_relatorio_html", side_effect=generate_report)
            )
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            main_module.main(
                ["https://pncp.gov.br/app/editais/10635424000186/2025/187", *arguments]
            )
        return project

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_json_files_are_removed_by_default_after_report_generation(self):
        project = self._run_main_in_temp_project([])

        self.assertFalse((project / "etapa1_dados_compra.json").exists())
        self.assertFalse((project / "etapa2_empenhos.json").exists())
        self.assertTrue((project / "relatorio_compra_90026_2025.html").exists())

    def test_keep_json_flag_preserves_json_files(self):
        project = self._run_main_in_temp_project(["--manter-json"])

        self.assertTrue((project / "etapa1_dados_compra.json").exists())
        self.assertTrue((project / "etapa2_empenhos.json").exists())
        self.assertTrue((project / "relatorio_compra_90026_2025.html").exists())

    def test_keep_json_camel_case_alias_preserves_json_files(self):
        project = self._run_main_in_temp_project(["--manterJSON"])

        self.assertTrue((project / "etapa1_dados_compra.json").exists())
        self.assertTrue((project / "etapa2_empenhos.json").exists())


if __name__ == "__main__":
    unittest.main()
