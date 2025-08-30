-- 0005_add_venta_id_to_pagos_cliente.sql

-- Si existe una VISTA llamada pagos_cliente, eliminarla primero
DROP VIEW IF EXISTS pagos_cliente;

-- Crear la TABLA pagos_cliente (si no existía)
CREATE TABLE IF NOT EXISTS pagos_cliente (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id),
  venta_id   INTEGER     REFERENCES ventas(id),
  monto      REAL    NOT NULL DEFAULT 0,
  fecha      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
  nota       TEXT
);

-- Índices útiles
CREATE INDEX IF NOT EXISTS idx_pagos_cliente_cliente ON pagos_cliente(cliente_id);
CREATE INDEX IF NOT EXISTS idx_pagos_cliente_venta   ON pagos_cliente(venta_id);
CREATE INDEX IF NOT EXISTS idx_pagos_cliente_fecha   ON pagos_cliente(fecha);

-- Migrar datos legacy desde pagos_credito (si existe)
INSERT INTO pagos_cliente (cliente_id, venta_id, monto, fecha, nota)
SELECT pc.cliente_id,
       NULL AS venta_id,
       pc.monto,
       datetime('now','localtime') AS fecha_migrada,
       COALESCE(pc.descripcion, 'Migrado de pagos_credito')
FROM pagos_credito pc
WHERE EXISTS (SELECT 1 FROM sqlite_master WHERE type='table' AND name='pagos_credito');
