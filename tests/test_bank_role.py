import json
import os
import re
import unittest
from uuid import uuid4

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('ADMIN_PASSWORD', 'test-only-password-long-enough')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-only')
from app import app, db, User, CompanyAccount, Record, allowed
from werkzeug.security import generate_password_hash


class BankRoleTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.session.remove(); db.drop_all(); db.create_all()
            admin = User(username='admin', password_hash=generate_password_hash('admin-test'), role='admin', areas='admin')
            bank = User(username='banco-test', password_hash=generate_password_hash('bank-test'), role='banco', areas='banco')
            account = CompanyAccount(name='Banco 1', bank='', number='', balance=10000000, balance_usd=0)
            db.session.add_all([admin, bank, account]); db.session.commit()
            self.admin_id, self.bank_id, self.account_id = admin.id, bank.id, account.id
        self.sign_as(self.admin_id)

    def sign_as(self, uid):
        with self.client.session_transaction() as sess:
            sess.clear(); sess['uid'] = uid

    def test_admin_can_create_and_edit_bank_role_without_extra_permissions(self):
        response = self.client.get('/usuarios')
        self.assertIn(b'<option value="banco">Banco</option>', response.data)
        self.assertNotIn(b'name="areas" value="banco"', response.data)
        self.client.post('/usuarios', data={'username':'nuevo-banco', 'password':'bank-test', 'role':'banco', 'areas':['admin','caja','tesoreria']})
        with app.app_context():
            user = User.query.filter_by(username='nuevo-banco').one()
            self.assertEqual((user.role,user.areas),('banco','banco')); uid=user.id
        response = self.client.get(f'/usuarios/{uid}/editar')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'value="banco" selected',response.data)
        self.client.post(f'/usuarios/{uid}/editar', data={'username':'nuevo-banco','role':'banco','areas':['admin','inventario'],'active':'on'})
        with app.app_context():
            self.assertEqual(db.session.get(User,uid).areas,'banco')
        # Un rol normal tampoco puede recibir Banco como área adicional.
        self.client.post(f'/usuarios/{uid}/editar', data={'username':'nuevo-banco','role':'caja','areas':['banco'],'active':'on'})
        with app.app_context():
            self.assertEqual(db.session.get(User,uid).areas,'caja')

    def test_bank_login_lands_in_bank_and_navigation_has_no_other_sections(self):
        self.client.get('/logout')
        response=self.client.post('/login?next=/historial',data={'username':'banco-test','password':'bank-test'},follow_redirects=True)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.request.path.endswith('/modulo/cuentas_empresa'))
        nav=re.search(rb'<nav>(.*?)</nav>',response.data,re.S)[1]
        links=re.findall(rb'href="([^"]+)"',nav)
        self.assertEqual(links,[b'/modulo/cuentas_empresa'])
        self.assertNotIn(b'Panel principal',nav)
        self.assertNotIn(b'Informes',nav)
        self.assertNotIn(b'Historial de inventario',nav)

    def test_bank_can_save_and_view_only_bank_history(self):
        with app.app_context():
            db.session.add(Record(module='pagos_diarios',title='Pago bancario',data=json.dumps({'fecha':'2026-11-16'}),
                                 amount=1000,company_account_id=self.account_id,created_by=self.admin_id));db.session.commit()
        self.sign_as(self.bank_id)
        response=self.client.get('/modulo/cuentas_empresa?month=2026-11')
        payload=json.loads(re.search(rb'<script id="bank-sheet-data" type="application/json">(.*?)</script>',response.data,re.S)[1])
        entries=payload['accounts'][0]['entries']
        self.assertEqual(entries[0]['description'],'Pago bancario')
        self.assertIsNone(entries[0].get('detail_url'))
        result=self.client.post('/modulo/cuentas_empresa?month=2026-11',json={'action':'save_row','account_id':self.account_id,
            'key':str(uuid4()),'version':0,'date':'2026-11-16','description':'Movimiento Banco','amount':'-5.000'},
            headers={'X-Bank-CSRF':payload['csrf']})
        self.assertEqual(result.status_code,200,result.data)
        self.assertEqual(result.get_json()['ledger']['balance'],'9.995.000')
        self.assertIsNone(result.get_json()['ledger']['entries'][0].get('detail_url'))
        for path in ('/static/bank_sheet.js','/static/bank_sheet.css'):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code,200)

    def test_every_other_application_route_is_blocked_for_bank(self):
        self.sign_as(self.bank_id)
        safe_endpoints={'index','login','logout'}
        blocked=0
        adapter=app.url_map.bind('localhost')
        for rule in app.url_map.iter_rules():
            if rule.endpoint in safe_endpoints: continue
            values={name:(self.admin_id if name in ('uid','rid','mid','id') else 'gastos' if name=='module' else 'tesoreria' if name=='section' else 'registrar_ticket.js' if name=='filename' else 1 if 'int' in str(rule._converters.get(name)) else 'test') for name in rule.arguments}
            # Convertidores enteros, también los que usan nombres específicos de cada módulo.
            for name, converter in rule._converters.items():
                if converter.__class__.__name__=='IntegerConverter': values[name]=1
            for method in ('GET','POST'):
                if method not in rule.methods: continue
                with self.subTest(route=str(rule),method=method):
                    url=adapter.build(rule.endpoint,values,method=method)
                    response=self.client.open(url,method=method)
                    self.assertEqual(response.status_code,403,(url,response.status_code))
                    blocked+=1
        self.assertGreater(blocked,70)
        for path in ('/','/login'):
            self.assertEqual(self.client.get(path).location,'/modulo/cuentas_empresa')

    def test_bank_role_stays_restricted_even_if_stale_extra_areas_exist(self):
        with app.app_context():
            bank=db.session.get(User,self.bank_id);bank.areas='banco,admin,caja,inventario,estacion';db.session.commit()
        self.sign_as(self.bank_id)
        for path in ('/historial','/informes','/usuarios','/admin/respaldo.json','/modulo/tickets','/imprimir/1'):
            self.assertEqual(self.client.get(path).status_code,403,path)
        response=self.client.get('/modulo/cuentas_empresa')
        nav=re.search(rb'<nav>(.*?)</nav>',response.data,re.S)[1]
        self.assertEqual(len(re.findall(rb'href=',nav)),1)

    def test_deactivated_bank_user_cannot_continue_existing_session(self):
        with app.app_context():
            db.session.get(User,self.bank_id).active=False;db.session.commit()
        self.sign_as(self.bank_id)
        response=self.client.get('/modulo/cuentas_empresa')
        self.assertEqual(response.status_code,302)
        self.assertEqual(response.location,'/login')
