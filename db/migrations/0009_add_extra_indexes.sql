-- 0009_add_extra_indexes.sql
PRAGMA foreign_keys = ON;

-- Índices adicionales (en caso de que no existan)
CREATE INDEX IF NOT EXISTS idx_ventas_estado       ON ventas(estado);
CREATE INDEX IF NOT EXISTS idx_compras_tipo        ON compras(tipo_compra);
CREATE INDEX IF NOT EXISTS idx_gastos_empleado     ON gastos(empleado_id);
CREATE INDEX IF NOT EXISTS idx_gastos_cliente      ON gastos(cliente_id);
