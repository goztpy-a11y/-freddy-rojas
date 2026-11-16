import json
import os
import re
import unittest
from decimal import Decimal

os.environ.setdefault('DATABASE_URL','sqlite://')
os.environ.setdefault('ADMIN_PASSWORD','test-only-password-long-enough')
os.environ.setdefault('SECRET_KEY','test-secret-key-only')
from flask import session
from app import app,db,User,CompanyAccount,Record,paraguay_now
from bank_sheet import ensure_accounts,ledgers


class DailyPaymentBankTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING']=True
        self.client=app.test_client()
        with app.app_context():
            db.session.remove();db.drop_all();db.create_all()
            user=User(username='caja-test',password_hash='unused',role='caja',areas='caja')
            db.session.add(user);db.session.commit();self.uid=user.id
            accounts=ensure_accounts()
            for index,account in enumerate(accounts):
                account.name='Banco de prueba '+str(index+1)
                account.balance=Decimal('1000000')*(index+1)
                account.balance_usd=Decimal('100.50')
            self.ids=[a.id for a in accounts]
            ticket=Record(module='tickets_entrada',title='Ticket 001',data=json.dumps({'ticket':'001','persona':'Proveedor','en_pagos':True,'fecha':paraguay_now().strftime('%Y-%m-%d')}),amount=100000,created_by=self.uid)
            db.session.add(ticket);db.session.commit();self.rid=ticket.id
        with self.client.session_transaction() as session:
            session['uid']=self.uid

    def pay(self,account_id=None,amount='10000'):
        data={'importe':amount,'medio':'Transferencia'}
        if account_id is not None:data['account_id']=str(account_id)
        return self.client.post(f'/pagos/{self.rid}/pagar',data=data)

    def balances(self):
        with app.app_context():
            return [(a.id,a.balance,a.balance_usd) for a in CompanyAccount.query.order_by(CompanyAccount.id)]

    def test_both_payment_urls_offer_all_eight_banks_and_require_selection(self):
        for url in ('/pagos','/pagos-diarios'):
            response=self.client.get(url)
            self.assertEqual(response.status_code,200)
            select=re.search(rb'<select name="account_id" required>(.*?)</select>',response.data,re.S)[1]
            self.assertEqual(len(re.findall(rb'<option value="\d+"',select)),8)
            self.assertIn(b'Banco de prueba 8',select)
            self.assertIn(b'Banco de origen',response.data)
            self.assertNotIn(b'cuenta central',response.data)

    def test_each_bank_is_debited_only_when_selected_and_history_is_linked(self):
        original=self.balances()
        for index,aid in enumerate(self.ids):
            self.assertEqual(self.pay(aid,amount='1000').status_code,302)
            after=self.balances()
            for pos,balance in enumerate(after):
                expected=original[pos][1]-(1000 if pos<=index else 0)
                self.assertEqual(balance[1],expected)
                self.assertEqual(balance[2],original[pos][2])
        with app.app_context():
            records=Record.query.filter_by(module='pagos_diarios').order_by(Record.id).all()
            self.assertEqual([r.company_account_id for r in records],self.ids)
            self.assertEqual([json.loads(r.data)['company_account_id'] for r in records],self.ids)
            self.assertEqual(db.session.get(Record,self.rid).status,'Pago parcial')
            self.assertEqual(json.loads(db.session.get(Record,self.rid).data)['saldo'],'92000.00')
            with app.test_request_context():
                session['uid']=self.uid
                sheets=ledgers(CompanyAccount.query.order_by(CompanyAccount.id).all(),paraguay_now().strftime('%Y-%m'),'PYG')
            for sheet in sheets:
                self.assertEqual(len(sheet['entries']),1)
                self.assertEqual(sheet['entries'][0]['amount'],'-1.000')
        response=self.client.get('/pagos-diarios')
        section=re.search(rb'<h2>Historial de pagos registrados</h2>(.*?)</section>',response.data,re.S)[1]
        for number in range(1,9):self.assertIn(('Banco de prueba '+str(number)).encode(),section)

    def test_missing_unknown_or_inactive_bank_does_not_fall_back_to_central(self):
        before=self.balances()
        with app.app_context():
            db.session.get(CompanyAccount,self.ids[1]).active=False;db.session.commit()
        for bank in (None,'','no-es-un-id','999999',self.ids[1]):
            with self.subTest(bank=bank):
                self.assertEqual(self.pay(bank).status_code,302)
                self.assertEqual(self.balances(),before)
                with app.app_context():
                    self.assertEqual(Record.query.filter_by(module='pagos_diarios').count(),0)
                    self.assertEqual(db.session.get(Record,self.rid).status,'Registrado')

    def test_insufficient_selected_balance_is_rejected_even_if_other_banks_have_funds(self):
        with app.app_context():
            db.session.get(CompanyAccount,self.ids[-1]).balance=0;db.session.commit()
        before=self.balances()
        self.pay(self.ids[-1])
        self.assertEqual(self.balances(),before)
        with app.app_context():self.assertEqual(Record.query.filter_by(module='pagos_diarios').count(),0)

    def test_refund_returns_to_original_selected_bank(self):
        before=self.balances()
        self.pay(self.ids[5],amount='25000')
        with app.app_context():pid=Record.query.filter_by(module='pagos_diarios').one().id
        self.assertEqual(self.client.post(f'/pagos/{pid}/eliminar').status_code,302)
        self.assertEqual(self.balances(),before)
        with app.app_context():
            self.assertEqual(Record.query.filter_by(module='pagos_diarios').count(),0)
            ticket=db.session.get(Record,self.rid)
            self.assertEqual(ticket.status,'Pendiente')
            self.assertEqual(Decimal(json.loads(ticket.data)['saldo']),Decimal('100000'))

    def test_expired_session_redirects_payment_pages_to_login(self):
        with self.client.session_transaction() as session:
            session.clear()
        for path in ('/pagos-diarios','/pagos','/registrar-ticket'):
            with self.subTest(path=path):
                response=self.client.get(path)
                self.assertEqual(response.status_code,302)
                self.assertTrue(response.location.startswith('/login?next='),response.location)
        with app.app_context():
            self.assertEqual(Record.query.filter_by(module='pagos_diarios').count(),0)
            from werkzeug.security import generate_password_hash
            db.session.get(User,self.uid).password_hash=generate_password_hash('session-test-password')
            db.session.commit()
        login_url=self.client.get('/pagos-diarios').location
        response=self.client.post(login_url,data={'username':'caja-test','password':'session-test-password'},follow_redirects=True)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.request.path,'/pagos-diarios')
        self.assertIn(b'Banco de origen',response.data)

    def test_expired_session_cannot_submit_or_remove_payments(self):
        before=self.balances()
        with self.client.session_transaction() as session:
            session.clear()
        for path in (f'/pagos/{self.rid}/pagar',f'/pagos/{self.rid}/eliminar','/pagos-diarios/crear','/registrar-ticket'):
            with self.subTest(path=path):
                response=self.client.post(path,data={'account_id':self.ids[0],'importe':'1000'})
                self.assertEqual(response.status_code,302)
                self.assertTrue(response.location.startswith('/login?next='),response.location)
        self.assertEqual(self.balances(),before)
        with app.app_context():
            self.assertEqual(Record.query.filter_by(module='pagos_diarios').count(),0)
