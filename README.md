# Freddy Rojas

Sistema independiente para la gestión del negocio de Freddy Rojas. Este repositorio no pertenece a los sistemas El Toro Reciclados, Sistema de Recepción, Sistema de Inventario ni Localcito.

## Estado
- Base web inicial en Flask.
- Endpoint de salud: `/health`.
- Configuración de despliegue gratuito en Render mediante `render.yaml`.
- Los módulos de negocio, inicio de sesión, permisos y base de datos todavía deben desarrollarse y probarse antes de registrar datos reales.

## Ejecutar localmente
```bash
pip install -r requirements.txt
python app.py
```

## Despliegue
Usar el Blueprint de Render con este repositorio y confirmar que el servicio seleccionado sea `freddy-rojas` y el plan `Free`. No crear base de datos de pago sin autorización explícita.
