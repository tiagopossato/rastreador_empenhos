import json
import tempfile
import unittest
from pathlib import Path

from generate_reports_index import gerar_index_relatorios


class GenerateReportsIndexTests(unittest.TestCase):
    def _write_report(self, reports_dir, filename, number, year, object_text):
        report_data = {
            "chaves": {"numero_compra": number, "ano_compra": year},
            "objeto": object_text,
        }
        content = (
            '<script id="report-data" type="application/json">'
            + json.dumps(report_data, ensure_ascii=False)
            + "</script>"
        )
        (reports_dir / filename).write_text(content, encoding="utf-8")

    def test_index_links_to_reports_in_sorted_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            self._write_report(
                reports_dir,
                "relatorio_compra_90027_2025.html",
                "90027",
                2025,
                "Objeto do segundo edital",
            )
            self._write_report(
                reports_dir,
                "relatorio_compra_90026_2025.html",
                "90026",
                2025,
                "Eventual aquisição de equipamentos de proteção individual",
            )
            (reports_dir / "outro_arquivo.html").write_text(
                "<html></html>", encoding="utf-8"
            )
            (reports_dir / "index.html").write_text("stale", encoding="utf-8")

            index = gerar_index_relatorios(reports_dir)
            conteudo = index.read_text(encoding="utf-8")

            self.assertIn('href="relatorio_compra_90026_2025.html"', conteudo)
            self.assertIn('href="relatorio_compra_90027_2025.html"', conteudo)
            self.assertIn("Edital nº 90026/2025", conteudo)
            self.assertIn(
                "Eventual aquisição de equipamentos de proteção individual",
                conteudo,
            )
            self.assertNotIn("outro_arquivo.html", conteudo)
            self.assertLess(
                conteudo.index("Edital nº 90026/2025"),
                conteudo.index("Edital nº 90027/2025"),
            )
            self.assertNotIn("stale", conteudo)

    def test_index_shows_empty_state_when_no_reports_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index = gerar_index_relatorios(Path(temp_dir))

            self.assertIn(
                "Nenhum relatório disponível.",
                index.read_text(encoding="utf-8"),
            )

    def test_generated_links_escape_unexpected_filename_characters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            self._write_report(
                reports_dir,
                "relatorio_compra_&teste'_2025.html",
                "&teste'",
                2025,
                "Objeto com & e aspas '",
            )

            conteudo = gerar_index_relatorios(reports_dir).read_text(encoding="utf-8")

            self.assertIn("relatorio_compra_%26teste%27_2025.html", conteudo)
            self.assertIn("Edital nº &amp;teste&#x27;/2025", conteudo)
            self.assertIn("Objeto com &amp; e aspas &#x27;", conteudo)

    def test_index_reports_missing_embedded_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            (reports_dir / "relatorio_compra_90026_2025.html").write_text(
                "<html></html>", encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "Dados do edital não encontrados"):
                gerar_index_relatorios(reports_dir)


if __name__ == "__main__":
    unittest.main()
