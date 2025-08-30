-- ==========================================================
--  Sistema de Comercio — Esquema de Base de Datos (SQLite)
--  Archivo: db/schema.sql
--
--  Descripción
--  ----------------------------------------------------------
--  - Ventas: total SIEMPRE = precio * (kilos OR unidades).
--    num_cajas es solo informativo (stock); no influye en el total.
--    Soporta post-venta (cancelación/modificación).
--  - Clientes: +direccion.
--  - Proveedores y Compras a crédito, + pagos_proveedor.
--  - Gastos: opcionalmente asociados a empleados o clientes.
--  - Índices para búsquedas/reportes.
--  - Idempotente (IF NOT EXISTS / INSERT OR IGNORE).
-- ==========================================================

PRAGMA foreign_keys = ON;
-- PRAGMA journal_mode = WAL;  -- opcional

-- ==========================================================
-- Soporte de migraciones (opcional)
-- ==========================================================
CREATE TABLE IF NOT EXISTS schema_migrations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    filename   TEXT UNIQUE NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

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
-- Tabla: clientes
-- ==========================================================
CREATE TABLE IF NOT EXISTS clientes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre       TEXT    NOT NULL,
    telefono     TEXT,
    direccion    TEXT, -- NUEVO
    deuda_total  REAL            DEFAULT 0.0 CHECK (deuda_total >= 0)
);
CREATE INDEX IF NOT EXISTS idx_clientes_nombre ON clientes(nombre);

-- ==========================================================
-- Tabla: empleados (para gastos de tipo salario u otros)
-- ==========================================================
CREATE TABLE IF NOT EXISTS empleados (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre    TEXT NOT NULL,
    telefono  TEXT,
    direccion TEXT
);
CREATE INDEX IF NOT EXISTS idx_empleados_nombre ON empleados(nombre);

-- ==========================================================
-- Tabla: proveedores
-- ==========================================================
CREATE TABLE IF NOT EXISTS proveedores (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre       TEXT NOT NULL,
    telefono     TEXT,
    deuda_total  REAL NOT NULL DEFAULT 0.0 CHECK (deuda_total >= 0)
);
CREATE INDEX IF NOT EXISTS idx_proveedores_nombre ON proveedores(nombre);

-- ==========================================================
-- Tabla: ventas
--   * num_cajas = informativo/stock; NO influye en el total.
--   * Modalidad válida: por KILOS o por UNIDADES (exclusivas).
--   * Post-venta: cancelación/modificación.
-- ==========================================================
CREATE TABLE IF NOT EXISTS ventas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id         INTEGER NOT NULL,
    kilos               REAL    NOT NULL DEFAULT 0.0  CHECK (kilos >= 0),
    num_cajas           REAL    NOT NULL DEFAULT 0.0  CHECK (num_cajas >= 0),
    unidades            INTEGER NOT NULL DEFAULT 0    CHECK (unidades >= 0),
    precio              REAL    NOT NULL              CHECK (precio > 0),
    total               REAL    NOT NULL DEFAULT 0.0  CHECK (total >= 0),
    fecha               TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    tipo_venta          TEXT    NOT NULL DEFAULT 'contado' CHECK (tipo_venta IN ('contado','credito')),
    cliente_id          INTEGER,
    -- Post-venta:
    estado              TEXT    NOT NULL DEFAULT 'ACTIVA' CHECK (estado IN ('ACTIVA','CANCELADA')),
    fecha_cancelacion   TEXT,
    motivo_cancelacion  TEXT,
    FOREIGN KEY (producto_id) REFERENCES productos(id),
    FOREIGN KEY (cliente_id)  REFERENCES clientes(id),
    CHECK ( (kilos > 0 AND unidades = 0) OR (unidades > 0 AND kilos = 0) )
);
CREATE INDEX IF NOT EXISTS idx_ventas_fecha        ON ventas(fecha);
CREATE INDEX IF NOT EXISTS idx_ventas_producto     ON ventas(producto_id);
CREATE INDEX IF NOT EXISTS idx_ventas_cliente      ON ventas(cliente_id);
CREATE INDEX IF NOT EXISTS idx_ventas_tipo         ON ventas(tipo_venta);
CREATE INDEX IF NOT EXISTS idx_ventas_estado       ON ventas(estado);

-- Bitácora de eventos de venta (creada/modificada/cancelada)
CREATE TABLE IF NOT EXISTS ventas_eventos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id  INTEGER NOT NULL,
    tipo      TEXT NOT NULL CHECK (tipo IN ('CREADA','MODIFICADA','CANCELADA')),
    detalle   TEXT,
    fecha     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (venta_id) REFERENCES ventas(id)
);
CREATE INDEX IF NOT EXISTS idx_ventas_eventos_venta ON ventas_eventos(venta_id);
CREATE INDEX IF NOT EXISTS idx_ventas_eventos_fecha ON ventas_eventos(fecha);

-- ==========================================================
-- Tabla: inventario (entradas/ajustes manuales)
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
-- Tabla: mermas (salidas por pérdida/daño)
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
-- Tabla: pagos_credito (pagos individuales de clientes)
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

-- Vista alias para reportes (nomenclatura clara)
CREATE VIEW IF NOT EXISTS pagos_cliente AS
SELECT id, cliente_id, monto, fecha, descripcion FROM pagos_credito;

-- ==========================================================
-- Compras a proveedores + pagos_proveedor
-- ==========================================================
CREATE TABLE IF NOT EXISTS compras (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor_id  INTEGER NOT NULL,
    producto_id   INTEGER NOT NULL,
    kilos         REAL    NOT NULL DEFAULT 0.0  CHECK (kilos >= 0),
    num_cajas     REAL    NOT NULL DEFAULT 0.0  CHECK (num_cajas >= 0),
    unidades      INTEGER NOT NULL DEFAULT 0    CHECK (unidades >= 0),
    precio        REAL    NOT NULL DEFAULT 0.0  CHECK (precio >= 0),
    total         REAL    NOT NULL DEFAULT 0.0  CHECK (total >= 0),
    fecha         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    tipo_compra   TEXT    NOT NULL DEFAULT 'contado' CHECK (tipo_compra IN ('contado','credito')),
    FOREIGN KEY (proveedor_id) REFERENCES proveedores(id),
    FOREIGN KEY (producto_id)  REFERENCES productos(id),
    CHECK ( (kilos > 0 AND unidades = 0) OR (unidades > 0 AND kilos = 0) )
);
CREATE INDEX IF NOT EXISTS idx_compras_fecha       ON compras(fecha);
CREATE INDEX IF NOT EXISTS idx_compras_proveedor   ON compras(proveedor_id);
CREATE INDEX IF NOT EXISTS idx_compras_producto    ON compras(producto_id);
CREATE INDEX IF NOT EXISTS idx_compras_tipo        ON compras(tipo_compra);

CREATE TABLE IF NOT EXISTS pagos_proveedor (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor_id  INTEGER NOT NULL,
    monto         REAL    NOT NULL CHECK (monto > 0),
    fecha         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    descripcion   TEXT,
    FOREIGN KEY (proveedor_id) REFERENCES proveedores(id)
);
CREATE INDEX IF NOT EXISTS idx_pagos_proveedor_prov  ON pagos_proveedor(proveedor_id);
CREATE INDEX IF NOT EXISTS idx_pagos_proveedor_fecha ON pagos_proveedor(fecha);

-- ==========================================================
-- Tabla: gastos (asociables a empleado o cliente)
-- ==========================================================
CREATE TABLE IF NOT EXISTS gastos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo         TEXT    NOT NULL,
    monto        REAL    NOT NULL CHECK (monto >= 0),
    descripcion  TEXT,
    fecha        TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    empleado_id  INTEGER,
    cliente_id   INTEGER,
    FOREIGN KEY (empleado_id) REFERENCES empleados(id),
    FOREIGN KEY (cliente_id)  REFERENCES clientes(id)
);
CREATE INDEX IF NOT EXISTS idx_gastos_fecha     ON gastos(fecha);
CREATE INDEX IF NOT EXISTS idx_gastos_tipo      ON gastos(tipo);
CREATE INDEX IF NOT EXISTS idx_gastos_empleado  ON gastos(empleado_id);
CREATE INDEX IF NOT EXISTS idx_gastos_cliente   ON gastos(cliente_id);

-- ==========================================================
-- Tabla: tipos_gasto (catálogo)
-- ==========================================================
CREATE TABLE IF NOT EXISTS tipos_gasto (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre       TEXT UNIQUE NOT NULL
);
INSERT OR IGNORE INTO tipos_gasto (nombre) VALUES
('Salarios'),
('Préstamos'),
('Gastos Generales');
