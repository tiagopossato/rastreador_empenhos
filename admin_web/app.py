import logging
import os
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Tuple

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from admin_web.auth import load_users, validate_users_path, verify_password
from admin_web.auth import hash_password
from pncp_tracker.report_registry import (
    INDEX_PATH,
    REPORTS_DIR,
    adicionar_registro,
    ler_registros,
    remover_registro,
)
from pncp_tracker.process_lock import interprocess_lock, lock_path_for


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_USERS_FILE = _PROJECT_ROOT / ".private" / "usuarios.json"
_LOGGER = logging.getLogger(__name__)


class LoginAttemptLimiter:
    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: int = 600,
        lockout_seconds: int = 600,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._lock = threading.Lock()
        self._attempts: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._blocked_until: Dict[Tuple[str, str], float] = {}

    def is_blocked(self, key: Tuple[str, str]) -> bool:
        now = time.monotonic()
        with self._lock:
            blocked_until = self._blocked_until.get(key, 0)
            if blocked_until <= now:
                self._blocked_until.pop(key, None)
                return False
            return True

    def record_failure(self, key: Tuple[str, str]) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            for existing_key, existing_attempts in list(self._attempts.items()):
                while existing_attempts and existing_attempts[0] <= cutoff:
                    existing_attempts.popleft()
                if not existing_attempts:
                    self._attempts.pop(existing_key, None)
            for existing_key, blocked_until in list(self._blocked_until.items()):
                if blocked_until <= now:
                    self._blocked_until.pop(existing_key, None)
            if key not in self._attempts and len(self._attempts) >= 10000:
                self._attempts.pop(next(iter(self._attempts)))
            attempts = self._attempts[key]
            attempts.append(now)
            if len(attempts) >= self.max_attempts:
                self._blocked_until[key] = now + self.lockout_seconds
                attempts.clear()
                return True
            return False

    def clear(self, key: Tuple[str, str]) -> None:
        with self._lock:
            self._attempts.pop(key, None)
            self._blocked_until.pop(key, None)


class JobRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._active_job: Optional[str] = None
        self._latest_job: Optional[str] = None

    def create(self, action: str, url: Optional[str]) -> Optional[str]:
        with self._lock:
            if self._active_job is not None:
                return None
            job_id = uuid.uuid4().hex
            self._active_job = job_id
            self._jobs[job_id] = {
                "id": job_id,
                "status": "executando",
                "acao": action,
                "iniciado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            self._latest_job = job_id
            while len(self._jobs) > 20:
                oldest = next(iter(self._jobs))
                if oldest == self._active_job:
                    break
                self._jobs.pop(oldest)
            return job_id

    def update(self, job_id: str, values: Dict[str, Any]) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(values)

    def complete(self, job_id: str) -> None:
        with self._lock:
            if self._active_job == job_id:
                self._active_job = None

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None

    def latest(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(self._latest_job) if self._latest_job else None
            return dict(job) if job is not None else None


def _csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def _run_job(app: Flask, job_id: str, action: str, url: Optional[str]) -> None:
    from pncp_tracker.report_service import atualizar_processo, atualizar_todos

    registry = app.extensions["pncp_jobs"]

    def report_progress(message: str) -> None:
        _LOGGER.info("Atualização %s: %s", job_id, message)

    _LOGGER.info(
        "Iniciando atualização %s (%s)%s",
        job_id,
        action,
        " — {}".format(url) if url else "",
    )
    try:
        if action == "one":
            if not url:
                raise ValueError("A atualização individual precisa de uma URL PNCP.")
            result = atualizar_processo(
                url,
                reports_dir=Path(app.config["REPORTS_DIR"]),
                index_path=Path(app.config["INDEX_PATH"]),
                on_progress=report_progress,
                cadastrar_se_ausente=False,
            )
            updated = [result["registro"]]
            failures = []
        else:
            result = atualizar_todos(
                reports_dir=Path(app.config["REPORTS_DIR"]),
                index_path=Path(app.config["INDEX_PATH"]),
                on_progress=report_progress,
            )
            updated = result["atualizados"]
            failures = result["falhas"]

        registry.update(
            job_id,
            {
                "status": "concluido_com_falhas" if failures else "concluido",
                "atualizados": len(updated),
                "falhas": failures,
                "finalizado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
        )
        _LOGGER.info(
            "Atualização %s finalizada: %s relatório(s) atualizado(s), %s falha(s).",
            job_id,
            len(updated),
            len(failures),
        )
    except Exception as exc:
        _LOGGER.exception("Falha na atualização %s", job_id)
        registry.update(
            job_id,
            {
                "status": "erro",
                "erro": str(exc),
                "finalizado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
        )
    finally:
        registry.complete(job_id)


def _start_job(app: Flask, action: str, url: Optional[str] = None) -> Optional[str]:
    registry = app.extensions["pncp_jobs"]
    job_id = registry.create(action, url)
    if job_id is None:
        return None
    thread = threading.Thread(
        target=_run_job,
        args=(app, job_id, action, url),
        daemon=True,
    )
    try:
        thread.start()
    except RuntimeError as exc:
        registry.update(job_id, {"status": "erro", "erro": str(exc)})
        registry.complete(job_id)
        raise
    return job_id


def create_app(config: Optional[Dict[str, Any]] = None) -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config.update(
        SECRET_KEY=os.environ.get("PNCP_ADMIN_SESSION_SECRET"),
        USERS_FILE=Path(os.environ.get("PNCP_ADMIN_USERS_FILE", str(_DEFAULT_USERS_FILE))),
        REPORTS_DIR=REPORTS_DIR,
        INDEX_PATH=INDEX_PATH,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("PNCP_ADMIN_COOKIE_SECURE", "1") != "0",
        PERMANENT_SESSION_LIFETIME=8 * 60 * 60,
        LOGIN_MAX_ATTEMPTS=5,
        LOGIN_WINDOW_SECONDS=600,
        LOGIN_LOCKOUT_SECONDS=600,
    )
    if config:
        app.config.update(config)
    app.config["USERS_FILE"] = validate_users_path(
        Path(app.config["USERS_FILE"]),
        Path(app.config["REPORTS_DIR"]),
    )
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("Defina PNCP_ADMIN_SESSION_SECRET antes de iniciar a interface.")
    app.extensions["pncp_jobs"] = JobRegistry()
    app.extensions["pncp_login_attempts"] = LoginAttemptLimiter(
        max_attempts=app.config["LOGIN_MAX_ATTEMPTS"],
        window_seconds=app.config["LOGIN_WINDOW_SECONDS"],
        lockout_seconds=app.config["LOGIN_LOCKOUT_SECONDS"],
    )
    app.extensions["pncp_dummy_password_record"] = hash_password(
        secrets.token_urlsafe(32)
    )

    @app.before_request
    def protect_post_requests():
        token = _csrf_token()
        if request.method == "POST":
            submitted = request.form.get("csrf_token", "")
            if not secrets.compare_digest(token, submitted):
                abort(400, description="Token de formulário inválido ou expirado.")

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": _csrf_token}

    @app.after_request
    def set_cache_policy(response):
        is_public_html = (
            request.method == "GET"
            and response.status_code == 200
            and (request.path == "/" or request.path.lower().endswith(".html"))
        )
        response.headers["Cache-Control"] = (
            "no-cache, must-revalidate" if is_public_html else "no-store"
        )
        return response

    @app.get("/login")
    def login():
        if session.get("username"):
            return redirect(url_for("index"))
        return render_template("login.html")

    @app.post("/login")
    def authenticate():
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        client_ip = request.remote_addr or "unknown"
        attempt_key = (client_ip, username.casefold())
        users = load_users(Path(app.config["USERS_FILE"]))
        record = users.get(username)
        valid_password = verify_password(
            password,
            record if isinstance(record, dict) else app.extensions["pncp_dummy_password_record"],
        )
        limiter = app.extensions["pncp_login_attempts"]
        blocked = limiter.is_blocked(attempt_key)
        if blocked or not valid_password:
            newly_blocked = limiter.record_failure(attempt_key) if not blocked else False
            _LOGGER.warning(
                "Tentativa de autenticação recusada para usuário %r de %s%s",
                username,
                client_ip,
                " (bloqueado temporariamente)" if blocked or newly_blocked else "",
            )
            flash("Usuário ou senha inválidos.", "error")
            return redirect(url_for("login"))
        limiter.clear(attempt_key)
        session.clear()
        session["username"] = username
        session.permanent = True
        _csrf_token()
        return redirect(url_for("index"))

    @app.post("/logout")
    @login_required
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    def public_index():
        index_file = Path(app.config["REPORTS_DIR"]) / "index.html"
        if not index_file.is_file():
            abort(404, description="O índice de relatórios ainda não foi gerado.")
        content = index_file.read_text(encoding="utf-8")
        marker = "<!-- admin-link -->"
        if marker not in content:
            abort(500, description="O índice não contém o local reservado ao acesso administrativo.")
        admin_link = (
            '<a class="admin-link" href="/login" target="_blank" '
            'rel="noopener noreferrer">Administração</a>'
        )
        return app.response_class(
            content.replace(marker, admin_link, 1),
            mimetype="text/html",
        )

    @app.get("/<path:filename>")
    def public_report(filename: str):
        if not filename.lower().endswith(".html"):
            abort(404)
        return send_from_directory(Path(app.config["REPORTS_DIR"]), filename)

    @app.get("/admin")
    @login_required
    def index():
        records = ler_registros(Path(app.config["INDEX_PATH"]))
        active_job = app.extensions["pncp_jobs"].latest()
        return render_template(
            "index.html",
            records=records,
            active_job=active_job,
            username=session["username"],
        )

    @app.post("/processes")
    @login_required
    def add_process():
        url = request.form.get("url_pncp", "")
        index_path = Path(app.config["INDEX_PATH"])
        lock_path = lock_path_for(index_path)
        registro = None
        with interprocess_lock(lock_path):
            try:
                registro = adicionar_registro(url, index_path)
            except ValueError as exc:
                flash(str(exc), "error")
            else:
                from relatorios.gerar_relatorios import gerar_relatorios

                gerar_relatorios(
                    Path(app.config["REPORTS_DIR"]),
                    index_path=index_path,
                )
        if registro is not None:
            job_id = _start_job(app, "one", registro["url_pncp"])
            if job_id is None:
                flash(
                    "Processo cadastrado, mas já existe uma atualização em andamento. "
                    "Atualize este processo depois.",
                    "warning",
                )
            else:
                flash("Processo cadastrado. Atualização iniciada.", "success")
        return redirect(url_for("index"))

    @app.post("/processes/<process_id>/delete")
    @login_required
    def delete_process(process_id: str):
        index_path = Path(app.config["INDEX_PATH"])
        lock_path = lock_path_for(index_path)
        with interprocess_lock(lock_path):
            try:
                removido = remover_registro(process_id, index_path)
            except KeyError:
                flash("Processo não encontrado.", "error")
            else:
                from relatorios.gerar_relatorios import gerar_relatorios

                gerar_relatorios(
                    Path(app.config["REPORTS_DIR"]),
                    index_path=index_path,
                )
                flash(
                    "Processo removido da lista ativa; os dados arquivados foram preservados."
                    if removido.get("pasta")
                    else "Processo removido da lista ativa.",
                    "success",
                )
        return redirect(url_for("index"))

    @app.post("/processes/<process_id>/refresh")
    @login_required
    def refresh_process(process_id: str):
        records = ler_registros(Path(app.config["INDEX_PATH"]))
        record = next((item for item in records if item["id"] == process_id), None)
        if record is None:
            flash("Processo não encontrado.", "error")
        elif _start_job(app, "one", record["url_pncp"]) is None:
            flash("Já existe uma atualização em andamento.", "error")
        else:
            flash("Atualização iniciada.", "success")
        return redirect(url_for("index"))

    @app.post("/processes/refresh-all")
    @login_required
    def refresh_all():
        if _start_job(app, "all") is None:
            flash("Já existe uma atualização em andamento.", "error")
        else:
            flash("Atualização de todos os processos iniciada.", "success")
        return redirect(url_for("index"))

    @app.get("/jobs/<job_id>")
    @login_required
    def job_status(job_id: str):
        job = app.extensions["pncp_jobs"].get(job_id)
        if job is None:
            abort(404)
        return jsonify(job)

    return app
