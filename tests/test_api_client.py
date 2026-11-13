import unittest
from unittest.mock import Mock, patch

import requests

from pncp_tracker.api_client import (
    _buscar_json_robusto,
    buscar_dados_compra,
    buscar_resultados_item,
    listar_itens,
)


def _resposta(status_code=200, payload=None, erro_json=None):
    resposta = Mock(status_code=status_code)
    if erro_json is not None:
        resposta.json.side_effect = erro_json
    else:
        resposta.json.return_value = payload
    return resposta


class BuscarJsonRobustoTests(unittest.TestCase):
    def test_uses_the_first_endpoint_that_returns_json(self):
        resposta = _resposta(payload={"numeroCompra": "90059"})
        with patch("pncp_tracker.api_client.requests.get", return_value=resposta) as get:
            self.assertEqual(
                _buscar_json_robusto(["https://pncp.gov.br/a", "https://pncp.gov.br/b"]),
                {"numeroCompra": "90059"},
            )
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], "https://pncp.gov.br/a")

    def test_falls_back_to_the_next_endpoint_after_a_request_error(self):
        falha = Mock()
        falha.raise_for_status.side_effect = requests.RequestException("indisponível")
        sucesso = _resposta(payload={"numeroCompra": "90059"})
        with patch(
            "pncp_tracker.api_client.requests.get",
            side_effect=[falha, sucesso],
        ):
            self.assertEqual(
                _buscar_json_robusto(["https://pncp.gov.br/a", "https://pncp.gov.br/b"]),
                {"numeroCompra": "90059"},
            )

    def test_falls_back_when_the_payload_is_not_valid_json(self):
        invalido = _resposta(erro_json=ValueError("sem json"))
        sucesso = _resposta(payload={"numeroCompra": "90059"})
        with patch(
            "pncp_tracker.api_client.requests.get",
            side_effect=[invalido, sucesso],
        ):
            self.assertEqual(
                _buscar_json_robusto(["https://pncp.gov.br/a", "https://pncp.gov.br/b"]),
                {"numeroCompra": "90059"},
            )

    def test_no_content_response_is_not_a_valid_purchase_header(self):
        with patch(
            "pncp_tracker.api_client.requests.get",
            return_value=_resposta(status_code=204),
        ):
            with self.assertRaises(requests.RequestException):
                _buscar_json_robusto(["https://pncp.gov.br/a"])

    def test_raises_when_no_endpoint_returns_valid_json(self):
        falha = Mock()
        falha.raise_for_status.side_effect = requests.RequestException("indisponível")
        with patch("pncp_tracker.api_client.requests.get", return_value=falha):
            with self.assertRaises(requests.RequestException):
                _buscar_json_robusto(["https://pncp.gov.br/a", "https://pncp.gov.br/b"])


class ConsultasPncpTests(unittest.TestCase):
    def test_purchase_header_uses_the_edital_parameters(self):
        with patch(
            "pncp_tracker.api_client.requests.get",
            return_value=_resposta(payload={"numeroCompra": "282"}),
        ) as get:
            buscar_dados_compra("10635424000186", "2025", "282")

        primeira_url = get.call_args_list[0].args[0]
        self.assertTrue(primeira_url.endswith("/10635424000186/compras/2025/282"))
        self.assertTrue(primeira_url.startswith("https://pncp.gov.br/api/consulta/v1/orgaos/"))
        self.assertEqual(get.call_count, 1)

    def test_purchase_header_does_not_retry_removed_endpoints(self):
        falha = Mock()
        falha.raise_for_status.side_effect = requests.RequestException("indisponível")
        with patch("pncp_tracker.api_client.requests.get", return_value=falha) as get:
            with self.assertRaises(requests.RequestException):
                buscar_dados_compra("10635424000186", "2025", "282")

        self.assertEqual(get.call_count, 1)

    def test_item_page_sends_pagination_parameters(self):
        with patch(
            "pncp_tracker.api_client.requests.get",
            return_value=_resposta(payload=[{"numeroItem": 1}]),
        ) as get:
            itens = listar_itens("10635424000186", "2025", "282", pagina=2)

        self.assertEqual(itens, [{"numeroItem": 1}])
        self.assertIn("/api/pncp/v1/", get.call_args.args[0])
        self.assertEqual(get.call_args.kwargs["params"], {"pagina": 2, "tamanhoPagina": 50})

    def test_item_page_without_content_returns_empty_list(self):
        with patch(
            "pncp_tracker.api_client.requests.get",
            return_value=_resposta(status_code=204),
        ):
            self.assertEqual(listar_itens("10635424000186", "2025", "282"), [])

    def test_item_results_raise_for_http_errors(self):
        response = _resposta(status_code=500)
        response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        with patch(
            "pncp_tracker.api_client.requests.get",
            return_value=response,
        ):
            with self.assertRaises(requests.HTTPError):
                buscar_resultados_item("10635424000186", "2025", "282", 1)

    def test_no_content_item_results_are_valid_empty_results(self):
        response = _resposta(status_code=204)
        with patch(
            "pncp_tracker.api_client.requests.get",
            return_value=response,
        ):
            self.assertEqual(
                buscar_resultados_item("10635424000186", "2025", "282", 1),
                [],
            )
        response.raise_for_status.assert_not_called()

    def test_item_results_reject_invalid_payload_shape(self):
        with patch(
            "pncp_tracker.api_client.requests.get",
            return_value=_resposta(payload={"error": "bad response"}),
        ):
            with self.assertRaisesRegex(ValueError, "deve ser uma lista"):
                buscar_resultados_item("10635424000186", "2025", "282", 1)

    def test_item_results_are_returned_when_the_api_responds_200(self):
        with patch(
            "pncp_tracker.api_client.requests.get",
            return_value=_resposta(payload=[{"niFornecedor": "12345678000199"}]),
        ) as get:
            self.assertEqual(
                buscar_resultados_item("10635424000186", "2025", "282", 1),
                [{"niFornecedor": "12345678000199"}],
            )
            self.assertIn("/api/pncp/v1/", get.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
