import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pncp_tracker.report_registry import adicionar_registro, salvar_registros
from pncp_tracker.report_service import atualizar_processo, atualizar_todos
from pncp_tracker.process_lock import lock_path_for


class ReportServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.reports_dir = Path(self.temp_dir.name) / "relatorios"
        self.index_path = self.reports_dir / "indice_relatorios.json"
        self.url = "https://pncp.gov.br/app/editais/10635424000186/2025/000282"
        self.purchase = {
            "chaves_integracao": {
                "cnpj_orgao": "10635424000186",
                "uasg_codigo": "158125",
                "uasg_nome": "Órgão de teste",
                "numero_compra": "90059",
                "ano_compra": 2025,
                "numero_controle_pncp": "10635424000186-1-000282/2025",
            },
            "objeto": "Compra de teste",
            "quantidade_itens": 0,
            "itens": [],
        }
        self.result = {
            "chaves_integracao": self.purchase["chaves_integracao"],
            "objeto": "Compra de teste",
            "status": "ok",
            "quantidade_empenhos": 0,
            "quantidade_empenhos_com_detalhes": 0,
            "empenhos": [],
            "itens_mapeados": [],
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_update_persists_both_datasets_metadata_html_and_registry_summary(self):
        resultado_etapa2 = dict(self.result)
        resultado_etapa2["itens_mapeados"] = [
            {
                "numero_item": 1,
                "descricao": "Item de teste",
                "valor_total_estimado": 100,
                "valor_total_homologado": 90,
                "quantidade_homologada": 1,
                "resultados": [
                    {
                        "nomeRazaoSocialFornecedor": "Fornecedor",
                        "niFornecedor": "12345678000199",
                        "dataResultado": "2026-10-19",
                        "quantidadeHomologada": 1,
                        "valorUnitarioHomologado": 90,
                        "valorTotalHomologado": 90,
                    }
                ],
                "empenhos": [],
            }
        ]
        with patch(
            "pncp_tracker.report_service.baixar_dados_compra_pncp",
            return_value=self.purchase,
        ), patch(
            "pncp_tracker.report_service.consultar_e_mapear_empenhos",
            return_value=resultado_etapa2,
        ):
            result = atualizar_processo(
                self.url,
                reports_dir=self.reports_dir,
                index_path=self.index_path,
            )

        report_dir = self.reports_dir / result["registro"]["pasta"]
        self.assertTrue((report_dir / "dados_pregao.json").exists())
        self.assertTrue((report_dir / "dados_empenhos.json").exists())
        self.assertTrue((report_dir / "metadados.json").exists())
        self.assertTrue(result["caminho_relatorio"].exists())
        self.assertEqual(result["registro"]["status"], "atualizado")
        self.assertEqual(len(result["registro"]["resumo_cards"]), 9)
        metadata = json.loads((report_dir / "metadados.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["url_pncp"], self.url)
        self.assertTrue(metadata["criado_em"])
        self.assertTrue(metadata["atualizado_em"])
        html = result["caminho_relatorio"].read_text(encoding="utf-8")
        embedded = re.search(
            r'<script id="report-data" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(embedded)
        report = json.loads(embedded.group(1))
        self.assertEqual(
            report["itens"][0]["resultados"][0]["data_homologacao"],
            "19/10/2026",
        )
        self.assertIn("Data da homologação:", html)

    def test_update_forwards_progress_messages_from_both_collection_stages(self):
        mensagens = []

        def fake_collection(_url, on_progress):
            on_progress("Itens coletados")
            return self.purchase

        def fake_mapping(_url, dados_compra, on_progress):
            self.assertIs(dados_compra, self.purchase)
            on_progress("Empenhos mapeados")
            return self.result

        with patch(
            "pncp_tracker.report_service.baixar_dados_compra_pncp",
            side_effect=fake_collection,
        ), patch(
            "pncp_tracker.report_service.consultar_e_mapear_empenhos",
            side_effect=fake_mapping,
        ):
            atualizar_processo(
                self.url,
                reports_dir=self.reports_dir,
                index_path=self.index_path,
                on_progress=mensagens.append,
            )

        self.assertIn("Itens coletados", mensagens)
        self.assertIn("Empenhos mapeados", mensagens)
        self.assertIn("Relatório individual e índice atualizados.", mensagens)

    def test_bulk_update_continues_after_failure(self):
        url2 = "https://pncp.gov.br/app/editais/10635424000186/2025/000283"
        adicionar_registro(self.url, self.index_path)
        adicionar_registro(url2, self.index_path)

        def fake_update(url, **_kwargs):
            if url == self.url:
                raise RuntimeError("falha simulada")
            return {"registro": {"url_pncp": url}}

        with patch("pncp_tracker.report_service._atualizar_processo", side_effect=fake_update):
            result = atualizar_todos(
                reports_dir=self.reports_dir,
                index_path=self.index_path,
            )

        self.assertEqual(len(result["atualizados"]), 1)
        self.assertEqual(len(result["falhas"]), 1)
        self.assertEqual(result["falhas"][0]["url_pncp"], self.url)
        records = json.loads(self.index_path.read_text(encoding="utf-8"))["relatorios"]
        self.assertEqual(records[0]["status"], "erro")

    def test_bulk_update_holds_a_single_lock_for_the_entire_batch(self):
        second_url = "https://pncp.gov.br/app/editais/10635424000186/2025/000283"
        adicionar_registro(self.url, self.index_path)
        adicionar_registro(second_url, self.index_path)
        with patch("pncp_tracker.report_service.interprocess_lock") as lock, patch(
            "pncp_tracker.report_service._atualizar_processo",
            side_effect=lambda url, **_kwargs: {"registro": {"url_pncp": url}},
        ) as update:
            result = atualizar_todos(
                reports_dir=self.reports_dir,
                index_path=self.index_path,
            )

        lock.assert_called_once_with(lock_path_for(self.index_path))
        self.assertEqual(update.call_count, 2)
        self.assertEqual(len(result["atualizados"]), 2)
        self.assertEqual(result["falhas"], [])

    def test_invalid_registered_folder_is_rejected_before_collection(self):
        record = {
            "url_pncp": self.url,
            "pasta": "..",
            "status": "atualizado",
        }
        salvar_registros([record], self.index_path)
        with patch(
            "pncp_tracker.report_service.baixar_dados_compra_pncp"
        ) as collect:
            with self.assertRaisesRegex(ValueError, "Nome da pasta"):
                atualizar_processo(
                    self.url,
                    reports_dir=self.reports_dir,
                    index_path=self.index_path,
                )
        collect.assert_not_called()

    def test_incomplete_purchase_header_is_rejected_without_writing_a_report(self):
        incomplete_purchase = {
            "chaves_integracao": {
                "cnpj_orgao": "10635424000186",
                "uasg_codigo": "158125",
                "uasg_nome": "Órgão de teste",
            },
            "objeto": "Compra sem chaves",
            "quantidade_itens": 0,
            "itens": [],
        }
        with patch(
            "pncp_tracker.report_service.baixar_dados_compra_pncp",
            return_value=incomplete_purchase,
        ), patch("pncp_tracker.report_service.consultar_e_mapear_empenhos") as map_items:
            with self.assertRaisesRegex(ValueError, "Cabeçalho da compra incompleto"):
                atualizar_processo(
                    self.url,
                    reports_dir=self.reports_dir,
                    index_path=self.index_path,
                )

        map_items.assert_not_called()
        records = json.loads(self.index_path.read_text(encoding="utf-8"))["relatorios"]
        self.assertEqual(records[0]["status"], "erro")
        self.assertFalse(list(self.reports_dir.glob("processo_*")))

    def test_failed_collection_keeps_the_last_successful_json_snapshot(self):
        with patch(
            "pncp_tracker.report_service.baixar_dados_compra_pncp",
            return_value=self.purchase,
        ), patch(
            "pncp_tracker.report_service.consultar_e_mapear_empenhos",
            return_value=self.result,
        ):
            result = atualizar_processo(
                self.url,
                reports_dir=self.reports_dir,
                index_path=self.index_path,
            )
        report_dir = self.reports_dir / result["registro"]["pasta"]
        paths = [
            report_dir / "dados_pregao.json",
            report_dir / "dados_empenhos.json",
            report_dir / "metadados.json",
        ]
        snapshot = [path.read_bytes() for path in paths]

        with patch(
            "pncp_tracker.report_service.baixar_dados_compra_pncp",
            return_value=self.purchase,
        ), patch(
            "pncp_tracker.report_service.consultar_e_mapear_empenhos",
            side_effect=RuntimeError("falha da etapa 2"),
        ):
            with self.assertRaisesRegex(RuntimeError, "falha da etapa 2"):
                atualizar_processo(
                    self.url,
                    reports_dir=self.reports_dir,
                    index_path=self.index_path,
                )

        self.assertEqual([path.read_bytes() for path in paths], snapshot)
        records = json.loads(self.index_path.read_text(encoding="utf-8"))["relatorios"]
        self.assertEqual(records[0]["status"], "erro")
        self.assertEqual(records[0]["erro"], "falha da etapa 2")


if __name__ == "__main__":
    unittest.main()
