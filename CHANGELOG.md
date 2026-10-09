# 📜 REGISTRO DE CAMBIOS Y VERSIONES (CHANGELOG)
Todas las modificaciones notables en este proyecto se documentarán en este archivo de manera sistemática y continua.
El formato se basa en [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/) y este proyecto se adhiere a [Semantic Versioning](https://semver.org/lang/es/).

---

## [1.4.0] - 2026-10-09

### Cambios
- Modo oscuro por defecto en portal, consola y login; el botón de tema conmuta a modo claro.
- Eliminados los portales sin uso `MESA DE SOPORTE S6 LOCAL.html` y `MESA DE SOPORTE S6 EXTERNA.html` y sus rutas.
- Configuración de red (dominio de correo, subred de inventario, proxies y objetivos de Estado de la Red) externalizada a `config/site_config.json`.
- Copia sin información interna (`tools/sync_public_copy.ps1`) y regla de sincronización en `.github/copilot-instructions.md`.
- Nueva guía `docs/CONFIGURACION_PROYECTO_BLANCO.md`.

## [1.3.0] - 2026-10-08

### Documentación
- Manual detallado de usuario para acceso, envío, radicado, límites de adjuntos, correo y privacidad.
- Manual operativo de administrador TI con cuentas, consola, tarea persistente, firewall, backup y diagnóstico.
- Procedimiento de migración entre unidades del dominio, con alternativas de instancia nueva o traslado autorizado de tickets, TLS y rollback.
- Reescrita la documentación técnica para reflejar Flask/SQLite/Waitress, y etiquetados los archivos de plantilla/esquema legados.
- README enlaza el índice documental y especifica el modo LAN persistente y su alcance.
- Versiones HTML autónomas del manual de usuario, manual administrador TI, guía de migración e índice para abrir/imprimir desde navegador.
- Rutas de solo lectura `/docs/<manual-html>` con allowlist de los cuatro documentos, para abrirlos por la URL LAN sin exponer archivos arbitrarios.

## [1.2.0] - 2026-10-08

### Añadido
- Servicio Flask con base SQLite central, sesiones administrativas y alta segura del primer usuario.
- Límite de ingreso público de tickets y API autenticada para consulta, cambios de estado, asignación y bitácora.
- Formularios local y externo conectados al mismo servicio; radicados emitidos por el servidor.
- Proxy inverso IIS hacia Waitress; la consola ya no debe servirse como archivo estático.

### Seguridad
- Escapado de contenido variable de tickets en la consola.
- Desactivados el correo silencioso y el envío automático a terceros; WhatsApp requiere acción explícita.
- Cookies HttpOnly/SameSite, token CSRF y contraseñas PBKDF2.

### Pendiente
- Centralizar inventario y administración de agentes.
- Almacenamiento validado de soportes de imagen por ticket, con compresión en el navegador y consulta administrativa autenticada.

### Actualizado
- Portal personalizado `index.html` integrado con el API central; `/` sirve este portal.
- Modo piloto HTTP LAN explícito en `deploy/run-lan-http.ps1`, enlazado a `192.0.2.10` y firewall limitado a `192.0.2.0/24`; requiere consentimiento explícito por el tráfico sin cifrar.
- Tarea programada `MesaSoporteS6-LAN` bajo SYSTEM para iniciar el servidor con Windows y reiniciarlo ante fallos; base SQLite protegida para SYSTEM/Administradores.

## [1.1.0] - 2026-10-07

### ✨ Añadido (Added)
- **Módulo de Base de Datos de Inventario / Activos (`mockup_helpdesk.html`)**:
  - Vista interactiva en **Administración -> Inventario / Activos** con **133 registros** consolidados del cruce entre `INVENTARIO EQUIPOS MANUAL.xlsx` (104 filas de equipos) e `INVENTARIO OCTUBRE 2026.pdf` (161 páginas / 131 equipos únicos).
  - Tarjetas KPI interactivas de validación: Total registros (`107` computadores + `26` dispositivos de red), Cruzados `Excel + PDF` (`102`), `Solo Excel` (`2`), `Solo PDF` (`29`) y Registros `Con alertas`.
  - Filtros combinados por dependencia (16 áreas), fuente documental, estado de validación y buscador instantáneo multicampo (hostname, serial, plaqueta, cédula, login AD, IP, MAC, procesador, disco).
  - Panel lateral deslizante (*Asset Drawer*) con tabla comparativa campo a campo (**Excel Manual vs PDF Octubre 2026**), alertas de auditoría y ficha técnica completa de hardware y red.
  - Exportación directa a CSV (`inventario_equipos_revision.csv`) y respaldo SQL integrado.
- **Archivos de Datos Consolidados (`datos/`)**:
  - `datos/inventario_equipos.json`: Base estructurada completa con los 133 registros y metadatos de cruce.
  - `datos/inventario_equipos.sql`: Script DDL + `INSERT` listo para importar en SQLite/PostgreSQL/MySQL.
  - `datos/LISTADO_RELACIONADO_EQUIPOS.md`: Listado maestro en Markdown relacionando cada equipo, usuario y características técnicas.

---

## [1.0.0] - 2026-10-05

### ✨ Añadido (Added)
- **Prototipo Gráfico Interactivo (`mockup_helpdesk.html`)**:
  - Consola web completa desarrollada en HTML5, CSS3 y JavaScript moderno nativo (Vanilla JS).
  - 100% libre de CDNs externas o conexiones a internet (autonomía total en red LAN).
  - Integración de iconografía SVG inline ultra ligera.
  - Conmutador de modo claro y oscuro con variables CSS dinámicas.
  - Sistema de KPIs en tiempo real (Tickets Abiertos, En Proceso, Críticos con SLA en riesgo y Resueltos hoy).
  - Tabla de incidencias con búsqueda instantánea por ID, solicitante, equipo o falla.
  - Pestañas de filtrado rápido por estado de atención.
  - Modal para registro de nuevos tickets con selector jerárquico dinámico (Categoría -> Subcategoría).
  - Panel lateral deslizante (*Drawer*) para visualización de detalles, cambio rápido de estado técnico y registro en bitácora cronológica sin recargar página.
  - Función de exportación de respaldo SQL en caliente.

- **Esquema Relacional SQL (`database_schema.sql`)**:
  - DDL normalizado con 7 tablas relacionales: `roles`, `usuarios`, `activos`, `categorias`, `subcategorias`, `tickets`, `bitacora_tickets`.
  - Integración completa de las 26 incidencias técnicas especificadas en `BASE DE CLASIFICACION DE INCIDENCIAS.txt`.
  - Índices de rendimiento para búsquedas por estado, prioridad, categoría y técnico.
  - Tiempos de resolución recomendados (SLA) para cada subcategoría técnica.

- **Documentación Integral del Sistema (`DOCUMENTACION_SISTEMA.md`)**:
  - Manual técnico exhaustivo que explica el 100% de la arquitectura, diccionario de datos, topología de red local, requerimientos de servidor y procedimientos de mantenimiento.
  - Diagrama de red local (LAN/Intranet) y diagrama Entidad-Relación (Mermaid).

- **Gestión de Versiones y Configuración**:
  - Inicialización del repositorio Git local para control estricto y salvaguarda automática de cambios.
  - Creación del archivo `.gitignore` para exclusión de archivos temporales y dependencias.
