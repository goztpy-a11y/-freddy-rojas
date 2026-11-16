import json
import os
import re
import unittest
from decimal import Decimal
from uuid import uuid4

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('ADMIN_PASSWORD', 'test-only-password-long-enough')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-only')
from app import app, db, User, CompanyAccount, BankSheetEntry, Record
from bank_sheet import ledgers, ensure_accounts


class BankSheetTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()
            user = User(username='admin', password_hash='unused', role='admin', areas='admin')
            db.session.add(user)
            account = CompanyAccount(name='Cuenta existente', bank='Banco original', number='123',
                balance=Decimal('10000000'), opening_balance=Decimal('10000000'),
                balance_usd=Decimal('100.50'), opening_balance_usd=Decimal('100.50'))
            db.session.add(account)
            db.session.commit()
            self.uid, self.aid = user.id, account.id
        with self.client.session_transaction() as sess:
            sess['uid'] = self.uid
        self.load()

    def load(self, currency='PYG', month='2026-11'):
        response = self.client.get('/modulo/cuentas_empresa?month=' + month + '&currency=' + currency)
        self.assertEqual(response.status_code, 200)
        payload = re.search(rb'<script id="bank-sheet-data" type="application/json">(.*?)</script>', response.data, re.S)[1]
        self.config = json.loads(payload)
        return self.config

    def api(self, action, currency='PYG', **fields):
        return self.client.post('/modulo/cuentas_empresa?month=2026-11&currency=' + currency,
            json={'action': action, 'account_id': self.aid, **fields},
            headers={'X-Bank-CSRF': self.config['csrf']})

    def row(self, amount='-5.000.000', **fields):
        return self.api('save_row', key=str(uuid4()), version=0, date='2026-11-16', description='Movimiento manual', amount=amount, **fields)

    def balances(self):
        with app.app_context():
            return [(a.id, a.balance, a.balance_usd) for a in CompanyAccount.query.order_by(CompanyAccount.id)]

    def test_eight_banks_preserve_original_and_do_not_duplicate(self):
        config = self.load()
        self.assertEqual(len(config['accounts']), 8)
        self.assertEqual(config['accounts'][0]['name'], 'Cuenta existente')
        self.assertEqual(config['accounts'][0]['balance'], '10.000.000')
        self.assertEqual([a['name'] for a in config['accounts'][1:]], ['Banco ' + str(i) for i in range(2,9)])
        self.assertEqual(self.balances()[0][2], Decimal('100.50'))
        self.assertEqual(self.api('rename_account', name='Nuevo banco', expected_name='Cuenta existente').status_code, 200)
        self.assertEqual(self.load()['accounts'][0]['name'], 'Nuevo banco')
        self.assertEqual(len(self.load()['accounts']), 8)

    def test_expanding_five_existing_banks_preserves_names_balances_and_rows(self):
        saved = self.row(amount='-1.000').get_json()['entry']
        with app.app_context():
            accounts = CompanyAccount.query.order_by(CompanyAccount.id).all()
            for account in accounts[5:]:
                db.session.delete(account)
            for index, account in enumerate(accounts[:5]):
                account.name = 'Mi banco ' + str(index + 1)
                account.balance += index * 1000
            db.session.commit()
            original = [(a.id,a.name,a.balance,a.balance_usd) for a in accounts[:5]]
        config = self.load()
        self.assertEqual(len(config['accounts']),8)
        with app.app_context():
            accounts = CompanyAccount.query.order_by(CompanyAccount.id).all()
            self.assertEqual([(a.id,a.name,a.balance,a.balance_usd) for a in accounts[:5]],original)
            self.assertEqual([a.name for a in accounts[5:]],['Banco 6','Banco 7','Banco 8'])
            self.assertTrue(all(a.balance == 0 and a.balance_usd == 0 for a in accounts[5:]))
            self.assertEqual(BankSheetEntry.query.filter_by(entry_key=saved['key']).count(),1)
        self.assertEqual(len(self.load()['accounts']),8)

    def test_negative_rows_edit_idempotency_and_stale_version(self):
        response = self.row()
        self.assertEqual(response.status_code, 200, response.data)
        saved = response.get_json()
        self.assertEqual(saved['ledger']['balance'], '5.000.000')
        self.assertEqual(saved['entry']['amount'], '-5.000.000')
        params = dict(key=saved['entry']['key'], version=0, date='2026-11-16', description='Movimiento manual', amount='-5.000.000')
        self.assertEqual(self.api('save_row', **params).status_code, 200)
        params.update(version=1, amount='-4.000.000')
        edited = self.api('save_row', **params).get_json()
        self.assertEqual(edited['ledger']['balance'], '6.000.000')
        self.assertEqual(edited['entry']['version'], 2)
        params.update(amount='-3.000.000')
        self.assertEqual(self.api('save_row', **params).status_code, 409)
        self.assertEqual(self.balances()[0][1], Decimal('6000000'))
        self.assertEqual(self.row(amount='-7.000.000').status_code, 400)
        self.assertEqual(self.balances()[0][1], Decimal('6000000'))

    def test_monthly_history_keeps_carry_and_global_balance(self):
        self.api('save_row', key=str(uuid4()), version=0, date='2026-10-31', description='Octubre', amount='-1.000.000')
        self.row(amount='-2.000.000')
        november = self.load()['accounts'][0]
        self.assertEqual(november['opening'], '9.000.000')
        self.assertEqual(november['closing'], '7.000.000')
        self.assertEqual(len(november['entries']), 1)
        october = self.load(month='2026-10')['accounts'][0]
        self.assertEqual(october['closing'], '9.000.000')
        self.assertEqual(october['balance'], '7.000.000')
        self.assertEqual(len(october['entries']), 1)

    def test_transfers_all_destinations_idempotency_and_atomic_edit(self):
        ids = [a['id'] for a in self.config['accounts']][1:]
        for destination in ids:
            key = str(uuid4())
            args = dict(source_account_id=self.aid, destination_account_id=destination, key=key,
                        amount='100.000', description='Prueba de transferencia')
            response = self.api('transfer', **args)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(self.api('transfer', **args).status_code, 200)
        balances = self.balances()
        self.assertEqual(balances[0][1], Decimal('9300000'))
        self.assertEqual(sum(b[1] for b in balances), Decimal('10000000'))
        sheets = self.load()['accounts']
        self.assertTrue(all(len(s['entries']) == 1 for s in sheets[1:]))
        entry = sheets[0]['entries'][0]
        response = self.api('edit_transfer', key=entry['key'], version=entry['version'], amount='150.000', description='Editada')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(sum(b[1] for b in self.balances()), Decimal('10000000'))
        self.assertEqual(self.balances()[0][1], Decimal('9250000'))
        # Gastar el saldo de destino impide reducir la transferencia; todo se revierte.
        dest = entry['destination_account_id']
        self.api('save_row', account_id=dest, key=str(uuid4()), version=0, date='2026-11-16', description='Salida', amount='-150.000')
        before = self.balances()
        failed = self.api('edit_transfer', key=entry['key'], version=2, amount='50.000', description='No permitida')
        self.assertEqual(failed.status_code, 400)
        self.assertEqual(self.balances(), before)
        self.assertEqual(self.api('transfer', source_account_id=self.aid, destination_account_id=self.aid, key=str(uuid4()), amount='1').status_code, 400)

    def test_usd_and_adjustments_are_separate(self):
        self.load(currency='USD')
        saved = self.row(amount='-25,50', currency='USD').get_json()
        self.assertEqual(saved['ledger']['balance'], '75')
        self.assertEqual(self.balances()[0][1], Decimal('10000000'))
        updated = self.api('set_balance', currency='USD', amount='120,75', expected_balance='75').get_json()
        self.assertEqual(updated['ledger']['balance'], '120,75')
        self.assertEqual(self.api('set_balance', currency='USD', amount='130', expected_balance='75').status_code, 409)
        self.assertEqual(self.balances()[0][2], Decimal('120.75'))

    def test_legacy_payments_are_visible_without_changing_balance(self):
        with app.app_context():
            db.session.add(Record(module='pagos_diarios', title='Pago ticket 123', data=json.dumps({'fecha':'2026-11-15'}), amount=200000,
                company_account_id=self.aid, created_by=self.uid))
            db.session.add(Record(module='pagos_cliente_admin', title='Pago proveedor', data=json.dumps({'fecha':'2026-11-14', 'cuenta_id': self.aid}),
                amount=100000, created_by=self.uid))
            db.session.commit()
        sheet = self.load()['accounts'][0]
        self.assertEqual(sheet['balance'], '10.000.000')
        self.assertEqual(len(sheet['entries']), 2)
        self.assertEqual(sheet['entries'][-1]['balance'], '10.000.000')
        self.assertEqual(sheet['opening'], '10.300.000')
        self.assertIn('detail_url', sheet['entries'][0])

    def test_permissions_csrf_foreign_rows_and_no_delete(self):
        self.assertEqual(self.client.post('/modulo/cuentas_empresa', json={'action':'rename_account'}).status_code, 403)
        saved = self.row(amount='1.000').get_json()['entry']
        other = self.config['accounts'][1]['id']
        self.assertEqual(self.api('save_row', account_id=other, key=saved['key'], version=1, date='2026-11-16', description='Wrong', amount='2.000').status_code, 400)
        self.assertEqual(self.api('delete_row', key=saved['key'], version=1).status_code, 400)
        with app.app_context():
            user = User(username='caja-test', password_hash='unused', role='caja', areas='caja')
            db.session.add(user); db.session.commit(); uid = user.id
        with self.client.session_transaction() as sess:
            sess['uid'] = uid
        self.assertEqual(self.client.get('/modulo/cuentas_empresa').status_code, 403)
        self.assertEqual(self.api('set_balance', amount='0', expected_balance='10001000').status_code, 403)

    def test_full_backup_includes_new_ledger(self):
        self.row(amount='1.000')
        response = self.client.get('/admin/respaldo.json')
        self.assertEqual(response.status_code, 200)
        table = response.get_json()['tables']['bank_sheet_entry']
        self.assertEqual(table['row_count'], 1)
