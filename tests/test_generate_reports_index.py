import json
import tempfile
import unittest
from pathlib import Path

from relatorios.gerar_relatorios import gerar_relatorios
from pncp_tracker.report_registry import salvar_registros


class GenerateReportsIndexTests(unittest.TestCase):
    def _write_report(self, reports_dir, folder, number, year, object_text):
        report_dir = reports_dir / folder
        report_dir.mkdir()
        (report_dir / "dados_pregao.json").write_text(
            json.dumps({"quantidade_itens": 1}),
            encoding="utf-8",
        )
        report_data = {
            "chaves_integracao": {"numero_compra": number, "ano_compra": year},
            "objeto": object_text,
            "itens_mapeados": [
                {
                    "numero_item": 1,
                    "descricao": "Item de teste",
                    "valor_total_estimado": 200,
                    "valor_total_homologado": 100,
                    "resultados": [],
                    "empenhos": [
                        {
                            "numero_empenho": "2026NE000001",
                            "item_despesa": {"valorAtual": 25},
                        }
                    ],
                }
            ],
            "empenhos": [],
            "status": "ok",
            "quantidade_empenhos": 1,
            "quantidade_empenhos_com_detalhes": 1,
        }
        (report_dir / "dados_empenhos.json").write_text(
            json.dumps(report_data, ensure_ascii=False),
            encoding="utf-8",
        )
        metadata = {
            "url_pncp": "https://pncp.gov.br/app/editais/12345678000199/{}/{:06}".format(
                year, int(number)
            ),
            "criado_em": "2026-01-01T10:00:00-03:00",
            "atualizado_em": "2026-01-02T10:00:00-03:00",
            "chaves_integracao": report_data["chaves_integracao"],
            "arquivo_html": "{}.html".format(folder),
        }
        (report_dir / "metadados.json").write_text(
            json.dumps(metadata, ensure_ascii=False),
            encoding="utf-8",
        )
        return {
            "id": "12345678000199-{}-{}".format(year, int(number)),
            "url_pncp": metadata["url_pncp"],
            "pasta": folder,
            "status": "atualizado",
            "arquivo_html": metadata["arquivo_html"],
        }

    def test_generates_report_html_metadata_and_sorted_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            entries = [
                self._write_report(
                    reports_dir,
                    "relatorio_compra_90026_2025",
                    "90026",
                    2025,
                    "Aquisição de equipamentos de proteção individual",
                ),
                self._write_report(
                    reports_dir,
                    "relatorio_compra_90027_2025",
                    "90027",
                    2025,
                    "Objeto do segundo edital",
                ),
            ]
            index_path = reports_dir / "indice_relatorios.json"
            salvar_registros(entries, index_path)
            (reports_dir / "outro_arquivo.html").write_text(
                "<html></html>", encoding="utf-8"
            )
            (reports_dir / "index.html").write_text("stale", encoding="utf-8")

            index = gerar_relatorios(reports_dir, index_path=index_path)
            conteudo = index.read_text(encoding="utf-8")

            self.assertIn(
                'href="relatorio_compra_90026_2025/relatorio_compra_90026_2025.html"',
                conteudo,
            )
            self.assertIn(
                'href="relatorio_compra_90027_2025/relatorio_compra_90027_2025.html"',
                conteudo,
            )
            self.assertIn("Edital nº 90026/2025", conteudo)
            self.assertIn("Aquisição de equipamentos de proteção individual", conteudo)
            self.assertIn("<!-- admin-link -->", conteudo)
            self.assertNotIn("stale", conteudo)
            self.assertLess(
                conteudo.index("Edital nº 90026/2025"),
                conteudo.index("Edital nº 90027/2025"),
            )
            self.assertTrue(
                (reports_dir / "relatorio_compra_90026_2025" / "relatorio_compra_90026_2025.html").exists()
            )

            index_data = json.loads(
                (reports_dir / "indice_relatorios.json").read_text(encoding="utf-8")
            )
            self.assertEqual(index_data["quantidade_relatorios"], 2)
            self.assertEqual(
                index_data["relatorios"][0]["pasta"],
                "relatorio_compra_90026_2025",
            )
            metadata = json.loads(
                (
                    reports_dir
                    / "relatorio_compra_90026_2025"
                    / "metadados.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(len(metadata["resumo_cards"]), 8)
            cards_by_key = {
                card["chave"]: card for card in metadata["resumo_cards"]
            }
            self.assertEqual(cards_by_key["itens_empenhados"]["valor"], 1)
            self.assertEqual(cards_by_key["valor_estimado"]["exibicao"], "R$ 200,00")

    def test_index_shows_empty_state_when_no_reports_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            index_path = reports_dir / "indice_relatorios.json"
            index = gerar_relatorios(reports_dir, index_path=index_path)

            self.assertIn(
                "Nenhum relatório disponível.",
                index.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                json.loads(
                    (reports_dir / "indice_relatorios.json").read_text(encoding="utf-8")
                )["relatorios"],
                [],
            )

    def test_report_and_object_values_are_html_escaped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            record = self._write_report(
                reports_dir,
                "relatorio_teste",
                "90028",
                2025,
                "Objeto com & e aspas '",
            )
            report_data_path = reports_dir / "relatorio_teste" / "dados_empenhos.json"
            report_data = json.loads(report_data_path.read_text(encoding="utf-8"))
            report_data["objeto"] = "Objeto com & e aspas '"
            report_data_path.write_text(json.dumps(report_data), encoding="utf-8")
            index_path = reports_dir / "indice_relatorios.json"
            salvar_registros([record], index_path)

            content = gerar_relatorios(reports_dir, index_path=index_path).read_text(encoding="utf-8")

            self.assertIn("Objeto com &amp; e aspas &#x27;", content)

    def test_pending_record_is_retained_until_data_is_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            index_path = reports_dir / "indice_relatorios.json"
            record = {
                "id": "12345678000199-2025-282",
                "url_pncp": "https://pncp.gov.br/app/editais/12345678000199/2025/000282",
                "status": "pendente",
                "pasta": None,
                "resumo_cards": [],
            }
            salvar_registros([record], index_path)

            index = gerar_relatorios(reports_dir, index_path=index_path)

            self.assertIn("Processo aguardando atualização", index.read_text(encoding="utf-8"))
            saved = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["relatorios"][0]["status"], "pendente")

    def test_index_regeneration_does_not_hide_a_failed_update(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            record = self._write_report(
                reports_dir,
                "relatorio_existente",
                "90029",
                2025,
                "Objeto existente",
            )
            record["status"] = "erro"
            record["erro"] = "falha temporária"
            index_path = reports_dir / "indice_relatorios.json"
            salvar_registros([record], index_path)

            gerar_relatorios(reports_dir, index_path=index_path)

            saved = json.loads(index_path.read_text(encoding="utf-8"))["relatorios"][0]
            self.assertEqual(saved["status"], "erro")
            self.assertEqual(saved["erro"], "falha temporária")

    def test_incomplete_report_data_is_marked_as_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            record = self._write_report(
                reports_dir,
                "relatorio_incompleto",
                "90030",
                2025,
                "Objeto incompleto",
            )
            (reports_dir / "relatorio_incompleto" / "dados_pregao.json").unlink()
            index_path = reports_dir / "indice_relatorios.json"
            salvar_registros([record], index_path)

            gerar_relatorios(reports_dir, index_path=index_path)

            saved = json.loads(index_path.read_text(encoding="utf-8"))["relatorios"][0]
            self.assertEqual(saved["status"], "erro")
            self.assertIn("Dados incompletos", saved["erro"])


if __name__ == "__main__":
    unittest.main()
