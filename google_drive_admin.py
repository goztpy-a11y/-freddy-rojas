import base64
import hashlib
import json
import os
import secrets
from datetime import datetime
from io import BytesIO

import requests
from cryptography.fernet import Fernet
from flask import abort, flash, redirect, render_template_string, request, session, url_for
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from sqlalchemy import text

from app import app, db, admin_required, current_user, log_action
from backup_admin import _create_full_backup

SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/drive.file",
]
FOLDER_NAME = "Freddy Rojas - Copias de seguridad"
CALLBACK_URI = "https://freddy-rojas.onrender.com/admin/google-drive/callback"


def _ensure_table():
    # Tabla nueva y aislada para la conexión de Google. No modifica tablas existentes.
    with db.engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS freddy_google_drive_connection (
                id INTEGER PRIMARY KEY,
                email VARCHAR(320) NOT NULL,
                token_cipher TEXT NOT NULL,
                folder_id VARCHAR(255) NOT NULL,
                connected_at VARCHAR(40) NOT NULL,
                updated_at VARCHAR(40) NOT NULL
            )
        """))


def _row():
    _ensure_table()
    with db.engine.connect() as connection:
        result = connection.execute(text("""
            SELECT email, token_cipher, folder_id, connected_at
            FROM freddy_google_drive_connection WHERE id = 1
        """)).mappings().first()
        return dict(result) if result else None


def _fernet():
    dedicated_key = os.environ.get("GOOGLE_DRIVE_ENCRYPTION_KEY", "").strip()
    if dedicated_key:
        return Fernet(dedicated_key.encode("ascii"))
    secret = app.config.get("SECRET_KEY", "")
    if not secret or secret == "development-only-change-me":
        raise RuntimeError("Falta GOOGLE_DRIVE_ENCRYPTION_KEY en el servicio.")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def _client_config():
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [os.environ.get("GOOGLE_REDIRECT_URI", CALLBACK_URI)],
        }
    }


def _redirect_uri():
    return os.environ.get("GOOGLE_REDIRECT_URI", CALLBACK_URI).strip()


def _new_flow(state=None, code_verifier=None):
    config = _client_config()
    if not config:
        raise RuntimeError("La conexión todavía está pendiente de configurar las credenciales OAuth de Google.")
    flow = Flow.from_client_config(
        config, scopes=SCOPES, state=state, autogenerate_code_verifier=True
    )
    flow.redirect_uri = _redirect_uri()
    if code_verifier:
        flow.code_verifier = code_verifier
    return flow


def _save_connection(email, credentials_json, folder_id):
    encrypted = _fernet().encrypt(credentials_json.encode("utf-8")).decode("ascii")
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    _ensure_table()
    with db.engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO freddy_google_drive_connection
                (id, email, token_cipher, folder_id, connected_at, updated_at)
            VALUES (1, :email, :token_cipher, :folder_id, :connected_at, :updated_at)
            ON CONFLICT (id) DO UPDATE SET
                email = excluded.email,
                token_cipher = excluded.token_cipher,
                folder_id = excluded.folder_id,
                updated_at = excluded.updated_at
        """), {
            "email": email,
            "token_cipher": encrypted,
            "folder_id": folder_id,
            "connected_at": now,
            "updated_at": now,
        })


def _credentials_and_service(row=None):
    row = row or _row()
    if not row:
        raise RuntimeError("Todavía no hay una cuenta de Google conectada.")
    encrypted = row["token_cipher"].encode("ascii")
    info = json.loads(_fernet().decrypt(encrypted).decode("utf-8"))
    credentials = Credentials.from_authorized_user_info(info, SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleRequest())
        _save_connection(row["email"], credentials.to_json(), row["folder_id"])
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return credentials, service, row


def _create_drive_folder(service):
    folder = service.files().create(
        body={"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"},
        fields="id,name"
    ).execute()
    return folder["id"]


def upload_backup_bytes(raw, filename):
    """Sube a Drive una copia recién generada si hay una cuenta conectada."""
    row = _row()
    if not row:
        return None
    _, service, row = _credentials_and_service(row)
    media = MediaIoBaseUpload(BytesIO(raw), mimetype="application/json", resumable=True)
    return service.files().create(
        body={"name": filename, "parents": [row["folder_id"]]},
        media_body=media,
        fields="id,name,webViewLink"
    ).execute()


@app.get("/admin/google-drive")
@admin_required
def google_drive_settings():
    row = _row()
    configured = bool(_client_config())
    return render_template_string("""
    <!doctype html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Google Drive · Freddy Rojas</title>
    <style>
    *{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:#172b45;font:14px/1.5 system-ui,Arial,sans-serif}
    header{background:#142b46;color:#fff;padding:17px 22px;font-weight:800}
    main{max-width:850px;margin:26px auto;padding:0 15px}.card{background:#fff;border:1px solid #e1e8f0;border-radius:13px;padding:21px;margin-bottom:17px}
    h1{font-size:23px;margin:0 0 14px}h2{font-size:17px;margin:0 0 10px}p{color:#53677e}
    .btn,button{display:inline-block;background:#245fa8;color:#fff;text-decoration:none;padding:11px 15px;border:0;border-radius:8px;font-weight:750;font-size:13px;cursor:pointer}
    .secondary{background:#edf3fa;color:#245fa8}.danger{background:#a8323d}.status{font-weight:800;color:#a36b12}.ok{color:#187347}
    .notice{background:#fff7e5;border:1px solid #f2dfb2;padding:13px;border-radius:9px;color:#79561a;overflow-wrap:anywhere}
    code{overflow-wrap:anywhere}form{display:inline-block;margin:6px 6px 0 0}
    </style></head><body><header>EL TORO S.A. · Freddy Rojas</header><main>
    <p><a class="btn secondary" href="/admin/copias">← Volver a copias de seguridad</a></p>
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% for category, message in messages %}
        <div class="notice" role="status">{{message}}</div>
      {% endfor %}
    {% endwith %}
    <section class="card"><h1>Conexión con Google Drive</h1>
    {% if row %}
      <p class="ok">Cuenta conectada: <b>{{row.email}}</b></p>
      <p>Carpeta de destino: <b>{{folder_name}}</b></p>
      <p>Conexión realizada: {{row.connected_at}}</p>
      <form method="post" action="/admin/google-drive/subir-copia"><button>Crear copia y guardarla en Google Drive</button></form>
      <form method="post" action="/admin/google-drive/desconectar" onsubmit="return confirm('¿Desconectar esta cuenta de Google Drive de Freddy Rojas?');"><button class="danger">Desconectar cuenta</button></form>
    {% else %}
      <p class="status">Cuenta todavía no conectada.</p>
      {% if configured %}
        <p>La aplicación ya tiene las credenciales OAuth configuradas. Cuando tengas tu nueva cuenta de Gmail, podrás conectarla aquí.</p>
        <a class="btn" href="/admin/google-drive/conectar">Conectar cuenta de Google</a>
      {% else %}
        <div class="notice"><b>Preparación lista; falta un paso técnico.</b><br>
        Antes de conectar Gmail hay que crear las credenciales OAuth de tipo aplicación web en Google Cloud, habilitar Google Drive API y cargarlas como variables secretas en Render. No ingreses tu contraseña de Google en esta página.</div>
      {% endif %}
    {% endif %}
    </section>
    <section class="card"><h2>Dirección de retorno para Google</h2>
    <p>Cuando se creen las credenciales OAuth, registrar exactamente esta dirección como URI de redirección autorizada:</p>
    <p><code>{{callback_uri}}</code></p>
    <p>Permiso solicitado: crear y administrar únicamente los archivos que Freddy Rojas genere con esta integración.</p>
    </section></main></body></html>
    """, row=row, configured=configured, callback_uri=_redirect_uri(), folder_name=FOLDER_NAME)


@app.get("/admin/google-drive/conectar")
@admin_required
def google_drive_connect():
    if not _client_config():
        flash("Todavía faltan las credenciales OAuth de Google en Render. La conexión quedó preparada.")
        return redirect(url_for("google_drive_settings"))
    try:
        state = secrets.token_urlsafe(32)
        session["google_drive_oauth_state"] = state
        flow = _new_flow(state)
        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        # PKCE: conservar el verificador generado para usarlo al canjear el código.
        if not flow.code_verifier:
            raise RuntimeError("No se pudo generar el verificador PKCE de Google.")
        session["google_drive_code_verifier"] = flow.code_verifier
        return redirect(authorization_url)
    except Exception:
        flash("No se pudo iniciar la conexión con Google. Revisá la configuración OAuth.")
        return redirect(url_for("google_drive_settings"))


@app.get("/admin/google-drive/callback")
@admin_required
def google_drive_callback():
    expected_state = session.pop("google_drive_oauth_state", None)
    received_state = request.args.get("state")
    if not expected_state or not received_state or not secrets.compare_digest(expected_state, received_state):
        app.logger.warning("Google Drive OAuth: estado de sesión ausente o no coincidente.")
        flash("La sesión de autorización venció o cambió al regresar de Google. Iniciá la conexión nuevamente.")
        return redirect(url_for("google_drive_settings"))
    if request.args.get("error"):
        app.logger.warning("Google Drive OAuth denegado: %s", request.args.get("error"))
        flash("Google no autorizó la conexión. No se guardó ninguna cuenta.")
        return redirect(url_for("google_drive_settings"))
    code_verifier = session.pop("google_drive_code_verifier", None)
    if not code_verifier:
        flash("La sesión perdió la verificación de seguridad de Google. Iniciá la conexión nuevamente.")
        app.logger.warning("Google Drive OAuth: falta el verificador PKCE en la sesión de retorno.")
        return redirect(url_for("google_drive_settings"))
    code = request.args.get("code")
    if not code:
        flash("Google no devolvió el código de autorización. Volvé a intentar.")
        return redirect(url_for("google_drive_settings"))
    stage = "intercambio del permiso con Google"
    try:
        flow = _new_flow(expected_state, code_verifier=code_verifier)
        flow.fetch_token(code=code, code_verifier=code_verifier)
        credentials = flow.credentials
        if not credentials.refresh_token:
            raise RuntimeError("Google no entregó permiso de acceso persistente. Volvé a autorizar y aceptá los permisos solicitados.")
        stage = "validación de la cuenta de Google"
        claims = id_token.verify_oauth2_token(
            credentials.id_token, GoogleRequest(), os.environ["GOOGLE_CLIENT_ID"].strip()
        )
        email = claims.get("email")
        if not email or not claims.get("email_verified"):
            raise RuntimeError("Google no devolvió un correo verificado.")
        stage = "acceso a Google Drive y creación de la carpeta"
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        folder_id = _create_drive_folder(service)
        stage = "cifrado y guardado seguro de la conexión"
        _save_connection(email, credentials.to_json(), folder_id)
        try:
            log_action("conectar Google Drive", "backup", None, "Cuenta de Google Drive conectada: " + email)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("La conexión Drive se guardó, pero falló el registro de auditoría.")
        flash("Conexión exitosa. Cuenta vinculada: " + email)
        app.logger.info("Google Drive conectado correctamente para %s.", email)
    except Exception:
        db.session.rollback()
        app.logger.exception("Falló Google Drive OAuth durante: %s", stage)
        flash("No se pudo completar la conexión. Falló esta etapa: " + stage + ". El detalle técnico quedó registrado.")
    return redirect(url_for("google_drive_settings"))


@app.post("/admin/google-drive/subir-copia")
@admin_required
def google_drive_upload_backup():
    try:
        raw, table_count, row_count = _create_full_backup()
        credentials, service, row = _credentials_and_service()
        filename = "freddy_rojas_respaldo_" + datetime.utcnow().strftime("%Y%m%d_%H%M%S") + ".json"
        media = MediaIoBaseUpload(BytesIO(raw), mimetype="application/json", resumable=True)
        uploaded = service.files().create(
            body={"name": filename, "parents": [row["folder_id"]]},
            media_body=media,
            fields="id,name,webViewLink"
        ).execute()
        log_action(
            "subir copia a Google Drive", "backup", None,
            f"Archivo {filename}; {table_count} tablas; {row_count} filas; Drive ID {uploaded.get('id','')}"
        )
        db.session.commit()
        flash("Copia guardada en Google Drive: " + uploaded.get("name", filename))
    except Exception:
        db.session.rollback()
        flash("No se pudo subir la copia. Verificá la conexión de Google Drive e intentá nuevamente.")
    return redirect(url_for("google_drive_settings"))


@app.post("/admin/google-drive/desconectar")
@admin_required
def google_drive_disconnect():
    try:
        row = _row()
        if row:
            try:
                credentials, _, _ = _credentials_and_service(row)
                token = credentials.refresh_token or credentials.token
                if token:
                    requests.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": token},
                        headers={"content-type": "application/x-www-form-urlencoded"},
                        timeout=10,
                    )
            except Exception:
                pass
            with db.engine.begin() as connection:
                connection.execute(text("DELETE FROM freddy_google_drive_connection WHERE id = 1"))
            log_action("desconectar Google Drive", "backup", None, "Se desconectó la cuenta de Google Drive.")
            db.session.commit()
        flash("La cuenta quedó desconectada de Freddy Rojas.")
    except Exception:
        db.session.rollback()
        flash("No se pudo completar la desconexión.")
    return redirect(url_for("google_drive_settings"))


@app.after_request
def add_google_drive_navigation(response):
    try:
        user = current_user()
        if user and user.role == "admin" and response.mimetype == "text/html":
            html = response.get_data(as_text=True)
            link = '<a href="/admin/google-drive">Google Drive</a>'
            if "</nav>" in html and link not in html:
                response.set_data(html.replace("</nav>", link + "</nav>", 1))
    except Exception:
        pass
    return response
