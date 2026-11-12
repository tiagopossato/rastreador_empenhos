import unittest
from unittest.mock import patch

from pncp_tracker.collector import baixar_dados_compra_pncp
from pncp_tracker.constants import DEFAULT_PAGE_SIZE


_URL = "https://pncp.gov.br/app/editais/10635424000186/2025/000282"
_PURCHASE = {
    "numeroCompra": "90059",
    "anoCompra": 2025,
    "numeroControlePNCP": "10635424000186-1-000282/2025",
    "objetoCompra": "Compra de teste",
    "unidadeOrgao": {"codigoUnidade": "158125", "nomeUnidade": "Órgão de teste"},
}


class CollectorTests(unittest.TestCase):
    def _baixar(self, lotes, resultados=None, progresso=None):
        with patch(
            "pncp_tracker.collector.buscar_dados_compra",
            return_value=_PURCHASE,
        ), patch(
            "pncp_tracker.collector.listar_itens",
            side_effect=lotes,
        ), patch(
            "pncp_tracker.collector.buscar_resultados_item",
            return_value=resultados if resultados is not None else [{"niFornecedor": "1"}],
        ) as resultados_mock:
            dados = baixar_dados_compra_pncp(_URL, on_progress=progresso)
        return dados, resultados_mock

    def test_pagination_stops_at_the_first_short_page(self):
        primeira_pagina = [{"numeroItem": numero} for numero in range(1, DEFAULT_PAGE_SIZE + 1)]
        segunda_pagina = [{"numeroItem": DEFAULT_PAGE_SIZE + 1}]

        dados, resultados = self._baixar([primeira_pagina, segunda_pagina])

        self.assertEqual(dados["quantidade_itens"], DEFAULT_PAGE_SIZE + 1)
        self.assertEqual(resultados.call_count, DEFAULT_PAGE_SIZE + 1)
        self.assertEqual(dados["chaves_integracao"]["numero_compra"], "90059")

    def test_items_without_number_are_kept_without_result_lookup(self):
        dados, resultados = self._baixar([[{"descricao": "Item sem número"}]])

        self.assertEqual(dados["quantidade_itens"], 1)
        resultados.assert_not_called()
        self.assertEqual(dados["itens"], [{"descricao": "Item sem número"}])

    def test_progress_reports_pages_and_collected_totals(self):
        mensagens = []
        primeira_pagina = [{"numeroItem": numero} for numero in range(1, DEFAULT_PAGE_SIZE + 1)]
        segunda_pagina = [{"numeroItem": DEFAULT_PAGE_SIZE + 1}]

        self._baixar([primeira_pagina, segunda_pagina], progresso=mensagens.append)

        texto = " ".join(mensagens)
        self.assertIn("página 1", texto.lower())
        self.assertIn("página 2", texto.lower())
        self.assertIn(str(DEFAULT_PAGE_SIZE + 1), texto)

    def test_progress_reports_purchase_without_items(self):
        mensagens = []

        dados, _ = self._baixar([[]], progresso=mensagens.append)

        self.assertEqual(dados["quantidade_itens"], 0)
        self.assertTrue(any("não retornou itens" in mensagem for mensagem in mensagens))

    def test_results_are_attached_to_each_item(self):
        dados, _ = self._baixar(
            [[{"numeroItem": 7}]],
            resultados=[{"niFornecedor": "12345678000199", "valorUnitarioHomologado": 10}],
        )

        self.assertEqual(dados["erros_resultados_itens"], [])
        self.assertEqual(
            dados["itens"][0]["resultadosHomologados"],
            [{"niFornecedor": "12345678000199", "valorUnitarioHomologado": 10}],
        )

    def test_result_lookup_error_is_reported_without_marking_item_as_empty_success(self):
        mensagens = []
        with patch(
            "pncp_tracker.collector.buscar_dados_compra",
            return_value=_PURCHASE,
        ), patch(
            "pncp_tracker.collector.listar_itens",
            return_value=[{"numeroItem": 9}],
        ), patch(
            "pncp_tracker.collector.buscar_resultados_item",
            side_effect=TimeoutError("timeout"),
        ):
            dados = baixar_dados_compra_pncp(_URL, on_progress=mensagens.append)

        self.assertEqual(dados["itens"][0]["resultadosHomologados"], [])
        self.assertIn("TimeoutError: timeout", dados["itens"][0]["erroResultadosHomologados"])
        self.assertEqual(
            dados["erros_resultados_itens"],
            [{"numero_item": 9, "erro": "TimeoutError: timeout"}],
        )
        self.assertTrue(any("Falha ao consultar resultados" in msg for msg in mensagens))

    def test_invalid_purchase_header_stops_before_item_collection(self):
        with patch(
            "pncp_tracker.collector.buscar_dados_compra",
            return_value={},
        ), patch("pncp_tracker.collector.listar_itens") as list_items:
            with self.assertRaisesRegex(ValueError, "Cabeçalho da compra incompleto"):
                baixar_dados_compra_pncp(_URL)

        list_items.assert_not_called()


if __name__ == "__main__":
    unittest.main()
