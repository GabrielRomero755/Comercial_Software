-- 0013_add_deuda_fk_to_pagos_proveedores.sql
PRAGMA foreign_keys = ON;

-- 1) Asegurar tabla con la columna nueva
CREATE TABLE IF NOT EXISTS pagos_proveedores (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor_id        INTEGER NOT NULL,
    monto               REAL    NOT NULL CHECK (monto > 0),
    fecha               TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    descripcion         TEXT,
    deuda_proveedor_id  INTEGER,
    FOREIGN KEY (proveedor_id)       REFERENCES proveedores(id),
    FOREIGN KEY (deuda_proveedor_id) REFERENCES deudas_proveedores(id)
);

-- 2) Índices
CREATE INDEX IF NOT EXISTS idx_pagos_proveedores_prov  ON pagos_proveedores(proveedor_id);
CREATE INDEX IF NOT EXISTS idx_pagos_proveedores_fecha ON pagos_proveedores(fecha);
CREATE INDEX IF NOT EXISTS idx_pagos_proveedores_deuda ON pagos_proveedores(deuda_proveedor_id);
