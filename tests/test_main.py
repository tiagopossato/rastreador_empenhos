import unittest

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


if __name__ == "__main__":
    unittest.main()
