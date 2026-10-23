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
        response = self.client.post("/modulo/cuentas_cobrar", data={
            "cliente": "Proveedor A", "concepto": "Cuenta de prueba",
            "importe": "1000", "vencimiento": "2026-11-01", "estado": "Pendiente"
        })
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            original = Record.query.filter_by(module="cuentas_cobrar").first()
            self.assertIsNotNone(original)
            rid = original.id
        response = self.client.post("/modulo/cuentas_cobrar", data={
            "accion": "pago", "registro_id": str(rid), "importe": "300",
            "fecha": "2026-10-22", "medio": "Efectivo", "detalle": "Cobro parcial"
        })
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(Record.query.filter_by(module="cobros_cuentas").count(), 1)
            self.assertEqual(Record.query.filter_by(module="pagos_cuentas").count(), 0)
            original = db.session.get(Record, rid)
            self.assertEqual(original.status, "En proceso")

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
            "cantidad_item[]": ["2", "1"], "precio_item[]": ["15000", "25000"]
        })
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            from app import Record
            rec = Record.query.filter_by(module="gastos").first()
            self.assertIsNotNone(rec)
            self.assertEqual(str(rec.amount), "55000.00")
            account = CompanyAccount.query.first()
            self.assertEqual(str(account.balance), "45000.00")


if __name__ == "__main__":
    unittest.main()
