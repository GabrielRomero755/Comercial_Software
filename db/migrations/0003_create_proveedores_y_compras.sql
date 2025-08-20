-- 0003_create_proveedores_y_compras.sql
PRAGMA foreign_keys = ON;

-- Proveedores
CREATE TABLE IF NOT EXISTS proveedores (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre       TEXT NOT NULL,
    telefono     TEXT,
    deuda_total  REAL NOT NULL DEFAULT 0.0 CHECK (deuda_total >= 0)
);
CREATE INDEX IF NOT EXISTS idx_proveedores_nombre ON proveedores(nombre);

-- Compras a proveedores (por kilos o por unidades; num_cajas solo informativo)
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
