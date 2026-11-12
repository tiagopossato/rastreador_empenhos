import contextlib
import io
import unittest
from unittest.mock import patch

import atualizar_relatorios


class UpdateReportsCliTests(unittest.TestCase):
    def test_returns_failure_when_any_process_update_fails(self):
        result = {
            "atualizados": [{"url_pncp": "https://pncp.gov.br/processo-ok"}],
            "falhas": [
                {
                    "url_pncp": "https://pncp.gov.br/processo-falhou",
                    "erro": "timeout",
                }
            ],
        }
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(
            io.StringIO()
        ), patch("atualizar_relatorios.atualizar_todos", return_value=result):
            self.assertEqual(atualizar_relatorios.main(), 1)

    def test_returns_success_when_all_processes_update(self):
        with contextlib.redirect_stdout(io.StringIO()), patch(
            "atualizar_relatorios.atualizar_todos",
            return_value={"atualizados": [], "falhas": []},
        ):
            self.assertEqual(atualizar_relatorios.main(), 0)


if __name__ == "__main__":
    unittest.main()
