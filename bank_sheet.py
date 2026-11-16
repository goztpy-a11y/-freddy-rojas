"""Planilla bancaria de Freddy Rojas; conserva cuentas y operaciones existentes."""
import hmac
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from flask import abort, flash, jsonify, make_response, redirect, render_template_string, request, session, url_for
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from app import app, db, BankSheetEntry, CompanyAccount, Record, BASE, current_user, log_action, paraguay_now, local_time

MONTHS = ('Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre')
LEGACY_MODULES = ('pagos_diarios', 'pagos_cuentas', 'cobros_cuentas', 'gastos', 'ventas_caja', 'caja_chica', 'pagos_cliente_admin')


def money(value):
    value = Decimal(str(value or 0))
    integer, fraction = format(abs(value).quantize(Decimal('0.01')), '.2f').split('.')
    display = format(int(integer), ',').replace(',', '.')
    if fraction != '00':
        display += ',' + fraction.rstrip('0')
    return ('-' if value < 0 else '') + display


def parse_amount(value, currency):
    raw = str(value).strip().replace(' ', '')
    pattern = r'[+-]?(?:\d+|\d{1,3}(?:\.\d{3})+)' + (r'(?:,\d{1,2})?' if currency == 'USD' else '')
    if not re.fullmatch(pattern, raw):
        raise ValueError('Escribí un monto válido, por ejemplo -20.000' + (' o 25,50 USD.' if currency == 'USD' else '.'))
    amount = Decimal(raw.replace('.', '').replace(',', '.'))
    if abs(amount) > Decimal('9000000000000'):
        raise ValueError('El monto es demasiado grande.')
    return amount


def selection():
    month = request.args.get('month') or paraguay_now().strftime('%Y-%m')
    if not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])', month) or month[:4] == '0000':
        abort(400)
    currency = request.args.get('currency', 'PYG')
    if currency not in ('PYG', 'USD'):
        abort(400)
    return month, currency


def ensure_accounts():
    # La incorporación de bancos es aditiva; no cambia nombres, IDs ni saldos anteriores.
    if db.engine.dialect.name == 'postgresql':
        db.session.execute(text('SELECT pg_advisory_xact_lock(714032605)'))
    accounts = CompanyAccount.query.filter_by(active=True).order_by(CompanyAccount.id).all()
    for index in range(len(accounts), 5):
        db.session.add(CompanyAccount(name='Banco ' + str(index + 1), bank='', number='', currency='PYG',
                                     opening_balance=0, balance=0, opening_balance_usd=0, balance_usd=0))
    db.session.commit()
    return CompanyAccount.query.filter_by(active=True).order_by(CompanyAccount.id).all()


def legacy_entries(accounts, currency):
    entries = {account.id: [] for account in accounts}
    for record in Record.query.filter(Record.module.in_(LEGACY_MODULES)).order_by(Record.id).all():
        try:
            data = json.loads(record.data or '{}')
            aid = int(record.company_account_id or data.get('company_account_id') or data.get('cuenta_id') or 0)
        except (ValueError, TypeError):
            continue
        if aid not in entries or (data.get('moneda') or 'PYG').upper() != currency:
            continue
        if record.module == 'ventas_caja' and data.get('medio') != 'Transferencia':
            continue
        if record.module == 'caja_chica' and data.get('origen') != 'transferencia_bancaria':
            continue
        amount = Decimal(str(record.amount or 0))
        if record.module not in ('cobros_cuentas', 'ventas_caja'):
            amount = -amount
        date = str(data.get('fecha') or '')[:10]
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
            date = local_time(record.created_at).strftime('%Y-%m-%d')
        entries[aid].append(dict(key='record-' + str(record.id), date=date,
            description=record.title, amount=amount, source='Movimiento del sistema', editable=False,
            detail_url=None if current_user().role == 'banco' else url_for('view_record', rid=record.id),
            order=(date, record.created_at.isoformat(), 0, record.id)))
    return entries


def ledgers(accounts, month, currency):
    historic = legacy_entries(accounts, currency)
    names = {account.id: account.name or 'Banco ' + str(index + 1) for index, account in enumerate(accounts)}
    rows = BankSheetEntry.query.filter(BankSheetEntry.account_id.in_(names), BankSheetEntry.currency == currency).order_by(BankSheetEntry.id).all()
    for row in rows:
        entry = dict(key=row.entry_key, date=row.entry_date, description=row.description,
                     amount=Decimal(str(row.amount)), version=row.version, editable=row.kind == 'manual',
                     order=(row.entry_date, row.created_at.isoformat(), 1, row.id))
        if row.kind == 'transfer':
            receiving = row.amount > 0
            entry.update(source='Transferencia', can_edit=True,
                         source_account_id=row.counterpart_id if receiving else row.account_id,
                         destination_account_id=row.account_id if receiving else row.counterpart_id,
                         raw_amount=str(abs(row.amount)))
        elif row.kind == 'adjustment':
            entry.update(source='Ajuste manual de saldo')
        historic[row.account_id].append(entry)
    result = []
    for account in accounts:
        entries = sorted(historic[account.id], key=lambda entry: entry['order'])
        current = Decimal(str(account.balance_usd if currency == 'USD' else account.balance))
        opening = current - sum((entry['amount'] for entry in entries), Decimal(0))
        month_opening = opening + sum((entry['amount'] for entry in entries if entry['date'][:7] < month), Decimal(0))
        closing = month_opening + sum((entry['amount'] for entry in entries if entry['date'][:7] == month), Decimal(0))
        running = opening
        for entry in entries:
            running += entry['amount']
            entry['balance'] = money(running)
            entry['amount'] = money(entry['amount'])
            entry.pop('order')
        result.append(dict(id=account.id, name=names[account.id], balance=money(current), balance_raw=str(current),
                           opening=money(month_opening), closing=money(closing), month=month,
                           months=sorted({entry['date'][:7] for entry in entries}, reverse=True),
                           entries=[entry for entry in entries if entry['date'][:7] == month]))
    return result


def entry_payload(row):
    return dict(key=row.entry_key, date=row.entry_date, description=row.description,
                amount=money(row.amount), version=row.version)


def lock_accounts(ids):
    accounts = CompanyAccount.query.filter(CompanyAccount.id.in_(ids)).order_by(CompanyAccount.id).with_for_update().populate_existing().all()
    if {account.id for account in accounts if account.active} != set(ids):
        raise ValueError('No se encontró una cuenta bancaria activa.')
    return {account.id: account for account in accounts}


def change_balance(account, currency, delta):
    column = CompanyAccount.balance_usd if currency == 'USD' else CompanyAccount.balance
    current = Decimal(str(account.balance_usd if currency == 'USD' else account.balance))
    if delta < 0 and current + delta < 0:
        raise ValueError('El monto supera el saldo disponible de este banco.')
    db.session.execute(db.update(CompanyAccount).where(CompanyAccount.id == account.id).values({column: column + delta}))


def save_sheet(month, currency):
    token = session.get('bank_sheet_csrf', '')
    if not token or not hmac.compare_digest(token, request.headers.get('X-Bank-CSRF', '') if request.is_json else request.form.get('csrf', '')):
        return jsonify(ok=False, error='La sesión cambió. Recargá la página; el borrador se conserva.'), 403
    data = request.get_json(silent=True) if request.is_json else request.form
    if not isinstance(data, dict) and not hasattr(data, 'getlist'):
        return jsonify(ok=False, error='Datos inválidos.'), 400
    try:
        action = data.get('action')
        aid = int(data.get('source_account_id') if action == 'transfer' else data.get('account_id', 0))
        destination = int(data.get('destination_account_id', 0)) if action == 'transfer' else None
        row = None
        key = str(data.get('key', ''))
        if action in ('save_row', 'edit_transfer', 'transfer'):
            if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', key):
                raise ValueError('El movimiento no tiene un identificador válido. Recargá la página.')
            row = BankSheetEntry.query.filter_by(entry_key=key).first()
        if action == 'edit_transfer':
            if not row or row.kind != 'transfer' or row.account_id != aid or row.currency != currency:
                raise ValueError('No se encontró la transferencia.')
            destination = row.counterpart_id
        accounts = lock_accounts({aid, destination} if destination else {aid})
        account = accounts[aid]
        if action == 'rename_account':
            name = str(data.get('name', '')).strip()
            if not name or len(name) > 100:
                raise ValueError('Escribí el nombre del banco (hasta 100 caracteres).')
            if account.name not in (data.get('expected_name'), name):
                db.session.rollback()
                return jsonify(ok=False, error='Otro usuario cambió el nombre. Recargá la página.'), 409
            account.name = name
            log_action('editar nombre de banco', 'cuentas_empresa', aid, name)
            db.session.commit()
            return jsonify(ok=True, name=name)
        if action == 'set_balance':
            value = parse_amount(data.get('amount', ''), currency)
            current = Decimal(str(account.balance_usd if currency == 'USD' else account.balance))
            if current != Decimal(str(data.get('expected_balance'))):
                db.session.rollback()
                return jsonify(ok=False, error='El saldo cambió. Actualizá la página antes de ajustarlo.'), 409
            if value < 0:
                raise ValueError('El saldo no puede ser negativo.')
            delta = value - current
            if delta:
                change_balance(account, currency, delta)
                db.session.add(BankSheetEntry(account_id=aid, entry_key=str(uuid4()), currency=currency,
                    entry_date=paraguay_now().strftime('%Y-%m-%d'), description='Saldo corregido: ' + money(current) + ' → ' + money(value),
                    amount=delta, kind='adjustment', user_id=current_user().id))
        elif action == 'save_row':
            # Releer luego del bloqueo de cuenta: dos dispositivos no pueden pisar versiones.
            row = BankSheetEntry.query.filter_by(entry_key=key).populate_existing().first()
            if row and (row.account_id != aid or row.currency != currency or row.kind != 'manual'):
                raise ValueError('La fila pertenece a otro banco o moneda.')
            date = str(data.get('date', ''))
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
                raise ValueError('Indicá una fecha válida.')
            datetime.strptime(date, '%Y-%m-%d')
            description = str(data.get('description', '')).strip()
            if not description or len(description) > 240:
                raise ValueError('Escribí la descripción (hasta 240 caracteres).')
            amount = parse_amount(data.get('amount', ''), currency)
            same = row and (row.entry_date, row.description, row.amount) == (date, description, amount)
            if not same and int(data.get('version', 0)) != (row.version if row else 0):
                db.session.rollback()
                return jsonify(ok=False, error='Otro usuario modificó esta fila.', entry=entry_payload(row) if row else None), 409
            if not same:
                change_balance(account, currency, amount - (row.amount if row else 0))
                if row:
                    row.entry_date, row.description, row.amount = date, description, amount
                    row.version += 1
                    row.updated_at, row.user_id = paraguay_now(), current_user().id
                else:
                    row = BankSheetEntry(account_id=aid, entry_key=key, currency=currency, entry_date=date,
                                         description=description, amount=amount, kind='manual', user_id=current_user().id)
                    db.session.add(row)
        elif action == 'transfer':
            if aid == destination:
                raise ValueError('Elegí otro banco como destino.')
            # Bloquear siempre por ID para evitar deadlocks entre transferencias opuestas.
            previous = BankSheetEntry.query.filter_by(entry_key=key).first()
            amount = parse_amount(data.get('amount', ''), currency)
            description = str(data.get('description', '')).strip() or 'Transferencia entre bancos'
            if amount <= 0 or len(description) > 240:
                raise ValueError('Revisá el monto y la descripción de la transferencia.')
            if previous:
                if (previous.kind, previous.account_id, previous.counterpart_id, previous.currency, previous.amount, previous.description) != ('transfer', aid, destination, currency, -amount, description):
                    raise ValueError('Este identificador ya corresponde a otro movimiento.')
            else:
                change_balance(account, currency, -amount)
                change_balance(accounts[destination], currency, amount)
                for source, target, effect, entry_key in ((aid, destination, -amount, key), (destination, aid, amount, str(uuid4()))):
                    db.session.add(BankSheetEntry(account_id=source, counterpart_id=target, transfer_key=key,
                        entry_key=entry_key, currency=currency, entry_date=paraguay_now().strftime('%Y-%m-%d'),
                        description=description, amount=effect, kind='transfer', user_id=current_user().id))
        elif action == 'edit_transfer':
            pair = BankSheetEntry.query.filter_by(transfer_key=row.transfer_key).order_by(BankSheetEntry.id).populate_existing().all()
            row = next(item for item in pair if item.entry_key == key)
            if len(pair) != 2:
                raise ValueError('La transferencia está incompleta.')
            amount = parse_amount(data.get('amount', ''), currency)
            description = str(data.get('description', '')).strip()
            if amount <= 0 or not description or len(description) > 240:
                raise ValueError('Revisá el monto y la descripción.')
            same = abs(row.amount) == amount and row.description == description
            if not same and row.version != int(data.get('version', 0)):
                db.session.rollback()
                return jsonify(ok=False, error='Otro usuario modificó la transferencia. Recargá la página.'), 409
            if not same:
                for item in pair:
                    effect = amount if item.amount > 0 else -amount
                    change_balance(accounts[item.account_id], currency, effect - item.amount)
                    item.amount, item.description = effect, description
                    item.version += 1
                    item.updated_at, item.user_id = paraguay_now(), current_user().id
        else:
            raise ValueError('Acción no reconocida.')
        db.session.flush()
        log_action('editar planilla bancaria' if action != 'transfer' else 'transferir entre bancos', 'cuentas_empresa', aid,
                   action + ' · ' + currency + ' · ' + (key or str(data.get('amount', ''))))
        db.session.commit()
        all_accounts = CompanyAccount.query.filter_by(active=True).order_by(CompanyAccount.id).all()
        sheets = ledgers(all_accounts, month, currency)
        return jsonify(ok=True, entry=entry_payload(row) if row else None,
                       ledger=next(sheet for sheet in sheets if sheet['id'] == aid), ledgers=sheets)
    except (ValueError, TypeError, InvalidOperation, OverflowError) as exc:
        db.session.rollback()
        return jsonify(ok=False, error='Revisá los datos: ' + str(exc)), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify(ok=False, error='Otro dispositivo guardó este movimiento. Reintentá para recuperar su versión.'), 409


def accounts_page():
    month, currency = selection()
    if request.method == 'POST':
        result = save_sheet(month, currency)
        if request.is_json:
            return result
        response = app.make_response(result)
        payload = response.get_json() or {}
        flash('Transferencia registrada.' if payload.get('ok') else payload.get('error', 'No se pudo registrar la transferencia.'))
        return redirect(url_for('module_page', module='cuentas_empresa', month=month, currency=currency))
    accounts = ensure_accounts()
    session.setdefault('bank_sheet_csrf', uuid4().hex)
    sheets = ledgers(accounts, month, currency)
    current = paraguay_now().strftime('%Y-%m')
    months = sorted({month, current} | {m for sheet in sheets for m in sheet['months']}, reverse=True)
    config = dict(accounts=sheets, csrf=session['bank_sheet_csrf'], month=month, currency=currency,
                  money_label='USD ' if currency == 'USD' else 'Gs. ', user_id=current_user().id,
                  today=paraguay_now().strftime('%Y-%m-%d') if month == current else month + '-01',
                  url=url_for('module_page', module='cuentas_empresa', month=month, currency=currency))
    payload = json.dumps(config, ensure_ascii=False).replace('<', '\\u003c')
    body = '''<link rel="stylesheet" href="/static/bank_sheet.css?v=fr-five-1">
    <section class="bank-sheet-header"><div><h2>Cuentas bancarias</h2></div><span id="bank-save-summary" role="status" aria-live="polite">Guardado automático</span></section>
    <section class="bank-month-history"><form method="get">
    <label for="bank-month">Historial por mes</label><select id="bank-month" name="month">{% for m in months %}<option value="{{m}}" {{'selected' if m==month else ''}}>{{month_name(m)}}</option>{% endfor %}</select>
    <label for="bank-currency">Moneda</label><select id="bank-currency" name="currency"><option value="PYG" {{'selected' if currency=='PYG' else ''}}>Guaraníes</option><option value="USD" {{'selected' if currency=='USD' else ''}}>Dólares</option></select>
    <button type="submit">Ver mes</button><a href="{{url_for('module_page',module='cuentas_empresa',currency=currency)}}">Mes actual</a></form><p>Mostrando: <strong>{{month_name(month)}}</strong></p></section>
    <div id="bank-tabs" class="bank-tabs" role="tablist" aria-label="Bancos"></div><div id="bank-sheets"></div>
    <script id="bank-sheet-data" type="application/json">''' + payload + '''</script><script src="/static/bank_sheet.js?v=fr-five-1" defer></script>
    </main></body></html>'''
    response = make_response(render_template_string(BASE + body, title='Cuentas bancarias', months=months, month=month, currency=currency,
                               month_name=lambda value: MONTHS[int(value[5:]) - 1] + ' ' + value[:4]))
    response.headers['Cache-Control'] = 'no-store'
    return response
