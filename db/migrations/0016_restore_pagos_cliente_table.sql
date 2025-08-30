-- 0016_restore_pagos_cliente_table.sql
-- Reemplaza la vista pagos_cliente por una tabla real con columna venta_id
-- y migra los datos si existía pagos_credito

PRAGMA foreign_keys = OFF;

-- 1. Eliminar vista obsoleta
DROP VIEW IF EXISTS pagos_cliente;

-- 2. Eliminar tabla pagos_cliente si quedó creada por error
DROP TABLE IF EXISTS pagos_cliente;

-- 3. Crear tabla real unificada con venta_id
CREATE TABLE pagos_cliente (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id   INTEGER NOT NULL,
    venta_id     INTEGER,
    monto        REAL    NOT NULL CHECK (monto > 0),
    fecha        TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    nota         TEXT,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id),
    FOREIGN KEY (venta_id)   REFERENCES ventas(id)
);

-- 4. Migrar datos desde pagos_credito si existe
INSERT INTO pagos_cliente (cliente_id, venta_id, monto, fecha, nota)
SELECT cliente_id,
       NULL AS venta_id,
       monto,
       fecha,
       descripcion
FROM pagos_credito
WHERE EXISTS (
    SELECT 1 FROM sqlite_master WHERE type='table' AND name='pagos_credito'
);

-- 5. Eliminar tabla antigua pagos_credito (ya migrada)
DROP TABLE IF EXISTS pagos_credito;

-- 6. Índices recomendados
CREATE INDEX IF NOT EXISTS idx_pagos_cliente_cliente ON pagos_cliente(cliente_id);
CREATE INDEX IF NOT EXISTS idx_pagos_cliente_venta   ON pagos_cliente(venta_id);
CREATE INDEX IF NOT EXISTS idx_pagos_cliente_fecha   ON pagos_cliente(fecha);

PRAGMA foreign_keys = ON;
