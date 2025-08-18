-- ==========================================================
--  Sistema de Comercio — Esquema de Base de Datos (SQLite)
--  Archivo: db/init_db.sql
--
--  DESCRIPCIÓN (Uso, Flujo y Funcionalidad)
--  ----------------------------------------------------------
--  Flujo principal:
--    1) Productos: catálogo con precios (mayoreo/menudeo) y stock en:
--       - kilos (REAL), num_cajas (REAL, permite 0.5), peso_caja (kg),
--         unidades (INTEGER).
--    2) Inventario: entradas/ajustes que aumentan stock (kilos/cajas/unidades).
--    3) Mermas: salidas por pérdida/daño que disminuyen stock.
--    4) Ventas: pueden registrarse por kilos, por cajas (conversión por peso_caja) o por unidades.
--       - Permite precio manual/mayoreo/menudeo (lógica en la app).
--       - Se guarda el 'total' de la venta para reportes.
--       - Si 'tipo_venta' = 'credito', el cliente acumula deuda y puede abonar en pagos_credito.
--    5) Gastos: registro de gastos (con catálogo de tipos) para reportes financieros.
--
--  Reportes y calendario:
--    - Fechas en hora local por defecto.
--    - Calendario puede resaltar días con ventas y con gastos (consultas por fecha).
--
--  Rendimiento:
--    - Índices en campos de búsqueda frecuentes (nombre, fecha, tipo, etc.).
--
--  Notas:
--    - Validación de hasta 2 decimales (kilos, num_cajas, peso_caja, precios) se aplica en la UI.
--    - En la BD se usan CHECKs de no-negatividad para consistencia.
-- ==========================================================

PRAGMA foreign_keys = ON;
-- PRAGMA journal_mode = WAL;  -- (opcional) mejor concurrencia

-- ==========================================================
-- Tabla: productos
-- ==========================================================
CREATE TABLE IF NOT EXISTS productos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre           TEXT    NOT NULL,
    precio_mayoreo   REAL    NOT NULL DEFAULT 0.0  CHECK (precio_mayoreo >= 0),
    precio_menudeo   REAL    NOT NULL DEFAULT 0.0  CHECK (precio_menudeo >= 0),
    kilos            REAL    NOT NULL DEFAULT 0.0  CHECK (kilos >= 0),
    num_cajas        REAL    NOT NULL DEFAULT 0.0  CHECK (num_cajas >= 0),
    peso_caja        REAL    NOT NULL DEFAULT 0.0  CHECK (peso_caja >= 0),
    unidades         INTEGER NOT NULL DEFAULT 0    CHECK (unidades >= 0)
);
CREATE INDEX IF NOT EXISTS idx_productos_nombre ON productos(nombre);

-- ==========================================================
-- Tabla: clientes (antes de ventas por FKs)
-- ==========================================================
CREATE TABLE IF NOT EXISTS clientes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre       TEXT    NOT NULL,
    telefono     TEXT,
    deuda_total  REAL            DEFAULT 0.0 CHECK (deuda_total >= 0)
);
CREATE INDEX IF NOT EXISTS idx_clientes_nombre ON clientes(nombre);

-- ==========================================================
-- Tabla: ventas
-- ==========================================================
CREATE TABLE IF NOT EXISTS ventas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id  INTEGER NOT NULL,
    kilos        REAL    NOT NULL DEFAULT 0.0  CHECK (kilos >= 0),
    num_cajas    REAL    NOT NULL DEFAULT 0.0  CHECK (num_cajas >= 0),
    unidades     INTEGER NOT NULL DEFAULT 0    CHECK (unidades >= 0),
    precio       REAL    NOT NULL              CHECK (precio > 0),
    total        REAL    NOT NULL DEFAULT 0.0  CHECK (total >= 0),
    fecha        TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    tipo_venta   TEXT    NOT NULL DEFAULT 'contado' CHECK (tipo_venta IN ('contado','credito')),
    cliente_id   INTEGER,
    FOREIGN KEY (producto_id) REFERENCES productos(id),
    FOREIGN KEY (cliente_id) REFERENCES clientes(id),
    CHECK ( (kilos > 0) OR (num_cajas > 0) OR (unidades > 0) )
);
CREATE INDEX IF NOT EXISTS idx_ventas_fecha        ON ventas(fecha);
CREATE INDEX IF NOT EXISTS idx_ventas_producto     ON ventas(producto_id);
CREATE INDEX IF NOT EXISTS idx_ventas_cliente      ON ventas(cliente_id);
CREATE INDEX IF NOT EXISTS idx_ventas_tipo         ON ventas(tipo_venta);

-- ==========================================================
-- Tabla: inventario (entradas/ajustes)
-- ==========================================================
CREATE TABLE IF NOT EXISTS inventario (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id  INTEGER NOT NULL,
    kilos        REAL    NOT NULL DEFAULT 0.0  CHECK (kilos >= 0),
    num_cajas    REAL    NOT NULL DEFAULT 0.0  CHECK (num_cajas >= 0),
    unidades     INTEGER NOT NULL DEFAULT 0    CHECK (unidades >= 0),
    tipo         TEXT,
    motivo       TEXT,
    fecha        TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (producto_id) REFERENCES productos(id),
    CHECK ( (kilos > 0) OR (num_cajas > 0) OR (unidades > 0) )
);
CREATE INDEX IF NOT EXISTS idx_inventario_producto ON inventario(producto_id);
CREATE INDEX IF NOT EXISTS idx_inventario_fecha    ON inventario(fecha);
CREATE INDEX IF NOT EXISTS idx_inventario_tipo     ON inventario(tipo);

-- ==========================================================
-- Tabla: mermas
-- ==========================================================
CREATE TABLE IF NOT EXISTS mermas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id  INTEGER NOT NULL,
    kilos        REAL    NOT NULL DEFAULT 0.0  CHECK (kilos >= 0),
    num_cajas    REAL    NOT NULL DEFAULT 0.0  CHECK (num_cajas >= 0),
    unidades     INTEGER NOT NULL DEFAULT 0    CHECK (unidades >= 0),
    motivo       TEXT,
    fecha        TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (producto_id) REFERENCES productos(id),
    CHECK ( (kilos > 0) OR (num_cajas > 0) OR (unidades > 0) )
);
CREATE INDEX IF NOT EXISTS idx_mermas_producto ON mermas(producto_id);
CREATE INDEX IF NOT EXISTS idx_mermas_fecha    ON mermas(fecha);

-- ==========================================================
-- Tabla: pagos_credito
-- ==========================================================
CREATE TABLE IF NOT EXISTS pagos_credito (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id   INTEGER NOT NULL,
    monto        REAL    NOT NULL CHECK (monto > 0),
    fecha        TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    descripcion  TEXT,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);
CREATE INDEX IF NOT EXISTS idx_pagos_credito_cliente ON pagos_credito(cliente_id);
CREATE INDEX IF NOT EXISTS idx_pagos_credito_fecha   ON pagos_credito(fecha);

-- ==========================================================
-- Tabla: gastos
-- ==========================================================
CREATE TABLE IF NOT EXISTS gastos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo         TEXT    NOT NULL,
    monto        REAL    NOT NULL,
    descripcion  TEXT,
    fecha        TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_gastos_fecha ON gastos(fecha);
CREATE INDEX IF NOT EXISTS idx_gastos_tipo  ON gastos(tipo);

-- ==========================================================
-- Tabla: tipos_gasto
-- ==========================================================
CREATE TABLE IF NOT EXISTS tipos_gasto (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre       TEXT UNIQUE NOT NULL
);
INSERT OR IGNORE INTO tipos_gasto (nombre) VALUES
('Salarios'),
('Préstamos'),
('Gastos Generales');

-- ==========================================================
--  Notas de migración (si vienes de un esquema anterior):
--    - productos:
--        * Añadir columnas: unidades (INTEGER), num_cajas REAL (si antes era INTEGER).
--        * Mantener kilos/peso_caja como REAL.
--        * (La columna histórica 'unidad' TEXT ya NO se usa en la app actual.)
--    - inventario/mermas:
--        * Añadir columnas: num_cajas (REAL), unidades (INTEGER).
--        * Renombrar cantidad→kilos si aplica.
--    - ventas:
--        * Añadir columnas: kilos REAL, num_cajas REAL, unidades INTEGER, total REAL.
--        * Ajustar reportes para usar 'total'.
--    - pagos_credito:
--        * Nueva tabla para abonos, enlazada a clientes.
--  Si necesitas, puedo generarte scripts de ALTER TABLE + copia segura
--  (BEGIN TRANSACTION/COMMIT) para migrar una base existente sin perder datos.
-- ==========================================================
