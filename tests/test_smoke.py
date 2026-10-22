import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "test-only-password-long-enough")
os.environ.setdefault("SECRET_KEY", "test-secret-key-only")

from app import app, db, User, Material
from werkzeug.security import generate_password_hash


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        cls.client = app.test_client()

    def setUp(self):
        with app.app_context():
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
            "/modulo/auditoria", "/pagos-diarios", "/prestamos", "/proveedores",
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

    def test_expense_with_multiple_items(self):
        response = self.client.post("/modulo/gastos", data={
            "fecha": "2026-10-22", "categoria": "Herramientas", "medio": "Efectivo",
            "comprobante": "G-001", "item[]": ["Guantes", "Llave"], 
            "cantidad_item[]": ["2", "1"], "precio_item[]": ["15000", "25000"]
        })
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            from app import Record
            rec = Record.query.filter_by(module="gastos").first()
            self.assertIsNotNone(rec)
            self.assertEqual(str(rec.amount), "55000.00")


if __name__ == "__main__":
    unittest.main()
