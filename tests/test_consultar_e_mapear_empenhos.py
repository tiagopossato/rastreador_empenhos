import os
import tempfile
import threading
import time
import unittest
from datetime import datetime as RealDateTime, timezone as RealTimezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import requests

from pncp_tracker.consultar_e_mapear_empenhos import (
    _classificar_empenhos_pncp,
    _unir_empenhos,
    consultar_e_mapear_empenhos,
)
from pncp_tracker.contratos_empenhos import consultar_contratos_empenhos
from pncp_tracker.empenho_details import (
    classificar_situacao_empenho,
    enriquecer_empenhos_com_detalhes_portal,
)
from pncp_tracker.empenho_matcher import mapear_empenhos_por_item
from pncp_tracker.empenho_portal import (
    buscar_empenhos_portal_para_compra,
    classificar_origem_organ,
    consome_saldo,
    quantidade_estimada,
)
from pncp_tracker import portal_transparencia
from pncp_tracker.portal_transparencia import (
    PortalTransparenciaBlockedError,
    consultar_documentos_despesa_favorecido,
)
from pncp_tracker.report_html import _preparar_relatorio, gerar_relatorio_html


class ClassificarOrigemOrganTests(unittest.TestCase):
    """Classificação não depende de rede: apenas das chaves já coletadas."""

    def test_adesao_posterior_nao_consome_saldo(self):
        self.assertEqual(
            classificar_origem_organ(True, None, "158379"), "adesao_posterior"
        )
        self.assertFalse(consome_saldo("adesao_posterior"))

    def test_original_consome_saldo_mesmo_com_ug_diferente(self):
        dados_cgov = {
            "ug_emitente": "158461",
            "chave_compra": {"unidade_compra": "158125", "numero": "90149", "ano": "2026"},
        }
        self.assertEqual(classificar_origem_organ(False, dados_cgov, "158461"), "original")
        self.assertTrue(consome_saldo("original"))

    def test_sem_adesao_com_mesma_ug_da_compra_e_propria_ug(self):
        dados_cgov = {
            "ug_emitente": "158125",
            "chave_compra": {"unidade_compra": "158125", "numero": "90149", "ano": "2026"},
        }
        self.assertEqual(classificar_origem_organ(None, dados_cgov, "158125"), "propria_ug")
        self.assertTrue(consome_saldo("propria_ug"))

    def test_sem_adesao_com_ug_divergente_e_indefinido(self):
        dados_cgov = {
            "ug_emitente": "158379",
            "chave_compra": {"unidade_compra": "158125", "numero": "404", "ano": "2026"},
        }
        self.assertEqual(classificar_origem_organ(None, dados_cgov, "158379"), "indefinido")
        self.assertFalse(consome_saldo("indefinido"))

    def test_sem_dados_suficientes_e_indefinido(self):
        self.assertEqual(classificar_origem_organ(None, None, ""), "indefinido")


class SituacaoEmpenhoTests(unittest.TestCase):
    """A situação compara o registro do PNCP com o documento atual do Portal."""

    def test_reinforced_value_is_detected(self):
        situacao = classificar_situacao_empenho(
            {
                "numeroContratoEmpenho": "2026NE000001",
                "valorGlobal": 100.0,
                "valorInicial": 100.0,
                "detalhesPortalTransparencia": {
                    "status": "ok",
                    "detalhamento": {"valor": "150,00"},
                },
            }
        )
        self.assertEqual(situacao["situacao"], "reforcado")
        self.assertEqual(situacao["diferenca"], 50.0)

    def test_reduced_value_is_detected_as_partial_annulment(self):
        situacao = classificar_situacao_empenho(
            {
                "numeroContratoEmpenho": "2026NE000001",
                "valorGlobal": 100.0,
                "detalhesPortalTransparencia": {
                    "status": "ok",
                    "detalhamento": {"valor": "40,00"},
                },
            }
        )
        self.assertEqual(situacao["situacao"], "anulado")
        self.assertEqual(situacao["diferenca"], -60.0)

    def test_zeroed_document_is_cancelled(self):
        situacao = classificar_situacao_empenho(
            {
                "numeroContratoEmpenho": "2026NE000001",
                "valorGlobal": 100.0,
                "detalhesPortalTransparencia": {
                    "status": "ok",
                    "detalhamento": {"valor": "0,00"},
                },
            }
        )
        self.assertEqual(situacao["situacao"], "cancelado")

    def test_retification_without_value_change_is_alteracao(self):
        situacao = classificar_situacao_empenho(
            {
                "numeroContratoEmpenho": "2026NE000001",
                "valorGlobal": 100.0,
                "valorInicial": 100.0,
                "numeroRetificacao": 2,
                "detalhesPortalTransparencia": {
                    "status": "ok",
                    "detalhamento": {"valor": "100,00"},
                },
            }
        )
        self.assertEqual(situacao["situacao"], "alterado")
        self.assertEqual(situacao["retificacoes"], 2)

    def test_document_missing_in_portal_is_reported(self):
        situacao = classificar_situacao_empenho(
            {
                "numeroContratoEmpenho": "2026NE000001",
                "valorGlobal": 100.0,
                "detalhesPortalTransparencia": {"status": "nao_encontrado"},
            }
        )
        self.assertEqual(situacao["situacao"], "nao_localizado")

    def test_unavailable_details_are_indeterminate(self):
        situacao = classificar_situacao_empenho(
            {
                "numeroContratoEmpenho": "2026NE000001",
                "valorGlobal": 100.0,
                "detalhesPortalTransparencia": {"status": "erro"},
            }
        )
        self.assertEqual(situacao["situacao"], "indeterminado")

    def test_non_empenho_record_is_not_applicable(self):
        situacao = classificar_situacao_empenho(
            {
                "numeroContratoEmpenho": "00095",
                "detalhesPortalTransparencia": {
                    "status": "nao_consultado",
                    "motivo": "Registro sem identificador de empenho ou unidade gestora.",
                },
            }
        )
        self.assertEqual(situacao["situacao"], "nao_aplicavel")

    def test_matching_values_are_normal(self):
        situacao = classificar_situacao_empenho(
            {
                "numeroContratoEmpenho": "2026NE000001",
                "valorGlobal": 65.0,
                "valorInicial": 65.0,
                "detalhesPortalTransparencia": {
                    "status": "ok",
                    "detalhamento": {"valor": "65,00"},
                },
            }
        )
        self.assertEqual(situacao["situacao"], "normal")


class CarregamentoEnvTests(unittest.TestCase):
    def test_chave_do_env_fica_visivel_para_todas_as_threads(self):
        """Sem o lock, as threads paralelas podiam ver o .env como já carregado e vazio."""

        def ler_com_atraso():
            time.sleep(0.05)
            return {"PORTAL_DADOS_API_KEY": "chave-teste"}

        with patch.object(
            portal_transparencia, "_ler_variaveis_env", side_effect=ler_com_atraso
        ), patch.object(
            portal_transparencia, "_env_carregado", False
        ), patch.dict(os.environ, {}, clear=True):
            resultados = []
            barreira = threading.Barrier(4)

            def consultar():
                barreira.wait()
                resultados.append(portal_transparencia._api_key())

            threads = [threading.Thread(target=consultar) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(resultados, ["chave-teste"] * 4)


class QuantidadeEstimadaTests(unittest.TestCase):
    """A quantidade estimada é o quociente real, sem arredondamento para inteiro."""

    def test_fractional_ratio_is_kept_with_three_decimals(self):
        self.assertEqual(quantidade_estimada("3.840,00", 700.0), Decimal("5.486"))

    def test_exact_multiple_has_zero_fraction(self):
        self.assertEqual(quantidade_estimada("10.161,88", 5080.94), Decimal("2.000"))

    def test_float_noise_is_absorbed_by_decimal_math(self):
        self.assertEqual(quantidade_estimada("0,9999999", 1.0), Decimal("1.000"))

    def test_value_below_one_unit_keeps_the_fraction(self):
        self.assertEqual(quantidade_estimada("300,00", 700.0), Decimal("0.429"))

    def test_missing_unit_price_is_not_estimable(self):
        self.assertIsNone(quantidade_estimada("300,00", None))


class ConsultarEMapearEmpenhosTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("pncp_tracker.empenho_portal.coletar_dados_empenho", return_value=None)
        self.cgov = patcher.start()
        self.addCleanup(patcher.stop)

    def test_report_generation_time_uses_brazil_utc_minus_three(self):
        utc_instant = RealDateTime(2026, 11, 12, 10, 22, tzinfo=RealTimezone.utc)
        with patch("pncp_tracker.report_html.datetime") as report_datetime:
            report_datetime.now.side_effect = lambda tz: utc_instant.astimezone(tz)
            report = _preparar_relatorio({})

        self.assertEqual(report["gerado_em"], "12/11/2026 07:22")

    def test_supplier_documents_without_purchase_link_are_not_in_html(self):
        data = {
            "empenhos_nao_confirmados": [{"numero": "2026NE000567"}],
            "quantidade_empenhos_pncp": 2,
            "quantidade_empenhos_portal": 3,
        }
        prepared = _preparar_relatorio(data)
        self.assertEqual(prepared["quantidade_documentos_descartados"], 1)

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            gerar_relatorio_html(data, output)
            html = output.read_text(encoding="utf-8")

        self.assertNotIn("Documentos do fornecedor sem vínculo com a compra", html)
        self.assertNotIn("['Documentos descartados'", html)
        self.assertNotIn("['Origem dos registros'", html)
        self.assertIn('id="discarded-count"', html)
        self.assertIn('id="record-origins"', html)
        self.assertIn("Origem dos registros:", html)
        self.assertNotIn("2026NE000567", html)

    def test_pncp_records_remain_visible_when_portal_details_are_missing(self):
        data = {
            "quantidade_empenhos": 4,
            "quantidade_empenhos_pncp": 4,
            "empenhos": [
                {
                    "numeroContratoEmpenho": "2026NE000042",
                    "origem": "pncp",
                    "nomeRazaoSocialFornecedor": "Fornecedor PNCP",
                    "niFornecedor": "12345678000199",
                    "unidadeOrgao": {
                        "codigoUnidade": "158460",
                        "nomeUnidade": "Unidade PNCP",
                    },
                    "valorGlobal": 65,
                    "objetoContrato": "Objeto publicado no PNCP",
                    "detalhesPortalTransparencia": {
                        "status": "nao_encontrado",
                        "mensagem": "Detalhamento não localizado.",
                    },
                },
                {
                    "numeroContratoEmpenho": "2026NE000043",
                    "origem": "pncp",
                    "nomeRazaoSocialFornecedor": "Outro fornecedor",
                    "valorGlobal": 10,
                    "detalhesPortalTransparencia": {
                        "status": "ok",
                        "detalhamento": {
                            "itensEmpenho": [
                                {
                                    "descricao": "Item compra: 00001 - Areia",
                                    "valorAtual": "10,00",
                                }
                            ]
                        },
                    },
                },
                {
                    "numeroContratoEmpenho": "2026NE000044",
                    "origem": "pncp",
                    "detalhesPortalTransparencia": {
                        "detalhamento": {"itensEmpenho": None}
                    },
                },
                {
                    "numeroContratoEmpenho": "2026NE000045",
                    "origem": "pncp",
                    "detalhesPortalTransparencia": None,
                },
                {
                    "numeroContratoEmpenho": "2026NE000999",
                    "origem": "portal_favorecido",
                },
            ],
        }

        prepared = _preparar_relatorio(data)
        self.assertEqual(len(prepared["registros_pncp"]), 4)
        self.assertEqual(prepared["registros_pncp"][0]["portal_status"], "nao_encontrado")
        self.assertEqual(
            prepared["registros_pncp"][1]["itens_portal"][0]["descricao"],
            "Item compra: 00001 - Areia",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            gerar_relatorio_html(data, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn("Registros recebidos da aba Contratos/Empenhos do PNCP", html)
        self.assertIn("2026NE000042", html)
        self.assertIn("2026NE000043", html)
        self.assertIn("2026NE000044", html)
        self.assertIn("2026NE000045", html)
        self.assertNotIn("2026NE000999", html)

    def test_pncp_records_section_is_collapsed_and_links_each_record(self):
        data = {
            "chaves_integracao": {"cnpj_orgao": "10635424000186"},
            "quantidade_empenhos_pncp": 2,
            "empenhos": [
                {
                    "numeroContratoEmpenho": "2026NE000042",
                    "origem": "pncp",
                    "anoContrato": 2026,
                    "sequencialContrato": 61,
                    "orgaoEntidade": {"cnpj": "10635424000186"},
                    "detalhesPortalTransparencia": {
                        "status": "ok",
                        "codigoDocumento": "158379264222026NE000042",
                        "detalhamento": {"valor": "65,00"},
                    },
                },
                {
                    "numeroContratoEmpenho": "00095",
                    "origem": "pncp",
                    "anoContrato": 2026,
                    "sequencialContrato": 95,
                    "detalhesPortalTransparencia": {"status": "nao_consultado"},
                },
            ],
        }

        prepared = _preparar_relatorio(data)
        primeiro, segundo = prepared["registros_pncp"]
        self.assertEqual(
            primeiro["pncp_url"],
            "https://pncp.gov.br/app/contratos/10635424000186/2026/61",
        )
        self.assertEqual(
            primeiro["portal_url"],
            "https://portaldatransparencia.gov.br/despesas/empenho/158379264222026NE000042",
        )
        self.assertEqual(
            segundo["pncp_url"],
            "https://pncp.gov.br/app/contratos/10635424000186/2026/95",
        )
        self.assertIsNone(segundo["portal_url"])

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.html"
            gerar_relatorio_html(data, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn('<details class="panel" id="pncp-records-panel" hidden>', html)
        self.assertNotIn('<section class="panel" id="pncp-records-panel"', html)
        self.assertNotIn("id=\"pncp-records-panel\" open", html)
        self.assertIn("<th>Links</th>", html)

    @patch("pncp_tracker.portal_transparencia._api_key", return_value="test-key")
    @patch("pncp_tracker.portal_transparencia._http_get")
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

    @patch("pncp_tracker.portal_transparencia._api_key", return_value="test-key")
    @patch("pncp_tracker.portal_transparencia._http_get")
    def test_supplier_lookup_without_management_unit_omits_ug(self, get, _api_key):
        response = unittest.mock.Mock(status_code=200)
        response.json.return_value = []
        response.raise_for_status.return_value = None
        get.return_value = response

        consultar_documentos_despesa_favorecido("12345678000199", 2026, None)

        self.assertNotIn("ug", get.call_args.kwargs["params"])

    @patch("pncp_tracker.portal_transparencia._http_get")
    def test_request_limiter_waits_before_sending_next_request(self, get):
        response = unittest.mock.Mock(status_code=200, text="")
        get.return_value = response
        with (
            patch.object(portal_transparencia, "_portal_blocked", False),
            patch.object(portal_transparencia, "_last_request_at", 9.8),
            patch.object(portal_transparencia, "_intervalo_minimo", return_value=0.5),
            patch("pncp_tracker.portal_transparencia.time.monotonic", side_effect=[10, 10.5]),
            patch("pncp_tracker.portal_transparencia.time.sleep") as sleep,
        ):
            portal_transparencia._get("https://example.test/endpoint")

        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], 0.3)

    @patch("pncp_tracker.portal_transparencia._api_key", return_value="test-key")
    @patch("pncp_tracker.portal_transparencia._http_get")
    def test_blocked_token_stops_all_following_portal_requests(self, get, _api_key):
        response = unittest.mock.Mock(
            status_code=200,
            text="Usuário bloqueado, pois o limite de acesso à API de Dados foi atingido!",
        )
        get.return_value = response
        with patch.object(portal_transparencia, "_portal_blocked", False):
            with self.assertRaises(PortalTransparenciaBlockedError):
                consultar_documentos_despesa_favorecido("12345678000199", 2026, None)
            with self.assertRaises(PortalTransparenciaBlockedError):
                consultar_documentos_despesa_favorecido("12345678000199", 2027, None)

        get.assert_called_once()

    @patch("pncp_tracker.empenho_portal.consultar_detalhes_documento_despesa")
    @patch("pncp_tracker.empenho_portal.consultar_documentos_despesa_favorecido")
    @patch("pncp_tracker.empenho_portal.consultar_licitacoes_por_processo", return_value=[])
    @patch("pncp_tracker.empenho_portal.consultar_contratos_por_processo", return_value=[])
    def test_portal_fallback_filters_process_and_builds_matchable_empenho(
        self, _contratos, _licitacoes, search, detail
    ):
        search.side_effect = [
            [{"documentoResumido": "2026NE000236", "documento": "doc-1",
              "numeroProcesso": "23352.001311/2026-49"}],
            [],
            [{"documentoResumido": "2028NE000001", "documento": "doc-3",
              "numeroProcesso": "23352.001311/2026-49"}],
        ]
        detail.return_value = {
            "numeroProcesso": "23352.001311/2026-49",
            "codigoFavorecido": "46675900000259",
            "itensEmpenho": [{"descricao": "Item compra: 00049", "valorAtual": "10.161,88"}],
        }
        purchase = {
            "chaves_integracao": {"processo": "23352.001311/2026-49", "ano_compra": 2026},
            "itens": [{"numeroItem": 49, "resultadosHomologados": [
                {"niFornecedor": "46.675.900/0002-59"}
            ]}],
        }

        registros, erros = buscar_empenhos_portal_para_compra(purchase)

        self.assertEqual(erros, [])
        self.assertEqual(
            [r["numeroContratoEmpenho"] for r in registros],
            ["2026NE000236", "2028NE000001"],
        )
        self.assertEqual(registros[0]["detalhesPortalTransparencia"]["status"], "ok")
        mapped = mapear_empenhos_por_item(purchase, registros)
        self.assertEqual(mapped[0]["empenhos"][0]["numero_empenho"], "2026NE000236")
        self.assertEqual(
            [call.args[1] for call in search.call_args_list],
            ["2026", "2027", "2028"],
        )
        self.assertTrue(all(call.args[2] is None for call in search.call_args_list))

    @staticmethod
    def _compra_para_portal() -> dict:
        return {
            "chaves_integracao": {
                "processo": "23352.001311/2026-49",
                "ano_compra": 2026,
                "modalidade_id": 6,
                "uasg_codigo": "158125",
                "numero_compra": "404",
            },
            "itens": [
                {
                    "numeroItem": 49,
                    "quantidade": 2,
                    "resultadosHomologados": [
                        {"niFornecedor": "46.675.900/0002-59", "valorUnitarioHomologado": 5080.94}
                    ],
                }
            ],
        }

    def test_purchase_identity_confirms_empenho_from_another_ug(self):
        """Adesão/compra compartilhada: processo e UG divergentes, vínculo confirmado pela compra."""
        self.cgov.return_value = {
            "id": 1068541,
            "ug_emitente": "158379",
            "chave_compra": {
                "unidade_compra": "158125",
                "modalidade": "05",
                "numero": "404",
                "ano": "2026",
            },
            "itens": [
                {
                    "numero_item_compra": "00049",
                    "quantidade": 2.0,
                    "valor_unitario": 5080.94,
                    "valor_total": 10161.88,
                }
            ],
        }
        with (
            patch("pncp_tracker.empenho_portal.consultar_contratos_por_processo", return_value=[]),
            patch("pncp_tracker.empenho_portal.consultar_licitacoes_por_processo", return_value=[]),
            patch(
                "pncp_tracker.empenho_portal.consultar_documentos_despesa_favorecido",
                return_value=[
                    {
                        "documentoResumido": "2026NE000236",
                        "documento": "158379264222026NE000236",
                        "codigoUg": "158379",
                        "numeroProcesso": "23352.001311/2026-49",
                    }
                ],
            ),
            patch(
                "pncp_tracker.empenho_portal.consultar_detalhes_documento_despesa",
                return_value={
                    "numeroProcesso": "99999.000000/2026-00",
                    "codigoFavorecido": "46675900000259",
                    "codigoUg": "158379",
                    "itensEmpenho": [{"descricao": "Item compra: 00049", "valorAtual": "10.161,88"}],
                },
            ),
        ):
            registros, erros = buscar_empenhos_portal_para_compra(self._compra_para_portal())

        self.assertEqual(erros, [])
        self.assertEqual(len(registros), 1)
        registro = registros[0]
        self.assertEqual(registro["vinculo"], "compra_identidade")
        self.assertEqual(registro["confianca"], "alta")
        self.assertEqual(registro["origem_organ"], "indefinido")
        self.assertFalse(registro["consome_saldo"])
        self.assertEqual(
            registro["dadosContratosGov"]["itens"][0]["quantidade"],
            2.0,
        )
        self.cgov.assert_called_once_with("158379", "2026NE000236")

    def test_contratos_gov_is_skipped_when_the_process_already_confirms_the_link(self):
        """Sob demanda: processo igual e itens presentes dispensam a consulta externa."""
        with (
            patch("pncp_tracker.empenho_portal.consultar_contratos_por_processo", return_value=[]),
            patch("pncp_tracker.empenho_portal.consultar_licitacoes_por_processo", return_value=[]),
            patch(
                "pncp_tracker.empenho_portal.consultar_documentos_despesa_favorecido",
                return_value=[
                    {
                        "documentoResumido": "2026NE000236",
                        "documento": "158379264222026NE000236",
                        "codigoUg": "158379",
                    }
                ],
            ),
            patch(
                "pncp_tracker.empenho_portal.consultar_detalhes_documento_despesa",
                return_value={
                    "numeroProcesso": "23352.001311/2026-49",
                    "codigoFavorecido": "46675900000259",
                    "codigoUg": "158379",
                    "itensEmpenho": [{"descricao": "Item compra: 00049", "valorAtual": "10.161,88"}],
                },
            ),
        ):
            registros, erros = buscar_empenhos_portal_para_compra(self._compra_para_portal())

        self.assertEqual(erros, [])
        self.assertEqual(registros[0]["vinculo"], "processo")
        self.assertEqual(registros[0]["confianca"], "alta")
        self.cgov.assert_not_called()

    def test_empenho_from_another_purchase_is_discarded(self):
        self.cgov.return_value = {
            "ug_emitente": "158379",
            "chave_compra": {
                "unidade_compra": "158125",
                "modalidade": "05",
                "numero": "999",
                "ano": "2025",
            },
            "itens": [],
        }
        with (
            patch("pncp_tracker.empenho_portal.consultar_contratos_por_processo", return_value=[]),
            patch("pncp_tracker.empenho_portal.consultar_licitacoes_por_processo", return_value=[]),
            patch(
                "pncp_tracker.empenho_portal.consultar_documentos_despesa_favorecido",
                return_value=[
                    {
                        "documentoResumido": "2025NE000999",
                        "documento": "158379264222025NE000999",
                        "codigoUg": "158379",
                    }
                ],
            ),
            patch(
                "pncp_tracker.empenho_portal.consultar_detalhes_documento_despesa",
                return_value={
                    "codigoFavorecido": "46675900000259",
                    "itensEmpenho": [{"descricao": "Item compra: 00049", "valorAtual": "10.161,88"}],
                },
            ),
        ):
            registros, erros = buscar_empenhos_portal_para_compra(self._compra_para_portal())

        self.assertEqual(registros, [])
        self.assertEqual(erros[0]["motivo"], "Documento descartado: pertence a outra compra.")

    def test_contratos_gov_unavailable_falls_back_to_item_and_value_evidence(self):
        self.cgov.side_effect = requests.RequestException("indisponível")
        with (
            patch("pncp_tracker.empenho_portal.consultar_contratos_por_processo", return_value=[]),
            patch("pncp_tracker.empenho_portal.consultar_licitacoes_por_processo", return_value=[]),
            patch(
                "pncp_tracker.empenho_portal.consultar_documentos_despesa_favorecido",
                return_value=[
                    {
                        "documentoResumido": "2026NE000236",
                        "documento": "158379264222026NE000236",
                        "codigoUg": "158379",
                    }
                ],
            ),
            patch(
                "pncp_tracker.empenho_portal.consultar_detalhes_documento_despesa",
                return_value={
                    "numeroProcesso": "99999.000000/2026-00",
                    "codigoFavorecido": "46675900000259",
                    "itensEmpenho": [{"descricao": "Item compra: 00049", "valorAtual": "10.161,88"}],
                },
            ),
        ):
            registros, _erros = buscar_empenhos_portal_para_compra(self._compra_para_portal())

        self.assertEqual(len(registros), 1)
        self.assertEqual(registros[0]["vinculo"], "item_e_valor")
        self.assertEqual(registros[0]["confianca"], "media")

    @staticmethod
    def _compra_418_2026() -> dict:
        """Compra 418/2026 (UASG 158125): item 8 é uma impressora 3D de R$ 9.211,00."""
        return {
            "chaves_integracao": {
                "processo": "233520003181/2026-89",
                "ano_compra": 2026,
                "modalidade_id": 6,
                "uasg_codigo": "158125",
                "numero_compra": "418",
            },
            "itens": [
                {
                    "numeroItem": 8,
                    "descricao": "Impressora 3d padrão: fff/fdm, tipo gabinete: fechado",
                    "resultadosHomologados": [
                        {
                            "niFornecedor": "04.821.081/0001-41",
                            "valorUnitarioHomologado": 9211.0,
                        }
                    ],
                }
            ],
        }

    @patch("pncp_tracker.empenho_portal.consultar_detalhes_documento_despesa")
    @patch("pncp_tracker.empenho_portal.consultar_documentos_despesa_favorecido")
    @patch("pncp_tracker.empenho_portal.consultar_licitacoes_por_processo", return_value=[])
    @patch("pncp_tracker.empenho_portal.consultar_contratos_por_processo", return_value=[])
    def test_supplier_document_from_another_purchase_is_discarded(
        self, _contratos, _licitacoes, search, detail
    ):
        """Caso real 2026NE000567: item 8 de outro órgão, sem vínculo com a compra."""
        search.return_value = [
            {
                "documentoResumido": "2026NE000567",
                "documento": "167440000012026NE000567",
                "codigoUg": "167440",
                "numeroProcesso": "64062.000245/2026-44",
                "valor": "710,00",
                # Texto livre não é evidência: nem citando a compra ele é considerado.
                "observacao": "ADESAO AO PE 418/2026, UASG 158125",
            }
        ]
        detail.return_value = {
            "numeroProcesso": "64062.000245/2026-44",
            "codigoFavorecido": "04.821.081/0001-41",
            "codigoUg": "167440",
            "valor": "710,00",
            "itensEmpenho": [
                {
                    "descricao": "Item compra: 00008 - PREGO COM CABECA, MATERIAL FERRO COMUM",
                    "valorAtual": "710,00",
                }
            ],
        }

        registros, erros = buscar_empenhos_portal_para_compra(self._compra_418_2026())

        self.assertEqual(registros, [])
        descartes = [erro for erro in erros if erro.get("tipo") == "descartado"]
        self.assertEqual(len(descartes), 1)
        self.assertEqual(descartes[0]["numero"], "2026NE000567")
        self.assertEqual(descartes[0]["unidade"], "167440")
        self.assertEqual(
            descartes[0]["motivo"],
            "Documento descartado: nenhuma evidência de vínculo com a compra.",
        )
        self.assertNotIn("observacao", descartes[0])

    @patch("pncp_tracker.empenho_portal.consultar_detalhes_documento_despesa")
    @patch("pncp_tracker.empenho_portal.consultar_documentos_despesa_favorecido")
    @patch("pncp_tracker.empenho_portal.consultar_licitacoes_por_processo", return_value=[])
    @patch("pncp_tracker.empenho_portal.consultar_contratos_por_processo", return_value=[])
    def test_item_and_supplier_need_a_compatible_description(
        self, _contratos, _licitacoes, search, detail
    ):
        search.return_value = [
            {
                "documentoResumido": "2026NE000300",
                "documento": "158379264222026NE000300",
                "codigoUg": "158379",
                "numeroProcesso": "23352.001311/2026-49",
            }
        ]
        detail.return_value = {
            "numeroProcesso": "23352.001311/2026-49",
            "codigoFavorecido": "04.821.081/0001-41",
            "codigoUg": "158379",
            "itensEmpenho": [
                {
                    "descricao": "Item compra: 00008 - IMPRESSORA 3D PADRAO FFF FDM, GABINETE FECHADO",
                    "valorAtual": "710,00",
                }
            ],
        }

        registros, _erros = buscar_empenhos_portal_para_compra(self._compra_418_2026())

        self.assertEqual(len(registros), 1)
        self.assertEqual(registros[0]["vinculo"], "item_e_fornecedor")
        self.assertEqual(registros[0]["confianca"], "alta")

    @patch("pncp_tracker.empenho_portal.consultar_detalhes_documento_despesa")
    @patch("pncp_tracker.empenho_portal.consultar_documentos_despesa_favorecido")
    @patch("pncp_tracker.empenho_portal.consultar_licitacoes_por_processo", return_value=[])
    @patch("pncp_tracker.empenho_portal.consultar_contratos_por_processo", return_value=[])
    def test_incompatible_description_and_value_are_discarded(
        self, _contratos, _licitacoes, search, detail
    ):
        """Número do item e fornecedor coincidem, mas descrição e preço não: sem vínculo."""
        search.return_value = [
            {
                "documentoResumido": "2026NE000301",
                "documento": "158379264222026NE000301",
                "codigoUg": "158379",
                "numeroProcesso": "23352.001311/2026-49",
            }
        ]
        detail.return_value = {
            "numeroProcesso": "23352.001311/2026-49",
            "codigoFavorecido": "04.821.081/0001-41",
            "codigoUg": "158379",
            "itensEmpenho": [
                {
                    "descricao": "Item compra: 00008 - PREGO COM CABECA, BITOLA 22 X 42",
                    "valorAtual": "3.840,00",
                }
            ],
        }

        registros, erros = buscar_empenhos_portal_para_compra(self._compra_418_2026())

        self.assertEqual(registros, [])
        self.assertEqual(erros[0]["tipo"], "descartado")

    @patch("pncp_tracker.empenho_portal.consultar_detalhes_documento_despesa")
    @patch("pncp_tracker.empenho_portal.consultar_documentos_despesa_favorecido")
    @patch("pncp_tracker.empenho_portal.consultar_licitacoes_por_processo", return_value=[])
    @patch("pncp_tracker.empenho_portal.consultar_contratos_por_processo", return_value=[])
    def test_candidates_with_the_purchase_process_are_detailed_first(
        self, _contratos, _licitacoes, search, detail
    ):
        search.return_value = [
            {
                "documentoResumido": "2026NE000900",
                "documento": "158379264222026NE000900",
                "codigoUg": "158379",
                "numeroProcesso": "99999.000000/2026-00",
            },
            {
                "documentoResumido": "2026NE000901",
                "documento": "158379264222026NE000901",
                "codigoUg": "158379",
                "numeroProcesso": "233520003181/2026-89",
            },
        ]
        detail.return_value = {"numeroProcesso": "233520003181/2026-89"}

        buscar_empenhos_portal_para_compra(self._compra_418_2026())

        self.assertEqual(detail.call_args_list[0].args[0], "158379264222026NE000901")

    def test_real_quantity_from_contratos_gov_is_used_by_the_matcher(self):
        registro = {
            "numeroContratoEmpenho": "2026NE000236",
            "niFornecedor": "46675900000259",
            "origem_organ": "indefinido",
            "consome_saldo": False,
            "dadosContratosGov": {
                "itens": [{"numero_item_compra": "00049", "quantidade": 2.0}]
            },
            "detalhesPortalTransparencia": {
                "status": "ok",
                "detalhamento": {
                    "codigoFavorecido": "46675900000259",
                    "itensEmpenho": [
                        {"descricao": "Item compra: 00049", "valorAtual": "10.161,88"}
                    ],
                },
            },
        }

        mapeado = mapear_empenhos_por_item(self._compra_para_portal(), [registro])

        linha = mapeado[0]["empenhos"][0]
        self.assertEqual(linha["quantidade"], 2.0)
        self.assertEqual(linha["quantidade_origem"], "contratos_gov")
        self.assertFalse(linha["consome_saldo"])

    def test_report_keeps_adesao_out_of_the_balance(self):
        empenhos = [
            {
                "numeroContratoEmpenho": "2026NE000236",
                "origem_organ": "adesao_posterior",
                "consome_saldo": False,
                "detalhesPortalTransparencia": {"status": "ok", "detalhamento": {}},
            }
        ]
        report = _preparar_relatorio(
            {
                "status": "ok",
                "quantidade_empenhos": 1,
                "chaves_integracao": {},
                "itens_mapeados": [
                    {
                        "numero_item": 49,
                        "quantidade_homologada": 2,
                        "valor_unitario_homologado": 5080.94,
                        "valor_total_homologado": 10161.88,
                        "resultados": [{"niFornecedor": "46675900000259"}],
                        "empenhos": [
                            {
                                "numero_empenho": "2026NE000236",
                                "fornecedor_cnpj": "46675900000259",
                                "quantidade": 2.0,
                                "item_despesa": {"valorAtual": "10.161,88"},
                            }
                        ],
                    }
                ],
                "empenhos": empenhos,
            }
        )

        item = report["itens"][0]
        self.assertEqual(item["valor_empenhado"], 0)
        self.assertEqual(item["valor_empenhado_adesao"], 10161.88)
        self.assertEqual(item["quantidade_empenhada_estimada"], 0)
        self.assertEqual(report["valor_empenhado_mapeado"], 0)
        self.assertEqual(report["valor_empenhado_adesao"], 10161.88)

    def test_item_with_original_and_adesao_counts_only_the_original(self):
        empenhos = [
            {
                "numeroContratoEmpenho": "2026NE000100",
                "origem_organ": "original",
                "consome_saldo": True,
                "detalhesPortalTransparencia": {"status": "ok", "detalhamento": {}},
            },
            {
                "numeroContratoEmpenho": "2026NE000236",
                "origem_organ": "adesao_posterior",
                "consome_saldo": False,
                "detalhesPortalTransparencia": {"status": "ok", "detalhamento": {}},
            },
        ]
        report = _preparar_relatorio(
            {
                "status": "ok",
                "quantidade_empenhos": 2,
                "chaves_integracao": {},
                "itens_mapeados": [
                    {
                        "numero_item": 49,
                        "quantidade_homologada": 4,
                        "valor_unitario_homologado": 1000.0,
                        "valor_total_homologado": 4000.0,
                        "resultados": [{"niFornecedor": "46675900000259"}],
                        "empenhos": [
                            {
                                "numero_empenho": "2026NE000100",
                                "fornecedor_cnpj": "46675900000259",
                                "quantidade": 1.0,
                                "item_despesa": {"valorAtual": "1.000,00"},
                            },
                            {
                                "numero_empenho": "2026NE000236",
                                "fornecedor_cnpj": "46675900000259",
                                "quantidade": 3.0,
                                "item_despesa": {"valorAtual": "3.000,00"},
                            },
                        ],
                    }
                ],
                "empenhos": empenhos,
            }
        )

        item = report["itens"][0]
        self.assertEqual(item["valor_empenhado"], 1000.0)
        self.assertEqual(item["valor_empenhado_adesao"], 3000.0)
        self.assertEqual(item["quantidade_empenhada_estimada"], 1.0)
        self.assertEqual(report["valor_empenhado_mapeado"], 1000.0)

    @patch("pncp_tracker.empenho_portal.consultar_documentos_despesa_favorecido")
    @patch("pncp_tracker.empenho_portal.consultar_licitacoes_por_processo")
    @patch("pncp_tracker.empenho_portal.consultar_empenhos_de_contrato")
    @patch("pncp_tracker.empenho_portal.consultar_contratos_por_processo")
    @patch("pncp_tracker.empenho_portal.consultar_detalhes_documento_despesa")
    def test_contract_strategy_short_circuits_the_other_searches(
        self, detail, contratos, empenhos_contrato, licitacoes, favorecido
    ):
        contratos.return_value = [{"id": 10, "numero": "C1"}]
        empenhos_contrato.return_value = [
            {"empenho": "158379264222026NE000236", "empenhoResumido": "2026NE000236"}
        ]
        detail.return_value = {
            "numeroProcesso": "23352.001311/2026-49",
            "codigoFavorecido": "46675900000259",
        }

        registros, erros = buscar_empenhos_portal_para_compra(self._compra_para_portal())

        self.assertEqual(erros, [])
        self.assertEqual([r["numeroContratoEmpenho"] for r in registros], ["2026NE000236"])
        self.assertEqual(registros[0]["origem"], "portal_contrato")
        contratos.assert_called_once_with("23352.001311/2026-49")
        empenhos_contrato.assert_called_once_with(10)
        detail.assert_called_once_with("158379264222026NE000236")
        licitacoes.assert_not_called()
        favorecido.assert_not_called()

    @patch("pncp_tracker.empenho_portal.consultar_documentos_despesa_favorecido")
    @patch("pncp_tracker.empenho_portal.consultar_empenhos_de_contrato")
    @patch("pncp_tracker.empenho_portal.consultar_contratos_por_processo")
    @patch("pncp_tracker.empenho_portal.consultar_licitacoes_por_processo")
    @patch("pncp_tracker.empenho_portal.consultar_empenhos_de_licitacao")
    @patch("pncp_tracker.empenho_portal.consultar_detalhes_documento_despesa")
    def test_contract_failure_falls_back_to_licitacao_strategy(
        self,
        detail,
        empenhos_licitacao,
        licitacoes,
        contratos,
        empenhos_contrato,
        favorecido,
    ):
        contratos.return_value = [{"id": 10, "numero": "C1"}]
        empenhos_contrato.side_effect = requests.HTTPError("500 Server Error")
        licitacoes.return_value = [
            {
                "id": 7,
                "unidadeGestora": {"codigo": "158125"},
                "licitacao": {"numero": "004042026"},
                "codigoModalidade": "6",
            }
        ]
        empenhos_licitacao.return_value = [
            {"empenho": "158379264222026NE000236", "empenhoResumido": "2026NE000236"}
        ]
        detail.return_value = {
            "numeroProcesso": "23352.001311/2026-49",
            "codigoFavorecido": "46675900000259",
        }

        registros, erros = buscar_empenhos_portal_para_compra(self._compra_para_portal())

        self.assertEqual(len(erros), 1)
        self.assertEqual(erros[0]["origem"], "portal_contrato")
        self.assertEqual(registros[0]["origem"], "portal_licitacao")
        empenhos_licitacao.assert_called_once_with("158125", "004042026", "6")
        favorecido.assert_not_called()

    @patch("pncp_tracker.empenho_portal.consultar_detalhes_documento_despesa")
    @patch("pncp_tracker.empenho_portal.consultar_empenhos_de_contrato")
    @patch("pncp_tracker.empenho_portal.consultar_contratos_por_processo")
    def test_same_empenho_in_two_contracts_is_detailed_once(
        self, contratos, empenhos_contrato, detail
    ):
        contratos.return_value = [{"id": 10}, {"id": 11}]
        empenhos_contrato.return_value = [
            {"empenho": "158379264222026NE000236", "empenhoResumido": "2026NE000236"}
        ]
        detail.return_value = {"numeroProcesso": "23352.001311/2026-49"}

        registros, erros = buscar_empenhos_portal_para_compra(self._compra_para_portal())

        self.assertEqual(erros, [])
        self.assertEqual([r["numeroContratoEmpenho"] for r in registros], ["2026NE000236"])
        self.assertEqual(detail.call_count, 1)

    @patch("pncp_tracker.empenho_portal.consultar_detalhes_documento_despesa")
    @patch("pncp_tracker.empenho_portal.consultar_empenhos_de_contrato")
    @patch("pncp_tracker.empenho_portal.consultar_contratos_por_processo")
    def test_empenho_of_a_contract_found_by_process_is_accepted_with_another_process(
        self, contratos, empenhos_contrato, detail
    ):
        """Estratégia A: o vínculo vem do contrato do processo; o processo do documento pode divergir."""
        contratos.return_value = [{"id": 10}]
        empenhos_contrato.return_value = [
            {"empenho": "158379264222026NE000999", "empenhoResumido": "2026NE000999"}
        ]
        detail.return_value = {"numeroProcesso": "99999.000000/2026-00"}

        registros, erros = buscar_empenhos_portal_para_compra(self._compra_para_portal())

        self.assertEqual(erros, [])
        self.assertEqual([r["numeroContratoEmpenho"] for r in registros], ["2026NE000999"])
        self.assertEqual(registros[0]["vinculo"], "contrato_do_processo")
        self.assertEqual(registros[0]["confianca"], "alta")

    @patch("pncp_tracker.empenho_portal.consultar_detalhes_documento_despesa")
    @patch("pncp_tracker.empenho_portal.consultar_empenhos_de_contrato")
    @patch("pncp_tracker.empenho_portal.consultar_contratos_por_processo")
    def test_blocked_token_stops_the_cascade_with_partial_result(
        self, contratos, empenhos_contrato, detail
    ):
        contratos.return_value = [{"id": 10}]
        empenhos_contrato.return_value = [
            {"empenho": "158379264222026NE000236", "empenhoResumido": "2026NE000236"},
            {"empenho": "158379264222026NE000237", "empenhoResumido": "2026NE000237"},
        ]
        detail.side_effect = PortalTransparenciaBlockedError("token bloqueado")

        registros, erros = buscar_empenhos_portal_para_compra(self._compra_para_portal())

        self.assertEqual(registros, [])
        self.assertEqual(len(erros), 1)
        self.assertEqual(detail.call_count, 1)

    def test_pncp_adesao_flag_is_classified_and_kept_out_of_balance(self):
        with (
            patch(
                "pncp_tracker.consultar_e_mapear_empenhos.consultar_contratos_empenhos",
                return_value=[
                    {
                        "numeroContratoEmpenho": "2026NE000001",
                        "frutoAdesao": True,
                        "unidadeOrgao": {"codigoUnidade": "158379"},
                    },
                    {
                        "numeroContratoEmpenho": "2026NE000002",
                        "frutoAdesao": False,
                        "unidadeOrgao": {"codigoUnidade": "158379"},
                    },
                ],
            ),
            patch(
                "pncp_tracker.consultar_e_mapear_empenhos.enriquecer_empenhos_com_detalhes_portal",
                side_effect=lambda empenhos: ([dict(e) for e in empenhos], []),
            ),
            patch(
                "pncp_tracker.consultar_e_mapear_empenhos.buscar_empenhos_portal_para_compra",
                return_value=([], []),
            ),
            patch("pncp_tracker.consultar_e_mapear_empenhos.mapear_empenhos_por_item", return_value=[]),
        ):
            resultado = consultar_e_mapear_empenhos(
                "https://pncp.gov.br/app/editais/10635424000186/2026/000187",
                dados_compra={
                    "chaves_integracao": {
                        "cnpj_orgao": "10635424000186",
                        "numero_compra": "404",
                        "ano_compra": 2026,
                        "numero_controle_pncp": "controle",
                    },
                    "itens": [],
                },
            )

        empenhos = {e["numeroContratoEmpenho"]: e for e in resultado["empenhos"]}
        self.assertEqual(empenhos["2026NE000001"]["origem_organ"], "adesao_posterior")
        self.assertFalse(empenhos["2026NE000001"]["consome_saldo"])
        self.assertEqual(empenhos["2026NE000002"]["origem_organ"], "original")
        self.assertTrue(empenhos["2026NE000002"]["consome_saldo"])
        self.assertEqual(resultado["quantidade_empenhos_adesao"], 1)
        self.assertEqual(resultado["quantidade_empenhos_confirmados"], 1)

    def test_pncp_record_without_adesao_flag_is_treated_as_not_adhesion(self):
        """Decisão de projeto: ausência de `frutoAdesao` no PNCP não é adesão."""
        classificados = _classificar_empenhos_pncp(
            [
                {
                    "numeroContratoEmpenho": "2026NE000003",
                    "unidadeOrgao": {"codigoUnidade": "158379"},
                }
            ]
        )

        empenho = classificados[0]
        self.assertEqual(empenho["origem_organ"], "original")
        self.assertTrue(empenho["consome_saldo"])
        self.assertTrue(empenho["flag_adesao_ausente"])
        self.assertIsNone(empenho["fruto_adesao"])

    def test_contratos_gov_is_listed_as_source_when_it_was_used(self):
        with (
            patch(
                "pncp_tracker.consultar_e_mapear_empenhos.consultar_contratos_empenhos",
                return_value=[],
            ),
            patch(
                "pncp_tracker.consultar_e_mapear_empenhos.enriquecer_empenhos_com_detalhes_portal",
                side_effect=lambda empenhos: ([dict(empenho) for empenho in empenhos], []),
            ),
            patch(
                "pncp_tracker.consultar_e_mapear_empenhos.buscar_empenhos_portal_para_compra",
                return_value=(
                    [
                        {
                            "numeroContratoEmpenho": "2026NE000236",
                            "origem": "portal_favorecido",
                            "origem_organ": "indefinido",
                            "consome_saldo": False,
                            "dadosContratosGov": {
                                "chave_compra": {"unidade_compra": "158125"},
                                "itens": [{"numero_item_compra": "00049", "quantidade": 2.0}],
                            },
                        }
                    ],
                    [],
                ),
            ),
            patch("pncp_tracker.consultar_e_mapear_empenhos.mapear_empenhos_por_item", return_value=[]),
        ):
            resultado = consultar_e_mapear_empenhos(
                "https://pncp.gov.br/app/editais/10635424000186/2026/000187",
                dados_compra={
                    "chaves_integracao": {
                        "cnpj_orgao": "10635424000186",
                        "numero_compra": "404",
                        "ano_compra": 2026,
                        "numero_controle_pncp": "controle",
                    },
                    "itens": [],
                },
                buscar_empenhos_portal=True,
            )

        self.assertIn("Contratos.gov.br - identidade da compra e itens", resultado["fontes"])

    def test_two_empenhos_with_same_number_in_different_ugs_are_not_merged(self):
        """O número do empenho só é único dentro da UG; não pode colapsar registros distintos."""
        dados_compra = {
            "chaves_integracao": {
                "processo": "23352.001311/2026-49",
                "ano_compra": 2026,
                "uasg_codigo": "158125",
                "numero_compra": "404",
            },
            "itens": [],
        }
        empenhos = [
            {
                "numeroContratoEmpenho": "2026NE000102",
                "unidadeOrgao": {"codigoUnidade": "152805"},
                "frutoAdesao": True,
                "detalhesPortalTransparencia": {
                    "status": "ok",
                    "codigoDocumento": "152805264022026NE000102",
                    "detalhamento": {},
                },
            },
            {
                "numeroContratoEmpenho": "2026NE000102",
                "unidadeOrgao": {"codigoUnidade": "152254"},
                "frutoAdesao": False,
                "detalhesPortalTransparencia": {
                    "status": "ok",
                    "codigoDocumento": "152254264222026NE000102",
                    "detalhamento": {},
                },
            },
        ]

        unidos, adicionados = _unir_empenhos(
            _classificar_empenhos_pncp(empenhos), []
        )

        self.assertEqual(len(unidos), 2)
        self.assertEqual(adicionados, 0)
        self.assertEqual(
            sorted(e["origem_organ"] for e in unidos),
            ["adesao_posterior", "original"],
        )

    def test_report_uses_document_key_so_same_number_in_other_ug_is_not_misclassified(self):
        report = _preparar_relatorio(
            {
                "status": "ok",
                "quantidade_empenhos": 2,
                "chaves_integracao": {},
                "itens_mapeados": [
                    {
                        "numero_item": 1,
                        "quantidade_homologada": 2,
                        "valor_unitario_homologado": 100.0,
                        "valor_total_homologado": 200.0,
                        "resultados": [{"niFornecedor": "46675900000259"}],
                        "empenhos": [
                            {
                                "numero_empenho": "2026NE000102",
                                "chave_empenho": "152254264222026NE000102",
                                "fornecedor_cnpj": "46675900000259",
                                "item_despesa": {"valorAtual": "100,00"},
                            }
                        ],
                    }
                ],
                "empenhos": [
                    {
                        "numeroContratoEmpenho": "2026NE000102",
                        "unidadeOrgao": {"codigoUnidade": "152805"},
                        "origem_organ": "adesao_posterior",
                        "consome_saldo": False,
                        "detalhesPortalTransparencia": {
                            "status": "ok",
                            "codigoDocumento": "152805264022026NE000102",
                            "detalhamento": {},
                        },
                    },
                    {
                        "numeroContratoEmpenho": "2026NE000102",
                        "unidadeOrgao": {"codigoUnidade": "152254"},
                        "origem_organ": "original",
                        "consome_saldo": True,
                        "detalhesPortalTransparencia": {
                            "status": "ok",
                            "codigoDocumento": "152254264222026NE000102",
                            "detalhamento": {},
                        },
                    },
                ],
            }
        )

        item = report["itens"][0]
        self.assertEqual(item["valor_empenhado"], 100.0)
        self.assertEqual(item["valor_empenhado_adesao"], 0)

    @patch("pncp_tracker.empenho_details.consultar_detalhes_documento_despesa", return_value={})
    @patch("pncp_tracker.empenho_details.consultar_documentos_despesa_favorecido")
    def test_group_query_is_scoped_by_ug_to_avoid_extra_documents(self, supplier_documents, _detail):
        supplier_documents.return_value = [
            {"documentoResumido": "2026NE000129", "documento": "doc-1", "codigoUg": "158460"}
        ]

        result, errors = enriquecer_empenhos_com_detalhes_portal(
            [
                {
                    "numeroContratoEmpenho": "2026NE000129",
                    "unidadeOrgao": {"codigoUnidade": "158460"},
                    "niFornecedor": "36091140000160",
                }
            ]
        )

        self.assertEqual(errors, [])
        self.assertEqual(result[0]["detalhesPortalTransparencia"]["status"], "ok")
        supplier_documents.assert_called_once_with("36091140000160", "2026", "158460", fase=1)

    @patch("pncp_tracker.empenho_details.consultar_detalhes_documento_despesa")
    @patch("pncp_tracker.empenho_details.consultar_documentos_despesa_favorecido")
    def test_pncp_empenho_gets_portal_items_when_ug_lookup_misses(
        self, supplier_documents, get_detail
    ):
        supplier_documents.side_effect = [
            [
                {
                    "documentoResumido": "2026NE000999",
                    "documento": "other-document",
                    "codigoUg": "158460",
                }
            ],
            [
                {
                    "documentoResumido": "2026 NE-000129",
                    "documento": "pncp-document",
                    "codigoUg": "158460",
                },
                {
                    "documentoResumido": "2026NE000999",
                    "documento": "other-document",
                    "codigoUg": "158460",
                },
            ],
        ]
        get_detail.return_value = {
            "codigoUg": "158460",
            "codigoFavorecido": "36091140000160",
            "itensEmpenho": [
                {
                    "descricao": "Item compra: 00001 - Areia",
                    "valorAtual": "10,00",
                }
            ],
        }
        empenhos, errors = enriquecer_empenhos_com_detalhes_portal(
            [
                {
                    "numeroContratoEmpenho": "2026NE000129",
                    "unidadeOrgao": {"codigoUnidade": "158460"},
                    "niFornecedor": "36091140000160",
                }
            ]
        )
        purchase = {
            "itens": [
                {
                    "numeroItem": 1,
                    "descricao": "Areia",
                    "resultadosHomologados": [
                        {
                            "niFornecedor": "36091140000160",
                            "quantidadeHomologada": 1,
                            "valorTotalHomologado": 10,
                        }
                    ],
                }
            ]
        }
        mapped = mapear_empenhos_por_item(purchase, empenhos)

        self.assertEqual(errors, [])
        self.assertEqual(
            [call.args for call in supplier_documents.call_args_list],
            [
                ("36091140000160", "2026", "158460"),
                ("36091140000160", "2026", None),
            ],
        )
        get_detail.assert_called_once_with("pncp-document")
        self.assertEqual(empenhos[0]["detalhesPortalTransparencia"]["status"], "ok")
        self.assertEqual(
            [linha["numero_empenho"] for linha in mapped[0]["empenhos"]],
            ["2026NE000129"],
        )

    @patch("pncp_tracker.empenho_details.consultar_detalhes_documento_despesa")
    @patch("pncp_tracker.empenho_details.consultar_documentos_despesa_favorecido")
    def test_blocked_token_stops_targeted_pncp_lookups(
        self, supplier_documents, get_detail
    ):
        def consultar_documentos(fornecedor, _ano, unidade, fase=1):
            if unidade is None:
                raise PortalTransparenciaBlockedError("token bloqueado")
            return []

        supplier_documents.side_effect = consultar_documentos
        empenhos, errors = enriquecer_empenhos_com_detalhes_portal(
            [
                {
                    "numeroContratoEmpenho": "2026NE000129",
                    "unidadeOrgao": {"codigoUnidade": "158460"},
                    "niFornecedor": "36091140000160",
                },
                {
                    "numeroContratoEmpenho": "2026NE000130",
                    "unidadeOrgao": {"codigoUnidade": "158461"},
                    "niFornecedor": "12345678000199",
                },
            ]
        )

        self.assertEqual(len(errors), 1)
        self.assertEqual(
            sum(call.args[2] is None for call in supplier_documents.call_args_list),
            1,
        )
        get_detail.assert_not_called()
        self.assertEqual(
            [empenho["detalhesPortalTransparencia"]["status"] for empenho in empenhos],
            ["nao_consultado", "nao_consultado"],
        )

    def test_transient_connection_error_is_retried_once(self):
        response = unittest.mock.Mock(status_code=200, text="")
        response.json.return_value = [{"documentoResumido": "2026NE000129"}]
        response.raise_for_status.return_value = None
        with (
            patch.object(portal_transparencia, "_api_key", return_value="test-key"),
            patch.object(
                portal_transparencia,
                "_http_get",
                side_effect=[requests.ConnectionError("reset"), response],
            ) as http,
            patch.object(portal_transparencia, "_portal_blocked", False),
            patch.object(portal_transparencia, "_cache_favorecido", {}),
        ):
            documentos = consultar_documentos_despesa_favorecido("36091140000160", 2026, None)

        self.assertEqual(documentos, [{"documentoResumido": "2026NE000129"}])
        self.assertEqual(http.call_count, 2)

    def test_sequential_pagination_stops_at_short_page(self):
        paginas = {1: [{"id": 1}]}
        chamadas = []

        def fake_get(_url, params, **_kw):
            chamadas.append(params["pagina"])
            response = unittest.mock.Mock(status_code=200, text="")
            response.json.return_value = paginas.get(params["pagina"], [])
            response.raise_for_status.return_value = None
            return response

        with (
            patch.object(portal_transparencia, "_api_key", return_value="test-key"),
            patch.object(portal_transparencia, "_http_get") as http_mock,
            patch.object(portal_transparencia, "_portal_blocked", False),
        ):
            http_mock.side_effect = fake_get
            resultado = portal_transparencia._consultar_paginado(
                "https://example.test/outro", {}
            )

        self.assertEqual(len(resultado), 1)
        self.assertEqual(chamadas, [1])

    @patch("pncp_tracker.portal_transparencia._api_key", return_value="test-key")
    @patch("pncp_tracker.portal_transparencia._http_get")
    def test_supplier_lookup_is_cached_within_the_run(self, get, _api_key):
        response = unittest.mock.Mock(status_code=200, text="")
        response.json.return_value = [{"documentoResumido": "2026NE000129"}]
        response.raise_for_status.return_value = None
        get.return_value = response
        with patch.object(portal_transparencia, "_cache_favorecido", {}):
            primeira = consultar_documentos_despesa_favorecido("36091140000160", 2026, None)
            segunda = consultar_documentos_despesa_favorecido("36091140000160", 2026, None)

        get.assert_called_once()
        self.assertEqual(primeira, segunda)
        primeira[0]["documentoResumido"] = "alterado"
        self.assertEqual(segunda[0]["documentoResumido"], "2026NE000129")

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
        self.assertIn("/api/pncp/v1/", get.call_args.args[0])

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
                    "path": "/api/pncp/v1/orgaos/10635424000186/contratos/contratacao/2026/187",
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
                "codigoUg": "158460",
                "data": "14/05/2026",
            },
            {
                "documentoResumido": "2026NE000999",
                "documento": "999999264222026NE000999",
                "codigoUg": "999999",
                "data": "14/05/2026",
            },
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
        self.assertEqual(report["itens"][0]["quantidade_empenhada_estimada"], 5.0)
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

    def test_report_keeps_the_fractional_estimated_quantity(self):
        report = _preparar_relatorio(
            {
                "status": "ok",
                "quantidade_empenhos": 2,
                "chaves_integracao": {},
                "itens_mapeados": [
                    {
                        "numero_item": 58,
                        "descricao": "Estabilizador",
                        "unidade_medida": "Unidade",
                        "quantidade_licitada": 4,
                        "quantidade_homologada": 4,
                        "valor_unitario_homologado": 700.0,
                        "valor_total_estimado": 2800,
                        "valor_total_homologado": 2800,
                        "resultados": [
                            {
                                "niFornecedor": "05239149000141",
                                "quantidadeHomologada": 4,
                                "valorUnitarioHomologado": 700.0,
                                "valorTotalHomologado": 2800,
                            }
                        ],
                        "empenhos": [
                            {
                                "numero_empenho": "2026NE000567",
                                "fornecedor_cnpj": "05239149000141",
                                "valor_empenhado": "3.840,00",
                                "item_despesa": {"valorAtual": "3.840,00"},
                            },
                            {
                                "numero_empenho": "2026NE000568",
                                "fornecedor_cnpj": "05239149000141",
                                "valor_empenhado": "1.400,00",
                                "item_despesa": {"valorAtual": "1.400,00"},
                            },
                        ],
                    }
                ],
                "empenhos": [],
            }
        )

        linhas = report["itens"][0]["empenhos"]
        self.assertAlmostEqual(linhas[0]["quantidade_estimada"], 5.486, places=3)
        self.assertNotIn("quantidade_divergente", linhas[0])
        self.assertEqual(linhas[1]["quantidade_estimada"], 2.0)
        self.assertAlmostEqual(
            report["itens"][0]["quantidade_empenhada_estimada"], 7.486, places=3
        )

    @patch("pncp_tracker.consultar_e_mapear_empenhos.mapear_empenhos_por_item", return_value=[])
    @patch("pncp_tracker.consultar_e_mapear_empenhos.enriquecer_empenhos_com_detalhes_portal", return_value=([], []))
    @patch("pncp_tracker.consultar_e_mapear_empenhos.consultar_contratos_empenhos", return_value=[])
    @patch(
        "pncp_tracker.consultar_e_mapear_empenhos.buscar_empenhos_portal_para_compra",
        return_value=(
            [],
            [
                {"tipo": "descartado", "numero": "2026NE000567", "motivo": "sem vínculo"},
                {"motivo": "Orçamento de detalhamentos atingido"},
            ],
        ),
    )
    def test_discarded_supplier_documents_are_reported_separately(
        self, _portal, _contracts, _enrich, _map_items
    ):
        result = consultar_e_mapear_empenhos(
            "https://pncp.gov.br/app/editais/10635424000186/2026/000197",
            dados_compra={
                "chaves_integracao": {
                    "cnpj_orgao": "10635424000186",
                    "ano_compra": 2026,
                    "numero_compra": "418",
                    "numero_controle_pncp": "10635424000186-1-000197/2026",
                },
                "itens": [],
            },
            buscar_empenhos_portal=True,
        )

        self.assertEqual(result["quantidade_documentos_descartados"], 1)
        self.assertEqual(
            [documento["numero"] for documento in result["empenhos_nao_confirmados"]],
            ["2026NE000567"],
        )
        self.assertIn("descartado(s) por falta de vínculo com a compra", result["mensagem"])

    def test_report_exposes_origin_of_each_empenho(self):
        report = _preparar_relatorio(
            {
                "status": "ok",
                "quantidade_empenhos": 2,
                "chaves_integracao": {},
                "itens_mapeados": [
                    {
                        "numero_item": 49,
                        "descricao": "Material",
                        "quantidade_homologada": 2,
                        "valor_unitario_homologado": 5080.94,
                        "valor_total_homologado": 10161.88,
                        "resultados": [{"niFornecedor": "46675900000259"}],
                        "empenhos": [
                            {
                                "numero_empenho": "2026NE000236",
                                "fornecedor_cnpj": "46675900000259",
                                "item_despesa": {"valorAtual": "10.161,88"},
                            }
                        ],
                    }
                ],
                "empenhos": [
                    {
                        "numeroContratoEmpenho": "2026NE000236",
                        "origem": "portal_contrato",
                        "detalhesPortalTransparencia": {
                            "status": "ok",
                            "detalhamento": {"data": "13/11/2026"},
                        },
                    },
                    {
                        "numeroContratoEmpenho": "2026NE000999",
                        "origem": "pncp",
                        "detalhesPortalTransparencia": {"status": "nao_encontrado"},
                    },
                ],
            }
        )

        self.assertEqual(report["quantidade_registros_pncp"], 1)
        self.assertEqual(report["quantidade_registros_portal"], 1)
        self.assertEqual(report["itens"][0]["empenhos"][0]["origem"], "portal_contrato")
        # A seção "Registros sem vínculo confirmado a item" foi removida do relatório.
        self.assertNotIn("registros_sem_vinculo", report)

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
    @patch(
        "pncp_tracker.consultar_e_mapear_empenhos.buscar_empenhos_portal_para_compra",
        return_value=(
            [],
            [{"erro": "PortalTransparenciaBlockedError: token bloqueado"}],
        ),
    )
    def test_blocked_portal_token_is_reported_in_the_message(
        self, _portal, _contracts, _enrich, _map_items
    ):
        result = consultar_e_mapear_empenhos(
            "https://pncp.gov.br/app/editais/10635424000186/2026/000187",
            dados_compra={
                "chaves_integracao": {
                    "cnpj_orgao": "10635424000186", "numero_compra": "00404",
                    "ano_compra": 2026, "numero_controle_pncp": "controle",
                },
                "itens": [],
            },
            buscar_empenhos_portal=True,
        )

        self.assertEqual(result["status"], "parcial")
        self.assertIn("bloqueou o token", result["mensagem"])

    @patch("pncp_tracker.consultar_e_mapear_empenhos.buscar_empenhos_portal_para_compra", return_value=([], []))
    @patch("pncp_tracker.consultar_e_mapear_empenhos.mapear_empenhos_por_item", return_value=[])
    @patch("pncp_tracker.consultar_e_mapear_empenhos.enriquecer_empenhos_com_detalhes_portal", return_value=([], []))
    @patch("pncp_tracker.consultar_e_mapear_empenhos.consultar_contratos_empenhos", return_value=[])
    @patch("pncp_tracker.consultar_e_mapear_empenhos.baixar_dados_compra_pncp")
    def test_consultar_e_mapear_empenhos_reuses_stage_one_data(self, download, get_contracts, enrich, map_items, portal):
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
            buscar_empenhos_portal=True,
        )

        download.assert_not_called()
        get_contracts.assert_called_once_with("10635424000186", "2025", "000272")
        portal.assert_called_once()
        self.assertEqual(result["objeto"], "Compra de teste")

    @patch("pncp_tracker.consultar_e_mapear_empenhos.mapear_empenhos_por_item", return_value=[])
    @patch("pncp_tracker.consultar_e_mapear_empenhos.enriquecer_empenhos_com_detalhes_portal")
    @patch(
        "pncp_tracker.consultar_e_mapear_empenhos.consultar_contratos_empenhos",
        return_value=[
            {
                "numeroContratoEmpenho": "2026NE000001",
                "unidadeOrgao": {"codigoUnidade": "158379"},
            },
            {
                "numeroContratoEmpenho": "2026NE000002",
                "unidadeOrgao": {"codigoUnidade": "158379"},
            },
        ],
    )
    @patch(
        "pncp_tracker.consultar_e_mapear_empenhos.buscar_empenhos_portal_para_compra",
        return_value=(
            [
                {
                    "numeroContratoEmpenho": "2026NE000001",
                    "unidadeOrgao": {"codigoUnidade": "158379"},
                    "detalhesPortalTransparencia": {
                        "status": "ok",
                        "codigoDocumento": "158379264222026NE000001",
                        "detalhamento": {},
                    },
                    "origem": "portal_contrato",
                },
                {
                    "numeroContratoEmpenho": "2026NE000002",
                    "unidadeOrgao": {"codigoUnidade": "158379"},
                    "detalhesPortalTransparencia": {
                        "status": "ok",
                        "codigoDocumento": "158379264222026NE000002",
                        "detalhamento": {},
                    },
                    "origem": "portal_contrato",
                },
                {
                    "numeroContratoEmpenho": "2026NE000003",
                    "niFornecedor": "46675900000259",
                    "unidadeOrgao": {"codigoUnidade": "158379"},
                    "detalhesPortalTransparencia": {
                        "status": "ok",
                        "codigoDocumento": "158379264222026NE000003",
                        "detalhamento": {},
                    },
                    "origem": "portal_contrato",
                },
            ],
            [],
        ),
    )
    def test_portal_finds_the_third_record_missing_from_pncp(
        self, _portal, _contracts, enrich, _map_items
    ):
        enrich.side_effect = lambda empenhos: ([dict(e) for e in empenhos], [])
        result = consultar_e_mapear_empenhos(
            "https://pncp.gov.br/app/editais/10635424000186/2026/000187",
            dados_compra={
                "chaves_integracao": {
                    "cnpj_orgao": "10635424000186", "numero_compra": "00404",
                    "ano_compra": 2026, "numero_controle_pncp": "controle",
                },
                "itens": [],
            },
            buscar_empenhos_portal=True,
        )

        self.assertEqual(result["quantidade_empenhos"], 3)
        self.assertEqual(result["quantidade_empenhos_pncp"], 2)
        self.assertEqual(result["quantidade_empenhos_portal"], 1)
        self.assertEqual(
            [e["numeroContratoEmpenho"] for e in result["empenhos"]],
            ["2026NE000001", "2026NE000002", "2026NE000003"],
        )
        self.assertEqual(result["empenhos"][0]["origem"], "pncp")
        self.assertTrue(result["empenhos"][0]["encontrado_tambem_no_portal"])
        self.assertTrue(result["empenhos"][1]["encontrado_tambem_no_portal"])
        self.assertNotIn("encontrado_tambem_no_portal", result["empenhos"][2])
        self.assertEqual(result["empenhos"][2]["origem"], "portal_contrato")

    @patch("pncp_tracker.consultar_e_mapear_empenhos.mapear_empenhos_por_item", return_value=[])
    @patch("pncp_tracker.consultar_e_mapear_empenhos.enriquecer_empenhos_com_detalhes_portal", return_value=([], []))
    @patch("pncp_tracker.consultar_e_mapear_empenhos.consultar_contratos_empenhos", return_value=[])
    @patch("pncp_tracker.consultar_e_mapear_empenhos.buscar_empenhos_portal_para_compra")
    def test_portal_discovery_is_skipped_unless_requested(
        self, portal, _contracts, _enrich, _map_items
    ):
        mensagens = []
        result = consultar_e_mapear_empenhos(
            "https://pncp.gov.br/app/editais/10635424000186/2026/000187",
            dados_compra={
                "chaves_integracao": {
                    "cnpj_orgao": "10635424000186",
                    "ano_compra": 2026,
                    "numero_compra": "404",
                    "numero_controle_pncp": "controle",
                },
                "itens": [],
            },
            on_progress=mensagens.append,
        )

        portal.assert_not_called()
        self.assertFalse(result["busca_portal_realizada"])
        self.assertEqual(result["quantidade_empenhos_portal"], 0)
        self.assertEqual(result["empenhos_nao_confirmados"], [])
        self.assertIn("não executada", result["mensagem"])
        self.assertNotIn(
            "Portal da Transparência - descoberta por processo/favorecido", result["fontes"]
        )
        self.assertTrue(any("desativada" in mensagem for mensagem in mensagens))

    def test_result_without_portal_search_matches_when_nothing_extra_is_found(self):
        purchase = {
            "chaves_integracao": {
                "cnpj_orgao": "10635424000186",
                "ano_compra": 2026,
                "numero_compra": "404",
                "numero_controle_pncp": "controle",
            },
            "itens": [
                {
                    "numeroItem": 1,
                    "descricao": "Parafuso",
                    "unidadeMedida": "UN",
                    "resultadosHomologados": [
                        {
                            "niFornecedor": "46675900000259",
                            "quantidadeHomologada": 2,
                            "valorTotalHomologado": 20,
                        }
                    ],
                }
            ],
        }
        empenhos_pncp = [
            {
                "numeroContratoEmpenho": "2026NE000001",
                "niFornecedor": "46675900000259",
                "unidadeOrgao": {"codigoUnidade": "158379"},
            }
        ]

        def enriquecer(empenhos):
            detalhados = []
            for empenho in empenhos:
                registro = dict(empenho)
                registro["detalhesPortalTransparencia"] = {
                    "status": "ok",
                    "codigoDocumento": "158379264222026NE000001",
                    "detalhamento": {
                        "data": "05/11/2026",
                        "codigoUg": "158379",
                        "ug": "UG TESTE",
                        "codigoFavorecido": "46.675.900/0002-59",
                        "nomeFavorecido": "APL CIENTIFICA LTDA",
                        "itensEmpenho": [
                            {
                                "codigoItemEmpenho": "158379264222026NE000001",
                                "descricao": "Item compra: 00001 - Parafuso",
                                "valorAtual": "10,00",
                                "sequencial": 1,
                            }
                        ],
                    },
                }
                detalhados.append(registro)
            return detalhados, []

        def executar(procurar_no_portal):
            snapshot = {
                **purchase,
                "itens": [dict(item) for item in purchase["itens"]],
            }
            with (
                patch(
                    "pncp_tracker.consultar_e_mapear_empenhos.consultar_contratos_empenhos",
                    return_value=[dict(empenho) for empenho in empenhos_pncp],
                ),
                patch(
                    "pncp_tracker.consultar_e_mapear_empenhos.enriquecer_empenhos_com_detalhes_portal",
                    side_effect=enriquecer,
                ),
                patch(
                    "pncp_tracker.consultar_e_mapear_empenhos.buscar_empenhos_portal_para_compra",
                    return_value=([], []),
                ),
            ):
                return consultar_e_mapear_empenhos(
                    "https://pncp.gov.br/app/editais/10635424000186/2026/000187",
                    dados_compra=snapshot,
                    buscar_empenhos_portal=procurar_no_portal,
                )

        sem_portal = executar(False)
        com_portal = executar(True)

        self.assertFalse(sem_portal["busca_portal_realizada"])
        self.assertTrue(com_portal["busca_portal_realizada"])
        for campo in (
            "quantidade_empenhos",
            "quantidade_empenhos_pncp",
            "quantidade_empenhos_portal",
            "quantidade_empenhos_com_detalhes",
            "empenhos",
            "itens_mapeados",
            "fontes",
        ):
            self.assertEqual(sem_portal[campo], com_portal[campo], campo)
        linhas = sem_portal["itens_mapeados"][0]["empenhos"]
        self.assertEqual([linha["numero_empenho"] for linha in linhas], ["2026NE000001"])
        self.assertEqual(linhas[0]["item_despesa"]["valorAtual"], "10,00")

    @patch("pncp_tracker.consultar_e_mapear_empenhos.mapear_empenhos_por_item", return_value=[])
    @patch("pncp_tracker.consultar_e_mapear_empenhos.enriquecer_empenhos_com_detalhes_portal", return_value=([], []))
    @patch(
        "pncp_tracker.consultar_e_mapear_empenhos.consultar_contratos_empenhos",
        return_value=[{"numeroContratoEmpenho": "2026NE000001"}],
    )
    @patch("pncp_tracker.consultar_e_mapear_empenhos.buscar_empenhos_portal_para_compra", return_value=([], []))
    def test_failed_stage_one_results_make_mapping_status_partial(
        self,
        _portal,
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
