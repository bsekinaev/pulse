"""ПУЛЬС — веб-интерфейс сбора обратной связи новичков."""
import hmac
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.db import Base, make_session_factory
from app.models import CheckIn, Employee, Issue
from app.services.onboarding import (
    CATEGORY_NAMES, InvalidAnswers, AlreadyResolved,
    dashboard_counts, resolve_issue, submit_checkin,
)
from scripts.seed_demo import seed_demo
from app.services.filters import filter_employees
from app.services.metrics import (
    format_minsk, is_issue_overdue, minsk_today,
    operational_metrics, resolution_label,
)
from app.security import (
    blocked_seconds, client_source, create_admin_session, register_failed_login,
    reset_failed_logins, revoke_admin_session, source_digest, valid_admin_session,
    parse_trusted_proxy_hosts,
)

ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.filters["minsk_datetime"] = format_minsk


def create_app(
    database_url: str | None = None,
    secret_key: str | None = None,
    admin_password: str | None = None,
    seed: bool = True,
) -> FastAPI:
    """Создаёт изолированное приложение для демо и тестов."""
    production = os.getenv("APP_ENV") == "production"
    secret = secret_key or os.getenv("APP_SECRET_KEY") or "local-dev-secret-not-for-production"
    password = admin_password or os.getenv("ADMIN_PASSWORD") or "local-dev-admin"
    username = os.getenv("ADMIN_USERNAME", "admin")
    # Доверяем только конкретному Caddy, а не всей общей Docker-подсети.
    trusted_proxies = parse_trusted_proxy_hosts(
        os.getenv("PULSE_TRUSTED_PROXY_CIDRS", "")
    )
    if production and (len(secret) < 32 or len(password) < 12):
        raise RuntimeError("Для production задайте APP_SECRET_KEY (32+) и ADMIN_PASSWORD (12+)")

    url = database_url or os.getenv("DATABASE_URL", "sqlite:///./pulse.sqlite3")
    engine, session_factory = make_session_factory(url)
    signer = URLSafeTimedSerializer(secret, salt="pulse-checkin-v1")
    # За Caddy схема ASGI-запроса может быть http, хотя клиент использует HTTPS.
    public_base_url = os.getenv("PUBLIC_BASE_URL") or (
        "https://pulse.bsekinaev.ru" if production else ""
    )
    public_base_url = public_base_url.rstrip("/")
    if production and not public_base_url.startswith("https://"):
        raise RuntimeError("PUBLIC_BASE_URL должен использовать HTTPS")


    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Base.metadata.create_all(engine)
        if seed:
            with session_factory() as db:
                seed_demo(db)
        yield
        engine.dispose()

    application = FastAPI(
        title="ПУЛЬС", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan,
    )
    application.add_middleware(
        SessionMiddleware, secret_key=secret, session_cookie="pulse_admin",
        https_only=production, same_site="lax", max_age=4 * 60 * 60,
    )
    application.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    application.state.sessions = session_factory

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        """Добавляет защитные заголовки и отключает кеширование личных страниц."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        if request.url.path.startswith(
            ("/login", "/dashboard", "/employees/", "/issues/", "/checkin/")
        ):
            response.headers["Cache-Control"] = "no-store"
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def get_db():
        with session_factory() as db:
            yield db

    def ensure_csrf(request: Request) -> str:
        if "csrf" not in request.session:
            request.session["csrf"] = secrets.token_urlsafe(24)
        return request.session["csrf"]

    def check_csrf(request: Request, provided: str):
        actual = request.session.get("csrf", "")
        if not actual or not hmac.compare_digest(actual, provided):
            raise HTTPException(status_code=403, detail="Проверка формы не пройдена")

    def require_admin(request: Request, db: Session = Depends(get_db)):
        if not valid_admin_session(db, request.session):
            raise HTTPException(status_code=401, detail="Требуется вход администратора")

    def token_employee(token: str, db: Session) -> Employee:
        try:
            data = signer.loads(token, max_age=7 * 24 * 60 * 60)
            if not isinstance(data, dict) or data.get("day") != 3:
                raise BadSignature("Неверная контрольная точка")
            employee_id = int(data["employee_id"])
        except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
            raise HTTPException(status_code=404, detail="Ссылка недействительна или устарела")
        employee = db.get(Employee, employee_id)
        if employee is None:
            raise HTTPException(status_code=404, detail="Сотрудник не найден")
        return employee

    @application.get("/")
    def index(request: Request, db: Session = Depends(get_db)):
        target = "/dashboard" if valid_admin_session(db, request.session) else "/login"
        return RedirectResponse(target, status_code=303)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/login")
    def login_form(request: Request):
        return templates.TemplateResponse(request, "login.html", {
            "csrf": ensure_csrf(request), "error": None,
        })

    @application.post("/login")
    def login(
        request: Request, username_input: str = Form(alias="username"),
        password_input: str = Form(alias="password"), csrf: str = Form(),
        db: Session = Depends(get_db),
    ):
        check_csrf(request, csrf)
        source = client_source(request, trusted_proxies)
        key = source_digest(source, secret)
        wait_seconds = blocked_seconds(db, key)
        if wait_seconds:
            return HTMLResponse(
                "Слишком много попыток входа. Повторите позже.",
                status_code=429, headers={"Retry-After": str(wait_seconds)},
            )

        # Оба сравнения выполняются независимо от правильности логина.
        valid_username = hmac.compare_digest(username_input, username)
        valid_password = hmac.compare_digest(password_input, password)
        if not (valid_username & valid_password):
            register_failed_login(db, key)
            return templates.TemplateResponse(request, "login.html", {
                "csrf": ensure_csrf(request), "error": "Неверный логин или пароль",
            }, status_code=401)
        reset_failed_logins(db, key)
        session_token = create_admin_session(db)
        request.session.clear()
        request.session["admin"] = True
        request.session["sid"] = session_token
        request.session["csrf"] = secrets.token_urlsafe(24)
        return RedirectResponse("/dashboard", status_code=303)

    @application.post("/logout")
    def logout(
        request: Request, csrf: str = Form(),
        db: Session = Depends(get_db), _: None = Depends(require_admin),
    ):
        check_csrf(request, csrf)
        revoke_admin_session(db, request.session)
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @application.get("/dashboard")
    def dashboard(request: Request, db: Session = Depends(get_db), _: None = Depends(require_admin)):
        people = db.scalars(select(Employee)).all()
        checkins = {c.employee_id for c in db.scalars(select(CheckIn)).all()}
        issues = db.scalars(select(Issue).where(Issue.status == "open").order_by(Issue.created_at)).all()
        open_counts: dict[int, int] = {}
        for issue in issues:
            open_counts[issue.employee_id] = open_counts.get(issue.employee_id, 0) + 1
        people.sort(key=lambda person: (-open_counts.get(person.id, 0), person.name))
        today = minsk_today()
        departments = sorted({person.department for person in people})
        query = request.query_params.get("q", "").strip()[:80]
        department = request.query_params.get("department", "").strip()[:40]
        state = request.query_params.get("status", "all")
        if state not in ("all", "needs_help", "answered", "awaiting", "not_due"):
            state = "all"
        filtered = filter_employees(
            people, checkins, open_counts, today,
            query=query, department=department, state=state,
        )
        metrics = operational_metrics(db)
        return templates.TemplateResponse(request, "dashboard.html", {
            "people": filtered, "checkins": checkins, "open_counts": open_counts,
            "issues": issues, "counts": dashboard_counts(db), "csrf": ensure_csrf(request),
            "today": today, "category_names": CATEGORY_NAMES,
            "metrics": metrics, "total_people": len(people),
            "departments": departments, "query": query, "department": department,
            "selected_status": state,
            "resolution_label": resolution_label(metrics["average_resolution_minutes"]),
        })

    @application.get("/employees/{employee_id}")
    def employee_detail(
        employee_id: int, request: Request, db: Session = Depends(get_db),
        _: None = Depends(require_admin),
    ):
        employee = db.get(Employee, employee_id)
        if employee is None:
            raise HTTPException(status_code=404, detail="Сотрудник не найден")
        checkin = db.scalar(select(CheckIn).where(CheckIn.employee_id == employee_id))
        issues = db.scalars(select(Issue).where(Issue.employee_id == employee_id)).all()
        token = signer.dumps({"employee_id": employee.id, "day": 3})
        return templates.TemplateResponse(request, "employee.html", {
            "employee": employee, "checkin": checkin, "issues": issues,
            "checkin_url": (f"{public_base_url}/checkin/{token}" if public_base_url
                            else str(request.url_for("checkin_form", token=token))),
            "day": max(1, (minsk_today() - employee.start_date).days + 1),
            "category_names": CATEGORY_NAMES, "csrf": ensure_csrf(request),
        })

    @application.get("/checkin/{token}")
    def checkin_form(token: str, request: Request, db: Session = Depends(get_db)):
        employee = token_employee(token, db)
        checkin = db.scalar(select(CheckIn).where(
            CheckIn.employee_id == employee.id, CheckIn.checkpoint_day == 3,
        ))
        if checkin:
            return RedirectResponse(f"/checkin/{token}/done", status_code=303)
        return templates.TemplateResponse(request, "checkin.html", {
            "employee": employee, "token": token, "error": None,
        })

    @application.post("/checkin/{token}")
    def checkin_submit(
        token: str, request: Request,
        equipment: str = Form(), instructions: str = Form(),
        support: str = Form(), comment: str = Form(""),
        db: Session = Depends(get_db),
    ):
        employee = token_employee(token, db)
        try:
            submit_checkin(db, employee, {
                "equipment": equipment, "instructions": instructions, "support": support,
            }, comment)
        except InvalidAnswers as exc:
            return templates.TemplateResponse(request, "checkin.html", {
                "employee": employee, "token": token, "error": str(exc),
            }, status_code=422)
        return RedirectResponse(f"/checkin/{token}/done", status_code=303)

    @application.get("/checkin/{token}/done")
    def checkin_done(token: str, request: Request, db: Session = Depends(get_db)):
        employee = token_employee(token, db)
        checkin = db.scalar(select(CheckIn).where(
            CheckIn.employee_id == employee.id, CheckIn.checkpoint_day == 3,
        ))
        if checkin is None:
            return RedirectResponse(f"/checkin/{token}", status_code=303)
        return templates.TemplateResponse(request, "done.html", {"employee": employee})

    @application.get("/issues/{issue_id}")
    def issue_detail(
        issue_id: int, request: Request, db: Session = Depends(get_db),
        _: None = Depends(require_admin),
    ):
        issue = db.get(Issue, issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="Проблема не найдена")
        return templates.TemplateResponse(request, "issue.html", {
            "issue": issue, "category_names": CATEGORY_NAMES,
            "csrf": ensure_csrf(request), "error": None,
            "overdue": is_issue_overdue(issue),
        })

    @application.post("/issues/{issue_id}/resolve")
    def issue_resolve(
        issue_id: int, request: Request, resolution: str = Form(),
        csrf: str = Form(), db: Session = Depends(get_db),
        _: None = Depends(require_admin),
    ):
        check_csrf(request, csrf)
        issue = db.get(Issue, issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="Проблема не найдена")
        try:
            resolve_issue(db, issue, resolution)
        except (ValueError, AlreadyResolved) as exc:
            return templates.TemplateResponse(request, "issue.html", {
                "issue": issue, "category_names": CATEGORY_NAMES,
                "csrf": ensure_csrf(request), "error": str(exc),
                "overdue": is_issue_overdue(issue),
            }, status_code=409 if isinstance(exc, AlreadyResolved) else 422)
        return RedirectResponse(f"/issues/{issue_id}", status_code=303)

    return application


app = create_app()
