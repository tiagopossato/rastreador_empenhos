import tempfile
import unittest
from pathlib import Path

from generate_reports_index import gerar_index_relatorios


class GenerateReportsIndexTests(unittest.TestCase):
    def test_index_links_to_reports_in_sorted_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            (reports_dir / "relatorio_compra_90027_2025.html").write_text(
                "<html></html>", encoding="utf-8"
            )
            (reports_dir / "relatorio_compra_90026_2025.html").write_text(
                "<html></html>", encoding="utf-8"
            )
            (reports_dir / "outro_arquivo.html").write_text(
                "<html></html>", encoding="utf-8"
            )
            (reports_dir / "index.html").write_text("stale", encoding="utf-8")

            index = gerar_index_relatorios(reports_dir)
            conteudo = index.read_text(encoding="utf-8")

            self.assertIn('href="relatorio_compra_90026_2025.html"', conteudo)
            self.assertIn('href="relatorio_compra_90027_2025.html"', conteudo)
            self.assertNotIn("outro_arquivo.html", conteudo)
            self.assertLess(
                conteudo.index("Compra 90026"),
                conteudo.index("Compra 90027"),
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
            (reports_dir / "relatorio_compra_&teste'_2025.html").write_text(
                "<html></html>", encoding="utf-8"
            )

            conteudo = gerar_index_relatorios(reports_dir).read_text(encoding="utf-8")

            self.assertIn("relatorio_compra_%26teste%27_2025.html", conteudo)
            self.assertIn("Compra &amp;teste&#x27; — 2025", conteudo)


if __name__ == "__main__":
    unittest.main()
