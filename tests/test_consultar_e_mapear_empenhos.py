import unittest
from datetime import datetime as RealDateTime, timezone as RealTimezone
from unittest.mock import patch

import requests

from pncp_tracker.consultar_e_mapear_empenhos import consultar_e_mapear_empenhos
from pncp_tracker.contratos_empenhos import consultar_contratos_empenhos
from pncp_tracker.empenho_details import enriquecer_empenhos_com_detalhes_portal
from pncp_tracker.empenho_matcher import mapear_empenhos_por_item
from pncp_tracker.portal_transparencia import consultar_documentos_despesa_favorecido
from pncp_tracker.report_html import _preparar_relatorio


class ConsultarEMapearEmpenhosTests(unittest.TestCase):
    def test_report_generation_time_uses_brazil_utc_minus_three(self):
        utc_instant = RealDateTime(2026, 11, 12, 10, 22, tzinfo=RealTimezone.utc)
        with patch("pncp_tracker.report_html.datetime") as report_datetime:
            report_datetime.now.side_effect = lambda tz: utc_instant.astimezone(tz)
            report = _preparar_relatorio({})

        self.assertEqual(report["gerado_em"], "12/11/2026 07:22")

    @patch("pncp_tracker.portal_transparencia._api_key", return_value="test-key")
    @patch("pncp_tracker.portal_transparencia.requests.get")
    def test_supplier_document_lookup_uses_year_and_management_unit(self, get, api_key):
        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return [{"documentoResumido": "2026NE000129"}]

        get.return_value = FakeResponse()

        result = consultar_documentos_despesa_favorecido(
            "36091140000160",
            2026,
            "158460",
        )

        self.assertEqual(result, [{"documentoResumido": "2026NE000129"}])
        self.assertEqual(get.call_args.kwargs["params"], {
            "codigoPessoa": "36091140000160",
            "fase": 1,
            "ano": 2026,
            "ug": "158460",
            "pagina": 1,
        })

    def test_empenhos_without_item_number_are_only_supplier_candidates(self):
        result = mapear_empenhos_por_item(
            {
                "itens": [
                    {
                        "numeroItem": 1,
                        "descricao": "Material",
                        "resultadosHomologados": [{"niFornecedor": "12.345.678/0001-99"}],
                    }
                ]
            },
            [
                {
                    "numeroContratoEmpenho": "2026NE000001",
                    "niFornecedor": "12345678000199",
                    "detalhesPortalTransparencia": {
                        "detalhamento": {"codigoFavorecido": "12345678000199"}
                    },
                }
            ],
        )

        self.assertEqual(result[0]["status"], "empenhos_do_fornecedor_sem_item_identificado")
        self.assertEqual(result[0]["empenhos_fornecedor_sem_item_identificado"][0]["numero_empenho"], "2026NE000001")

    def test_empenho_item_number_is_mapped_to_pncp_item(self):
        result = mapear_empenhos_por_item(
            {
                "itens": [
                    {
                        "numeroItem": 24,
                        "descricao": "Areia",
                        "resultadosHomologados": [{"niFornecedor": "12345678000199"}],
                    },
                    {"numeroItem": 25, "descricao": "Outro item"},
                ]
            },
            [
                {
                    "numeroContratoEmpenho": "2026NE000043",
                    "niFornecedor": "12345678000199",
                    "detalhesPortalTransparencia": {
                        "detalhamento": {
                            "codigoFavorecido": "12345678000199",
                            "nomeFavorecido": "Fornecedor",
                            "data": "03/02/2026",
                            "codigoUg": "158379",
                            "ug": "IF CATARINENSE - CAMPUS CAMBORIU",
                            "itensEmpenho": [
                                {
                                    "descricao": "Item compra: 00024 - AREIA, TIPO NORMAL BRASILEIRA",
                                    "valorAtual": "2.024,50",
                                }
                            ],
                        }
                    },
                }
            ],
        )

        self.assertEqual(result[0]["status"], "mapeado_por_numero_item")
        self.assertEqual(result[0]["empenhos"][0]["numero_empenho"], "2026NE000043")
        self.assertEqual(result[0]["empenhos"][0]["unidade_gestora_codigo"], "158379")
        self.assertEqual(
            result[0]["empenhos"][0]["unidade_gestora_nome"],
            "IF CATARINENSE - CAMPUS CAMBORIU",
        )
        self.assertEqual(result[1]["status"], "sem_empenho_mapeado")

    def test_failed_result_lookup_is_not_counted_as_a_desert(self):
        mapped = mapear_empenhos_por_item(
            {
                "itens": [
                    {
                        "numeroItem": 3,
                        "descricao": "Material",
                        "erroResultadosHomologados": "HTTPError: serviço indisponível",
                        "resultadosHomologados": [],
                    }
                ]
            },
            [],
        )
        self.assertEqual(
            mapped[0]["status"],
            "resultados_homologados_indisponiveis",
        )
        self.assertIsNone(mapped[0]["valor_total_homologado"])
        self.assertIsNone(mapped[0]["quantidade_homologada"])

        report = _preparar_relatorio(
            {
                "itens_mapeados": mapped,
                "erros_resultados_itens": [
                    {"numero_item": 3, "erro": "HTTPError: serviço indisponível"}
                ],
            }
        )
        self.assertIsNone(report["itens"][0]["valor_total_homologado"])
        self.assertEqual(report["erros_resultados_itens"][0]["numero_item"], 3)

    @patch("pncp_tracker.contratos_empenhos.requests.get")
    def test_contracts_and_empenhos_pagination(self, get):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self.payload

        get.side_effect = [
            FakeResponse({"data": [{"numeroContratoEmpenho": "NE1"}], "totalPaginas": 2}),
            FakeResponse({"data": [{"numeroContratoEmpenho": "NE2"}], "totalPaginas": 2}),
        ]

        result = consultar_contratos_empenhos("10635424000186", "2025", "000272", tamanho_pagina=1)

        self.assertEqual([row["numeroContratoEmpenho"] for row in result], ["NE1", "NE2"])
        self.assertEqual(get.call_count, 2)

    @patch("pncp_tracker.contratos_empenhos.requests.get")
    def test_contracts_404_with_no_published_contracts_payload_returns_empty(self, get):
        class FakeResponse:
            status_code = 404

            def raise_for_status(self):
                raise requests.HTTPError("404 Client Error")

            def json(self):
                return {
                    "timestamp": "2026-11-10T21:50:37.748-03:00",
                    "status": "404",
                    "error": "404 NOT_FOUND",
                    "message": "Não há contrato publicado no PNCP para esta contratação.",
                    "path": "/pncp-api/v1/orgaos/10635424000186/contratos/contratacao/2026/187",
                }

        get.return_value = FakeResponse()

        self.assertEqual(
            consultar_contratos_empenhos("10635424000186", "2026", "187"),
            [],
        )
        get.assert_called_once()

    @patch("pncp_tracker.contratos_empenhos.requests.get")
    def test_any_contracts_404_is_treated_as_no_published_contracts(self, get):
        class FakeResponse:
            status_code = 404

            def raise_for_status(self):
                raise requests.HTTPError("404 Client Error")

            def json(self):
                return {"status": "404", "message": "Unexpected endpoint failure"}

        get.return_value = FakeResponse()

        self.assertEqual(
            consultar_contratos_empenhos("10635424000186", "2026", "187"),
            [],
        )

    @patch("pncp_tracker.contratos_empenhos.requests.get")
    def test_contracts_server_error_is_still_raised(self, get):
        response = unittest.mock.Mock(status_code=500)
        response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        get.return_value = response

        with self.assertRaises(requests.HTTPError):
            consultar_contratos_empenhos("10635424000186", "2026", "187")

    @patch("pncp_tracker.empenho_details.consultar_detalhes_documento_despesa")
    @patch("pncp_tracker.empenho_details.consultar_documentos_despesa_favorecido")
    def test_portal_detail_is_resolved_and_attached(self, list_documents, get_detail):
        list_documents.return_value = [
            {
                "documentoResumido": "2026NE000043",
                "documento": "158379264222026NE000043",
            }
        ]
        get_detail.return_value = {
            "documentoResumido": "2026NE000043",
            "itensEmpenho": [{"descricao": "Areia"}],
        }

        result, errors = enriquecer_empenhos_com_detalhes_portal(
            [
                {
                    "numeroContratoEmpenho": "2026NE000043",
                    "dataAssinatura": "2026-02-03",
                    "unidadeOrgao": {"codigoUnidade": "158379"},
                    "niFornecedor": "12345678000199",
                }
            ]
        )

        self.assertEqual(errors, [])
        self.assertEqual(result[0]["detalhesPortalTransparencia"]["status"], "ok")
        self.assertEqual(
            result[0]["detalhesPortalTransparencia"]["detalhamento"]["itensEmpenho"][0]["descricao"],
            "Areia",
        )

    @patch(
        "pncp_tracker.empenho_details.consultar_detalhes_documento_despesa",
        return_value={"documentoResumido": "2026NE000129"},
    )
    @patch("pncp_tracker.empenho_details.consultar_documentos_despesa_favorecido")
    def test_portal_lookup_uses_supplier_and_year_not_signature_date(
        self,
        supplier_documents,
        get_detail,
    ):
        supplier_documents.return_value = [
            {
                "documentoResumido": "2026NE000129",
                "documento": "158460264222026NE000129",
                "data": "14/05/2026",
            }
        ]

        result, errors = enriquecer_empenhos_com_detalhes_portal(
            [
                {
                    "numeroContratoEmpenho": "2026NE000129",
                    "dataAssinatura": "2026-01-13",
                    "unidadeOrgao": {"codigoUnidade": "158460"},
                    "niFornecedor": "36.091.140/0001-60",
                }
            ]
        )

        self.assertEqual(errors, [])
        self.assertEqual(result[0]["detalhesPortalTransparencia"]["status"], "ok")
        supplier_documents.assert_called_once_with(
            "36091140000160",
            "2026",
            "158460",
            fase=1,
        )
        get_detail.assert_called_once_with("158460264222026NE000129")

    def test_report_sums_committed_value_and_estimates_quantity(self):
        report = _preparar_relatorio(
            {
                "status": "ok",
                "quantidade_empenhos": 1,
                "quantidade_empenhos_com_detalhes": 1,
                "chaves_integracao": {},
                "itens_mapeados": [
                    {
                        "numero_item": 24,
                        "descricao": "Areia",
                        "unidade_medida": "Metro Cúbico",
                        "quantidade_licitada": 15,
                        "quantidade_homologada": 15,
                        "valor_unitario_homologado": 404.9,
                        "valor_total_estimado": 7476,
                        "valor_total_homologado": 6073.5,
                        "resultados": [
                            {
                                "niFornecedor": "12345678000199",
                                "nomeRazaoSocialFornecedor": "Fornecedor",
                                "quantidadeHomologada": 15,
                                "valorUnitarioHomologado": 404.9,
                                "valorTotalHomologado": 6073.5,
                                "dataResultado": "2026-02-03",
                                "urlAta": "https://pncp.gov.br/app/atas/12345678000199/2026/1",
                            }
                        ],
                        "empenhos": [
                            {
                                "numero_empenho": "2026NE000043",
                                "data_emissao": "03/02/2026",
                                "unidade_gestora_codigo": "158379",
                                "unidade_gestora_nome": "IF CATARINENSE - CAMPUS CAMBORIU",
                                "fornecedor_cnpj": "12345678000199",
                                "valor_empenhado": "2.024,50",
                                "item_despesa": {
                                    "valorAtual": "2.024,50",
                                    "descricao": "Item compra: 00024 - Areia",
                                },
                            }
                        ],
                    }
                ],
                "empenhos": [],
            }
        )

        self.assertEqual(report["valor_empenhado_mapeado"], 2024.5)
        self.assertEqual(report["itens"][0]["quantidade_empenhada_estimada"], 5)
        self.assertEqual(
            report["itens"][0]["resultados"][0]["data_homologacao"],
            "03/02/2026",
        )
        self.assertEqual(
            report["itens"][0]["resultados"][0]["url_ata"],
            "https://pncp.gov.br/app/atas/12345678000199/2026/1",
        )
        self.assertEqual(
            report["itens"][0]["empenhos"][0]["unidade_gestora_codigo"],
            "158379",
        )
        self.assertEqual(
            report["itens"][0]["empenhos"][0]["unidade_gestora_nome"],
            "IF CATARINENSE - CAMPUS CAMBORIU",
        )

    def test_report_uses_zero_empenhada_quantity_when_no_empenhos_are_mapped(self):
        report = _preparar_relatorio(
            {
                "status": "ok",
                "quantidade_empenhos": 0,
                "chaves_integracao": {},
                "itens_mapeados": [
                    {
                        "numero_item": 1,
                        "quantidade_homologada": 15,
                        "valor_total_homologado": 150,
                        "resultados": [],
                        "empenhos": [],
                    },
                    {
                        "numero_item": 2,
                        "quantidade_homologada": 8,
                        "valor_total_homologado": 80,
                        "resultados": [],
                        "empenhos": [
                            {
                                "numero_empenho": "2026NE000001",
                                "item_despesa": {"valorAtual": "20,00"},
                            }
                        ],
                    },
                ],
                "empenhos": [],
            }
        )

        self.assertEqual(
            report["itens"][0]["quantidade_empenhada_estimada"],
            0,
        )
        self.assertIsNone(report["itens"][1]["quantidade_empenhada_estimada"])

    @patch("pncp_tracker.consultar_e_mapear_empenhos.mapear_empenhos_por_item", return_value=[])
    @patch("pncp_tracker.consultar_e_mapear_empenhos.enriquecer_empenhos_com_detalhes_portal", return_value=([], []))
    @patch("pncp_tracker.consultar_e_mapear_empenhos.consultar_contratos_empenhos", return_value=[])
    @patch("pncp_tracker.consultar_e_mapear_empenhos.baixar_dados_compra_pncp")
    def test_consultar_e_mapear_empenhos_reuses_stage_one_data(self, download, get_contracts, enrich, map_items):
        purchase = {
            "chaves_integracao": {
                "cnpj_orgao": "10635424000186",
                "ano_compra": 2025,
                "numero_compra": "90027",
                "numero_controle_pncp": "10635424000186-1-000272/2025",
            },
            "itens": [],
            "objeto": "Compra de teste",
        }

        result = consultar_e_mapear_empenhos(
            "https://pncp.gov.br/app/editais/10635424000186/2025/000272",
            dados_compra=purchase,
        )

        download.assert_not_called()
        get_contracts.assert_called_once_with("10635424000186", "2025", "000272")
        self.assertEqual(result["objeto"], "Compra de teste")

    @patch("pncp_tracker.consultar_e_mapear_empenhos.mapear_empenhos_por_item", return_value=[])
    @patch("pncp_tracker.consultar_e_mapear_empenhos.enriquecer_empenhos_com_detalhes_portal", return_value=([], []))
    @patch("pncp_tracker.consultar_e_mapear_empenhos.consultar_contratos_empenhos", return_value=[])
    def test_failed_stage_one_results_make_mapping_status_partial(
        self,
        _get_contracts,
        _enrich,
        _map_items,
    ):
        errors = [{"numero_item": 3, "erro": "HTTPError: serviço indisponível"}]
        result = consultar_e_mapear_empenhos(
            "https://pncp.gov.br/app/editais/10635424000186/2025/000272",
            dados_compra={
                "chaves_integracao": {
                    "cnpj_orgao": "10635424000186",
                    "ano_compra": 2025,
                    "numero_compra": "90027",
                    "numero_controle_pncp": "10635424000186-1-000272/2025",
                },
                "itens": [],
                "erros_resultados_itens": errors,
            },
        )

        self.assertEqual(result["status"], "parcial")
        self.assertEqual(result["erros_resultados_itens"], errors)


if __name__ == "__main__":
    unittest.main()
