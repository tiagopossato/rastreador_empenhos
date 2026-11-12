import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pncp_tracker.report_registry import adicionar_registro, salvar_registros
from pncp_tracker.report_service import atualizar_processo, atualizar_todos


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
        self.assertTrue((report_dir / "dados_pregao.json").exists())
        self.assertTrue((report_dir / "dados_empenhos.json").exists())
        self.assertTrue((report_dir / "metadados.json").exists())
        self.assertTrue(result["caminho_relatorio"].exists())
        self.assertEqual(result["registro"]["status"], "atualizado")
        self.assertEqual(len(result["registro"]["resumo_cards"]), 8)
        metadata = json.loads((report_dir / "metadados.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["url_pncp"], self.url)
        self.assertTrue(metadata["criado_em"])
        self.assertTrue(metadata["atualizado_em"])

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

        with patch("pncp_tracker.report_service.atualizar_processo", side_effect=fake_update):
            result = atualizar_todos(
                reports_dir=self.reports_dir,
                index_path=self.index_path,
            )

        self.assertEqual(len(result["atualizados"]), 1)
        self.assertEqual(len(result["falhas"]), 1)
        self.assertEqual(result["falhas"][0]["url_pncp"], self.url)
        records = json.loads(self.index_path.read_text(encoding="utf-8"))["relatorios"]
        self.assertEqual(records[0]["status"], "erro")

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
            return_value={"objeto": "novo"},
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
