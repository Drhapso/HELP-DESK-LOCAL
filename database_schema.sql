-- =====================================================================
-- ESQUEMA LEGADO DE REFERENCIA. No es ejecutado por el runtime.
-- El esquema SQLite autoritativo se inicializa en server.py.
-- =====================================================================

-- 1. TABLA DE ROLES DE ACCESO
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre VARCHAR(50) NOT NULL UNIQUE,       -- 'Administrador', 'Técnico IT', 'Usuario Solicitante'
    descripcion TEXT
);

-- 2. TABLA DE USUARIOS Y TÉCNICOS
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_completo VARCHAR(120) NOT NULL,
    usuario VARCHAR(60) NOT NULL UNIQUE,
    clave_hash VARCHAR(255) NOT NULL,
    departamento VARCHAR(80),                  -- 'Finanzas', 'Talento Humano', 'Sistemas', 'Operaciones'
    correo_interno VARCHAR(120),
    ip_habitual VARCHAR(45),
    rol_id INTEGER NOT NULL,
    activo BOOLEAN DEFAULT 1,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (rol_id) REFERENCES roles(id)
);

-- 3. TABLA DE INVENTARIO / ACTIVOS LOCALES (CMDB básica)
CREATE TABLE IF NOT EXISTS activos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_activo VARCHAR(50) NOT NULL UNIQUE, -- 'PC-FIN-02', 'PRN-HP-PISO2', 'WS-DSGN-01'
    nombre_equipo VARCHAR(100) NOT NULL,
    tipo_activo VARCHAR(50) NOT NULL,          -- 'Estación de Trabajo', 'Impresora', 'Laptop', 'Servidor', 'Switch'
    direccion_ip VARCHAR(45),
    direccion_mac VARCHAR(45),
    ubicacion VARCHAR(100),
    responsable_id INTEGER,
    notas_hardware TEXT,
    FOREIGN KEY (responsable_id) REFERENCES usuarios(id)
);

-- 4. TABLA DE CATEGORÍAS PRINCIPALES
CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre VARCHAR(80) NOT NULL UNIQUE,       -- 'Fallas de Hardware', 'Fallas de Software', etc.
    codigo_prefijo VARCHAR(10),                -- 'HW', 'SW', 'NET', 'PRN'
    color_distintivo VARCHAR(20) DEFAULT '#2563eb'
);

-- 5. TABLA DE SUBCATEGORÍAS (ÁRBOL ESPECÍFICO DE INCIDENCIAS)
CREATE TABLE IF NOT EXISTS subcategorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    categoria_id INTEGER NOT NULL,
    nombre VARCHAR(150) NOT NULL,
    prioridad_sugerida VARCHAR(20) DEFAULT 'Media', -- 'Baja', 'Media', 'Alta', 'Crítica'
    sla_horas_resolucion INTEGER DEFAULT 8,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id)
);

-- 6. TABLA PRINCIPAL DE TICKETS (INCIDENCIAS Y REQUERIMIENTOS)
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_ticket VARCHAR(20) NOT NULL UNIQUE,     -- 'INC-1041', 'INC-1042'
    titulo VARCHAR(200) NOT NULL,
    descripcion TEXT NOT NULL,
    categoria_id INTEGER NOT NULL,
    subcategoria_id INTEGER NOT NULL,
    solicitante_id INTEGER NOT NULL,
    activo_id INTEGER,                             -- Equipo afectado
    prioridad VARCHAR(20) NOT NULL,                -- 'Baja', 'Media', 'Alta', 'Crítica'
    estado VARCHAR(30) NOT NULL DEFAULT 'Abierto', -- 'Abierto', 'En Proceso', 'En Espera', 'Resuelto', 'Cancelado'
    tecnico_asignado_id INTEGER,
    fecha_limite_sla DATETIME,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resuelto_en TIMESTAMP NULL,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id),
    FOREIGN KEY (subcategoria_id) REFERENCES subcategorias(id),
    FOREIGN KEY (solicitante_id) REFERENCES usuarios(id),
    FOREIGN KEY (activo_id) REFERENCES activos(id),
    FOREIGN KEY (tecnico_asignado_id) REFERENCES usuarios(id)
);

-- 7. TABLA DE HISTORIAL / BITÁCORA TÉCNICA Y COMENTARIOS
CREATE TABLE IF NOT EXISTS bitacora_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    usuario_id INTEGER NOT NULL,
    tipo_evento VARCHAR(40) NOT NULL,              -- 'Nota Técnica', 'Cambio de Estado', 'Reasignación', 'Diagnóstico'
    mensaje TEXT NOT NULL,
    es_nota_privada BOOLEAN DEFAULT 0,            -- 1: solo técnicos, 0: visible al usuario
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);

-- =====================================================================
-- POBLACIÓN INICIAL DE DATOS (TAXONOMÍA BASADA EN EL ARCHIVO LOCAL)
-- =====================================================================

-- Roles básicos
INSERT OR IGNORE INTO roles (id, nombre, descripcion) VALUES
(1, 'Administrador IT', 'Control total de la plataforma, usuarios, catálogo e informes'),
(2, 'Técnico Especialista', 'Gestión, diagnóstico y resolución de incidencias asignadas'),
(3, 'Usuario Solicitante', 'Creación y seguimiento del estado de sus requerimientos');

-- Categorías Maestras
INSERT OR IGNORE INTO categorias (id, nombre, codigo_prefijo, color_distintivo) VALUES
(1, 'FALLAS DE HARDWARE', 'HW', '#ef4444'),
(2, 'FALLAS DE SOFTWARE', 'SW', '#3b82f6'),
(3, 'FALLAS DE SERVICIOS DE RED', 'NET', '#8b5cf6'),
(4, 'FALLAS CON EQUIPOS DE IMPRESIÓN', 'PRN', '#f59e0b');

-- Subcategorías: 1. HARDWARE
INSERT OR IGNORE INTO subcategorias (categoria_id, nombre, prioridad_sugerida, sla_horas_resolucion) VALUES
(1, 'Fallo en los perifericos', 'Baja', 12),
(1, 'Fallo de Almacenamiento (HDD, SSD, NVME)', 'Crítica', 2),
(1, 'Fallo de memoria ram', 'Alta', 4),
(1, 'Fallo de fuente de poder', 'Alta', 4),
(1, 'Fallo de video GPU', 'Media', 8),
(1, 'Fallo de motherboard', 'Crítica', 6),
(1, 'Fallo de botones en Chasis', 'Baja', 16),
(1, 'Fallo de refrigeracion', 'Alta', 4),
(1, 'Fallo de tarjeta de red', 'Alta', 3),
(1, 'Fallo de pila de motherboard', 'Baja', 24),
(1, 'Fallo de monitores o pantalla integrada', 'Media', 6),
(1, 'Fallo en salidas de audio / video / puertos usb / otros puertos', 'Media', 8),
(1, 'Fallo en cables de audio o video', 'Baja', 12);

-- Subcategorías: 2. SOFTWARE
INSERT OR IGNORE INTO subcategorias (categoria_id, nombre, prioridad_sugerida, sla_horas_resolucion) VALUES
(2, 'Fallo de rendimiento del SO', 'Media', 6),
(2, 'Fallo de rendimiento de aplicativos', 'Media', 6),
(2, 'Fallo de aplicativos', 'Alta', 4),
(2, 'Fallo de lectura / escritura de archivos', 'Alta', 3),
(2, 'Fallo de servicios de dominio (inicios de sesion, conexion al dominio, sincronizacion general)', 'Crítica', 2);

-- Subcategorías: 3. RED
INSERT OR IGNORE INTO subcategorias (categoria_id, nombre, prioridad_sugerida, sla_horas_resolucion) VALUES
(3, 'Fallas en acceso a plataformas institucionales', 'Crítica', 2),
(3, 'Fallas en acceso a plataformas especificas', 'Alta', 4),
(3, 'Fallo de navegacion web', 'Media', 6),
(3, 'Fallo de red local (recusros compartidos, acceso a bases de datos)', 'Crítica', 2);

-- Subcategorías: 4. IMPRESIÓN
INSERT OR IGNORE INTO subcategorias (categoria_id, nombre, prioridad_sugerida, sla_horas_resolucion) VALUES
(4, 'Falla en impresion directa o protegida', 'Media', 6),
(4, 'Falla en maquina', 'Media', 8),
(4, 'Falla en conexion a impresoras o escaner compartidos', 'Media', 4),
(4, 'Falla en escaner local', 'Baja', 12),
(4, 'Falla en salida de impresion (Falta de toner/tinta, errores comunes en la impresion)', 'Baja', 8);

-- Índices de alto rendimiento para búsqueda rápida en el servidor local
CREATE INDEX IF NOT EXISTS idx_tickets_estado ON tickets(estado);
CREATE INDEX IF NOT EXISTS idx_tickets_prioridad ON tickets(prioridad);
CREATE INDEX IF NOT EXISTS idx_tickets_categoria ON tickets(categoria_id);
CREATE INDEX IF NOT EXISTS idx_tickets_tecnico ON tickets(tecnico_asignado_id);
CREATE INDEX IF NOT EXISTS idx_bitacora_ticket ON bitacora_tickets(ticket_id);

