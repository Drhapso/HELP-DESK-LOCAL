# Migración del servidor entre unidades del dominio

## 1. Propósito y modalidades

Esta guía mueve el servicio a otro servidor/unidad del dominio `example.org`. La unidad destino debe aprobar el hospedaje, DNS, segmento de red, tratamiento de tickets y accesos administrativos.

Hay dos modalidades; no confundirlas:

1. **Instancia nueva para otra unidad:** conserva el software, crea base y cuentas propias. No copia tickets ni datos personales de la unidad origen.
2. **Migración del servicio con historial:** traslada la base SQLite existente y, por tanto, también identificadores, correos, descripciones, eventos y hashes de contraseña. Requiere autorización del dueño de la información, transferencia cifrada y custodio de destino.

No se migra el archivo `lan-session-secret.txt`. En el nuevo servidor se genera un secreto nuevo; eso invalida cookies antiguas, pero no cambia contraseñas ni tickets si se migra la SQLite.

## 2. Estado de referencia

- Host actual: `example.org`.
- IP actual: `192.0.2.10/24`.
- Portal actual: `http://192.0.2.10:8080/`.
- Backend: Flask + Waitress.
- Datos: `D:\HELP DESK TELEMATICA\instance\helpdesk.sqlite3`.
- Clave local de sesión: `C:\ProgramData\MesaSoporteS6\lan-session-secret.txt`.
- Tarea: `MesaSoporteS6-LAN`, SYSTEM, inicio al arranque.
- Firewall piloto: TCP 8080, Domain, origen `192.0.2.0/24`.

La IP, subred y nombre DNS de destino no se presuponen. La unidad destino debe recibirlos de Redes/Infraestructura; no reutilice una IP todavía asignada al origen.

## 3. Preflight obligatorio

Antes de mover nada, solicite a Infraestructura/Seguridad:

- FQDN aprobado del nuevo servidor y registro A (y PTR si la norma lo exige).
- IP estática/reservada, máscara, gateway, DNS y VLAN autorizados.
- Segmentos CIDR que pueden acceder y puertos permitidos por firewall.
- Confirmación de unión al dominio y perfil de firewall Domain.
- Certificado TLS institucional con SAN para el FQDN de destino si accederán otras unidades o subredes.
- Instaladores/repositorios aprobados de Python, IIS URL Rewrite y ARR si se publicará con IIS.
- Aprobación explícita para mover la base y sus datos personales, o instrucción de iniciar una base vacía.
- Custodio que conservará y probará el backup y persona responsable de rollback.

No despliegue el modo HTTP actual entre sedes/VLAN ni por Wi-Fi público. La regla presente está limitada a `192.0.2.0/24` y el transporte no cifra datos ni contraseñas. Para otras unidades, el diseño de destino debe ser HTTPS institucional, con firewall de origen aprobado.

## 4. Preparar el servidor destino

1. Instale Windows Server/Windows Pro aprobado y aplique parches institucionales.
2. Asígnele hostname y únalo a `example.org` según procedimiento de la unidad. Use la cuenta local SYSTEM de la tarea; no incruste una contraseña de dominio en los scripts.
3. Redes debe configurar la IP estática/reservada. Valide `Get-NetIPAddress`, gateway, DNS, registro A y perfil `DomainAuthenticated`.
4. Copie el código desde un medio controlado/verificado. No publique el directorio como recurso SMB ni como carpeta estática; el portal necesita el API.
5. Cree/revise el entorno `.venv` con Python 3.13 y `requirements.txt`, usando paquetes aprobados. En una red aislada use un repositorio interno/offline aprobado.
6. Revise `deploy/run-lan-http.ps1`: actualice `$hostAddress` y el `RemoteAddress` a la IP/subred destino aprobadas. Revise el mismo alcance en las validaciones y documentación. No cambie gateway, DNS o proxy con este lanzador.
7. Para un piloto solo de la misma LAN y con autorización, ejecute la tarea según el manual TI. Para otras unidades, no habilite HTTP: primero complete el apartado TLS.

## 5. Instancia nueva, sin datos del origen

Esta es la modalidad recomendada cuando cada unidad debe mantener sus propios casos.

1. Mantenga una carpeta de datos nueva y protegida para el destino. No copie `instance/helpdesk.sqlite3` del origen.
2. Instale el secreto del host ejecutando el lanzador; verifique ACL SYSTEM/Administradores.
3. Instale la tarea y firewall limitados al segmento autorizado.
4. Cree el administrador de destino de forma interactiva:

   ```powershell
   Set-Location 'D:\HELP DESK TELEMATICA'
   .\.venv\Scripts\python.exe server.py create-admin
   ```

5. Pruebe el portal, login y un caso de prueba coordinado. No use datos personales reales para el smoke test si no ha sido autorizado.

## 6. Mover el historial de tickets

### 6.1. Backup de origen

1. Avise a usuarios del periodo de mantenimiento.
2. Detenga la tarea de origen y compruebe que el puerto dejó de escuchar:

   ```powershell
   Stop-ScheduledTask -TaskName MesaSoporteS6-LAN
   Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue
   ```

3. Desde Python/SQLite, haga una copia transaccional mediante `Connection.backup()` a un archivo de backup. No copie solo el `.sqlite3` mientras el servicio está escribiendo en modo WAL.
4. Verifique la copia con `PRAGMA integrity_check` y registre checksum, fecha, responsable y autorización.
5. Cifre el backup con el medio institucional aprobado, limite ACL y entregue solo al responsable autorizado. No transfiera por correo, WhatsApp ni SMB sin cifrado/aprobación.

### 6.2. Restauración de destino

1. Instale código y venv en destino; detenga el servicio destino y cree la carpeta `instance` con ACL SYSTEM/Administradores.
2. Transfiera el backup por canal cifrado aprobado. No copie el secreto de sesión del origen.
3. Restaure el backup como `instance\helpdesk.sqlite3`; verifique `PRAGMA integrity_check`, recuento esperado de usuarios/tickets y permisos NTFS.
4. Genere el nuevo secreto local ejecutando el lanzador bajo administrador.
5. Registre e inicie la tarea destino. El código de tickets existente y los hashes de contraseña permanecen en la base; todas las sesiones web anteriores quedan invalidadas.
6. Verifique acceso, ticket autorizado de prueba, vista de consola con una cuenta aprobada, backup nuevo y auditoría. Si hay errores, mantenga el destino cerrado a usuarios y ejecute rollback.

### 6.3. Evitar doble escritura

No mantenga simultáneamente origen y destino abiertos al ingreso público después de copiar la base. Si ambos aceptan tickets, se crearán dos historiales divergentes. En el corte, detenga origen, haga backup final, restaure destino, valide destino y solo entonces actualice DNS/enlaces/firewall. Mantenga el origen aislado como rollback de solo lectura hasta la aceptación formal.

## 7. TLS para comunicación entre unidades

Para tráfico que salga del segmento actual, HTTP no es aceptable para tickets y credenciales. Solicite un certificado de servidor emitido por la CA institucional con SAN igual al FQDN destino, EKU Server Authentication y clave privada protegida localmente.

La solicitud de referencia está en `deploy/iis-cert-request.inf` y actualmente contiene el hostname del servidor actual. En destino, cambie sujeto y SAN al FQDN aprobado, genere la CSR en el propio destino y envíela por el flujo autorizado. No envíe la clave privada; solo el `.csr`. Si RPC a la CA no está habilitado, entregue el CSR al equipo de PKI por el canal institucional.

Tras recibir el certificado, instálelo en Local Computer\Personal y confirme la cadena/confianza desde estaciones cliente. Instale URL Rewrite y ARR desde fuentes corporativas aprobadas; habilite ARR Proxy. Configure binding HTTPS en IIS y compruebe `web.config` (redirect HTTPS antes del proxy). Waitress debe seguir ligado a loopback `127.0.0.1:8080`; el firewall debe permitir solo HTTPS 443 desde los CIDR aprobados. Después quite la regla del piloto TCP 8080 y pruebe desde cada segmento autorizado.

**Este modo de producción aún requiere trabajo de despliegue:** `install-lan-task.ps1` registra la tarea LAN, y `run-lan-http.ps1` siempre enlaza a la IP LAN y activa el modo HTTP. No cambie solo IIS/firewall esperando que la tarea LAN se convierta en un backend HTTPS loopback. Antes del corte interunidad, TI debe preparar y probar una tarea/servicio de producción que establezca `HELPDESK_ENV=production`, `HELPDESK_COOKIE_SECURE=1`, `HELPDESK_SECRET_KEY` persistente con ACL, `HELPDESK_DATA_DIR` aprobado y lance Waitress exclusivamente en `127.0.0.1:8080`. Añada pruebas de reinicio, logs, backup/restore y acceso TLS; luego detenga/elimine la tarea piloto LAN.

No use el certificado SolarWinds-NTM, certificados autofirmados ignorados por usuarios ni una clave privada exportada desde otro host.

## 8. DNS, firewall y enlaces

- Redes crea/cambia el A record del FQDN hacia la IP aprobada.
- En HTTPS, los usuarios entran por `https://<FQDN>/`; no anuncie la IP en el bookmark final.
- En piloto LAN HTTP, el listener debe ser la IP específica, no `0.0.0.0`; firewall Domain y RemoteAddress deben coincidir exactamente con el CIDR aprobado.
- Si el servidor no está en perfil Domain, no amplíe a perfil Public: resuelva la unión/política con Infraestructura.
- Si hay más de una unidad/subred cliente, no agregue una regla amplia `Any`; documente y apruebe cada CIDR.

## 9. Rollback

1. Informe a usuarios y cierre la recepción en destino.
2. Detenga la tarea y confirme que 8080/443 ya no escucha.
3. Restaure el DNS/enlace al origen solo si el origen no ha recibido nuevas solicitudes desde el corte; de lo contrario, reconcilie ambos historiales bajo control del dueño de datos.
4. Restaure el backup validado y conserve evidencia del incidente/cambio.
5. Quite solo las reglas/bindings del destino creados por esta migración. No borre certificados institucionales compartidos ni reglas de otros sitios.

## 10. Criterios de aceptación

- DNS resuelve el FQDN al destino aprobado.
- Tarea y listener corresponden a la IP/puerto aprobados.
- Firewall limita origen y puerto a la matriz aprobada.
- En migración con historial, SQLite pasa `integrity_check` y los recuentos son los esperados.
- Solicitud de prueba crea un único radicado y puede consultarse en consola autenticada.
- Consola rechaza usuarios sin sesión y la sesión usa HTTPS en el despliegue entre unidades.
- Responsable de la unidad firma aceptación y rollback probado/documentado.
