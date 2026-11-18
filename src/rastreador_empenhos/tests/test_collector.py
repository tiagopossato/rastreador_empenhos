import unittest
from unittest.mock import patch

from rastreador_empenhos.pncp_tracker.collector import baixar_dados_compra_pncp
from rastreador_empenhos.pncp_tracker.constants import DEFAULT_PAGE_SIZE
from rastreador_empenhos.pncp_tracker.rate_limit import CONTRATOS_GOV_LIMITER, PNCP_LIMITER

PNCP_LIMITER.desativar()
CONTRATOS_GOV_LIMITER.desativar()


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
            "rastreador_empenhos.pncp_tracker.collector.buscar_dados_compra",
            return_value=_PURCHASE,
        ), patch(
            "rastreador_empenhos.pncp_tracker.collector.listar_itens",
            side_effect=lotes,
        ), patch(
            "rastreador_empenhos.pncp_tracker.collector.buscar_resultados_item",
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
            "rastreador_empenhos.pncp_tracker.collector.buscar_dados_compra",
            return_value=_PURCHASE,
        ), patch(
            "rastreador_empenhos.pncp_tracker.collector.listar_itens",
            return_value=[{"numeroItem": 9}],
        ), patch(
            "rastreador_empenhos.pncp_tracker.collector.buscar_resultados_item",
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

    def test_snapshot_is_reused_when_pncp_did_not_change(self):
        dados_anteriores = {
            "chave_cache": "10635424000186-1-000282/2025|2026-01-02T10:00:00",
            "itens": [{"numeroItem": 1, "resultadosHomologados": [{"niFornecedor": "1"}]}],
            "chaves_integracao": {"numero_compra": "90059"},
        }
        compra = dict(
            _PURCHASE,
            dataAtualizacaoGlobal="2026-01-02T10:00:00",
        )
        mensagens = []
        with patch(
            "rastreador_empenhos.pncp_tracker.collector.buscar_dados_compra", return_value=compra
        ), patch("rastreador_empenhos.pncp_tracker.collector.listar_itens") as listar, patch(
            "rastreador_empenhos.pncp_tracker.collector.buscar_resultados_item"
        ) as resultados:
            dados = baixar_dados_compra_pncp(
                _URL, on_progress=mensagens.append, dados_anteriores=dados_anteriores
            )

        listar.assert_not_called()
        resultados.assert_not_called()
        self.assertTrue(dados["cache_reutilizado"])
        self.assertEqual(dados["itens"], dados_anteriores["itens"])
        self.assertTrue(any("reutilizando" in m for m in mensagens))

    def test_snapshot_is_discarded_when_pncp_changed(self):
        dados_anteriores = {
            "chave_cache": "10635424000186-1-000282/2025|2026-01-01T00:00:00",
            "itens": [{"numeroItem": 99}],
        }
        compra = dict(_PURCHASE, dataAtualizacaoGlobal="2026-02-02T00:00:00")
        with patch(
            "rastreador_empenhos.pncp_tracker.collector.buscar_dados_compra", return_value=compra
        ), patch(
            "rastreador_empenhos.pncp_tracker.collector.listar_itens", side_effect=[[{"numeroItem": 1}]]
        ), patch(
            "rastreador_empenhos.pncp_tracker.collector.buscar_resultados_item", return_value=[]
        ):
            dados = baixar_dados_compra_pncp(_URL, dados_anteriores=dados_anteriores)

        self.assertNotIn("cache_reutilizado", dados)
        self.assertEqual([i["numeroItem"] for i in dados["itens"]], [1])
        self.assertEqual(dados["chave_cache"], "10635424000186-1-000282/2025|2026-02-02T00:00:00")

    def test_parallel_result_lookup_preserves_item_order(self):
        pagina = [{"numeroItem": numero} for numero in range(1, 21)]
        with patch(
            "rastreador_empenhos.pncp_tracker.collector.buscar_dados_compra",
            return_value=dict(_PURCHASE, dataAtualizacaoGlobal="2026-03-03T00:00:00"),
        ), patch("rastreador_empenhos.pncp_tracker.collector.listar_itens", side_effect=[pagina]), patch(
            "rastreador_empenhos.pncp_tracker.collector.buscar_resultados_item",
            side_effect=lambda _c, _a, _s, numero: [{"niFornecedor": str(numero)}],
        ):
            dados = baixar_dados_compra_pncp(_URL)

        self.assertEqual(
            [item["numeroItem"] for item in dados["itens"]],
            list(range(1, 21)),
        )
        self.assertEqual(
            [item["resultadosHomologados"][0]["niFornecedor"] for item in dados["itens"]],
            [str(numero) for numero in range(1, 21)],
        )

    def test_invalid_purchase_header_stops_before_item_collection(self):
        with patch(
            "rastreador_empenhos.pncp_tracker.collector.buscar_dados_compra",
            return_value={},
        ), patch("rastreador_empenhos.pncp_tracker.collector.listar_itens") as list_items:
            with self.assertRaisesRegex(ValueError, "Cabeçalho da compra incompleto"):
                baixar_dados_compra_pncp(_URL)

        list_items.assert_not_called()


if __name__ == "__main__":
    unittest.main()
