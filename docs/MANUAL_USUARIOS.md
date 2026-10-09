# Manual de usuario

## Acceso

El portal de solicitudes de la unidad está en:

- Portal cliente: `http://192.0.2.10:8080/`
- Requisito: estar conectado a la LAN institucional `192.0.2.0/24`.

La página raíz sirve el formulario personalizado `index.html`. Si no carga, avise a Soporte TI e indique la hora, el equipo y el mensaje mostrado. No pruebe direcciones IP de otros servidores.

> **Aviso de privacidad:** el piloto usa HTTP, que no cifra la información transmitida. Úselo solo dentro de la red institucional confiable. No lo abra desde Internet, una red pública, un punto Wi-Fi no confiable ni un equipo compartido fuera de la unidad.

## Registrar una solicitud

1. Escriba su nombre y usuario o cédula.
2. Ingrese un correo institucional terminado en `@example.org`.
3. Indique el hostname del equipo o su dependencia/puesto. Si es posible, use el hostname que aparece en el equipo.
4. Seleccione una categoría (Hardware, Software, Red o Impresoras).
5. Seleccione el tipo de problema específico que aparece después de elegir la categoría.
6. Describa el síntoma, cuándo comenzó y el mensaje de error. El contador del formulario limita la descripción a 500 caracteres.
7. Pulse **Enviar Ticket** una sola vez y espere la respuesta.

El servidor valida de nuevo los datos y crea el radicado. El número comienza con `S6-`, seguido del año y un consecutivo. Guárdelo para referirse al caso al comunicarse con Soporte.

### Catálogo del formulario

- **Hardware:** periféricos; almacenamiento HDD/SSD/NVME; memoria RAM; fuente de poder; video GPU; motherboard; botones de chasis; refrigeración; tarjeta de red; pila de motherboard; monitor/pantalla; puertos de audio/video/USB; cables de audio/video.
- **Software:** rendimiento del sistema operativo; rendimiento de aplicaciones; falla de aplicaciones; lectura/escritura de archivos; servicios de dominio/inicio de sesión/sincronización.
- **Red:** acceso a plataformas institucionales; acceso a plataformas específicas; navegación web; red local/recursos compartidos/bases de datos.
- **Impresoras:** impresión directa/protegida; falla de máquina; conexión a impresoras o escáner compartidos; escáner local; salida de impresión/tóner/tinta.

Los nombres exactos en pantalla pueden variar en acentos o abreviaturas; seleccione la opción que mejor describa el síntoma.

## Confirmación y errores

- Solo considere creado el ticket si aparece la confirmación y un número de radicado.
- Si aparece un error de conexión, el servidor no confirmó el registro. Espere y vuelva a intentarlo una vez; si se repite, contacte al técnico.
- Si aparece un límite de solicitudes, espere 10 minutos antes de reintentar.
- El formulario exige correo `@example.org`. No use una dirección personal.
- El portal no ofrece actualmente consulta de estado por número de radicado. Contacte a Soporte con el código `S6-...`.

## Archivos y notificaciones

El formulario acepta hasta seis capturas JPEG, PNG o WebP. Las imágenes se comprimen en el navegador y se cargan al ticket; el límite es 900 KB por imagen y 5 MB en total. El técnico las consulta desde la consola administrativa. No adjunte contraseñas, datos clasificados ni información que no sea necesaria para resolver la incidencia.

Si el servidor tiene configurado el relay SMTP institucional, recibirá una confirmación al crear el caso y una notificación cuando cambie su estado, en el correo institucional indicado. La confirmación también se muestra en el navegador. No incluya contraseñas, códigos de autenticación, datos clasificados ni información que no sea necesaria para resolver la incidencia.

## Solución de problemas

- **No abre la dirección:** confirme que está en la LAN institucional y pruebe de nuevo. Si otros sitios internos tampoco funcionan, contacte a soporte de red.
- **Categoría sin subtipos:** seleccione primero una categoría general.
- **Correo rechazado:** verifique que termine exactamente en `@example.org`.
- **La página confirmó, pero no recibió correo:** conserve el radicado y avise a soporte; el administrador debe revisar el relay SMTP del servidor.

Para acceder a la consola administrativa se requiere una cuenta autorizada; el portal de usuario no solicita una contraseña.
