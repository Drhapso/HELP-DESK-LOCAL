# Manual del administrador TI

## Alcance del servicio actual

- Aplicación: Flask en `server.py`; Waitress sirve el modo LAN.
- Portal cliente: `http://192.0.2.10:8080/` (el archivo `index.html`).
- Consola técnica: `http://192.0.2.10:8080/login`.
- Base de tickets: `D:\HELP DESK TELEMATICA\instance\helpdesk.sqlite3`.
- Tarea de inicio: `MesaSoporteS6-LAN`, ejecutada como `SYSTEM` al arrancar Windows.
- IP de escucha: `192.0.2.10:8080` solamente.
- Firewall: regla `MesaSoporteS6-LAN-HTTP`, TCP 8080, perfil Domain, origen `192.0.2.0/24`.

> HTTP no cifra solicitudes, credenciales ni tickets. Este modo es un piloto para la LAN confiable de la unidad, no un despliegue entre sedes ni acceso por Internet. Para esos usos se requiere TLS institucional aprobado.

## Consola y flujo de tickets

1. Abra `/login` e inicie sesión con una cuenta autorizada.
2. La consola `/admin` valida la sesión en el servidor. La lista de tickets se obtiene de SQLite; leer, cambiar estado, asignar técnico y agregar notas requiere sesión y protección CSRF.
3. Revise la bandeja, filtre por estado/categoría y busque por radicado o texto.
4. En el detalle, actualice el estado/asignación y guarde notas técnicas. Los cambios quedan en la base central.
5. Confirme que el navegador muestre éxito del servidor; ante error de red no asuma que se guardó.

Los estados admitidos por la API son `Abierto`, `En Proceso`, `En Espera`, `Resuelto` y `Cancelado`. Los radicados se generan como `S6-AAAA-NNNNNN`.

### Funciones aún no centralizadas

- El inventario, directorio de agentes y preferencias de la consola siguen en `localStorage` del navegador administrador; no se comparten automáticamente entre estaciones.
- Las imágenes JPEG, PNG y WebP quedan asociadas al ticket y se consultan desde el detalle administrativo. El backend limita cada imagen a 900 KB y el total por ticket a 5 MB.
- No hay cálculo de SLA de backend ni notificaciones automáticas por correo.
- El catálogo SQL de `database_schema.sql` es legado de referencia; el runtime crea su propio esquema SQLite desde `server.py`.
- La interfaz no ofrece gestión/recuperación de cuentas ni consulta de estado del solicitante.

No anuncie esas funciones como activas ni marque una notificación como enviada. No introduzca contraseñas, tokens SMTP, claves OAuth o credenciales de dominio en la configuración del navegador.

## Cuentas administrativas

El acceso utiliza usuarios de la tabla `users`, con roles `admin` o `technician`. No hay cuenta ni contraseña predeterminadas en el código. El alta inicial se hace de forma interactiva desde PowerShell elevado en la raíz del proyecto:

```powershell
Set-Location 'D:\HELP DESK TELEMATICA'
.\.venv\Scripts\python.exe server.py create-admin
```

El programa pide nombre de usuario y contraseña (mínimo 14 caracteres) sin mostrarlos. Las contraseñas se almacenan como PBKDF2-HMAC-SHA256 con salt. No comparta ni pegue contraseñas en tickets, scripts, documentación o chat. La consola aún no tiene función de restablecimiento/desactivación de usuarios; coordine recuperación con el responsable técnico y proteja una copia antes de cualquier operación directa de base.

## Comprobar estado y reiniciar

Ejecute PowerShell como administrador:

```powershell
Get-ScheduledTask -TaskName MesaSoporteS6-LAN
Get-ScheduledTaskInfo -TaskName MesaSoporteS6-LAN
Get-NetTCPConnection -State Listen -LocalPort 8080
Invoke-WebRequest 'http://192.0.2.10:8080/' -UseBasicParsing
```

Estado normal: la tarea está `Running`, el listener usa `192.0.2.10:8080` y la página devuelve HTTP 200.

Reiniciar la tarea:

```powershell
Restart-ScheduledTask -TaskName MesaSoporteS6-LAN
```

Después confirme listener y URL. Si el estado no vuelve a `Running`, revise `Get-ScheduledTaskInfo`; verifique que la IP continúe asignada, que el puerto 8080 esté libre y que `.venv\Scripts\python.exe` y `instance\helpdesk.sqlite3` existan.

La tarea arranca con Windows bajo SYSTEM, tiene inicio retrasado hasta 30 segundos, no termina por límite de tiempo y reintenta cinco veces con intervalos de un minuto. Para detener el servicio temporalmente, use `Stop-ScheduledTask -TaskName MesaSoporteS6-LAN` y compruebe que desaparezca el listener. La regla de firewall permanece mientras exista la tarea; no la quite para una detención breve.

## Firewall y exposición

Compruebe la regla:

```powershell
Get-NetFirewallRule -DisplayName MesaSoporteS6-LAN-HTTP |
  Get-NetFirewallAddressFilter
Get-NetFirewallRule -DisplayName MesaSoporteS6-LAN-HTTP |
  Get-NetFirewallPortFilter
```

Debe ser entrada TCP 8080, perfil Domain y origen `192.0.2.0/24`. No cree reglas `Any`, no abra 80/443 sin binding y certificado correctos y no enlace Waitress a `0.0.0.0`. La tarea valida la IP privada, el consentimiento explícito al modo HTTP y la regla antes de servir.

El archivo de clave de sesión está en `C:\ProgramData\MesaSoporteS6\lan-session-secret.txt`; la carpeta y el archivo permiten acceso solo a SYSTEM y Administradores. La tarea no guarda una contraseña de usuario. No borre ni regenere ese secreto durante operación: se invalidarían las sesiones.

## Respaldo de tickets

La SQLite usa WAL. Para una copia coherente, detenga la tarea y confirme que ya no hay listener antes de copiar/respaldar:

```powershell
Stop-ScheduledTask -TaskName MesaSoporteS6-LAN
Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue
```

Use la API de backup de SQLite desde el entorno virtual:

```powershell
@'
import sqlite3
source = sqlite3.connect(r"D:\HELP DESK TELEMATICA\instance\helpdesk.sqlite3")
backup = sqlite3.connect(r"D:\Backups\helpdesk-YYYYMMDD.sqlite3")
source.backup(backup)
backup.close()
source.close()
'@ | .\.venv\Scripts\python.exe -
```

Guarde los respaldos cifrados, con ACL de mínimo privilegio y retención aprobada. La base puede contener identificadores, correos y descripciones personales. Verifique copias con `PRAGMA integrity_check` antes de archivarlas y después de restaurarlas. Reinicie con `Start-ScheduledTask -TaskName MesaSoporteS6-LAN`.

## Incidentes frecuentes

- **La tarea falla al inicio:** compruebe IP, puerto ocupado, permisos/ACL, venv, módulos y `LastTaskResult`.
- **La página abre, pero enviar falla:** valide reachability al host:8080, API en mismo origen y que SQLite acepte escritura.
- **No entra otra PC:** revise que pertenezca a `192.0.2.0/24`, perfil de red Domain, regla de firewall y ruta entre VLAN; el modo actual no habilita otras subredes.
- **Prueba de correo:** configure el relay SMTP en el servidor mediante variables de entorno y pruebe creando un ticket con un correo institucional controlado. No introduzca credenciales SMTP en el cliente.
- **Certificado HTTPS:** la ruta LAN HTTP actual no lo usa. Para operación multiunidad, coordine FQDN, certificado institucional, TLS y política de firewall antes de abrir la nueva ruta.
