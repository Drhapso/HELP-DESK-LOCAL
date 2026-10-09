# Mesa de Soporte S6

Aplicación web Flask con SQLite central para registrar tickets desde los portales local y externo, y administrarlos desde una consola autenticada.

## Documentación

- [Índice de manuales](docs/INDICE_DOCUMENTACION.md)
- [Manual de usuario](docs/MANUAL_USUARIOS.md)
- [Manual del administrador TI](docs/MANUAL_ADMIN_TI.md)
- [Migración a otra unidad/servidor](docs/MIGRACION_ENTRE_UNIDADES.md)
- [Arquitectura y estado implementado](DOCUMENTACION_SISTEMA.md)
- [Cambios](CHANGELOG.md)
- [Configuración del proyecto en blanco (copia sin información interna)](docs/CONFIGURACION_PROYECTO_BLANCO.md)

### Versiones HTML para abrir en navegador

- Índice: [archivo](docs/INDICE_DOCUMENTACION.html) · [LAN](http://192.0.2.10:8080/docs/INDICE_DOCUMENTACION.html)
- Usuario: [archivo](docs/MANUAL_USUARIOS.html) · [LAN](http://192.0.2.10:8080/docs/MANUAL_USUARIOS.html)
- Administrador TI: [archivo](docs/MANUAL_ADMIN_TI.html) · [LAN](http://192.0.2.10:8080/docs/MANUAL_ADMIN_TI.html)
- Migración: [archivo](docs/MIGRACION_ENTRE_UNIDADES.html) · [LAN](http://192.0.2.10:8080/docs/MIGRACION_ENTRE_UNIDADES.html)

## Acceso actual

- Portal de cliente: [http://192.0.2.10:8080/](http://192.0.2.10:8080/)
- Consola administrador: [http://192.0.2.10:8080/login](http://192.0.2.10:8080/login)

La dirección está limitada a la subred `192.0.2.0/24`. El modo actual es HTTP sin cifrado; solo debe usarse dentro de la LAN institucional confiable. Para otras unidades o subredes es obligatorio completar la migración con HTTPS institucional.

## Requisitos

- Windows Server o Windows 10/11 para el despliegue actual.
- Python 3.13 o compatible.
- IIS con URL Rewrite y Application Request Routing (ARR) si se publica detrás de IIS.
- Certificado HTTPS para cualquier acceso desde equipos remotos.

## Portal local

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:HELPDESK_DATA_DIR = 'C:\ProgramData\MesaSoporteS6'
.\.venv\Scripts\python.exe server.py
```

El modo local escucha solo en `127.0.0.1:8080`. La base SQLite queda en `HELPDESK_DATA_DIR`; si no se define, se usa `instance/`. La ruta raíz `/` sirve el `index.html` personalizado.

## Acceso compartido en LAN sin certificado

Esta opción usa HTTP sin cifrado y solo es adecuada para un piloto dentro de una LAN confiable. Usuarios de la misma red pueden observar los datos de tickets y credenciales transmitidos; no usar por Internet, Wi-Fi público ni redes no confiables.

Con PowerShell como administrador, desde el repositorio:

```powershell
Set-Location 'D:\HELP DESK TELEMATICA'
.\deploy\run-lan-http.ps1
```

El lanzador conserva la base `instance/helpdesk.sqlite3` y los usuarios existentes, crea un secreto persistente en `C:\ProgramData\MesaSoporteS6` con ACL para SYSTEM/Administradores, enlaza Waitress solamente a `192.0.2.10:8080` y permite ese puerto solo desde `192.0.2.0/24` en el perfil Domain. No abre HTTP general, no cambia IP/DNS/proxy y no detiene un proceso que ya ocupe 8080.

Desde otra máquina de la misma subred, abre `http://192.0.2.10:8080/`. HTTP no cifra los datos transmitidos; úsalo solo en la LAN institucional confiable, nunca por Internet, Wi-Fi público ni redes no confiables.

El servidor ya está registrado como tarea programada `MesaSoporteS6-LAN`: corre como SYSTEM al arrancar Windows y reintenta hasta cinco veces si falla. Estado: `Get-ScheduledTask -TaskName MesaSoporteS6-LAN`. Reinicio manual: `Restart-ScheduledTask -TaskName MesaSoporteS6-LAN`. Reutiliza el secreto y la SQLite actuales; la carpeta de base de datos permite acceso solo a SYSTEM y Administradores.

Para instalarlo en otro equipo, detén primero cualquier servidor que use el puerto 8080 y ejecuta PowerShell como administrador:

```powershell
Set-Location 'D:\HELP DESK TELEMATICA'
Set-ExecutionPolicy -Scope Process Bypass
.\deploy\install-lan-task.ps1
Start-ScheduledTask -TaskName MesaSoporteS6-LAN
```

Al ejecutar detrás de IIS/ARR, configure `HELPDESK_TRUSTED_PROXY=1` únicamente si ARR reemplaza los encabezados `X-Forwarded-For` entrantes. Esto permite que el límite por IP use la IP real del cliente; sin proxy confiable, todas las solicitudes se verán como `127.0.0.1`.

## Primer administrador

Antes del alta, configure en el entorno `HELPDESK_SECRET_KEY` con un valor aleatorio persistente. En producción configure además `HELPDESK_ENV=production`, `HELPDESK_COOKIE_SECURE=1`, y termine TLS en IIS. Luego ejecute:

```powershell
.\.venv\Scripts\python.exe server.py create-admin
```

El comando solicita usuario y contraseña sin guardarlos en el repositorio. Las contraseñas se almacenan con PBKDF2-HMAC-SHA256. No hay credenciales iniciales.

## Rutas

- `/login`: acceso administrativo.
- `/admin`: consola protegida por sesión.
- `/api/tickets`: ingreso público limitado por IP y consulta administrativa autenticada.
- `/api/tickets/<id>`: cambios autenticados de estado, técnico y bitácora.
- `/api/admin/tickets-before?before=<ISO-8601>`: vista previa y eliminación confirmada de tickets anteriores a una fecha; exige sesión administrativa y CSRF para borrar.
- `/api/admin/inventory-monitor`: comprobación ICMP autenticada de equipos del inventario; requiere CSRF y solo permite IPs de `192.0.2.0/24`.
- `/api/tickets/<id>/support-report`: descarga autenticada del formato de soporte PDF de un ticket resuelto; `POST` lo vuelve a generar si es necesario.

## Formato de soporte técnico en PDF

Al resolver un ticket, el servidor completa [formato soporte tecnico.docx](datos/formato%20soporte%20tecnico.docx) y genera el PDF correspondiente. El formato usa los datos del ticket, la base de usuarios/equipos y el inventario; conserva vacías las firmas y la evaluación del usuario.

Siempre se completan **JEFATURA/UNIDAD** con `COLOG` y **COMANDO/DEPTO.** con `BRLOG1`. La dependencia se toma del equipo asociado en el inventario y la ubicación procede de la respuesta del usuario. El portal solicita **Ubicación del sitio de trabajo** para los tickets nuevos; los tickets anteriores usan como respaldo el campo de equipo/dependencia/puesto.

En **DESCRIPCIÓN DEL EQUIPO**, los campos se extraen directamente del inventario: **MARCA** y **MODELO** desde `EQUIPO`, **SERIAL** desde `SERIAL`, **SISTEMA OPERATIVO** desde `Sistema operativo`, **PROCESADOR**, **MEMORIA RAM** y **DISCO DURO** desde `HARDWARE`, **DIRECCIÓN IP** desde `IP/MAC` y **NOMBRE PC** desde `HOSTNAME`. Si el ticket solo indica una dependencia que tiene varios equipos, no se asigna un equipo arbitrario: es necesario registrar el hostname, serial o equipo específico.

La conversión principal usa LibreOffice Writer en modo *headless* sobre una copia temporal del DOCX diligenciado. Se crea un perfil temporal por conversión para que funcione también cuando el servicio `MesaSoporteS6-LAN` se ejecuta como `SYSTEM`; se recomienda instalarlo en `C:\Program Files\LibreOffice`. Así se conservan la estructura, tablas e imágenes de la plantilla original con la mayor fidelidad posible. Microsoft Word queda como segundo respaldo y el PDF nativo como último respaldo operativo si ninguno de los conversores está disponible.

La equivalencia visual absoluta entre Word y LibreOffice depende de las fuentes y del motor de renderizado instalados en el servidor. Para maximizarla, deben estar instaladas las mismas fuentes utilizadas por la plantilla y no se deben modificar sus estilos, imágenes ni estructura.

## Actualización automática de la consola

La consola administrativa consulta la versión publicada cada 30 segundos. Cuando detecta una actualización, elimina la caché web temporal y recarga automáticamente la página desde `/admin`, por lo que no es necesario cambiar de navegador ni usar una pestaña privada. Los datos persistentes de inventario no se eliminan: se vuelven a sincronizar desde el servidor.

## Estado de equipos en tiempo real

En **Inventario / Equipos**, el botón **Actualizar estado en tiempo real** consulta por ICMP las IP registradas y muestra si cada equipo está **En línea (ICMP)** o **Sin respuesta (ICMP)**. Mientras la vista permanece abierta, la consulta se actualiza cada minuto.

El resultado es una comprobación de conectividad puntual, no una modificación del inventario: no reemplaza el estado histórico ni cambia los datos del equipo. Un resultado *Sin respuesta* puede deberse a que el equipo esté apagado, desconectado o tenga ICMP bloqueado por firewall. Solo los administradores autenticados pueden ejecutar el monitoreo y el servidor rechaza destinos fuera de la subred LAN autorizada.

## Confirmación y limpieza de tickets

Antes de registrar una solicitud, el portal muestra un resumen con el correo, equipo, tipo de falla y soportes adjuntos. El solicitante puede volver a revisar los datos o confirmar el envío.

En **Configuración** de la consola administrativa, seleccione la fecha y hora de corte y pulse **Revisar eliminación**. El sistema muestra cuántos tickets se eliminarán y requiere una segunda confirmación. La eliminación incluye la bitácora y las imágenes adjuntas de los tickets afectados y no se puede deshacer.

La tabla de tickets también incluye la acción **Eliminar** para borrar selectivamente un ticket individual. Esta acción requiere confirmación, sesión administrativa y token CSRF; elimina el ticket junto con su bitácora, adjuntos y formato PDF. La limpieza por rango de fecha y hora permanece disponible.

## Tiempos de atención y cola pública

El tiempo de atención se calcula desde la fecha y hora de radicación, según categoría y prioridad:

| Categoría | Baja | Media | Alta | Crítica |
| --- | ---: | ---: | ---: | ---: |
| Hardware | 30 min | 60 min | 120 min | 180 min |
| Impresoras | 30 min | 60 min | 120 min | 180 min |
| Red | 60 min | 90 min | 120 min | 180 min |
| Software | 60 min | 90 min | 120 min | 180 min |

La consola muestra el tiempo restante, una alerta cuando faltan 30 minutos o menos y **Vencido** cuando se supera el límite. El portal del cliente muestra lateralmente la cola de tickets pendientes en orden de llegada, con turno, radicado, hora de inicio, estado y agente asignado. También muestra el nombre del usuario que radicó el ticket y su dependencia (campo «Equipo / Dependencia / Puesto»). Se actualiza cada 30 segundos y no expone cédula, correo ni descripción del problema.

### Estado de la Red

Basado en `datos\Estado general RED.txt`. El servidor comprueba en tiempo real (ICMP y, si falla, conexión TCP a los puertos del servicio; los nombres DNS se resuelven antes) el servidor principal, proxy, DNS, conexión externa (8.8.8.8), Orfeo, Zoho, Intranet, FOVID y SIATH Web. Endpoint `GET /api/portal/network-status` (resultado en caché 20 s). Se muestra en una columna del portal del cliente y en un panel de la consola de administración, ambos con refresco cada 30 segundos. Los destinos están en `NETWORK_STATUS_TARGETS` de `server.py`; un resultado «Sin conexión» puede deberse también a que el servicio bloquee ICMP y los puertos probados.

## Notificaciones por correo

El envío automático de correos está desactivado. Crear un ticket, cambiar su estado o resolverlo no realiza conexiones SMTP ni envía mensajes al usuario.

Como alternativa manual, abra un ticket en la consola administrativa y use **Copiar confirmación y abrir Zoho Mail**. El sistema muestra un cuadro con el destinatario, asunto y cuerpo del correo. Pulse **Copiar texto**, luego **Abrir Zoho Mail**, pegue el contenido, revíselo y pulse **Enviar**.

Para producción con IIS, `web.config` reenvía a Waitress en `127.0.0.1:8080`. Se requieren URL Rewrite, ARR habilitado y un certificado HTTPS institucional. No despliegues el directorio como sitio estático.

## Validación

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## Límites conocidos

- Los tickets se comparten mediante SQLite; el inventario, agentes y otros ajustes de la consola todavía usan almacenamiento del navegador y no son multiusuario.
- Los formularios aceptan hasta seis imágenes JPEG, PNG o WebP. El navegador las comprime antes del envío; cada imagen puede ocupar hasta 900 KB y el total del ticket hasta 5 MB. La consola administrativa permite abrirlas a tamaño completo.
- El correo automático está desactivado; el administrador puede preparar y enviar el mensaje manualmente desde Zoho Mail. WhatsApp solo se abre si el solicitante pulsa explícitamente su botón.
- El modo LAN HTTP es texto plano y solo para redes confiables; para operación normal, usa HTTPS institucional y reglas de firewall aprobadas.

## Estado del piloto LAN

El lanzador `deploy/run-lan-http.ps1` sirve el `index.html` personalizado en `http://192.0.2.10:8080/`. En este host la tarea `MesaSoporteS6-LAN` lo inicia automáticamente y conserva la regla `MesaSoporteS6-LAN-HTTP`, limitada a TCP 8080 desde `192.0.2.0/24` y el perfil Domain.
