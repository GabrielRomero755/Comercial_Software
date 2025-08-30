-- 0004_create_pagos_proveedor.sql
PRAGMA foreign_keys = ON;

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
