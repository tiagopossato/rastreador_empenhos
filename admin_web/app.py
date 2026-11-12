import logging
import os
import secrets
import threading
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Dict, Optional

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
from pncp_tracker.report_registry import (
    INDEX_PATH,
    REPORTS_DIR,
    adicionar_registro,
    ler_registros,
    remover_registro,
)
from pncp_tracker.process_lock import interprocess_lock


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_USERS_FILE = _PROJECT_ROOT / ".private" / "usuarios.json"
_LOGGER = logging.getLogger(__name__)
_JOB_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}
_ACTIVE_JOB: Optional[str] = None
_LATEST_JOB: Optional[str] = None


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

        with _JOB_LOCK:
            _JOBS[job_id].update(
                {
                    "status": "concluido_com_falhas" if failures else "concluido",
                    "atualizados": len(updated),
                    "falhas": failures,
                    "finalizado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
                }
            )
        _LOGGER.info(
            "Atualização %s finalizada: %s relatório(s) atualizado(s), %s falha(s).",
            job_id,
            len(updated),
            len(failures),
        )
    except Exception as exc:
        _LOGGER.exception("Falha na atualização %s", job_id)
        with _JOB_LOCK:
            _JOBS[job_id].update(
                {
                    "status": "erro",
                    "erro": str(exc),
                    "finalizado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
                }
            )
    finally:
        global _ACTIVE_JOB
        with _JOB_LOCK:
            if _ACTIVE_JOB == job_id:
                _ACTIVE_JOB = None


def _start_job(app: Flask, action: str, url: Optional[str] = None) -> Optional[str]:
    global _ACTIVE_JOB, _LATEST_JOB
    with _JOB_LOCK:
        if _ACTIVE_JOB is not None:
            return None
        job_id = uuid.uuid4().hex
        _ACTIVE_JOB = job_id
        _JOBS[job_id] = {
            "id": job_id,
            "status": "executando",
            "acao": action,
            "iniciado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        _LATEST_JOB = job_id
        while len(_JOBS) > 20:
            oldest = next(iter(_JOBS))
            if oldest == _ACTIVE_JOB:
                break
            _JOBS.pop(oldest)
        thread = threading.Thread(
            target=_run_job,
            args=(app, job_id, action, url),
            daemon=True,
        )
        thread.start()
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
    )
    if config:
        app.config.update(config)
    app.config["USERS_FILE"] = validate_users_path(
        Path(app.config["USERS_FILE"]),
        Path(app.config["REPORTS_DIR"]),
    )
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("Defina PNCP_ADMIN_SESSION_SECRET antes de iniciar a interface.")

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
    def disable_admin_page_caching(response):
        response.headers["Cache-Control"] = "no-store"
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
        users = load_users(Path(app.config["USERS_FILE"]))
        record = users.get(username)
        if not record or not verify_password(password, record):
            flash("Usuário ou senha inválidos.", "error")
            return redirect(url_for("login"))
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
        with _JOB_LOCK:
            active_job = dict(_JOBS[_LATEST_JOB]) if _LATEST_JOB in _JOBS else None
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
        lock_path = index_path.parent.parent / ".private" / "report_update.lock"
        with interprocess_lock(lock_path):
            try:
                adicionar_registro(url, index_path)
            except ValueError as exc:
                flash(str(exc), "error")
            else:
                from relatorios.gerar_relatorios import gerar_relatorios

                gerar_relatorios(
                    Path(app.config["REPORTS_DIR"]),
                    index_path=index_path,
                )
                flash("Processo cadastrado. Execute a atualização para gerar o relatório.", "success")
        return redirect(url_for("index"))

    @app.post("/processes/<process_id>/delete")
    @login_required
    def delete_process(process_id: str):
        index_path = Path(app.config["INDEX_PATH"])
        lock_path = index_path.parent.parent / ".private" / "report_update.lock"
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
        with _JOB_LOCK:
            job = _JOBS.get(job_id)
            if job is None:
                abort(404)
            return jsonify(job)

    return app
