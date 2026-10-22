# El Toro S.A.

Sistema independiente de gestión empresarial de El Toro S.A. Este repositorio no pertenece a El Toro Reciclados, Sistema de Recepción, Sistema de Inventario ni Localcito.

## Módulos incluidos en la primera versión de trabajo
- Administración de usuarios, roles y áreas; acceso validado en el servidor.
- Caja: clientes/proveedores, tickets de entrada, cantidades, materiales y solicitudes de pago.
- Materiales: precios y stock. Solo administración puede crear materiales o cambiar precios; el cambio queda auditado y los tickets existentes conservan su precio aplicado.
- Cuentas bancarias de El Toro S.A. separadas de los datos bancarios del cliente.
- Solicitudes de pago con estados pendiente, autorizado, rechazado y pagado. La autorización no descuenta saldo; el descuento ocurre al registrar el pago ejecutado y una sola vez.
- Tesorería: cuentas por pagar, cuentas por cobrar, cheques adelantados y movimientos de pago.
- Inventario: compras, ventas/salidas, stock, repuestos hidráulicos y movimientos.
- Gastos.
- Combustible por camión, con fecha/hora, cantidad, costo y odómetro.
- Gomería/servicios por camión.
- Auditoría de operaciones con usuario, fecha/hora y detalles.

## Roles y áreas
Administrador, Caja, Tesorería, Estación de servicio, Gomería, Inventario y Auditoría. Administración puede asignar áreas adicionales a cada usuario. El administrador es el único que administra los precios y crea las cuentas bancarias de la empresa.

## Estado importante antes de usar
La primera versión de trabajo está desplegada en Render Free para pruebas. **No ingresar datos financieros ni operaciones reales todavía.** Sin `DATABASE_URL`, la aplicación usa SQLite local, y el almacenamiento local de un servicio gratuito de Render no es persistente ante ciertos reinicios o despliegues. Primero debe conectarse una base de datos persistente y configurarse y probarse una copia de seguridad.

La contraseña inicial de administración se configura en Render mediante las variables `ADMIN_USERNAME` y `ADMIN_PASSWORD`; no hay contraseña pública predeterminada. Configurar también `SECRET_KEY` y `DATABASE_URL` en el panel de Render antes de utilizar el sistema. Nunca guardar secretos en este repositorio.

## Ejecución local
```bash
pip install -r requirements.txt
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD='use-una-clave-larga-y-unica'
python app.py
```

## Despliegue
Servicio Render: `freddy-rojas`, plan Free, rama `main`. El archivo `render.yaml` documenta la configuración para reproducir el despliegue. No crear bases de datos ni otros servicios pagos sin autorización explícita.
