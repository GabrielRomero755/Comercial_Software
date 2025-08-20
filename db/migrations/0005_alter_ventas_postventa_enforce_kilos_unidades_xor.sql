-- 0005_alter_ventas_postventa_enforce_kilos_unidades_xor.sql
PRAGMA foreign_keys = ON;
BEGIN TRANSACTION;

-- Reconstituir 'ventas' para:
--  * agregar estado/motivo/fecha_cancelacion (post-venta)
--  * exigir modalidad exclusiva (kilos XOR unidades)
--  * mantener num_cajas como informativo (no entra al total)
--  * normalizar 'total' si estuviera nulo

DROP TABLE IF EXISTS ventas_new;

CREATE TABLE ventas_new (
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
    estado              TEXT    NOT NULL DEFAULT 'ACTIVA' CHECK (estado IN ('ACTIVA','CANCELADA')),
    fecha_cancelacion   TEXT,
    motivo_cancelacion  TEXT,
    FOREIGN KEY (producto_id) REFERENCES productos(id),
    FOREIGN KEY (cliente_id)  REFERENCES clientes(id),
    CHECK ( (kilos > 0 AND unidades = 0) OR (unidades > 0 AND kilos = 0) )
);

-- Migrar datos, calculando kilos desde num_cajas*peso_caja si fue venta por cajas "puras"
INSERT INTO ventas_new (
    id, producto_id, kilos, num_cajas, unidades, precio, total, fecha, tipo_venta, cliente_id, estado, fecha_cancelacion, motivo_cancelacion
)
SELECT
    v.id,
    v.producto_id,
    -- kilos_new:
    CASE
        WHEN (IFNULL(v.kilos,0)=0 AND IFNULL(v.unidades,0)=0 AND IFNULL(v.num_cajas,0)>0)
             THEN ROUND( IFNULL(v.num_cajas,0) * IFNULL(p.peso_caja,0), 2 )
        ELSE IFNULL(v.kilos,0)
    END AS kilos_new,
    IFNULL(v.num_cajas,0) AS num_cajas_new,
    -- unidades_new: si hay kilos (>0) fuerzo unidades=0; si no, conservo unidades
    CASE
        WHEN (
            (IFNULL(v.kilos,0)>0) OR
            (IFNULL(v.kilos,0)=0 AND IFNULL(v.unidades,0)=0 AND IFNULL(v.num_cajas,0)>0)
        )
            THEN 0
        ELSE IFNULL(v.unidades,0)
    END AS unidades_new,
    v.precio,
    -- total_new: si total ya viene, respetarlo; si no, recalcular coherente
    CASE
        WHEN v.total IS NOT NULL AND v.total > 0 THEN v.total
        ELSE
            CASE
                WHEN (
                    (IFNULL(v.kilos,0)>0) OR
                    (IFNULL(v.kilos,0)=0 AND IFNULL(v.unidades,0)=0 AND IFNULL(v.num_cajas,0)>0)
                )
                    THEN ROUND(
                        (CASE
                            WHEN (IFNULL(v.kilos,0)=0 AND IFNULL(v.unidades,0)=0 AND IFNULL(v.num_cajas,0)>0)
                                THEN IFNULL(v.num_cajas,0) * IFNULL(p.peso_caja,0)
                            ELSE IFNULL(v.kilos,0)
                         END) * v.precio, 2)
                ELSE ROUND(IFNULL(v.unidades,0) * v.precio, 2)
            END
    END AS total_new,
    v.fecha,
    COALESCE(v.tipo_venta,'contado') AS tipo_venta_new,
    v.cliente_id,
    'ACTIVA' AS estado,
    NULL AS fecha_cancelacion,
    NULL AS motivo_cancelacion
FROM ventas v
JOIN productos p ON p.id = v.producto_id;

DROP TABLE ventas;
ALTER TABLE ventas_new RENAME TO ventas;

-- Índices
CREATE INDEX IF NOT EXISTS idx_ventas_fecha        ON ventas(fecha);
CREATE INDEX IF NOT EXISTS idx_ventas_producto     ON ventas(producto_id);
CREATE INDEX IF NOT EXISTS idx_ventas_cliente      ON ventas(cliente_id);
CREATE INDEX IF NOT EXISTS idx_ventas_tipo         ON ventas(tipo_venta);
CREATE INDEX IF NOT EXISTS idx_ventas_estado       ON ventas(estado);

COMMIT;
