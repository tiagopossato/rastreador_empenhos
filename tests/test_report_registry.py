import json
import tempfile
import unittest
from pathlib import Path

from pncp_tracker.report_registry import (
    adicionar_registro,
    atualizar_registro,
    chave_url_pncp,
    ler_registros,
    remover_registro,
    validar_url_pncp,
)


class ReportRegistryTests(unittest.TestCase):
    def test_add_and_remove_process_without_deleting_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            index_path = reports_dir / "indice_relatorios.json"
            url = "https://pncp.gov.br/app/editais/10635424000186/2025/000282"

            record = adicionar_registro(url, index_path)
            archive = reports_dir / "arquivo" / "dados_empenhos.json"
            archive.parent.mkdir()
            archive.write_text("{}", encoding="utf-8")
            removed = remover_registro(record["id"], index_path)

            self.assertEqual(removed["url_pncp"], url)
            self.assertEqual(ler_registros(index_path), [])
            self.assertTrue(archive.exists())
            self.assertEqual(
                json.loads(index_path.read_text(encoding="utf-8"))["quantidade_relatorios"],
                0,
            )

    def test_duplicate_urls_with_padded_sequence_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "indice_relatorios.json"
            adicionar_registro(
                "https://pncp.gov.br/app/editais/10635424000186/2025/000282",
                index_path,
            )
            with self.assertRaisesRegex(ValueError, "já está cadastrado"):
                adicionar_registro(
                    "https://pncp.gov.br/app/editais/10635424000186/2025/282",
                    index_path,
                )

    def test_only_exact_https_pncp_edital_urls_are_accepted(self):
        for url in (
            "http://pncp.gov.br/app/editais/10635424000186/2025/282",
            "https://example.com/app/editais/10635424000186/2025/282",
            "https://pncp.gov.br/app/editais/10635424000186/2025/282?next=x",
            "https://pncp.gov.br/app/editais/123/2025/282",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validar_url_pncp(url)

    def test_sequence_padding_is_not_part_of_process_identity(self):
        self.assertEqual(
            chave_url_pncp("https://pncp.gov.br/app/editais/10635424000186/2025/000282"),
            chave_url_pncp("https://pncp.gov.br/app/editais/10635424000186/2025/282"),
        )

    def test_updating_an_unknown_process_raises_key_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "indice_relatorios.json"

            with self.assertRaises(KeyError):
                atualizar_registro(
                    "https://pncp.gov.br/app/editais/10635424000186/2025/000282",
                    {"status": "atualizando"},
                    index_path,
                )

    def test_updating_a_registered_process_persists_the_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "indice_relatorios.json"
            url = "https://pncp.gov.br/app/editais/10635424000186/2025/000282"
            adicionar_registro(url, index_path)

            atualizado = atualizar_registro(url, {"status": "atualizando", "pasta": "abc"}, index_path)

            self.assertEqual(atualizado["status"], "atualizando")
            self.assertEqual(ler_registros(index_path)[0]["pasta"], "abc")


if __name__ == "__main__":
    unittest.main()
