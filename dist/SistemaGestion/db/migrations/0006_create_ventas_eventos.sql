-- 0006_create_ventas_eventos.sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ventas_eventos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id  INTEGER NOT NULL,
    tipo      TEXT NOT NULL CHECK (tipo IN ('CREADA','MODIFICADA','CANCELADA')),
    detalle   TEXT,
    fecha     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (venta_id) REFERENCES ventas(id)
);
CREATE INDEX IF NOT EXISTS idx_ventas_eventos_venta ON ventas_eventos(venta_id);
CREATE INDEX IF NOT EXISTS idx_ventas_eventos_fecha ON ventas_eventos(fecha);
