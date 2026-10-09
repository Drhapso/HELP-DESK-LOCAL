import base64
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

from server import CLIENT_BUILD, create_app, create_admin, make_password_hash, validate_lan_http_binding, verify_password
from support_report import SupportReportError, _lookup_context, generate_support_report


class HelpdeskServerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp_dir.name) / "helpdesk.sqlite3")
        self.app = create_app({"TESTING": True, "DATABASE": self.database, "SECRET_KEY": "test-secret"})
        self.client = self.app.test_client()
        create_admin("operator", "correct-horse-battery", self.database)

    def tearDown(self):
        self.temp_dir.cleanup()

    def csrf(self):
        page = self.client.get("/login")
        match = re.search(rb'id="csrf" type="hidden" value="([^"]+)"', page.data)
        self.assertIsNotNone(match)
        return match.group(1).decode("ascii")

    def login(self):
        return self.client.post(
            "/api/login",
            json={"username": "operator", "password": "correct-horse-battery"},
            headers={"X-CSRF-Token": self.csrf()},
        )

    def ticket_payload(self):
        return {
            "clientName": "Usuario de prueba",
            "clientUser": "12345678",
            "requesterEmail": "usuario@example.org",
            "asset": "Equipo de prueba",
            "category": "Hardware",
            "subcategory": "Fallo de memoria ram",
            "description": "La pantalla muestra un error al iniciar.",
            "origin": "Portal Local",
        }

    def test_password_hash_is_salted_and_verified(self):
        first = make_password_hash("a-secure-password")
        second = make_password_hash("a-secure-password")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("a-secure-password", first))
        self.assertFalse(verify_password("wrong-password", first))

    def test_ticket_is_persisted_and_visible_to_authenticated_admin(self):
        created = self.client.post("/api/tickets", json=self.ticket_payload())
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.json["id"].startswith("S6-"))
        self.assertEqual(self.client.get("/api/tickets").status_code, 401)
        self.assertEqual(
            self.client.patch(f"/api/tickets/{created.json['dbId']}", json={"status": "Resuelto"}).status_code,
            401,
        )
        self.assertEqual(self.login().status_code, 200)
        listing = self.client.get("/api/tickets")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json[0]["id"], created.json["id"])
        session = self.client.get("/api/session").json
        updated = self.client.patch(
            f"/api/tickets/{created.json['dbId']}",
            json={"status": "En Proceso", "assignee": "Técnico"},
            headers={"X-CSRF-Token": session["csrf"]},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json["status"], "En Proceso")

    def test_sla_is_calculated_from_category_priority_and_created_time(self):
        self.assertEqual(self.login().status_code, 200)
        payload = self.ticket_payload()
        payload.update({"category": "Red", "priority": "Media"})
        created = self.client.post("/api/tickets", json=payload)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json["slaTargetMinutes"], 90)
        self.assertRegex(created.json["sla"], r"^1h (2[89]|30)m$")
        self.assertEqual(created.json["slaClass"], "sla-ok")

    def test_public_ticket_queue_is_ordered_and_excludes_closed_tickets(self):
        first = self.client.post("/api/tickets", json=self.ticket_payload())
        second_payload = self.ticket_payload()
        second_payload["clientUser"] = "80012703"
        second = self.client.post("/api/tickets", json=second_payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(self.login().status_code, 200)
        csrf = self.client.get("/api/session").json["csrf"]
        resolved = self.client.patch(
            f"/api/tickets/{first.json['dbId']}",
            json={"status": "Resuelto", "note": "Atendido."},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(resolved.status_code, 200)

        queue = self.client.get("/api/portal/ticket-queue")
        self.assertEqual(queue.status_code, 200)
        self.assertEqual(queue.json["tickets"], [{
            "turn": 1,
            "code": second.json["id"],
            "startedAt": second.json["createdAt"],
            "status": "Abierto",
            "assignee": "Sin Asignar",
            "requesterName": "Usuario de prueba",
            "dependency": "Equipo de prueba",
            "sla": queue.json["tickets"][0]["sla"],
            "slaClass": "sla-ok",
        }])

    def test_public_network_status_reports_each_configured_target(self):
        import server

        with patch.object(
            server, "probe_network_target",
            side_effect=lambda t: {"name": t["name"], "group": t["group"], "host": t["host"],
                                   "status": "online", "detail": "", "latencyMs": 1},
        ):
            server._network_status_cache.update(at=0.0, payload=None)
            response = self.client.get("/api/portal/network-status")
        server._network_status_cache.update(at=0.0, payload=None)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["services"]), len(server.NETWORK_STATUS_TARGETS))
        self.assertTrue(all(s["status"] == "online" for s in response.json["services"]))

    def test_ticket_notifications_are_manual_only(self):
        created = self.client.post("/api/tickets", json=self.ticket_payload())
        self.assertEqual(created.status_code, 201)
        self.assertNotIn("emailNotification", created.json)

        self.assertEqual(self.login().status_code, 200)
        csrf = self.client.get("/api/session").json["csrf"]
        updated = self.client.patch(
            f"/api/tickets/{created.json['dbId']}",
            json={"status": "En Proceso"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertNotIn("emailNotification", updated.json)

    def test_image_attachment_is_persisted_and_requires_admin_to_download(self):
        payload = self.ticket_payload()
        image = b"\xff\xd8\xff\xd9"
        payload["attachments"] = [
            {
                "name": "captura.jpg",
                "type": "image/jpeg",
                "dataUrl": f"data:image/jpeg;base64,{base64.b64encode(image).decode('ascii')}",
            }
        ]
        created = self.client.post("/api/tickets", json=payload)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json["attachments"][0]["name"], "captura.jpg")
        attachment_url = created.json["attachments"][0]["url"]
        self.assertEqual(self.client.get(attachment_url).status_code, 401)

        self.assertEqual(self.login().status_code, 200)
        downloaded = self.client.get(attachment_url)
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.mimetype, "image/jpeg")
        self.assertEqual(downloaded.data, image)

    def test_console_is_not_served_without_a_session(self):
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/login")
        self.assertEqual(self.client.get("/mockup_helpdesk.html").status_code, 404)

    def test_root_serves_the_existing_custom_portal(self):
        response = self.client.get("/")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"MESA DE SOPORTE S6 LOCAL", response.data)
            self.assertIn(b"submitClientTicket", response.data)
        finally:
            response.close()

    def test_client_build_is_available_without_authentication(self):
        response = self.client.get("/api/client-build")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["build"], CLIENT_BUILD)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_html_manuals_are_available_but_arbitrary_files_are_not(self):
        for page in (
            "INDICE_DOCUMENTACION.html",
            "MANUAL_USUARIOS.html",
            "MANUAL_ADMIN_TI.html",
            "MIGRACION_ENTRE_UNIDADES.html",
        ):
            with self.subTest(page=page):
                response = self.client.get(f"/docs/{page}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"<!doctype html>", response.data.lower())
                response.close()
        self.assertEqual(self.client.get("/docs/../server.py").status_code, 404)

    def test_lan_http_requires_explicit_ack_private_ip_and_persistent_secret(self):
        self.assertEqual(
            validate_lan_http_binding(
                "192.0.2.10", "I_ACCEPT_UNENCRYPTED_LAN_HTTP", "persistent-session-key", False
            ),
            "192.0.2.10",
        )
        unsafe_settings = [
            ("192.0.2.10", "", "persistent-session-key", False),
            ("0.0.0.0", "I_ACCEPT_UNENCRYPTED_LAN_HTTP", "persistent-session-key", False),
            ("192.0.2.10", "I_ACCEPT_UNENCRYPTED_LAN_HTTP", "", False),
            ("192.0.2.10", "I_ACCEPT_UNENCRYPTED_LAN_HTTP", "persistent-session-key", True),
        ]
        for settings in unsafe_settings:
            with self.subTest(settings=settings), self.assertRaises(RuntimeError):
                validate_lan_http_binding(*settings)

    def test_ticket_fields_are_escaped_by_clients_not_trusted_by_server(self):
        payload = self.ticket_payload()
        payload["description"] = "<img src=x onerror=alert(1)>"
        created = self.client.post("/api/tickets", json=payload)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json["description"], payload["description"])
        source = (Path(__file__).resolve().parents[1] / "mockup_helpdesk.html").read_text(encoding="utf-8")
        self.assertIn("${escHtml(item.text)}", source)
        self.assertIn("${escHtml(t.title)}", source)

    def test_public_intake_rejects_non_institutional_email(self):
        payload = self.ticket_payload()
        payload["requesterEmail"] = "user@gmail.com"
        response = self.client.post("/api/tickets", json=payload)
        self.assertEqual(response.status_code, 400)

    def test_ticket_cleanup_requires_confirmation_and_removes_older_tickets(self):
        created = self.client.post("/api/tickets", json=self.ticket_payload())
        self.assertEqual(created.status_code, 201)
        self.assertEqual(self.login().status_code, 200)
        csrf = self.client.get("/api/session").json["csrf"]
        cutoff = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        endpoint = f"/api/admin/tickets-before?before={quote(cutoff, safe='')}"

        preview = self.client.get(endpoint)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json["count"], 1)

        unconfirmed = self.client.delete(endpoint, json={}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(unconfirmed.status_code, 400)

        deleted = self.client.delete(endpoint, json={"confirm": True}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json["deleted"], 1)
        self.assertEqual(self.client.get("/api/tickets").json, [])

    def test_selective_ticket_deletion_requires_confirmation_and_removes_only_target(self):
        first = self.client.post("/api/tickets", json=self.ticket_payload())
        second_payload = self.ticket_payload()
        second_payload["clientUser"] = "80012703"
        second = self.client.post("/api/tickets", json=second_payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(self.login().status_code, 200)
        csrf = self.client.get("/api/session").json["csrf"]
        endpoint = f"/api/admin/tickets/{first.json['dbId']}"

        unconfirmed = self.client.delete(endpoint, json={}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(unconfirmed.status_code, 400)

        deleted = self.client.delete(endpoint, json={"confirm": True}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json["deleted"], 1)
        remaining = self.client.get("/api/tickets").json
        self.assertEqual([ticket["dbId"] for ticket in remaining], [second.json["dbId"]])

    def test_inventory_monitor_requires_admin_csrf_and_limits_targets_to_lan(self):
        payload = {"assets": [{"id": 11, "ip": "192.0.2.10"}, {"id": "duplicate-ip", "ip": "192.0.2.10"}]}
        self.assertEqual(self.client.post("/api/admin/inventory-monitor", json=payload).status_code, 401)

        self.assertEqual(self.login().status_code, 200)
        csrf = self.client.get("/api/session").json["csrf"]
        self.assertEqual(
            self.client.post("/api/admin/inventory-monitor", json=payload).status_code,
            400,
        )
        with patch(
            "server.probe_inventory_host",
            return_value={"status": "online", "detail": "El equipo respondió a ICMP."},
        ) as probe:
            monitored = self.client.post(
                "/api/admin/inventory-monitor",
                json=payload,
                headers={"X-CSRF-Token": csrf},
            )
        self.assertEqual(monitored.status_code, 200)
        self.assertEqual([result["id"] for result in monitored.json["results"]], [11, "duplicate-ip"])
        self.assertTrue(all(result["status"] == "online" for result in monitored.json["results"]))
        probe.assert_called_once_with("192.0.2.10")

        invalid = self.client.post(
            "/api/admin/inventory-monitor",
            json={"assets": [{"id": 12, "ip": "192.168.1.20"}]},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(invalid.status_code, 400)

    def test_resolving_ticket_generates_downloadable_support_report(self):
        payload = self.ticket_payload()
        payload["workLocation"] = "Bloque A, oficina 201"
        created = self.client.post("/api/tickets", json=payload)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(self.login().status_code, 200)
        csrf = self.client.get("/api/session").json["csrf"]

        def create_fake_report(_ticket, *, output_directory, **_kwargs):
            output_directory.mkdir(parents=True, exist_ok=True)
            report = output_directory / "formato_soporte_S6-2026-000001.pdf"
            report.write_bytes(b"%PDF-1.4" + b"\n" + b"% fake report" + b"\n")
            return report

        with patch("server.generate_support_report", side_effect=create_fake_report):
            resolved = self.client.patch(
                f"/api/tickets/{created.json['dbId']}",
                json={"status": "Resuelto", "note": "Soporte completado."},
                headers={"X-CSRF-Token": csrf},
            )
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json["closureNote"], "Soporte completado.")
        self.assertTrue(resolved.json["supportReport"]["generated"])
        downloaded = self.client.get(resolved.json["supportReport"]["url"])
        try:
            self.assertEqual(downloaded.status_code, 200)
            self.assertEqual(downloaded.mimetype, "application/pdf")
            self.assertEqual(downloaded.data, b"%PDF-1.4\n% fake report\n")
        finally:
            downloaded.close()

    @unittest.skipUnless((Path(__file__).resolve().parent.parent / "datos" / "formato soporte tecnico.docx").exists(), "requiere datos locales")
    def test_native_pdf_fallback_generates_report_when_word_conversion_fails(self):
        ticket = {
            "id": 1,
            "code": "S6-2026-000001",
            "client_name": "Usuario de prueba",
            "client_user": "12345678",
            "requester_email": "usuario@example.org",
            "asset": "Equipo de prueba",
            "work_location": "Oficina de prueba",
            "category": "Hardware",
            "subcategory": "Fallo de memoria ram",
            "description": "Validación del generador PDF nativo.",
            "created_at": "2026-10-09T16:00:00+00:00",
        }
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as output, patch(
            "support_report._convert_docx_to_pdf",
            side_effect=SupportReportError("Word no disponible"),
        ):
            report = generate_support_report(
                ticket,
                template_path=root / "datos" / "formato soporte tecnico.docx",
                output_directory=Path(output),
                inventory_db=root / "datos" / "base_usuarios_equipos_octubre_2026.sqlite3",
                inventory_json=root / "datos" / "inventario_equipos.json",
            )
            self.assertTrue(report.is_file())
            self.assertEqual(report.read_bytes()[:5], b"%PDF-")

    @unittest.skipUnless((Path(__file__).resolve().parent.parent / "datos" / "inventario_equipos.json").exists(), "requiere datos locales")
    def test_support_report_context_uses_inventory_equipment_fields(self):
        root = Path(__file__).resolve().parents[1]
        context = _lookup_context(
            {"client_user": "1126456696", "asset": "BAINTS602"},
            root / "datos" / "base_usuarios_equipos_octubre_2026.sqlite3",
            root / "datos" / "inventario_equipos.json",
        )
        self.assertEqual(context["brand"], "HP")
        self.assertEqual(context["model"], "ELITEONE 800 G5")
        self.assertEqual(context["serial"], "MXL02947T7")
        self.assertEqual(context["operating_system"], "Microsoft Windows 11 Pro (64-bit)")
        self.assertEqual(context["processor"], "1 x Intel Core i7-9700 CPU @ 3.00GHz (3000 MHz)")
        self.assertEqual(context["memory"], "16384 MB")
        self.assertEqual(context["disk"], "WDC WDIOSPSX-60A6WTO (1000 GB), KXG60ZNVIT02 KIOXIA (1024 GB)")
        self.assertEqual(context["ip"], "192.0.2.10")
        self.assertEqual(context["hostname"], "BAINTS602")

    def test_intake_is_rate_limited(self):
        for _ in range(10):
            self.assertEqual(self.client.post("/api/tickets", json=self.ticket_payload()).status_code, 201)
        self.assertEqual(self.client.post("/api/tickets", json=self.ticket_payload()).status_code, 429)


if __name__ == "__main__":
    unittest.main()