import os
import unittest
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "test-only-password-long-enough")
os.environ.setdefault("SECRET_KEY", "test-secret-key-only")

from app import app, db, User, Material, CompanyAccount
from werkzeug.security import generate_password_hash


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        cls.client = app.test_client()

    def setUp(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()
            user = User(username="admin", password_hash=generate_password_hash("test-only-password-long-enough"),
                        role="admin", areas="admin,caja,tesoreria,estacion,gomeria,inventario,auditoria")
            db.session.add(user)
            db.session.commit()
            self.admin_id = user.id
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["uid"] = self.admin_id

    def test_all_sector_pages_render(self):
        paths = [
            "/", "/informes", "/historial",
            "/modulo/clientes", "/modulo/materiales", "/modulo/inventario",
            "/modulo/tickets", "/modulo/solicitudes", "/modulo/cuentas_empresa",
            "/modulo/gastos", "/modulo/ventas", "/modulo/cuentas_pagar",
            "/modulo/cuentas_cobrar", "/modulo/cheques", "/modulo/combustible",
            "/modulo/gomeria", "/modulo/repuestos", "/modulo/movimientos_stock",
            "/modulo/auditoria", "/registrar-ticket", "/pagos", "/pagos-diarios", "/prestamos", "/proveedores",
            "/planillas", "/fletes", "/flota", "/combustible-stock",
            "/mantenimiento", "/gomeria-camiones", "/auditoria-pagos",
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=True)
                self.assertEqual(response.status_code, 200, path)

    def test_add_material_with_optional_prices(self):
        response = self.client.post("/modulo/materiales", data={"nombre": "Cartón"})
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            material = Material.query.filter_by(name="Cartón").first()
            self.assertIsNotNone(material)
            self.assertEqual(str(material.price), "0.00")
            self.assertIsNone(material.wholesale_price)


    def test_receivable_collections_are_not_audited_as_outgoing_payments(self):
        from app import Record
        self.client.post("/modulo/cuentas_empresa", data={
            "nombre": "Cuenta de cobro", "saldo_inicial_pyg": "0", "saldo_inicial_usd": "0"
        })
        with app.app_context():
            account_id = CompanyAccount.query.filter_by(name="Cuenta de cobro").first().id
        response = self.client.post("/modulo/cuentas_cobrar", data={
            "cliente": "Proveedor A", "numero_ticket": "T-1001", "material": "Chatarra",
            "cantidad_kg": "2", "precio_kg": "500", "moneda": "PYG", "tipo_cambio": "1",
            "vencimiento": "2026-11-01"
        })
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            original = Record.query.filter_by(module="cuentas_cobrar").first()
            self.assertIsNotNone(original)
            self.assertEqual(str(original.amount), "1000.00")
            rid = original.id
        response = self.client.post("/modulo/cuentas_cobrar", data={
            "accion": "pago", "registro_id": str(rid), "importe": "300",
            "fecha": "2026-10-22", "medio": "Efectivo", "detalle": "Cobro parcial",
            "company_account_id": str(account_id), "tipo_cambio": "1"
        })
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(Record.query.filter_by(module="cobros_cuentas").count(), 1)
            self.assertEqual(Record.query.filter_by(module="pagos_cuentas").count(), 0)
            original = db.session.get(Record, rid)
            self.assertEqual(original.status, "En proceso")

    def test_receivable_ticket_total_is_calculated_and_ticket_is_unique(self):
        from app import Record
        data = {
            "cliente": "Cliente A", "numero_ticket": "T-UNICO-01", "material": "Cobre",
            "cantidad_kg": "12500", "precio_kg": "1800", "moneda": "PYG",
            "tipo_cambio": "1"
        }
        response = self.client.post("/modulo/cuentas_cobrar", data=data)
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            rec = Record.query.filter_by(module="cuentas_cobrar").first()
            self.assertEqual(str(rec.amount), "22500000.00")
            self.assertEqual(rec.status, "Pendiente")
        response = self.client.post("/modulo/cuentas_cobrar", data=data, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ese número de ticket ya está registrado".encode(), response.data)
        with app.app_context():
            self.assertEqual(Record.query.filter_by(module="cuentas_cobrar").count(), 1)

    def test_multiple_company_accounts_have_separate_currency_balances(self):
        self.client.post("/modulo/cuentas_empresa", data={
            "nombre": "Cuenta de prueba", "banco": "Banco", "numero": "001",
            "saldo_inicial_pyg": "100000", "saldo_inicial_usd": "50"
        })
        with app.app_context():
            account = CompanyAccount.query.filter_by(name="Cuenta de prueba").first()
            self.assertIsNotNone(account)
            self.assertEqual(str(account.balance), "100000.00")
            self.assertEqual(str(account.balance_usd), "50.00")
        self.client.post("/modulo/cuentas_empresa", data={
            "nombre": "Segunda cuenta", "saldo_inicial_pyg": "0", "saldo_inicial_usd": "0"
        })
        with app.app_context():
            self.assertEqual(CompanyAccount.query.count(), 2)

    def test_caja_can_open_receivables_and_payables(self):
        with app.app_context():
            caja_user = User(username="caja_test", password_hash=generate_password_hash("test-password"),
                             role="caja", areas="caja")
            db.session.add(caja_user)
            db.session.commit()
            caja_id = caja_user.id
        with self.client.session_transaction() as sess:
            sess["uid"] = caja_id
        for path in ("/modulo/cuentas_cobrar", "/modulo/cuentas_pagar"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_usd_receivable_collection_credits_selected_account(self):
        from app import Record
        self.client.post("/modulo/cuentas_empresa", data={
            "nombre": "Cuenta cobros", "saldo_inicial_pyg": "0", "saldo_inicial_usd": "0"
        })
        with app.app_context():
            account_id = CompanyAccount.query.filter_by(name="Cuenta cobros").first().id
        response = self.client.post("/modulo/cuentas_cobrar", data={
            "cliente": "Cliente USD", "numero_ticket": "T-USD-001", "material": "Cobre",
            "cantidad_kg": "2", "precio_kg": "50", "moneda": "USD", "tipo_cambio": "7300",
            "factura": "F-001", "fecha_factura": "2026-10-25", "vencimiento": ""
        })
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            rid = Record.query.filter_by(module="cuentas_cobrar").first().id
        response = self.client.post("/modulo/cuentas_cobrar", data={
            "accion": "pago", "registro_id": str(rid), "importe": "40",
            "fecha": "2026-10-26", "medio": "Transferencia", "detalle": "Cobro parcial",
            "company_account_id": str(account_id), "tipo_cambio": "7300"
        })
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            account = db.session.get(CompanyAccount, account_id)
            self.assertEqual(str(account.balance_usd), "40.00")
            self.assertEqual(str(account.balance), "0.00")
            payment = Record.query.filter_by(module="cobros_cuentas").first()
            self.assertEqual(payment.company_account_id, account_id)
            self.assertIn('"importe_pyg": "292000.00"', payment.data)

    def test_expense_with_multiple_items(self):
        with app.app_context():
            account = CompanyAccount(name="", bank="", number="", currency="PYG",
                                     opening_balance=Decimal("100000"), balance=Decimal("100000"))
            db.session.add(account)
            db.session.commit()
        response = self.client.post("/modulo/gastos", data={
            "fecha": "2026-10-22", "categoria": "Herramientas", "concepto": "Otros gastos",
            "detalle_concepto": "Prueba", "medio": "Efectivo",
            "comprobante": "G-001", "item[]": ["Guantes", "Llave"],
            "cantidad_item[]": ["2", "1"], "total_item[]": ["30000", "25000"]
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Gasto guardado", response.data, response.data.decode("utf-8", errors="replace")[-2000:])
        with app.app_context():
            from app import Record
            rec = Record.query.filter_by(module="gastos").first()
            self.assertIsNotNone(rec)
            self.assertEqual(str(rec.amount), "55000.00")
            account = CompanyAccount.query.first()
            self.assertEqual(str(account.balance), "45000.00")


if __name__ == "__main__":
    unittest.main()
