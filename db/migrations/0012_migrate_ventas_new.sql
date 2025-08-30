-- 0012_migrate_ventas_new.sql
PRAGMA foreign_keys = OFF;

-- 1) Quitar dependencias de 'ventas'
DROP VIEW IF EXISTS v_ventas_saldo;

-- 2) Migrar la tabla 'ventas' (permitir producto_id NULL)
CREATE TABLE ventas_new (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  producto_id        INTEGER NULL REFERENCES productos(id),
  kilos              REAL    NOT NULL DEFAULT 0,
  num_cajas          REAL    NOT NULL DEFAULT 0,
  unidades           INTEGER NOT NULL DEFAULT 0,
  precio             REAL    NOT NULL DEFAULT 0,
  total              REAL    NOT NULL DEFAULT 0,
  tipo_venta         TEXT,
  cliente_id         INTEGER REFERENCES clientes(id),
  fecha              TEXT    NOT NULL,
  estado             TEXT    DEFAULT 'ACTIVA',
  fecha_cancelacion  TEXT,
  motivo_cancelacion TEXT
);

INSERT INTO ventas_new
(id, producto_id, kilos, num_cajas, unidades, precio, total, tipo_venta, cliente_id, fecha, estado, fecha_cancelacion, motivo_cancelacion)
SELECT
 id, producto_id, kilos, num_cajas, unidades, precio, total, tipo_venta, cliente_id, fecha, estado, fecha_cancelacion, motivo_cancelacion
FROM ventas;

DROP TABLE ventas;
ALTER TABLE ventas_new RENAME TO ventas;

-- 3) (Re)crear índices mínimos si aplica
-- CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha);

-- 4) Recrear una vista mínima temporal (si necesitas la “saldo”, 0001 ya la define al inicio;
--    puedes re-aplicarla en una migración posterior si quieres esa versión final)
CREATE VIEW v_ventas_saldo AS
SELECT
  v.id,
  v.fecha,
  v.tipo_venta,
  v.total,
  COALESCE(c.nombre,'') AS cliente,
  COALESCE(p.nombre,'') AS producto
FROM ventas v
LEFT JOIN clientes  c ON c.id = v.cliente_id
LEFT JOIN productos p ON p.id = v.producto_id;

PRAGMA foreign_keys = ON;
