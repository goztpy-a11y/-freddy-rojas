import base64
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from flask import Response, abort, flash, render_template_string, send_file
from sqlalchemy import inspect, text

from app import app, db, admin_required, current_user, log_action, AuditLog


def _backup_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        return {"__type__": "bytes_base64", "value": base64.b64encode(value).decode("ascii")}
    return value


def verify_backup_bytes(raw):
    """Comprueba integridad estructural y legibilidad de una copia JSON completa."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("La copia no es un JSON UTF-8 legible.") from exc
    if not isinstance(payload, dict) or payload.get("format") != "freddy-rojas-full-backup-v1":
        raise ValueError("El formato de la copia no es válido.")
    tables = payload.get("tables")
    if not isinstance(tables, dict) or not tables:
        raise ValueError("La copia no contiene tablas.")
    counted_rows = 0
    for table_name, table in tables.items():
        if not isinstance(table, dict):
            raise ValueError("Estructura inválida en tabla: " + str(table_name))
        columns, rows = table.get("columns"), table.get("rows")
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise ValueError("Faltan columnas o filas en tabla: " + str(table_name))
        if table.get("row_count") != len(rows):
            raise ValueError("La cantidad de filas no coincide en tabla: " + str(table_name))
        counted_rows += len(rows)
    if payload.get("table_count") != len(tables):
        raise ValueError("La cantidad de tablas no coincide.")
    if payload.get("total_rows") != counted_rows or counted_rows <= 0:
        raise ValueError("La cantidad total de registros no coincide o la copia está vacía.")
    return {
        "table_count": len(tables),
        "total_rows": counted_rows,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _create_full_backup():
    inspector = inspect(db.engine)
    table_names = sorted(inspector.get_table_names())
    tables = {}
    with db.engine.connect() as connection:
        for table_name in table_names:
            quoted = db.engine.dialect.identifier_preparer.quote(table_name)
            rows = connection.execute(text(f"SELECT * FROM {quoted}")).mappings().all()
            columns = inspector.get_columns(table_name)
            tables[table_name] = {
                "columns": [
                    {"name": column["name"], "type": str(column["type"]), "nullable": column.get("nullable", True)}
                    for column in columns
                ],
                "row_count": len(rows),
                "rows": [
                    {key: _backup_value(value) for key, value in row.items()}
                    for row in rows
                ],
            }
    payload = {
        "format": "freddy-rojas-full-backup-v1",
        "application": "Freddy Rojas - El Toro S.A.",
        "created_at": datetime.now().astimezone().isoformat(),
        "database_engine": db.engine.dialect.name,
        "table_count": len(table_names),
        "total_rows": sum(table["row_count"] for table in tables.values()),
        "tables": tables,
        "restore_note": "Respaldo de datos completo. Mantener en un lugar privado y seguro. No editar manualmente.",
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return raw, payload["table_count"], payload["total_rows"]


@app.get("/admin/copias")
@admin_required
def backup_center():
    history = AuditLog.query.filter_by(module="backup").order_by(AuditLog.created_at.desc()).limit(20).all()
    return render_template_string("""
    <!doctype html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Copias de seguridad · Freddy Rojas</title>
    <style>
    *{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:#172b45;font:14px/1.5 system-ui,Arial,sans-serif}
    header{background:#142b46;color:#fff;padding:17px 22px;font-weight:800}
    main{max-width:900px;margin:28px auto;padding:0 16px}.card{background:#fff;border:1px solid #e1e8f0;border-radius:14px;padding:22px;margin-bottom:18px;box-shadow:0 5px 18px rgba(22,46,75,.035)}
    h1{font-size:24px;margin:0 0 16px}h2{font-size:18px;margin:0 0 12px}p{color:#52657b}
    .btn{display:inline-block;background:#245fa8;color:white;text-decoration:none;padding:12px 17px;border-radius:9px;font-weight:750}
    .btn:hover{background:#194b86}.warning{background:#fff7e5;border:1px solid #f2dfb2;padding:13px;border-radius:9px;color:#79561a}
    table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:11px;border-bottom:1px solid #e8edf3}th{background:#f4f7fb;font-size:11px;text-transform:uppercase}
    .actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:17px}.back{color:#245fa8;text-decoration:none;font-weight:700}
    @media(max-width:600px){.card{padding:16px}h1{font-size:21px}table{font-size:12px}}
    </style></head><body><header>EL TORO S.A. · Freddy Rojas</header><main>
    <p><a class="back" href="/">← Volver al inicio</a></p>
    <section class="card"><h1>Copias de seguridad</h1>
    <p>Generá y descargá una copia de seguridad de la información almacenada en Freddy Rojas.</p>
    <div class="warning"><b>Importante:</b> el archivo puede contener información empresarial y credenciales protegidas. Guardalo en un lugar privado y no lo compartas.</div>
    <div class="actions"><a class="btn" href="/admin/respaldo.json">Crear y descargar copia completa</a><a class="btn" href="/admin/google-drive">Configurar Google Drive</a></div>
    </section>
    <section class="card"><h2>Historial de copias descargadas</h2>
    <table><thead><tr><th>Fecha y hora</th><th>Usuario</th><th>Resultado</th></tr></thead><tbody>
    {% for item in history %}<tr><td>{{item.created_at.strftime('%d/%m/%Y %H:%M:%S')}}</td><td>{{item.user_id}}</td><td>{{item.detail}}</td></tr>
    {% else %}<tr><td colspan="3">Todavía no hay copias descargadas desde esta pantalla.</td></tr>{% endfor %}
    </tbody></table></section>
    </main></body></html>
    """, history=history)


def backup_export_full():
    raw, table_count, row_count = _create_full_backup()
    verification = verify_backup_bytes(raw)
    digest = verification["sha256"]
    log_action("crear copia completa", "backup", None,
               f"Descarga completa: {table_count} tablas, {row_count} filas, SHA-256 {digest}")
    filename = "freddy_rojas_respaldo_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
    try:
        # Si Google Drive ya está conectado, guardar también esta misma copia allí.
        from google_drive_admin import upload_backup_bytes
        uploaded = upload_backup_bytes(raw, filename)
        if uploaded:
            log_action("subir copia a Google Drive", "backup", None,
                       f"Archivo guardado en Drive: {uploaded.get('name', filename)}")
            flash("La copia también se guardó en Google Drive.")
    except Exception:
        flash("La copia se descargó, pero no se pudo guardar en Google Drive. Revisá la conexión.")
    db.session.commit()
    return send_file(BytesIO(raw), mimetype="application/json", as_attachment=True, download_name=filename)


# Reemplaza la exportación antigua (parcial) manteniendo su URL de descarga.
app.view_functions["backup_export"] = admin_required(backup_export_full)


@app.after_request
def add_backup_navigation(response):
    user = current_user()
    if user and user.role == "admin" and response.mimetype == "text/html":
        try:
            html = response.get_data(as_text=True)
            link = '<a href="/admin/copias">Copias de seguridad</a>'
            if "</nav>" in html and link not in html:
                response.set_data(html.replace("</nav>", link + "</nav>", 1))
        except Exception:
            pass
    return response
