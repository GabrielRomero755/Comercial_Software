-- ==========================================================
-- Tabla: deudas_proveedores (compras a crédito por proveedor)
--  Compatible con consultas del módulo de reportes:
--   - columnas usadas: fecha, producto_id, monto, saldo, descripcion, proveedor_id
-- ==========================================================
CREATE TABLE IF NOT EXISTS deudas_proveedores (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor_id  INTEGER NOT NULL,
    producto_id   INTEGER,  -- puede ser NULL si la deuda no está ligada a un producto
    monto         REAL    NOT NULL              CHECK (monto  >= 0),
    saldo         REAL    NOT NULL DEFAULT 0.0  CHECK (saldo  >= 0),
    descripcion   TEXT,
    fecha         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (proveedor_id) REFERENCES proveedores(id),
    FOREIGN KEY (producto_id)  REFERENCES productos(id)
);
CREATE INDEX IF NOT EXISTS idx_deudas_prov_proveedor ON deudas_proveedores(proveedor_id);
CREATE INDEX IF NOT EXISTS idx_deudas_prov_fecha     ON deudas_proveedores(fecha);

-- ==========================================================
-- Compatibilidad: el código busca la tabla "pagos_proveedores"
-- Si solo existe "pagos_proveedor" (singular), creamos la tabla
-- plural y migramos datos desde la singular.
--   - columnas usadas: fecha, descripcion, monto, proveedor_id
--   - columna opcional deuda_proveedor_id, si deseas vincular un pago a una deuda puntual
-- ==========================================================
CREATE TABLE IF NOT EXISTS pagos_proveedores (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor_id        INTEGER NOT NULL,
    monto               REAL    NOT NULL CHECK (monto > 0),
    fecha               TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    descripcion         TEXT,
    deuda_proveedor_id  INTEGER, -- opcional, para vincular a deudas_proveedores.id
    FOREIGN KEY (proveedor_id)       REFERENCES proveedores(id),
    FOREIGN KEY (deuda_proveedor_id) REFERENCES deudas_proveedores(id)
);
CREATE INDEX IF NOT EXISTS idx_pagos_proveedores_prov  ON pagos_proveedores(proveedor_id);
CREATE INDEX IF NOT EXISTS idx_pagos_proveedores_fecha ON pagos_proveedores(fecha);

-- Migración inicial de datos desde la tabla singular, si existe/contenido:
INSERT INTO pagos_proveedores (id, proveedor_id, monto, fecha, descripcion)
SELECT sp.id, sp.proveedor_id, sp.monto, sp.fecha, sp.descripcion
FROM pagos_proveedor AS sp
WHERE NOT EXISTS (
    SELECT 1 FROM pagos_proveedores pp WHERE pp.id = sp.id
);
