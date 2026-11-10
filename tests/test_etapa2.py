import unittest
from unittest.mock import patch

from pncp_tracker.contratos_empenhos import consultar_contratos_empenhos
from pncp_tracker.empenho_details import enriquecer_empenhos_com_detalhes_portal
from pncp_tracker.empenho_matcher import mapear_empenhos_por_item
from pncp_tracker.report_html import _preparar_relatorio


class Etapa2Tests(unittest.TestCase):
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
        self.assertEqual(result[1]["status"], "sem_empenho_mapeado")

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

    @patch("pncp_tracker.empenho_details.consultar_detalhes_documento_despesa")
    @patch("pncp_tracker.empenho_details.consultar_documentos_despesa")
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
                }
            ]
        )

        self.assertEqual(errors, [])
        self.assertEqual(result[0]["detalhesPortalTransparencia"]["status"], "ok")
        self.assertEqual(
            result[0]["detalhesPortalTransparencia"]["detalhamento"]["itensEmpenho"][0]["descricao"],
            "Areia",
        )

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
                            }
                        ],
                        "empenhos": [
                            {
                                "numero_empenho": "2026NE000043",
                                "data_emissao": "03/02/2026",
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


if __name__ == "__main__":
    unittest.main()
