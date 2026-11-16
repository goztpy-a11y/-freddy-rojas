import json,os,re,unittest
from uuid import uuid4
os.environ.setdefault('DATABASE_URL','sqlite://')
os.environ.setdefault('ADMIN_PASSWORD','test-only-password-long-enough')
os.environ.setdefault('SECRET_KEY','test-secret-key-only')
from app import app,db,User

class CajaBankAccessTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING']=True
        self.client=app.test_client()
        with app.app_context():
            db.session.remove();db.drop_all();db.create_all()
            user=User(username='caja-test',password_hash='unused',role='caja',areas='caja')
            db.session.add(user);db.session.commit();self.uid=user.id
        with self.client.session_transaction() as session:session['uid']=self.uid

    def config(self,response):
        self.assertEqual(response.status_code,200)
        return json.loads(re.search(rb'<script id="bank-sheet-data" type="application/json">(.*?)</script>',response.data,re.S)[1])

    def test_caja_can_open_all_eight_accounts_from_menu_and_area(self):
        home=self.client.get('/area/caja')
        self.assertEqual(home.status_code,200)
        self.assertIn('Cuentas bancarias · 8 bancos'.encode(),home.data)
        self.assertIn(b'/modulo/cuentas_empresa',home.data)
        response=self.client.get('/modulo/cuentas_empresa?month=2026-11')
        config=self.config(response)
        self.assertEqual(len(config['accounts']),8)
        nav=re.search(rb'<nav>(.*?)</nav>',response.data,re.S)[1]
        self.assertIn(b'/modulo/cuentas_empresa',nav)
        self.assertNotIn(b'/usuarios',nav)
        self.assertNotIn(b'/admin/respaldo.json',nav)
        self.assertEqual(len(self.config(self.client.get('/modulo/cuentas_empresa?currency=USD'))['accounts']),8)

    def test_caja_bank_history_and_operations_work_for_any_account(self):
        config=self.config(self.client.get('/modulo/cuentas_empresa?month=2026-11'))
        for account in config['accounts']:
            response=self.client.post('/modulo/cuentas_empresa?month=2026-11',headers={'X-Bank-CSRF':config['csrf']},json={
                'action':'save_row','account_id':account['id'],'key':str(uuid4()),'version':0,
                'date':'2026-11-16','description':'Movimiento de Caja','amount':'1.000'})
            self.assertEqual(response.status_code,200,response.data)
            self.assertEqual(response.get_json()['ledger']['balance'],'1.000')
        config=self.config(self.client.get('/modulo/cuentas_empresa?month=2026-11'))
        self.assertTrue(all(len(a['entries'])==1 for a in config['accounts']))
        for path in ('/usuarios','/configuracion','/admin/respaldo.json','/area/tesoreria','/area/administracion'):
            self.assertIn(self.client.get(path).status_code,(403,404),path)
        with self.client.session_transaction() as session:session.clear()
        self.assertEqual(self.client.get('/modulo/cuentas_empresa').status_code,302)

    def test_treasury_does_not_receive_the_new_bank_access(self):
        with app.app_context():
            user=db.session.get(User,self.uid)
            user.role='tesoreria';user.areas='tesoreria';db.session.commit()
        self.assertEqual(self.client.get('/modulo/cuentas_empresa').status_code,403)
        self.assertEqual(self.client.get('/area/tesoreria').status_code,403)
