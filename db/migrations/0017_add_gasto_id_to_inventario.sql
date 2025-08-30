-- 0017_add_gasto_id_to_inventario.sql
-- Agrega las columnas 'gasto_id', 'deuda_proveedor_id' y 'monto' a la tabla 'inventario'

PRAGMA foreign_keys = OFF;

ALTER TABLE inventario RENAME TO inventario_old;

CREATE TABLE inventario (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL,
    kilos REAL NOT NULL DEFAULT 0.0 CHECK (kilos >= 0),
    num_cajas REAL NOT NULL DEFAULT 0.0 CHECK (num_cajas >= 0),
    unidades INTEGER NOT NULL DEFAULT 0 CHECK (unidades >= 0),
    tipo TEXT,
    motivo TEXT,
    fecha TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    gasto_id INTEGER,
    deuda_proveedor_id INTEGER,
    monto REAL DEFAULT 0.0 CHECK (monto >= 0),

    FOREIGN KEY (producto_id) REFERENCES productos(id),
    FOREIGN KEY (gasto_id) REFERENCES gastos(id),
    FOREIGN KEY (deuda_proveedor_id) REFERENCES deudas_proveedores(id),

    CHECK ((kilos > 0) OR (num_cajas > 0) OR (unidades > 0))
);

INSERT INTO inventario (
    id, producto_id, kilos, num_cajas, unidades, tipo, motivo, fecha,
    gasto_id, deuda_proveedor_id, monto
)
SELECT
    id, producto_id, kilos, num_cajas, unidades, tipo, motivo, fecha,
    NULL AS gasto_id, NULL AS deuda_proveedor_id, 0.0 AS monto
FROM inventario_old;

DROP TABLE inventario_old;

CREATE INDEX IF NOT EXISTS idx_inventario_producto ON inventario(producto_id);
CREATE INDEX IF NOT EXISTS idx_inventario_fecha    ON inventario(fecha);
CREATE INDEX IF NOT EXISTS idx_inventario_tipo     ON inventario(tipo);

PRAGMA foreign_keys = ON;
