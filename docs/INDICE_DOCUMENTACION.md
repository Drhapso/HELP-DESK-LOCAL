# Documentación del proyecto

## Manuales operativos

- [Manual de usuario](MANUAL_USUARIOS.md): acceso, registro y seguimiento por radicado.
- [Manual del administrador TI](MANUAL_ADMIN_TI.md): consola, cuentas, tarea Windows, firewall, backup y soporte.
- [Migración entre unidades](MIGRACION_ENTRE_UNIDADES.md): preflight de red/dominio, modos de migración, TLS, traslado de SQLite y rollback.
- [Índice HTML para abrir en navegador](INDICE_DOCUMENTACION.html).
- [Manual de usuario HTML](MANUAL_USUARIOS.html).
- [Manual de administrador TI HTML](MANUAL_ADMIN_TI.html).
- [Guía de migración HTML](MIGRACION_ENTRE_UNIDADES.html).

Los mismos HTML se sirven desde el portal LAN en `/docs/INDICE_DOCUMENTACION.html`, `/docs/MANUAL_USUARIOS.html`, `/docs/MANUAL_ADMIN_TI.html` y `/docs/MIGRACION_ENTRE_UNIDADES.html`. Solo esos cuatro nombres están permitidos por el servidor; el directorio del proyecto no se expone como archivos libres.
- [Documentación del sistema](../DOCUMENTACION_SISTEMA.md): arquitectura y estado técnico implementado.
- [README e instalación](../README.md): instalación, acceso LAN actual, pruebas y límites.
- [Changelog](../CHANGELOG.md): registro de cambios.

## Estado actual resumido

- Cliente: `http://192.0.2.10:8080/`.
- Consola: `http://192.0.2.10:8080/login`.
- Persistencia de tickets: SQLite central.
- Inicio automático: tarea `MesaSoporteS6-LAN` ejecutada como SYSTEM.
- Firewall actual: TCP 8080, perfil Domain, origen `192.0.2.0/24`.
- Seguridad del transporte: HTTP no cifra datos; solo piloto de LAN confiable. Para otras unidades/subredes, completar HTTPS institucional antes de abrir conectividad.
