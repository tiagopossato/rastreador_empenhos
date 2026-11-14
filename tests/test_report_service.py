import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pncp_tracker.report_registry import (
    adicionar_registro,
    atualizar_registro,
    ler_registros,
    salvar_registros,
)
from pncp_tracker.report_service import (
    atualizar_processo,
    atualizar_todos,
    reprocessar_itens_pendentes,
)
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
        self.empty_collection = {
            "empenhos": [],
            "busca_portal_realizada": False,
            "quantidade_empenhos_pncp": 0,
            "quantidade_empenhos_portal": 0,
            "erros": [],
        }

    def _patch_pipeline(self, coleta=None, etapa2=None):
        """Substitui as duas etapas do fluxo de empenhos (valor fixo ou função)."""

        def _patcher(nome, valor, padrao):
            alvo = "pncp_tracker.report_service." + nome
            if isinstance(valor, BaseException) or callable(valor):
                return patch(alvo, side_effect=valor)
            return patch(alvo, return_value=padrao if valor is None else valor)

        return (
            _patcher("coletar_empenhos", coleta, dict(self.empty_collection)),
            _patcher("enriquecer_e_mapear_empenhos", etapa2, self.result),
        )

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
        coleta_patch, etapa2_patch = self._patch_pipeline(etapa2=resultado_etapa2)
        with patch(
            "pncp_tracker.report_service.baixar_dados_compra_pncp",
            return_value=self.purchase,
        ), coleta_patch, etapa2_patch:
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

        def fake_collection(_url, on_progress, dados_anteriores=None):
            on_progress("Itens coletados")
            return self.purchase

        def fake_empenhos(_url, _dados_compra, **_kwargs):
            return dict(self.empty_collection)

        def fake_mapping(dados_compra, on_progress=None):
            self.assertIs(dados_compra, self.purchase)
            on_progress("Empenhos mapeados")
            return self.result

        coleta_patch, etapa2_patch = self._patch_pipeline(
            coleta=fake_empenhos,
            etapa2=fake_mapping,
        )
        with patch(
            "pncp_tracker.report_service.baixar_dados_compra_pncp",
            side_effect=fake_collection,
        ), coleta_patch, etapa2_patch:
            atualizar_processo(
                self.url,
                reports_dir=self.reports_dir,
                index_path=self.index_path,
                on_progress=mensagens.append,
            )

        self.assertIn("Itens coletados", mensagens)
        self.assertIn("Empenhos mapeados", mensagens)
        self.assertIn("Relatório individual e índice atualizados.", mensagens)

    def _executar_atualizacao(self, buscar_empenhos_portal=None):
        kwargs = {}
        if buscar_empenhos_portal is not None:
            kwargs["buscar_empenhos_portal"] = buscar_empenhos_portal
        coleta_patch, etapa2_patch = self._patch_pipeline()
        with patch(
            "pncp_tracker.report_service.baixar_dados_compra_pncp",
            return_value=self.purchase,
        ), coleta_patch as coleta, etapa2_patch:
            result = atualizar_processo(
                self.url,
                reports_dir=self.reports_dir,
                index_path=self.index_path,
                **kwargs,
            )
        metadados = json.loads(
            (self.reports_dir / result["registro"]["pasta"] / "metadados.json").read_text(
                encoding="utf-8"
            )
        )
        return coleta.call_args.kwargs["buscar_empenhos_portal"], metadados

    def test_portal_search_flag_is_forwarded_and_recorded_in_metadata(self):
        procurado, metadados = self._executar_atualizacao(buscar_empenhos_portal=True)

        self.assertTrue(procurado)
        self.assertTrue(metadados["buscar_empenhos_portal"])

    def test_portal_search_defaults_to_the_value_stored_in_the_index(self):
        adicionar_registro(self.url, self.index_path, buscar_empenhos_portal=True)
        procurado, metadados = self._executar_atualizacao()

        self.assertTrue(procurado)
        self.assertTrue(metadados["buscar_empenhos_portal"])

    def test_portal_search_is_off_for_processes_without_the_flag(self):
        procurado, metadados = self._executar_atualizacao()

        self.assertFalse(procurado)
        self.assertFalse(metadados["buscar_empenhos_portal"])

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
        coleta_patch, etapa2_patch = self._patch_pipeline()
        with patch(
            "pncp_tracker.report_service.baixar_dados_compra_pncp",
            return_value=incomplete_purchase,
        ), coleta_patch as coleta, etapa2_patch as mapa:
            with self.assertRaisesRegex(ValueError, "Cabeçalho da compra incompleto"):
                atualizar_processo(
                    self.url,
                    reports_dir=self.reports_dir,
                    index_path=self.index_path,
                )

        coleta.assert_not_called()
        mapa.assert_not_called()
        records = json.loads(self.index_path.read_text(encoding="utf-8"))["relatorios"]
        self.assertEqual(records[0]["status"], "erro")
        self.assertFalse(list(self.reports_dir.glob("processo_*")))

    def _preparar_relatorio_com_itens_pendentes(self):
        adicionar_registro(self.url, self.index_path)
        atualizar_registro(
            self.url,
            {"pasta": "processo_10635424000186-2025-282"},
            self.index_path,
        )
        registro = ler_registros(self.index_path)[0]
        pasta = self.reports_dir / registro["pasta"]
        pasta.mkdir(parents=True, exist_ok=True)
        pendencia = [
            {"numero_item": 1, "erro": "ConnectTimeout"},
            {"numero_item": 2, "erro": "ConnectTimeout"},
        ]
        dados_compra = {
            "chaves_integracao": self.purchase["chaves_integracao"],
            "objeto": "Compra de teste",
            "itens": [
                {
                    "numeroItem": 1,
                    "descricao": "Parafuso",
                    "resultadosHomologados": [],
                    "erroResultadosHomologados": "ConnectTimeout",
                },
                {
                    "numeroItem": 2,
                    "descricao": "Areia",
                    "resultadosHomologados": [],
                    "erroResultadosHomologados": "ConnectTimeout",
                },
            ],
            "erros_resultados_itens": list(pendencia),
            "empenhos": [],
            "coleta_empenhos": {
                "busca_portal_realizada": False,
                "quantidade_empenhos_pncp": 0,
                "quantidade_empenhos_portal": 0,
                "erros": [],
            },
        }
        dados_empenhos = {
            "status": "parcial",
            "mensagem": "Itens pendentes.",
            "fontes": ["PNCP - aba Contratos/Empenhos"],
            "chaves_integracao": self.purchase["chaves_integracao"],
            "quantidade_empenhos": 0,
            "empenhos": [],
            "itens_mapeados": [],
            "erros_detalhamento": [],
            "erros_resultados_itens": list(pendencia),
        }
        metadados = {
            "url_pncp": self.url,
            "arquivo_html": "relatorio_compra_90059_2025.html",
            "atualizado_em": "2026-11-14T10:00:00-03:00",
            "chaves_integracao": self.purchase["chaves_integracao"],
        }
        for nome, conteudo in (
            ("dados_pregao.json", dados_compra),
            ("dados_empenhos.json", dados_empenhos),
            ("metadados.json", metadados),
        ):
            (pasta / nome).write_text(
                json.dumps(conteudo, ensure_ascii=False), encoding="utf-8"
            )
        return pasta

    def test_retry_recovers_pending_items_without_consulting_the_portal(self):
        pasta = self._preparar_relatorio_com_itens_pendentes()

        def buscar(cnpj, ano, sequencial, numero_item):
            if numero_item == 2:
                raise RuntimeError("serviço indisponível")
            return [
                {
                    "niFornecedor": "12345678000199",
                    "quantidadeHomologada": 2,
                    "valorTotalHomologado": 20,
                    "valorUnitarioHomologado": 10,
                }
            ]

        with patch(
            "pncp_tracker.report_service.buscar_resultados_item",
            side_effect=buscar,
        ) as chamadas:
            resultado = reprocessar_itens_pendentes(
                self.url,
                reports_dir=self.reports_dir,
                index_path=self.index_path,
            )

        self.assertEqual(resultado["pendentes"], 2)
        self.assertEqual(resultado["recuperados"], 1)
        self.assertEqual(resultado["falhas"], 1)
        self.assertTrue(resultado["atualizado"])
        self.assertEqual(chamadas.call_count, 2)

        dados_pregao = json.loads((pasta / "dados_pregao.json").read_text(encoding="utf-8"))
        self.assertEqual(len(dados_pregao["itens"][0]["resultadosHomologados"]), 1)
        self.assertNotIn("erroResultadosHomologados", dados_pregao["itens"][0])
        self.assertIn("erroResultadosHomologados", dados_pregao["itens"][1])
        self.assertEqual(
            [erro["numero_item"] for erro in dados_pregao["erros_resultados_itens"]], [2]
        )

        dados_empenhos = json.loads((pasta / "dados_empenhos.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [erro["numero_item"] for erro in dados_empenhos["erros_resultados_itens"]], [2]
        )
        itens = {item["numero_item"]: item for item in dados_empenhos["itens_mapeados"]}
        self.assertEqual(itens[1]["status"], "sem_empenho_mapeado")
        self.assertEqual(itens[2]["status"], "resultados_homologados_indisponiveis")

        metadados = json.loads((pasta / "metadados.json").read_text(encoding="utf-8"))
        self.assertNotEqual(metadados["atualizado_em"], "2026-11-14T10:00:00-03:00")
        self.assertTrue((pasta / "relatorio_compra_90059_2025.html").exists())

    def test_retry_without_pending_items_does_not_rewrite_the_report(self):
        pasta = self._preparar_relatorio_com_itens_pendentes()
        dados_pregao = json.loads((pasta / "dados_pregao.json").read_text(encoding="utf-8"))
        for item in dados_pregao["itens"]:
            item.pop("erroResultadosHomologados", None)
        dados_pregao["erros_resultados_itens"] = []
        (pasta / "dados_pregao.json").write_text(
            json.dumps(dados_pregao, ensure_ascii=False), encoding="utf-8"
        )

        with patch("pncp_tracker.report_service.buscar_resultados_item") as chamadas:
            resultado = reprocessar_itens_pendentes(
                self.url,
                reports_dir=self.reports_dir,
                index_path=self.index_path,
            )

        self.assertFalse(resultado["atualizado"])
        self.assertEqual(resultado["pendentes"], 0)
        chamadas.assert_not_called()

    def test_stage_one_snapshot_keeps_pncp_empenhos_even_if_enrichment_fails(self):
        coleta = {
            "empenhos": [{"numeroContratoEmpenho": "2026NE000042", "origem": "pncp"}],
            "busca_portal_realizada": False,
            "quantidade_empenhos_pncp": 1,
            "quantidade_empenhos_portal": 0,
            "erros": [],
        }
        coleta_patch, etapa2_patch = self._patch_pipeline(
            coleta=coleta,
            etapa2=RuntimeError("falha da etapa 2"),
        )
        with patch(
            "pncp_tracker.report_service.baixar_dados_compra_pncp",
            return_value=dict(self.purchase),
        ), coleta_patch, etapa2_patch:
            with self.assertRaisesRegex(RuntimeError, "falha da etapa 2"):
                atualizar_processo(
                    self.url,
                    reports_dir=self.reports_dir,
                    index_path=self.index_path,
                )

        dados_pregao = json.loads(
            (
                self.reports_dir
                / "processo_10635424000186-2025-282"
                / "dados_pregao.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            [empenho["numeroContratoEmpenho"] for empenho in dados_pregao["empenhos"]],
            ["2026NE000042"],
        )
        self.assertEqual(dados_pregao["coleta_empenhos"]["quantidade_empenhos_pncp"], 1)
        self.assertFalse(
            (self.reports_dir / "processo_10635424000186-2025-282" / "dados_empenhos.json").exists()
        )

    def test_failed_enrichment_keeps_the_last_successful_report_snapshot(self):
        coleta_patch, etapa2_patch = self._patch_pipeline()
        with patch(
            "pncp_tracker.report_service.baixar_dados_compra_pncp",
            return_value=dict(self.purchase),
        ), coleta_patch, etapa2_patch:
            result = atualizar_processo(
                self.url,
                reports_dir=self.reports_dir,
                index_path=self.index_path,
            )
        report_dir = self.reports_dir / result["registro"]["pasta"]
        paths = [
            report_dir / "dados_empenhos.json",
            report_dir / "metadados.json",
            result["caminho_relatorio"],
        ]
        snapshot = [path.read_bytes() for path in paths]

        coleta_patch, etapa2_patch = self._patch_pipeline(
            etapa2=RuntimeError("falha da etapa 2"),
        )
        with patch(
            "pncp_tracker.report_service.baixar_dados_compra_pncp",
            return_value=dict(self.purchase),
        ), coleta_patch, etapa2_patch:
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
