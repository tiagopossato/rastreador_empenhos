import json
import tempfile
import unittest
from pathlib import Path

from relatorios.gerar_relatorios import gerar_relatorios


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
            "url_pncp": "https://pncp.gov.br/app/editais/12345678000199/{}/{}".format(
                year, number
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
        return report_dir

    def test_generates_report_html_metadata_and_sorted_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            self._write_report(
                reports_dir,
                "relatorio_compra_90027_2025",
                "90027",
                2025,
                "Objeto do segundo edital",
            )
            self._write_report(
                reports_dir,
                "relatorio_compra_90026_2025",
                "90026",
                2025,
                "Aquisição de equipamentos de proteção individual",
            )
            (reports_dir / "outro_arquivo.html").write_text(
                "<html></html>", encoding="utf-8"
            )
            (reports_dir / "index.html").write_text("stale", encoding="utf-8")

            index = gerar_relatorios(reports_dir)
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
            index = gerar_relatorios(reports_dir)

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
            self._write_report(
                reports_dir,
                "relatorio_teste",
                "&teste'",
                2025,
                "Objeto com & e aspas '",
            )

            content = gerar_relatorios(reports_dir).read_text(encoding="utf-8")

            self.assertIn("Edital nº &amp;teste&#x27;/2025", content)
            self.assertIn("Objeto com &amp; e aspas &#x27;", content)

    def test_incomplete_report_folder_is_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            report_dir = reports_dir / "relatorio_incompleto"
            report_dir.mkdir()
            (report_dir / "metadados.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Pasta de relatório incompleta"):
                gerar_relatorios(reports_dir)


if __name__ == "__main__":
    unittest.main()
