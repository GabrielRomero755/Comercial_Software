-- 0014_alter_ventas_postventa_enforce_kilos_unidades_xor.sql
PRAGMA foreign_keys = OFF;

-- Eliminar vista dependiente para evitar conflictos
DROP VIEW IF EXISTS v_ventas_saldo;

-- Re-crear ventas con XOR y producto_id NOT NULL
CREATE TABLE ventas_new (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id        INTEGER NOT NULL REFERENCES productos(id),
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
    motivo_cancelacion TEXT,
    CONSTRAINT chk_kilos_unidades_xor CHECK (
        ((kilos > 0) AND (unidades = 0)) OR
        ((unidades > 0) AND (kilos = 0)) OR
        ((kilos = 0) AND (unidades = 0))
    )
);

INSERT INTO ventas_new (
    id, producto_id, kilos, num_cajas, unidades, precio, total,
    tipo_venta, cliente_id, fecha, estado, fecha_cancelacion, motivo_cancelacion
)
SELECT
    id,
    producto_id,
    CASE
        WHEN IFNULL(kilos,0) > 0 AND IFNULL(unidades,0) > 0 THEN IFNULL(kilos,0)
        ELSE IFNULL(kilos,0)
    END,
    IFNULL(num_cajas,0),
    CASE
        WHEN IFNULL(kilos,0) > 0 AND IFNULL(unidades,0) > 0 THEN 0
        ELSE IFNULL(unidades,0)
    END,
    IFNULL(precio,0),
    IFNULL(total, IFNULL(kilos,0) * IFNULL(precio,0)),
    tipo_venta, cliente_id, fecha, estado, fecha_cancelacion, motivo_cancelacion
FROM ventas;

DROP TABLE ventas;
ALTER TABLE ventas_new RENAME TO ventas;

-- Índices
CREATE INDEX IF NOT EXISTS idx_ventas_fecha    ON ventas(fecha);
CREATE INDEX IF NOT EXISTS idx_ventas_producto ON ventas(producto_id);
CREATE INDEX IF NOT EXISTS idx_ventas_cliente  ON ventas(cliente_id);
CREATE INDEX IF NOT EXISTS idx_ventas_tipo     ON ventas(tipo_venta);

-- Vista mínima (si necesitas la versión “saldo” completa, puedes re-aplicarla en una 0016)
CREATE VIEW v_ventas_saldo AS
SELECT
    v.id, v.producto_id, v.kilos, v.num_cajas, v.unidades, v.precio, v.total,
    v.tipo_venta, v.cliente_id, v.fecha, v.estado, v.fecha_cancelacion, v.motivo_cancelacion
FROM ventas v;

PRAGMA foreign_keys = ON;
