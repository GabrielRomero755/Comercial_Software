-- 00011_create_venta_items.sql
CREATE TABLE IF NOT EXISTS venta_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  venta_id INTEGER NOT NULL,
  producto_id INTEGER NOT NULL,
  kilos REAL DEFAULT 0,
  unidades INTEGER DEFAULT 0,
  num_cajas REAL DEFAULT 0,
  precio REAL NOT NULL DEFAULT 0,
  importe REAL NOT NULL DEFAULT 0,
  FOREIGN KEY (venta_id) REFERENCES ventas(id) ON DELETE CASCADE
);
-- Índices de apoyo
CREATE INDEX IF NOT EXISTS idx_venta_items_venta_id ON venta_items(venta_id);
CREATE INDEX IF NOT EXISTS idx_venta_items_producto_id ON venta_items(producto_id);
