from __future__ import annotations

import base64
import binascii
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import hmac
import ipaddress
from io import BytesIO
import json
import os
import re
import secrets
import sqlite3
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from flask import Flask, g, jsonify, redirect, render_template, request, send_file, session
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

from support_report import SupportReportError, generate_support_report

ROOT = Path(__file__).resolve().parent
SUPPORT_TEMPLATE = ROOT / "datos" / "formato soporte tecnico.docx"
USER_EQUIPMENT_DATABASE = ROOT / "datos" / "base_usuarios_equipos_octubre_2026.sqlite3"
INVENTORY_DATA = ROOT / "datos" / "inventario_equipos.json"
STATUSES = {"Abierto", "En Proceso", "En Espera", "Resuelto", "Cancelado"}


def load_site_config() -> dict[str, Any]:
    path = Path(os.environ.get("HELPDESK_SITE_CONFIG") or ROOT / "config" / "site_config.json")
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


SITE_CONFIG = load_site_config()
EMAIL_SUFFIX = str(SITE_CONFIG.get("email_suffix") or "@example.org").lower()
PASSWORD_ITERATIONS = 600_000
RATE_LIMIT = 10
RATE_WINDOW_SECONDS = 600
MAX_ATTACHMENTS = 6
MAX_ATTACHMENT_BYTES = 900 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 5 * 1024 * 1024
ALLOWED_ATTACHMENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
LAN_HTTP_ACK = "I_ACCEPT_UNENCRYPTED_LAN_HTTP"
INVENTORY_MONITOR_NETWORK = ipaddress.ip_network(
    str(SITE_CONFIG.get("inventory_network") or "192.0.2.0/24"), strict=False
)
MAX_INVENTORY_MONITOR_TARGETS = 200
CLIENT_BUILD = "2026-10-09-logo-1"
SUPPORT_REPORT_BUILD = "2026-10-09-libreoffice-3"
SLA_MINUTES = {
    "Hardware": {"Baja": 30, "Media": 60, "Alta": 120, "Crítica": 180},
    "Impresoras": {"Baja": 30, "Media": 60, "Alta": 120, "Crítica": 180},
    "Red": {"Baja": 60, "Media": 90, "Alta": 120, "Crítica": 180},
    "Software": {"Baja": 60, "Media": 90, "Alta": 120, "Crítica": 180},
}
DOCUMENT_PAGES = {
    "INDICE_DOCUMENTACION.html",
    "MANUAL_USUARIOS.html",
    "MANUAL_ADMIN_TI.html",
    "MIGRACION_ENTRE_UNIDADES.html",
}
DEFAULT_TAXONOMY = {
    "Hardware": ["Fallo en los perifericos", "Fallo de Almacenamiento (HDD, SSD, NVME)", "Fallo de memoria ram", "Fallo de video GPU", "Fallo de motherboard"],
    "Software": ["Fallo de rendimiento del SO", "Fallo de rendimiento de aplicativos", "Fallo de aplicativos", "Fallo de lectura / escritura de archivos"],
    "Red": ["Fallas en acceso a plataformas institucionales", "Fallo de navegacion web", "Fallo de red local (recursos compartidos, acceso a bases de datos)"],
    "Impresoras": ["Falla en impresion directa o protegida", "Falla en conexion a impresoras o escaner compartidos", "Falla en escaner local"],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ticket_sla(row: sqlite3.Row, *, now: datetime | None = None) -> dict[str, Any]:
    total_minutes = SLA_MINUTES[row["category"]][row["priority"]]
    created_at = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
    current_time = now or datetime.now(timezone.utc)
    elapsed_minutes = max(0, int((current_time - created_at).total_seconds() // 60))
    remaining_minutes = total_minutes - elapsed_minutes
    if row["status"] in {"Resuelto", "Cancelado"}:
        return {
            "targetMinutes": total_minutes,
            "elapsedMinutes": elapsed_minutes,
            "remainingMinutes": max(remaining_minutes, 0),
            "dueAt": (created_at + timedelta(minutes=total_minutes)).isoformat(timespec="seconds"),
            "label": row["status"],
            "class": "sla-ok",
        }
    if remaining_minutes < 0:
        return {
            "targetMinutes": total_minutes,
            "elapsedMinutes": elapsed_minutes,
            "remainingMinutes": 0,
            "dueAt": (created_at + timedelta(minutes=total_minutes)).isoformat(timespec="seconds"),
            "label": f"Vencido hace {-remaining_minutes} min",
            "class": "sla-danger",
        }
    hours, minutes = divmod(remaining_minutes, 60)
    return {
        "targetMinutes": total_minutes,
        "elapsedMinutes": elapsed_minutes,
        "remainingMinutes": remaining_minutes,
        "dueAt": (created_at + timedelta(minutes=total_minutes)).isoformat(timespec="seconds"),
        "label": f"{hours}h {minutes:02d}m",
        "class": "sla-warning" if remaining_minutes <= 30 else "sla-ok",
    }


def probe_inventory_host(address: str) -> dict[str, str]:
    command = ["ping", "-n", "1", "-w", "1000", address] if sys.platform.startswith("win") else [
        "ping", "-c", "1", "-W", "1", address
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "detail": "La comprobación ICMP excedió el tiempo de espera."}
    except OSError as exc:
        return {"status": "error", "detail": f"No fue posible ejecutar la comprobación ICMP: {exc}"}
    if completed.returncode == 0:
        return {"status": "online", "detail": "El equipo respondió a ICMP."}
    return {"status": "offline", "detail": "El equipo no respondió a ICMP."}


NETWORK_PROXIES = (("proxy.example.org", 3128), ("192.0.2.10", 3128))
NETWORK_STATUS_TARGETS: tuple[dict[str, Any], ...] = (
    {"group": "Servidor principal", "name": "Servidor principal", "host": "192.0.2.10", "ports": (445, 80, 443)},
    {"group": "Red", "name": "Proxy (puerto 3128)", "host": "proxy.example.org", "ports": (3128,), "icmp": False, "alt_hosts": ("192.0.2.10",)},
    {"group": "Red", "name": "DNS 1", "host": "192.0.2.10", "ports": (53,)},
    {"group": "Red", "name": "DNS 2", "host": "192.0.2.10", "ports": (53,)},
    {"group": "Red", "name": "Conexión externa", "host": "8.8.8.8", "ports": (443, 53), "external": True, "alt_hosts": ("www.google.com",)},
    {"group": "Aplicativos", "name": "Orfeo 1", "host": "192.0.2.10", "ports": (80, 443)},
    {"group": "Aplicativos", "name": "Orfeo 2", "host": "192.0.2.10", "ports": (80, 443)},
    {"group": "Aplicativos", "name": "Zoho Mail", "host": "mail.zoho.com", "ports": (443,), "external": True},
    {"group": "Aplicativos", "name": "Zoho WorkDrive", "host": "workdrive.zoho.com", "ports": (443,), "external": True},
    {"group": "Aplicativos", "name": "Zoho Cliq", "host": "cliq.zoho.com", "ports": (443,), "external": True},
    {"group": "Aplicativos", "name": "Intranet", "host": "example.org", "ports": (80,)},
    {"group": "Aplicativos", "name": "FOVID", "host": "example.org", "ports": (443,)},
    {"group": "Aplicativos", "name": "SIATH Web", "host": "example.org", "ports": (8449,), "external": True},
)
NETWORK_STATUS_CACHE_SECONDS = 20
_network_status_cache: dict[str, Any] = {"at": 0.0, "payload": None}
_network_status_lock = threading.Lock()


def probe_via_proxy(host: str, port: int) -> bool:
    for proxy in NETWORK_PROXIES:
        try:
            with socket.create_connection(proxy, timeout=2) as connection:
                connection.settimeout(4)
                connection.sendall(
                    f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode("ascii")
                )
                status_line = connection.recv(256).split(b"\r\n", 1)[0].decode("ascii", "replace")
        except (OSError, UnicodeError):
            continue
        parts = status_line.split()
        if len(parts) >= 2 and parts[0].startswith("HTTP/") and parts[1] == "200":
            return True
    return False


def probe_direct_port(host: str, ports: tuple[int, ...]) -> bool:
    for port in ports:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except OSError:
            continue
    return False


def probe_network_target(target: dict[str, Any]) -> dict[str, Any]:
    host = target["host"]
    started = time.monotonic()
    online = False
    detail = "Sin respuesta."
    if target.get("external"):
        if any(probe_via_proxy(h, port) for h in (host, *target.get("alt_hosts", ())) for port in target["ports"]):
            online, detail = True, "Responde a través del proxy 3128."
        elif probe_direct_port(host, target["ports"]):
            online, detail = True, "Responde por conexión directa."
    else:
        try:
            is_ip = bool(ipaddress.ip_address(host))
        except ValueError:
            is_ip = False
        if is_ip and target.get("icmp", True) and probe_inventory_host(host)["status"] == "online":
            online, detail = True, "Responde a ICMP."
        elif probe_direct_port(host, target["ports"]) or any(
            probe_direct_port(alt, target["ports"]) for alt in target.get("alt_hosts", ())
        ):
            online, detail = True, "Responde por TCP."
    return {
        "name": target["name"],
        "group": target["group"],
        "host": host,
        "status": "online" if online else "offline",
        "detail": detail,
        "latencyMs": round((time.monotonic() - started) * 1000) if online else None,
    }


def network_status_snapshot() -> dict[str, Any]:
    with _network_status_lock:
        cached = _network_status_cache["payload"]
        if cached and time.monotonic() - _network_status_cache["at"] < NETWORK_STATUS_CACHE_SECONDS:
            return cached
        with ThreadPoolExecutor(max_workers=len(NETWORK_STATUS_TARGETS)) as executor:
            services = list(executor.map(probe_network_target, NETWORK_STATUS_TARGETS))
        payload = {"checkedAt": utc_now(), "services": services}
        _network_status_cache.update(at=time.monotonic(), payload=payload)
        return payload


def make_password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt_text, digest_text = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.urlsafe_b64decode(salt_text.encode("ascii")),
            int(rounds),
        )
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def validate_lan_http_binding(host: str, acknowledgement: str, secret_key: str, secure_cookie: bool) -> str:
    if acknowledgement != LAN_HTTP_ACK:
        raise RuntimeError("Para exponer HTTP en LAN, configure HELPDESK_LAN_HTTP_ACK explícitamente")
    if not secret_key:
        raise RuntimeError("HELPDESK_SECRET_KEY persistente es obligatoria para el modo LAN")
    if secure_cookie:
        raise RuntimeError("HTTP LAN requiere HELPDESK_COOKIE_SECURE=0; no use cookies Secure sin TLS")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise RuntimeError("HELPDESK_HOST debe ser la IP privada específica de la interfaz LAN") from exc
    if not isinstance(address, ipaddress.IPv4Address) or not address.is_private or address.is_loopback or address.is_unspecified:
        raise RuntimeError("HELPDESK_HOST debe ser una IPv4 privada específica, no localhost ni una IP comodín")
    return str(address)


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, static_folder=None, template_folder="templates")
    data_dir = Path(os.environ.get("HELPDESK_DATA_DIR", ROOT / "instance"))
    app.config.update(
        SECRET_KEY=os.environ.get("HELPDESK_SECRET_KEY") or secrets.token_hex(32),
        DATABASE=str(data_dir / "helpdesk.sqlite3"),
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=os.environ.get("HELPDESK_COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=8 * 60 * 60,
    )
    if test_config:
        app.config.update(test_config)

    if os.environ.get("HELPDESK_TRUSTED_PROXY") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

    if os.environ.get("HELPDESK_ENV") == "production":
        if not os.environ.get("HELPDESK_SECRET_KEY"):
            raise RuntimeError("HELPDESK_SECRET_KEY es obligatorio en producción")
        if not app.config["SESSION_COOKIE_SECURE"]:
            raise RuntimeError("Configure HTTPS y HELPDESK_COOKIE_SECURE=1 en producción")

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)

    def connect_db() -> sqlite3.Connection:
        connection = sqlite3.connect(app.config["DATABASE"], timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def init_db() -> None:
        with closing(connect_db()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'technician')),
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    origin TEXT NOT NULL,
                    client_name TEXT NOT NULL,
                    client_user TEXT NOT NULL,
                    requester_email TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    work_location TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL,
                    subcategory TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    priority TEXT NOT NULL DEFAULT 'Media',
                    status TEXT NOT NULL DEFAULT 'Abierto',
                    assignee TEXT NOT NULL DEFAULT 'Sin Asignar',
                    closure_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ticket_events (
                    id INTEGER PRIMARY KEY,
                    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                    username TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ticket_attachments (
                    id INTEGER PRIMARY KEY,
                    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    content BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS support_reports (
                    ticket_id INTEGER PRIMARY KEY REFERENCES tickets(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    report_build TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS intake_limits (
                    client_key TEXT PRIMARY KEY,
                    window_start INTEGER NOT NULL,
                    request_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ticket_categories (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS ticket_subcategories (
                    id INTEGER PRIMARY KEY,
                    category_id INTEGER NOT NULL REFERENCES ticket_categories(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(category_id, name)
                );
                CREATE TABLE IF NOT EXISTS knowledge_articles (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category_id INTEGER REFERENCES ticket_categories(id) ON DELETE SET NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dashboard_state (
                    state_key TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_tickets_status_created
                    ON tickets(status, created_at);
                CREATE INDEX IF NOT EXISTS ix_ticket_events_ticket
                    ON ticket_events(ticket_id, id);
                CREATE INDEX IF NOT EXISTS ix_ticket_attachments_ticket
                    ON ticket_attachments(ticket_id, id);
                """
            )
            ticket_columns = {row["name"] for row in connection.execute("PRAGMA table_info(tickets)")}
            if "work_location" not in ticket_columns:
                connection.execute("ALTER TABLE tickets ADD COLUMN work_location TEXT NOT NULL DEFAULT ''")
            if "closure_note" not in ticket_columns:
                connection.execute("ALTER TABLE tickets ADD COLUMN closure_note TEXT NOT NULL DEFAULT ''")
            report_columns = {row["name"] for row in connection.execute("PRAGMA table_info(support_reports)")}
            if "report_build" not in report_columns:
                connection.execute("ALTER TABLE support_reports ADD COLUMN report_build TEXT NOT NULL DEFAULT ''")
            if connection.execute("SELECT COUNT(*) FROM ticket_categories").fetchone()[0] == 0:
                for category, subcategories in DEFAULT_TAXONOMY.items():
                    cursor = connection.execute("INSERT INTO ticket_categories(name) VALUES (?)", (category,))
                    connection.executemany(
                        "INSERT INTO ticket_subcategories(category_id, name) VALUES (?, ?)",
                        [(cursor.lastrowid, subcategory) for subcategory in subcategories],
                    )
                connection.executemany(
                    "INSERT INTO knowledge_articles(title, content, category_id, updated_at) VALUES (?, ?, ?, ?)",
                    [
                        ("Verifique conexiones antes de reportar", "Revise energía, cables y reinicie el equipo una vez antes de crear el ticket.", None, utc_now()),
                        ("Capturas de pantalla", "Adjunte una captura del mensaje de error, sin incluir contraseñas ni información clasificada.", None, utc_now()),
                    ],
                )
            connection.commit()

    def db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = connect_db()
        return g.db

    @app.teardown_appcontext
    def close_db(_error: BaseException | None) -> None:
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    def csrf_token() -> str:
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    def require_csrf() -> bool:
        supplied = request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        return bool(supplied and expected and hmac.compare_digest(supplied, expected))

    def require_admin() -> tuple[Any, int] | None:
        user_id = session.get("user_id")
        if not user_id:
            return jsonify(error="Autenticación requerida"), 401
        row = db().execute("SELECT username, role, active FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None or not row["active"] or row["role"] not in {"admin", "technician"}:
            session.clear()
            return jsonify(error="Sesión inválida"), 401
        return None

    def portal_config() -> dict[str, Any]:
        categories = db().execute("SELECT id, name FROM ticket_categories WHERE active = 1 ORDER BY name").fetchall()
        return {
            "categories": [
                {
                    "id": category["id"],
                    "name": category["name"],
                    "subcategories": [
                        {"id": row["id"], "name": row["name"]}
                        for row in db().execute(
                            "SELECT id, name FROM ticket_subcategories WHERE category_id = ? AND active = 1 ORDER BY name",
                            (category["id"],),
                        ).fetchall()
                    ],
                }
                for category in categories
            ],
            "knowledge": [
                {"id": row["id"], "title": row["title"], "content": row["content"], "category": row["category"] or "General"}
                for row in db().execute(
                    """
                    SELECT a.id, a.title, a.content, c.name AS category
                    FROM knowledge_articles a
                    LEFT JOIN ticket_categories c ON c.id = a.category_id
                    WHERE a.active = 1
                    ORDER BY a.id DESC
                    """
                ).fetchall()
            ],
        }

    def ticket_json(row: sqlite3.Row) -> dict[str, Any]:
        ticket_id = row["id"]
        sla = ticket_sla(row)
        events = db().execute(
            "SELECT username, event_type, message, created_at FROM ticket_events WHERE ticket_id = ? ORDER BY id",
            (ticket_id,),
        ).fetchall()
        timeline = [
            {"time": event["created_at"], "user": event["username"], "text": event["message"]}
            for event in events
        ]
        attachments = db().execute(
            "SELECT id, filename, mime_type, byte_size FROM ticket_attachments WHERE ticket_id = ? ORDER BY id",
            (ticket_id,),
        ).fetchall()
        report = db().execute(
            "SELECT filename, generated_at FROM support_reports WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()
        return {
            "dbId": ticket_id,
            "id": row["code"],
            "title": row["title"],
            "category": row["category"],
            "subcategory": row["subcategory"],
            "requester": f"{row['client_name']} ({row['client_user']})",
            "requesterEmail": row["requester_email"],
            "clientName": row["client_name"],
            "clientUser": row["client_user"],
            "asset": row["asset"],
            "workLocation": row["work_location"],
            "priority": row["priority"],
            "status": row["status"],
            "closureNote": row["closure_note"],
            "sla": sla["label"],
            "slaClass": sla["class"],
            "slaTargetMinutes": sla["targetMinutes"],
            "slaDueAt": sla["dueAt"],
            "assignee": row["assignee"],
            "description": row["description"],
            "origin": row["origin"],
            "createdAt": row["created_at"],
            "timeline": timeline,
            "attachments": [
                {
                    "id": attachment["id"],
                    "name": attachment["filename"],
                    "type": attachment["mime_type"],
                    "size": f"{attachment['byte_size'] / 1024:.0f} KB",
                    "url": f"/api/tickets/{ticket_id}/attachments/{attachment['id']}",
                }
                for attachment in attachments
            ],
            "supportReport": (
                {
                    "generated": True,
                    "generatedAt": report["generated_at"],
                    "url": f"/api/tickets/{ticket_id}/support-report",
                }
                if report
                else None
            ),
        }

    def generate_ticket_support_report(ticket: sqlite3.Row) -> dict[str, Any]:
        report_directory = Path(app.config["DATABASE"]).parent / "support_reports"
        filename = generate_support_report(
            ticket,
            template_path=SUPPORT_TEMPLATE,
            output_directory=report_directory,
            inventory_db=USER_EQUIPMENT_DATABASE,
            inventory_json=INVENTORY_DATA,
        ).name
        db().execute(
            """
            INSERT INTO support_reports(ticket_id, filename, generated_at, report_build) VALUES (?, ?, ?, ?)
            ON CONFLICT(ticket_id) DO UPDATE SET filename = excluded.filename, generated_at = excluded.generated_at,
                report_build = excluded.report_build
            """,
            (ticket["id"], filename, utc_now(), SUPPORT_REPORT_BUILD),
        )
        db().commit()
        return {
            "generated": True,
            "url": f"/api/tickets/{ticket['id']}/support-report",
        }

    def parse_attachments(payload: dict[str, Any]) -> list[tuple[str, str, bytes]] | tuple[dict[str, str], int]:
        attachments = payload.get("attachments", [])
        if attachments is None:
            return []
        if not isinstance(attachments, list):
            return {"error": "Los adjuntos deben enviarse como una lista."}, 400
        if len(attachments) > MAX_ATTACHMENTS:
            return {"error": f"Máximo {MAX_ATTACHMENTS} imágenes adjuntas por ticket."}, 400

        parsed: list[tuple[str, str, bytes]] = []
        total_bytes = 0
        for index, attachment in enumerate(attachments, 1):
            if not isinstance(attachment, dict):
                return {"error": f"Adjunto {index} inválido."}, 400
            filename = str(attachment.get("name", "")).strip()
            mime_type = str(attachment.get("type", "")).strip().lower()
            data_url = str(attachment.get("dataUrl", ""))
            if not filename or len(filename) > 200 or mime_type not in ALLOWED_ATTACHMENT_TYPES:
                return {"error": f"Adjunto {index} debe ser una imagen JPEG, PNG o WebP válida."}, 400
            prefix = f"data:{mime_type};base64,"
            if not data_url.startswith(prefix):
                return {"error": f"Contenido inválido para el adjunto {index}."}, 400
            try:
                content = base64.b64decode(data_url[len(prefix):], validate=True)
            except (binascii.Error, ValueError):
                return {"error": f"Contenido codificado inválido para el adjunto {index}."}, 400
            if not content or len(content) > MAX_ATTACHMENT_BYTES:
                return {"error": f"El adjunto {index} excede el límite de 900 KB."}, 400
            total_bytes += len(content)
            if total_bytes > MAX_TOTAL_ATTACHMENT_BYTES:
                return {"error": "El total de imágenes excede el límite de 5 MB."}, 400
            parsed.append((filename, mime_type, content))
        return parsed

    @app.after_request
    def security_headers(response: Any) -> Any:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
        if os.environ.get("HELPDESK_ENV") == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(_error: RequestEntityTooLarge) -> tuple[Any, int]:
        return jsonify(error="La solicitud excede el límite de 8 MB."), 413

    @app.get("/")
    def index() -> Any:
        return send_file(ROOT / "index.html")

    @app.get("/assets/logo-baint")
    def logo_baint() -> Any:
        logo = ROOT / "datos" / "LOGO BAINT.ico"
        if not logo.is_file():
            return jsonify(error="Logo no disponible"), 404
        return send_file(logo, mimetype="image/x-icon", max_age=3600)

    @app.get("/docs/<path:page>")
    def documentation_page(page: str) -> Any:
        if page not in DOCUMENT_PAGES:
            return jsonify(error="Documento no encontrado"), 404
        return send_file(ROOT / "docs" / page, mimetype="text/html")

    @app.get("/login")
    def login_page() -> Any:
        return render_template("login.html", csrf=csrf_token())

    @app.get("/admin")
    def admin_page() -> Any:
        if require_admin() is not None:
            return redirect("/login")
        return send_file(ROOT / "mockup_helpdesk.html")

    @app.get("/api/session")
    def current_session() -> Any:
        denied = require_admin()
        if denied:
            return denied
        row = db().execute("SELECT username, role FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        return jsonify(username=row["username"], role=row["role"], csrf=csrf_token())

    @app.get("/api/portal-config")
    def get_portal_config() -> Any:
        return jsonify(portal_config())

    @app.get("/api/client-build")
    def client_build() -> Any:
        return jsonify(build=CLIENT_BUILD)

    @app.get("/api/portal/ticket-queue")
    def portal_ticket_queue() -> Any:
        rows = db().execute(
            """
            SELECT id, code, created_at, status,             assignee, category, priority,
                               client_name, asset
                        FROM tickets
                        WHERE status NOT IN ('Resuelto', 'Cancelado')
            ORDER BY created_at ASC, id ASC
            """
        ).fetchall()
        return jsonify(
            updatedAt=utc_now(),
            tickets=[
                {
                    "turn": index,
                    "code": row["code"],
                    "startedAt": row["created_at"],
                    "status": row["status"],
                    "assignee": row["assignee"],
                    "requesterName": row["client_name"],
                    "dependency": row["asset"],
                    "sla": ticket_sla(row)["label"],
                    "slaClass": ticket_sla(row)["class"],
                }
                for index, row in enumerate(rows, start=1)
            ],
        )

    @app.get("/api/portal/network-status")
    def portal_network_status() -> Any:
        return jsonify(network_status_snapshot())

    @app.get("/api/admin/dashboard-state")
    def get_dashboard_state() -> Any:
        denied = require_admin()
        if denied:
            return denied
        return jsonify(
            {
                row["state_key"]: json.loads(row["state_json"])
                for row in db().execute("SELECT state_key, state_json FROM dashboard_state").fetchall()
            }
        )

    @app.put("/api/admin/dashboard-state/<state_key>")
    def save_dashboard_state(state_key: str) -> Any:
        denied = require_admin()
        if denied:
            return denied
        if not require_csrf():
            return jsonify(error="Solicitud inválida"), 400
        if state_key not in {
            "inventory",
            "agents",
            "system_users",
            "dependencies",
            "network_config",
            "email_log",
        }:
            return jsonify(error="Estado no permitido"), 404
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify(error="Se esperaba JSON"), 400
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 8 * 1024 * 1024:
            return jsonify(error="El estado excede el límite de 8 MB"), 413
        db().execute(
            """
            INSERT INTO dashboard_state(state_key, state_json, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(state_key) DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at
            """,
            (state_key, encoded, utc_now()),
        )
        db().commit()
        return jsonify(ok=True)

    @app.post("/api/admin/inventory-monitor")
    def monitor_inventory() -> Any:
        denied = require_admin()
        if denied:
            return denied
        if not require_csrf():
            return jsonify(error="Solicitud inválida"), 400
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("assets"), list):
            return jsonify(error="Se esperaba una lista de equipos para monitorear."), 400
        assets = payload["assets"]
        if not assets or len(assets) > MAX_INVENTORY_MONITOR_TARGETS:
            return jsonify(error=f"Seleccione entre 1 y {MAX_INVENTORY_MONITOR_TARGETS} equipos para monitorear."), 400

        targets: list[tuple[int | str, str]] = []
        for asset in assets:
            if not isinstance(asset, dict):
                return jsonify(error="Cada equipo a monitorear debe ser un objeto válido."), 400
            asset_id = asset.get("id")
            if not isinstance(asset_id, (int, str)) or isinstance(asset_id, bool):
                return jsonify(error="Cada equipo debe incluir un identificador válido."), 400
            raw_address = str(asset.get("ip", "")).strip()
            try:
                address = ipaddress.ip_address(raw_address)
            except ValueError:
                return jsonify(error=f"La IP '{raw_address}' no es válida."), 400
            if address.version != 4 or address not in INVENTORY_MONITOR_NETWORK:
                return jsonify(error=f"La IP '{raw_address}' está fuera de la red de inventario autorizada."), 400
            normalized_address = str(address)
            targets.append((asset_id, normalized_address))

        with ThreadPoolExecutor(max_workers=min(20, len(targets))) as executor:
            futures_by_address = {
                address: executor.submit(probe_inventory_host, address)
                for address in {address for _, address in targets}
            }
            results = [
                {"id": asset_id, "ip": address, **futures_by_address[address].result()}
                for asset_id, address in targets
            ]
        return jsonify(checkedAt=utc_now(), results=results)

    def parse_ticket_cutoff(value: str) -> str | tuple[dict[str, str], int]:
        try:
            cutoff = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return {"error": "Fecha y hora de corte inválidas."}, 400
        if cutoff.tzinfo is None:
            return {"error": "La fecha y hora de corte debe incluir zona horaria."}, 400
        return cutoff.astimezone(timezone.utc).isoformat(timespec="seconds")

    @app.route("/api/admin/tickets-before", methods=["GET", "DELETE"])
    def tickets_before() -> Any:
        denied = require_admin()
        if denied:
            return denied
        cutoff = parse_ticket_cutoff(request.args.get("before", ""))
        if isinstance(cutoff, tuple):
            return jsonify(*cutoff)
        if request.method == "GET":
            count = db().execute("SELECT COUNT(*) FROM tickets WHERE created_at < ?", (cutoff,)).fetchone()[0]
            return jsonify(count=count, before=cutoff)
        if not require_csrf():
            return jsonify(error="Solicitud inválida"), 400
        payload = request.get_json(silent=True) or {}
        if payload.get("confirm") is not True:
            return jsonify(error="Confirme explícitamente la eliminación."), 400
        cursor = db().execute("DELETE FROM tickets WHERE created_at < ?", (cutoff,))
        db().commit()
        app.logger.warning("Usuario %s eliminó %s tickets anteriores a %s", session["username"], cursor.rowcount, cutoff)
        return jsonify(deleted=cursor.rowcount, before=cutoff)

    @app.delete("/api/admin/tickets/<int:ticket_id>")
    def delete_ticket(ticket_id: int) -> Any:
        denied = require_admin()
        if denied:
            return denied
        if not require_csrf():
            return jsonify(error="Solicitud inválida"), 400
        payload = request.get_json(silent=True) or {}
        if payload.get("confirm") is not True:
            return jsonify(error="Confirme explícitamente la eliminación."), 400
        row = db().execute("SELECT code FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            return jsonify(error="Ticket no encontrado"), 404
        db().execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
        db().commit()
        app.logger.warning("Usuario %s eliminó selectivamente el ticket %s", session["username"], row["code"])
        return jsonify(deleted=1, ticket=row["code"])

    @app.route("/api/admin/knowledge", methods=["GET", "POST"])
    def knowledge_endpoint() -> Any:
        denied = require_admin()
        if denied:
            return denied
        if request.method == "GET":
            return jsonify(portal_config())
        if not require_csrf():
            return jsonify(error="Solicitud inválida"), 400
        payload = request.get_json(silent=True) or {}
        title, content = str(payload.get("title", "")).strip(), str(payload.get("content", "")).strip()
        category_id = payload.get("categoryId")
        if not title or not content or len(title) > 160 or len(content) > 4000:
            return jsonify(error="Título o contenido inválido"), 400
        if category_id is not None and db().execute("SELECT 1 FROM ticket_categories WHERE id = ?", (category_id,)).fetchone() is None:
            return jsonify(error="Categoría no encontrada"), 400
        db().execute("INSERT INTO knowledge_articles(title, content, category_id, updated_at) VALUES (?, ?, ?, ?)", (title, content, category_id, utc_now()))
        db().commit()
        return jsonify(portal_config()), 201

    @app.route("/api/admin/knowledge/<int:article_id>", methods=["PUT", "DELETE"])
    def knowledge_item(article_id: int) -> Any:
        denied = require_admin()
        if denied:
            return denied
        if not require_csrf():
            return jsonify(error="Solicitud inválida"), 400
        if request.method == "DELETE":
            db().execute("DELETE FROM knowledge_articles WHERE id = ?", (article_id,))
        else:
            payload = request.get_json(silent=True) or {}
            title, content = str(payload.get("title", "")).strip(), str(payload.get("content", "")).strip()
            if not title or not content or len(title) > 160 or len(content) > 4000:
                return jsonify(error="Título o contenido inválido"), 400
            db().execute("UPDATE knowledge_articles SET title = ?, content = ?, updated_at = ? WHERE id = ?", (title, content, utc_now(), article_id))
        db().commit()
        return jsonify(portal_config())

    @app.route("/api/admin/categories", methods=["POST"])
    def create_category() -> Any:
        denied = require_admin()
        if denied:
            return denied
        if not require_csrf():
            return jsonify(error="Solicitud inválida"), 400
        name = str((request.get_json(silent=True) or {}).get("name", "")).strip()
        if not name or len(name) > 80:
            return jsonify(error="Nombre de categoría inválido"), 400
        try:
            db().execute("INSERT INTO ticket_categories(name) VALUES (?)", (name,))
            db().commit()
        except sqlite3.IntegrityError:
            return jsonify(error="La categoría ya existe"), 409
        return jsonify(portal_config()), 201

    @app.route("/api/admin/categories/<int:category_id>", methods=["PUT", "DELETE"])
    def category_item(category_id: int) -> Any:
        denied = require_admin()
        if denied:
            return denied
        if not require_csrf():
            return jsonify(error="Solicitud inválida"), 400
        if request.method == "DELETE":
            db().execute("DELETE FROM ticket_categories WHERE id = ?", (category_id,))
        else:
            name = str((request.get_json(silent=True) or {}).get("name", "")).strip()
            if not name or len(name) > 80:
                return jsonify(error="Nombre de categoría inválido"), 400
            db().execute("UPDATE ticket_categories SET name = ? WHERE id = ?", (name, category_id))
        db().commit()
        return jsonify(portal_config())

    @app.route("/api/admin/categories/<int:category_id>/subcategories", methods=["POST"])
    def create_subcategory(category_id: int) -> Any:
        denied = require_admin()
        if denied:
            return denied
        if not require_csrf():
            return jsonify(error="Solicitud inválida"), 400
        name = str((request.get_json(silent=True) or {}).get("name", "")).strip()
        if not name or len(name) > 160:
            return jsonify(error="Nombre de tipo de falla inválido"), 400
        try:
            db().execute("INSERT INTO ticket_subcategories(category_id, name) VALUES (?, ?)", (category_id, name))
            db().commit()
        except sqlite3.IntegrityError:
            return jsonify(error="El tipo de falla ya existe"), 409
        return jsonify(portal_config()), 201

    @app.route("/api/admin/subcategories/<int:subcategory_id>", methods=["PUT", "DELETE"])
    def subcategory_item(subcategory_id: int) -> Any:
        denied = require_admin()
        if denied:
            return denied
        if not require_csrf():
            return jsonify(error="Solicitud inválida"), 400
        if request.method == "DELETE":
            db().execute("DELETE FROM ticket_subcategories WHERE id = ?", (subcategory_id,))
        else:
            name = str((request.get_json(silent=True) or {}).get("name", "")).strip()
            if not name or len(name) > 160:
                return jsonify(error="Nombre de tipo de falla inválido"), 400
            db().execute("UPDATE ticket_subcategories SET name = ? WHERE id = ?", (name, subcategory_id))
        db().commit()
        return jsonify(portal_config())

    @app.get("/api/tickets/<int:ticket_id>/attachments/<int:attachment_id>")
    def download_ticket_attachment(ticket_id: int, attachment_id: int) -> Any:
        denied = require_admin()
        if denied:
            return denied
        attachment = db().execute(
            """
            SELECT filename, mime_type, content
            FROM ticket_attachments
            WHERE id = ? AND ticket_id = ?
            """,
            (attachment_id, ticket_id),
        ).fetchone()
        if attachment is None:
            return jsonify(error="Adjunto no encontrado"), 404
        return send_file(
            BytesIO(attachment["content"]),
            mimetype=attachment["mime_type"],
            as_attachment=False,
            download_name=attachment["filename"],
        )

    @app.route("/api/tickets/<int:ticket_id>/support-report", methods=["GET", "POST"])
    def ticket_support_report(ticket_id: int) -> Any:
        denied = require_admin()
        if denied:
            return denied
        ticket = db().execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if ticket is None:
            return jsonify(error="Ticket no encontrado"), 404
        if ticket["status"] != "Resuelto":
            return jsonify(error="El formato PDF solo se genera para tickets resueltos."), 409
        if request.method == "POST":
            if not require_csrf():
                return jsonify(error="Solicitud inválida"), 400
            try:
                report = generate_ticket_support_report(ticket)
            except SupportReportError as exc:
                app.logger.error("No se pudo generar el formato del ticket %s: %s", ticket["code"], exc)
                return jsonify(error=str(exc)), 502
            return jsonify(report), 201
        report = db().execute(
            "SELECT filename, report_build FROM support_reports WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()
        if report is None:
            return jsonify(error="El formato PDF aún no ha sido generado."), 404
        path = Path(app.config["DATABASE"]).parent / "support_reports" / report["filename"]
        if report["report_build"] != SUPPORT_REPORT_BUILD:
            try:
                refreshed = generate_ticket_support_report(ticket)
            except SupportReportError as exc:
                app.logger.error("No se pudo actualizar el formato del ticket %s: %s", ticket["code"], exc)
                return jsonify(error=str(exc)), 502
            refreshed_record = db().execute(
                "SELECT filename FROM support_reports WHERE ticket_id = ?",
                (ticket_id,),
            ).fetchone()
            path = Path(app.config["DATABASE"]).parent / "support_reports" / refreshed_record["filename"]
        if not path.is_file():
            app.logger.error("El formato registrado para el ticket %s no existe: %s", ticket["code"], path)
            return jsonify(error="El archivo PDF generado no está disponible."), 404
        return send_file(path, mimetype="application/pdf", as_attachment=True, download_name=report["filename"])

    @app.post("/api/login")
    def login() -> Any:
        if not require_csrf():
            return jsonify(error="Solicitud inválida"), 400
        if not consume_intake_quota(db(), f"login:{request.remote_addr or 'unknown'}"):
            return jsonify(error="Demasiados intentos. Espere antes de volver a intentar."), 429
        payload = request.get_json(silent=True) or {}
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        row = db().execute(
            "SELECT id, username, password_hash, role FROM users WHERE username = ? COLLATE NOCASE AND active = 1",
            (username,),
        ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return jsonify(error="Usuario o contraseña incorrectos"), 401
        session.clear()
        session.permanent = True
        session["user_id"] = row["id"]
        session["username"] = row["username"]
        csrf = csrf_token()
        return jsonify(username=row["username"], role=row["role"], csrf=csrf)

    @app.post("/api/logout")
    def logout() -> Any:
        if not require_csrf():
            return jsonify(error="Solicitud inválida"), 400
        session.clear()
        return jsonify(ok=True)

    @app.route("/api/tickets", methods=["GET", "POST"])
    def tickets_endpoint() -> Any:
        if request.method == "GET":
            denied = require_admin()
            if denied:
                return denied
            rows = db().execute("SELECT * FROM tickets ORDER BY id DESC").fetchall()
            return jsonify([ticket_json(row) for row in rows])

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Se esperaba una solicitud JSON"), 400
        attachments = parse_attachments(payload)
        if isinstance(attachments, tuple):
            return jsonify(*attachments)
        if not consume_intake_quota(db(), request.remote_addr or "unknown"):
            return jsonify(error="Se alcanzó el límite de solicitudes. Intente más tarde."), 429

        def value(*keys: str) -> Any:
            return next((payload.get(key) for key in keys if payload.get(key) is not None), "")

        client_name = str(value("clientName", "name")).strip()
        client_user = str(value("clientUser", "user")).strip()
        email = str(value("requesterEmail", "clientEmail", "email")).strip().lower()
        asset = str(value("asset")).strip()
        work_location = str(value("workLocation")).strip()
        category = str(value("category")).strip()
        subcategory = str(value("subcategory")).strip()
        description = str(value("description")).strip()
        first_line = description.splitlines()[0][:75] if description.splitlines() else ""
        title = str(value("title") or first_line).strip()
        origin = str(value("origin") or "Portal Local")[:40]

        fields = {
            "nombre": (client_name, 120),
            "usuario": (client_user, 60),
            "correo": (email, 160),
            "equipo": (asset, 160),
            "categoría": (category, 80),
            "subcategoría": (subcategory, 160),
            "título": (title, 200),
            "descripción": (description, 2000),
        }
        for label, (field, limit) in fields.items():
            if not field or len(field) > limit:
                return jsonify(error=f"Campo {label} obligatorio o excede {limit} caracteres"), 400
        if len(work_location) > 160:
            return jsonify(error="Campo ubicación excede 160 caracteres"), 400
        if not re.fullmatch(rf"[^\s@]+{re.escape(EMAIL_SUFFIX)}", email, re.IGNORECASE):
            return jsonify(error=f"Use un correo institucional {EMAIL_SUFFIX}"), 400

        priority = "Media"
        assignee = "Sin Asignar"
        user_id = session.get("user_id")
        if user_id:
            user_row = db().execute("SELECT role, active FROM users WHERE id = ?", (user_id,)).fetchone()
            if user_row and user_row["active"] and user_row["role"] in {"admin", "technician"}:
                requested_priority = str(value("priority") or "Media")
                if requested_priority not in {"Baja", "Media", "Alta", "Crítica"}:
                    return jsonify(error="Prioridad no permitida"), 400
                priority = requested_priority
                assignee = str(value("assignee") or "Sin Asignar").strip()[:120]

        created_at = utc_now()
        connection = db()
        cursor = connection.execute(
            """INSERT INTO tickets (
                code, origin, client_name, client_user, requester_email, asset, work_location,
                category, subcategory, title, description, created_at, updated_at
                , priority, assignee
            ) VALUES ('pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                origin,
                client_name,
                client_user,
                email,
                asset,
                work_location,
                category,
                subcategory,
                title,
                description,
                created_at,
                created_at,
                priority,
                assignee,
            ),
        )
        ticket_id = cursor.lastrowid
        code = f"S6-{datetime.now(timezone.utc).year}-{ticket_id:06d}"
        connection.execute("UPDATE tickets SET code = ? WHERE id = ?", (code, ticket_id))
        connection.execute(
            "INSERT INTO ticket_events (ticket_id, username, event_type, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (ticket_id, client_name, "Creación", "Ticket recibido por el servidor.", created_at),
        )
        if attachments:
            connection.executemany(
                """
                INSERT INTO ticket_attachments (ticket_id, filename, mime_type, byte_size, content)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (ticket_id, filename, mime_type, len(content), content)
                    for filename, mime_type, content in attachments
                ],
            )
        connection.commit()
        row = connection.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        response = ticket_json(row)
        return jsonify(response), 201

    @app.patch("/api/tickets/<int:ticket_id>")
    def update_ticket(ticket_id: int) -> Any:
        denied = require_admin()
        if denied:
            return denied
        if not require_csrf():
            return jsonify(error="Solicitud inválida"), 400
        payload = request.get_json(silent=True) or {}
        row = db().execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            return jsonify(error="Ticket no encontrado"), 404

        changes: list[str] = []
        values: list[Any] = []
        event_parts: list[str] = []
        status = payload.get("status")
        if status is not None:
            if status not in STATUSES:
                return jsonify(error="Estado no permitido"), 400
            changes.append("status = ?")
            values.append(status)
            event_parts.append(f"Estado actualizado a {status}.")
        assignee = payload.get("assignee")
        if assignee is not None:
            assignee = str(assignee).strip()
            if len(assignee) > 120:
                return jsonify(error="Asignación demasiado larga"), 400
            changes.append("assignee = ?")
            values.append(assignee)
            event_parts.append(f"Técnico asignado: {assignee}.")
        note = str(payload.get("note", "")).strip()
        if len(note) > 2000:
            return jsonify(error="Nota demasiado larga"), 400
        if not changes and not note:
            return jsonify(error="No hay cambios para guardar"), 400
        previous_status = row["status"]
        if status == "Resuelto":
            changes.append("closure_note = ?")
            values.append(note or "Incidencia atendida, solucionada y cerrada satisfactoriamente por Mesa de Soporte S6.")
        if changes:
            changes.append("updated_at = ?")
            values.extend([utc_now(), ticket_id])
            db().execute(f"UPDATE tickets SET {', '.join(changes)} WHERE id = ?", values)
        if note:
            event_parts.append(note)
        db().execute(
            "INSERT INTO ticket_events (ticket_id, username, event_type, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (ticket_id, session["username"], "Actualización", " ".join(event_parts), utc_now()),
        )
        db().commit()
        updated = db().execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        response = ticket_json(updated)
        if status == "Resuelto" and previous_status != "Resuelto":
            try:
                response["supportReport"] = generate_ticket_support_report(updated)
            except SupportReportError as exc:
                app.logger.error("No se pudo generar el formato del ticket %s: %s", updated["code"], exc)
                response["supportReport"] = {"generated": False, "error": str(exc)}
        return jsonify(response)

    with app.app_context():
        init_db()

    return app


def consume_intake_quota(connection: sqlite3.Connection, client_key: str) -> bool:
    now = int(datetime.now(timezone.utc).timestamp())
    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute("SELECT window_start, request_count FROM intake_limits WHERE client_key = ?", (client_key,)).fetchone()
    if row is None or now - row["window_start"] >= RATE_WINDOW_SECONDS:
        connection.execute(
            "INSERT INTO intake_limits (client_key, window_start, request_count) VALUES (?, ?, 1) "
            "ON CONFLICT(client_key) DO UPDATE SET window_start = excluded.window_start, request_count = 1",
            (client_key, now),
        )
        connection.commit()
        return True
    if row["request_count"] >= RATE_LIMIT:
        connection.rollback()
        return False
    connection.execute("UPDATE intake_limits SET request_count = request_count + 1 WHERE client_key = ?", (client_key,))
    connection.commit()
    return True


def create_admin(username: str, password: str, database: str) -> None:
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, 'admin', ?)",
        (username, make_password_hash(password), utc_now()),
    )
    connection.commit()
    connection.close()


app = create_app()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "create-admin":
        import getpass

        username = input("Usuario administrador: ").strip()
        password = getpass.getpass("Contraseña (mínimo 14 caracteres): ")
        if len(password) < 14:
            raise SystemExit("La contraseña debe tener al menos 14 caracteres")
        create_admin(username, password, app.config["DATABASE"])
        print("Administrador creado.")
    else:
        port = int(os.environ.get("HELPDESK_PORT", "8080"))
        mode = os.environ.get("HELPDESK_MODE", "local")
        if mode == "lan-http":
            if os.environ.get("HELPDESK_ENV") == "production":
                raise SystemExit("No combine lan-http con el modo de producción HTTPS")
            host = validate_lan_http_binding(
                os.environ.get("HELPDESK_HOST", ""),
                os.environ.get("HELPDESK_LAN_HTTP_ACK", ""),
                os.environ.get("HELPDESK_SECRET_KEY", ""),
                app.config["SESSION_COOKIE_SECURE"],
            )
            from waitress import serve

            serve(app, host=host, port=port, threads=8)
        elif os.environ.get("HELPDESK_ENV") == "production":
            from waitress import serve

            serve(app, host="127.0.0.1", port=port)
        else:
            app.run(host="127.0.0.1", port=port, debug=False)