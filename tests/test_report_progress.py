import unittest
from datetime import datetime, timedelta, timezone

from pncp_tracker.report_progress import ProgressoTracker

_TZ = timezone(timedelta(hours=-3))


def _inicio() -> datetime:
    return datetime(2026, 11, 14, 9, 0, tzinfo=_TZ)


class ProgressoTrackerTests(unittest.TestCase):
    def test_parses_collection_messages_into_statistics(self):
        tracker = ProgressoTracker(duracao_referencia=600, iniciado_em=_inicio())
        tracker.atualizar("Consultando página 2 de itens no PNCP.", agora=_inicio())
        estado = tracker.atualizar(
            "Página 2 concluída: 100 itens coletados.",
            agora=_inicio() + timedelta(seconds=120),
        )

        self.assertEqual(estado["etapa"], "coleta")
        self.assertEqual(estado["estatisticas"]["paginas_coletadas"], 2)
        self.assertEqual(estado["estatisticas"]["itens_coletados"], 100)
        self.assertEqual(estado["percentual"], 20.0)
        self.assertEqual(estado["segundos_restantes"], 480)
        self.assertTrue(estado["previsao_conclusao"].startswith("2026-11-14T09:10"))

    def test_parses_empenho_and_report_phases(self):
        tracker = ProgressoTracker(duracao_referencia=600, iniciado_em=_inicio())
        estado = tracker.atualizar(
            "Registros do PNCP recebidos: 110. Consultando detalhes no Portal da Transparência.",
            agora=_inicio(),
        )
        self.assertEqual(estado["etapa"], "empenhos")
        self.assertEqual(estado["estatisticas"]["empenhos_pncp"], 110)
        self.assertGreaterEqual(estado["percentual"], 45.0)

        estado = tracker.atualizar(
            "Portal da Transparência retornou 19 empenho(s) para a compra.",
            agora=_inicio(),
        )
        self.assertEqual(estado["estatisticas"]["empenhos_portal"], 19)

        estado = tracker.atualizar(
            "Gerando os arquivos HTML do relatório.", agora=_inicio()
        )
        self.assertEqual(estado["etapa"], "relatorio")
        self.assertGreaterEqual(estado["percentual"], 90.0)

        estado = tracker.atualizar(
            "Relatório individual e índice atualizados.", agora=_inicio()
        )
        self.assertEqual(estado["etapa"], "concluido")
        self.assertEqual(estado["percentual"], 100.0)

    def test_progress_never_goes_backwards(self):
        tracker = ProgressoTracker(duracao_referencia=300, iniciado_em=_inicio())
        anteriores = []
        for indice, mensagem in enumerate(
            [
                "Consultando página 1 de itens no PNCP.",
                "Página 1 concluída: 50 itens coletados.",
                "Consultando e mapeando contratos e empenhos.",
                "Gerando os arquivos HTML do relatório.",
            ]
        ):
            estado = tracker.atualizar(
                mensagem, agora=_inicio() + timedelta(seconds=indice * 30)
            )
            anteriores.append(estado["percentual"])
        self.assertEqual(anteriores, sorted(anteriores))

    def test_without_history_uses_elapsed_time_as_estimate(self):
        tracker = ProgressoTracker(iniciado_em=_inicio())
        cedo = tracker.atualizar(
            "Consultando página 1 de itens no PNCP.",
            agora=_inicio() + timedelta(seconds=10),
        )
        self.assertIsNone(cedo["segundos_restantes"])

        estado = tracker.atualizar(
            "Registros do PNCP recebidos: 40. Consultando e mapeando empenhos.",
            agora=_inicio() + timedelta(seconds=60),
        )

        self.assertIsNone(estado["duracao_referencia_segundos"])
        self.assertIsNotNone(estado["segundos_restantes"])
        self.assertIsNotNone(estado["previsao_conclusao"])

    def test_failure_does_not_forecast_completion(self):
        tracker = ProgressoTracker(duracao_referencia=100, iniciado_em=_inicio())
        estado = tracker.concluir(sucesso=False, agora=_inicio() + timedelta(seconds=90))

        self.assertEqual(estado["etapa"], "erro")
        self.assertIsNone(estado["segundos_restantes"])
        self.assertIsNone(estado["previsao_conclusao"])

    def test_conclusion_marks_one_hundred_percent(self):
        tracker = ProgressoTracker(duracao_referencia=100, iniciado_em=_inicio())
        estado = tracker.concluir(sucesso=True, agora=_inicio() + timedelta(seconds=90))

        self.assertEqual(estado["percentual"], 100.0)
        self.assertEqual(estado["etapa"], "concluido")
        self.assertEqual(estado["segundos_restantes"], 0)

    def test_bulk_progress_reads_process_position(self):
        tracker = ProgressoTracker(acao="all", iniciado_em=_inicio())
        estado = tracker.atualizar(
            "Atualizando processo 3/7: https://pncp.gov.br/app/editais/1/2026/1",
            agora=_inicio(),
        )

        self.assertEqual(estado["estatisticas"]["processo_indice"], 3)
        self.assertEqual(estado["estatisticas"]["processos_total"], 7)


if __name__ == "__main__":
    unittest.main()
