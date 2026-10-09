# Guía de configuración del proyecto en blanco

Esta guía describe, paso a paso, cómo dejar operativa la copia **sin información interna** de Mesa de Soporte S6. La copia no incluye datos, bases de datos, secretos, direcciones reales ni documentos restringidos: todo eso se configura localmente siguiendo estas instrucciones. Los valores `192.0.2.x`, `example.org` y `proxy.example.org` son **marcadores de posición** que debe reemplazar por los reales de su red.

## 1. Requisitos previos

| Requisito | Detalle |
|---|---|
| Sistema operativo | Windows 10/11 o Windows Server con PowerShell 5.1 |
| Python | 3.13 o compatible (`py -3.13 --version`) |
| LibreOffice | Opcional pero recomendado, para generar el PDF idéntico al Word. Ruta esperada: `C:\Program Files\LibreOffice\program\soffice.com` |
| Permisos | Cuenta de administrador local para firewall y tarea programada |
| Red | Una IP fija del servidor y la subred de los clientes |

## 2. Preparar el entorno Python

```powershell
Set-Location '<carpeta del proyecto>'
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Dependencias: Flask, Waitress, python-docx y reportlab.

## 3. Configuración de la organización (`config\site_config.json`)

El archivo `config\site_config.json` se crea a partir de `config\site_config.example.json` y **nunca se sube a GitHub** (está en `.gitignore`). Edítelo con UTF-8:

| Clave | Significado | Ejemplo |
|---|---|---|
| `email_suffix` | Dominio obligatorio del correo de quien radica | `"@miorganizacion.gov"` |
| `inventory_network` | Subred (CIDR) permitida para monitorear equipos del inventario | `"10.20.30.0/24"` |
| `proxies` | Lista de proxies de salida (`host`, `port`) usados para probar plataformas externas | `[{"host": "proxy.miorg.gov", "port": 3128}]` |
| `network_targets` | Servicios mostrados en "Estado de la Red" | ver abajo |

Cada elemento de `network_targets` admite:

- `group`: agrupación visual (`Red`, `Aplicativos`, `Servidor principal`...).
- `name`: nombre mostrado.
- `host`: IP o nombre DNS.
- `ports`: lista de puertos TCP a probar (si ninguno responde, se considera sin conexión).
- `external` (opcional, `true`): se prueba con `HTTP CONNECT` a través de los `proxies`; úselo para plataformas en Internet.
- `icmp` (opcional, `false`): omite el ping para equipos que no lo responden.
- `alt_hosts` (opcional): hosts alternativos que se prueban si el principal falla.

Después de editar, reinicie el servicio. Se puede usar otra ubicación con la variable `HELPDESK_SITE_CONFIG`.

> La validación de correo en `index.html` (función `esCorreoInstitucionalZoho`) y los textos del manual usan `example.org`; reemplácelos por su dominio con una búsqueda y reemplazo de `example.org`.

## 4. Datos locales (carpeta `datos\`)

La carpeta `datos\` no se incluye. Créela y coloque, si los usa:

| Archivo | Uso |
|---|---|
| `datos\formato soporte tecnico.docx` | Plantilla Word del formato de soporte; se rellena y se convierte a PDF |
| `datos\base_usuarios_equipos_octubre_2026.sqlite3` | Base de usuarios/equipos para autocompletar datos del solicitante |
| `datos\inventario_equipos.json` | Inventario de equipos (marca, modelo, serial, SO, hardware, IP, hostname) |

Sin estos archivos la aplicación inicia igualmente; solo se desactivan el autocompletado y el PDF de formato.

## 5. IP, puerto y firewall del servidor LAN

Edite `deploy\run-lan-http.ps1` y cambie:

- `$hostAddress = '192.0.2.10'` → la IP fija real del servidor (debe estar asignada y activa en la tarjeta de red).
- `$port = 8080` → puerto deseado.
- `-RemoteAddress '192.0.2.0/24'` (dos apariciones, además de `192.0.2.10/255.255.255.0`) → la subred de los clientes.

En `deploy\install-lan-task.ps1` cambie la subred de la descripción y, si cambia el puerto, la comprobación del `8080`.

El script crea la regla de firewall `MesaSoporteS6-LAN-HTTP` (entrada TCP, perfil Domain, solo la subred indicada), un secreto de sesión persistente en `C:\ProgramData\MesaSoporteS6\lan-session-secret.txt` con permisos solo para SYSTEM y Administradores, y lanza Waitress. HTTP no cifra el tráfico: úselo solo en una LAN confiable o ponga HTTPS (IIS/ARR con `web.config`).

## 6. Primer arranque y administrador

```powershell
$env:HELPDESK_SECRET_KEY = [Convert]::ToBase64String((1..48 | % { Get-Random -Max 256 }) -as [byte[]])
.\.venv\Scripts\python.exe server.py create-admin
```

El comando pide usuario y contraseña (guardada con PBKDF2-HMAC-SHA256). No existen credenciales iniciales. Para pruebas locales: `.\.venv\Scripts\python.exe server.py` escucha solo en `127.0.0.1:8080`.

Variables de entorno relevantes: `HELPDESK_MODE` (`local` o `lan-http`), `HELPDESK_HOST`, `HELPDESK_PORT`, `HELPDESK_DATA_DIR` (carpeta de la base; por defecto `instance\`), `HELPDESK_SECRET_KEY`, `HELPDESK_COOKIE_SECURE`, `HELPDESK_TRUSTED_PROXY`, `HELPDESK_SITE_CONFIG`.

## 7. Ejecución permanente (tarea programada)

Con PowerShell como administrador y el puerto libre:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy\install-lan-task.ps1
Start-ScheduledTask -TaskName MesaSoporteS6-LAN
```

La tarea corre como SYSTEM al arrancar y reintenta cinco veces. Reinicio: `schtasks /End /TN MesaSoporteS6-LAN` y luego `schtasks /Run /TN MesaSoporteS6-LAN`.

## 8. Verificación

1. `http://<IP>:<puerto>/api/client-build` devuelve el identificador de versión.
2. `http://<IP>:<puerto>/` muestra el portal en **modo oscuro** (botón de tema para alternar a claro).
3. `/login` permite entrar con el administrador creado.
4. "Estado de la Red" lista los servicios de `network_targets`.
5. Radique un ticket de prueba con un correo del dominio configurado y confirme que aparece en la cola y en `/admin`.

## 9. Pruebas automáticas

```powershell
$env:HELPDESK_DATA_DIR = "$env:TEMP\helpdesk-test"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'
```

## 10. Copias de seguridad

Respalde periódicamente `instance\helpdesk.sqlite3`, `config\site_config.json`, la carpeta `datos\` y `C:\ProgramData\MesaSoporteS6\` (el secreto de sesión; si se pierde, las sesiones se invalidan pero los datos se conservan).

## 11. Qué NO debe subirse a GitHub

`datos\`, `instance\`, `config\site_config.json`, `.env`, bases `*.sqlite3`, PDFs generados, certificados y cualquier archivo con direcciones reales. El `.gitignore` ya los excluye; no lo debilite.
