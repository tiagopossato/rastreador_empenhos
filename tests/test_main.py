import contextlib
import io
import unittest
from unittest.mock import patch

import main as main_module
from main import _obter_url_pncp


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
        with self.assertRaisesRegex(ValueError, "URL HTTPS"):
            _obter_url_pncp("https://example.com/app/editais/10635424000186/2025/187")

    def test_main_delegates_to_the_shared_service(self):
        url = "https://pncp.gov.br/app/editais/10635424000186/2025/187"
        result = {
            "resultado_etapa2": {
                "status": "ok",
                "mensagem": "Coleta concluída",
                "quantidade_empenhos": 2,
            },
            "caminho_relatorio": "relatorio.html",
            "caminho_index": "index.html",
        }
        with contextlib.redirect_stdout(io.StringIO()), patch.object(
            main_module, "atualizar_processo", return_value=result
        ) as service:
            main_module.main([url])
        service.assert_called_once_with(url, on_progress=unittest.mock.ANY)

    def test_main_reports_service_error_as_nonzero_exit(self):
        with contextlib.redirect_stderr(io.StringIO()), patch.object(
            main_module,
            "atualizar_processo",
            side_effect=RuntimeError("falha de teste"),
        ):
            with self.assertRaises(SystemExit) as exc:
                main_module.main(
                    ["https://pncp.gov.br/app/editais/10635424000186/2025/187"]
                )
        self.assertEqual(exc.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
