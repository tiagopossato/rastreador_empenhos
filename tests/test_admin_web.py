import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from admin_web.app import LoginAttemptLimiter, _start_job, create_app
from admin_web.auth import hash_password, save_users, verify_password
import criar_usuario_admin
from pncp_tracker.report_registry import ler_registros, salvar_registros


_URL = "https://pncp.gov.br/app/editais/10635424000186/2025/000282"


class AdminWebTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.reports_dir = root / "relatorios"
        self.index_path = self.reports_dir / "indice_relatorios.json"
        self.reports_dir.mkdir()
        (self.reports_dir / "index.html").write_text(
            '<main><!-- admin-link --></main>',
            encoding="utf-8",
        )
        report_dir = self.reports_dir / "relatorio_compra_90027_2025"
        report_dir.mkdir()
        (report_dir / "relatorio_compra_90027_2025.html").write_text(
            "<html>Relatório público</html>",
            encoding="utf-8",
        )
        (report_dir / "metadados.json").write_text("{}", encoding="utf-8")
        self.users_path = root / "usuarios.json"
        save_users({"admin": hash_password("test-password")}, self.users_path)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "USERS_FILE": self.users_path,
                "REPORTS_DIR": self.reports_dir,
                "INDEX_PATH": self.index_path,
                "SESSION_COOKIE_SECURE": False,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _csrf(self, response):
        match = re.search(
            r'name="csrf_token" value="([^"]+)"',
            response.get_data(as_text=True),
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def _login(self):
        response = self.client.get("/login")
        return self.client.post(
            "/login",
            data={
                "csrf_token": self._csrf(response),
                "username": "admin",
                "password": "test-password",
            },
            follow_redirects=True,
        )

    def test_dashboard_requires_login_and_password_is_verified_from_hash(self):
        public_index = self.client.get("/")
        self.assertEqual(public_index.status_code, 200)
        self.assertEqual(
            public_index.headers["Cache-Control"],
            "no-cache, must-revalidate",
        )
        self.assertIn('href="/login" target="_blank"', public_index.get_data(as_text=True))
        report = self.client.get(
            "/relatorio_compra_90027_2025/relatorio_compra_90027_2025.html"
        )
        self.assertEqual(report.status_code, 200)
        self.assertEqual(
            report.headers["Cache-Control"],
            "no-cache, must-revalidate",
        )
        self.assertIn("Relatório público", report.get_data(as_text=True))
        report.close()
        self.assertEqual(
            self.client.get("/relatorio_compra_90027_2025/metadados.json").status_code,
            404,
        )

        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

        login_page = self.client.get("/login")
        self.assertEqual(login_page.headers["Cache-Control"], "no-store")
        admin_page = self._login()
        self.assertEqual(admin_page.status_code, 200)
        self.assertEqual(admin_page.headers["Cache-Control"], "no-store")
        self.assertIn("Processos PNCP", admin_page.get_data(as_text=True))
        self.assertIn(
            'href="/" target="_blank" rel="noopener noreferrer">Página inicial</a>',
            admin_page.get_data(as_text=True),
        )
        record = json.loads(self.users_path.read_text(encoding="utf-8"))["admin"]
        self.assertNotIn("test-password", json.dumps(record))
        self.assertTrue(verify_password("test-password", record))
        self.assertFalse(verify_password("wrong-password", record))

    def test_crud_is_csrf_protected_and_delete_preserves_archive(self):
        response = self._login()
        token = self._csrf(response)
        with patch("admin_web.app._start_job", return_value="job-1") as start:
            added = self.client.post(
                "/processes",
                data={"csrf_token": token, "url_pncp": _URL},
                follow_redirects=True,
            )
        self.assertIn("Processo cadastrado.", added.get_data(as_text=True))
        self.assertNotIn("Abrir relatório gerado", added.get_data(as_text=True))
        record = ler_registros(self.index_path)[0]
        self.assertEqual(record["status"], "pendente")
        start.assert_called_once_with(self.app, "one", _URL)

        archived_dir = self.reports_dir / "historico"
        archived_dir.mkdir()
        archive_file = archived_dir / "dados_empenhos.json"
        archive_file.write_text("{}", encoding="utf-8")
        record["pasta"] = "historico"
        salvar_registros([record], self.index_path)

        denied = self.client.post("/processes/{}/delete".format(record["id"]))
        self.assertEqual(denied.status_code, 400)
        deleted = self.client.post(
            "/processes/{}/delete".format(record["id"]),
            data={"csrf_token": token},
            follow_redirects=True,
        )
        self.assertIn("arquivados foram preservados", deleted.get_data(as_text=True))
        self.assertEqual(ler_registros(self.index_path), [])
        self.assertTrue(archive_file.exists())

    def test_admin_lists_a_link_to_an_existing_generated_report(self):
        salvar_registros(
            [
                {
                    "id": "processo-teste",
                    "url_pncp": _URL,
                    "pasta": "relatorio_compra_90027_2025",
                    "arquivo_html": "relatorio_compra_90027_2025.html",
                    "status": "atualizado",
                }
            ],
            self.index_path,
        )

        page = self._login()

        self.assertIn(
            'href="/relatorio_compra_90027_2025/relatorio_compra_90027_2025.html"',
            page.get_data(as_text=True),
        )
        self.assertIn("Abrir relatório gerado", page.get_data(as_text=True))

    def test_refresh_action_starts_a_background_update(self):
        response = self._login()
        token = self._csrf(response)
        with patch("admin_web.app._start_job", return_value="job-add"):
            self.client.post(
                "/processes",
                data={"csrf_token": token, "url_pncp": _URL},
            )
        record = ler_registros(self.index_path)[0]
        with patch("admin_web.app._start_job", return_value="job-1") as start:
            result = self.client.post(
                "/processes/{}/refresh".format(record["id"]),
                data={"csrf_token": token},
            )
        self.assertEqual(result.status_code, 302)
        start.assert_called_once_with(self.app, "one", _URL)

    def test_background_job_exposes_completion_status(self):
        with patch(
            "pncp_tracker.report_service.atualizar_processo",
            side_effect=lambda *args, **kwargs: (
                kwargs["on_progress"]("Coletando itens do PNCP.")
                or {"registro": {"url_pncp": _URL}}
            ),
        ), self.assertLogs("admin_web.app", level="INFO") as captured:
            job_id = _start_job(self.app, "one", _URL)
            self.assertIsNotNone(job_id)
            jobs = self.app.extensions["pncp_jobs"]
            for _ in range(100):
                status = jobs.get(job_id)["status"]
                if status != "executando":
                    break
                time.sleep(0.01)

        self.assertEqual(jobs.get(job_id)["status"], "concluido")
        self.assertEqual(jobs.get(job_id)["atualizados"], 1)
        self.assertTrue(
            any("Coletando itens do PNCP." in line for line in captured.output)
        )

    def test_login_attempt_limiter_blocks_and_expires_attempt_keys(self):
        limiter = LoginAttemptLimiter(
            max_attempts=2,
            window_seconds=10,
            lockout_seconds=20,
        )
        key = ("127.0.0.1", "admin")
        with patch("admin_web.app.time.monotonic", return_value=100):
            self.assertFalse(limiter.record_failure(key))
            self.assertTrue(limiter.record_failure(key))
            self.assertTrue(limiter.is_blocked(key))
        with patch("admin_web.app.time.monotonic", return_value=121):
            self.assertFalse(limiter.is_blocked(key))

    def test_login_endpoint_temporarily_blocks_after_repeated_failures(self):
        response = self.client.get("/login")
        token = self._csrf(response)
        for _ in range(5):
            self.client.post(
                "/login",
                data={
                    "csrf_token": token,
                    "username": "admin",
                    "password": "wrong-password",
                },
            )

        blocked = self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "username": "admin",
                "password": "test-password",
            },
            follow_redirects=True,
        )
        self.assertIn("Usuário ou senha inválidos.", blocked.get_data(as_text=True))
        self.assertNotIn("Processos PNCP", blocked.get_data(as_text=True))

    def test_job_registries_are_isolated_between_app_instances(self):
        other_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "USERS_FILE": self.users_path,
                "REPORTS_DIR": self.reports_dir,
                "INDEX_PATH": self.index_path,
                "SESSION_COOKIE_SECURE": False,
            }
        )
        self.assertIsNot(
            self.app.extensions["pncp_jobs"],
            other_app.extensions["pncp_jobs"],
        )

    def test_individual_job_without_url_fails_explicitly(self):
        jobs = self.app.extensions["pncp_jobs"]
        with self.assertLogs("admin_web.app", level="ERROR"):
            job_id = _start_job(self.app, "one")
            for _ in range(100):
                job = jobs.get(job_id)
                if job["status"] != "executando":
                    break
                time.sleep(0.01)

        self.assertEqual(job["status"], "erro")
        self.assertEqual(
            job["erro"],
            "A atualização individual precisa de uma URL PNCP.",
        )

    def test_hash_uses_a_unique_salt(self):
        first = hash_password("test-password")
        second = hash_password("test-password")
        self.assertNotEqual(first["salt"], second["salt"])
        self.assertTrue(verify_password("test-password", first))

    def test_user_database_must_not_live_in_public_reports_directory(self):
        with self.assertRaisesRegex(ValueError, "fora da pasta publicada"):
            create_app(
                {
                    "SECRET_KEY": "test-secret",
                    "USERS_FILE": self.reports_dir / "usuarios.json",
                    "REPORTS_DIR": self.reports_dir,
                    "INDEX_PATH": self.index_path,
                }
            )

    def test_user_creation_script_stores_only_password_hash(self):
        users_file = Path(self.temp_dir.name) / "created_users.json"
        with patch.object(criar_usuario_admin, "_USERS_FILE", users_file), patch(
            "builtins.input", return_value="operator"
        ), patch(
            "criar_usuario_admin.getpass",
            side_effect=["long-test-password", "long-test-password"],
        ):
            result = criar_usuario_admin.main()

        self.assertEqual(result, 0)
        stored = users_file.read_text(encoding="utf-8")
        self.assertNotIn("long-test-password", stored)
        self.assertTrue(verify_password("long-test-password", json.loads(stored)["operator"]))


if __name__ == "__main__":
    unittest.main()
