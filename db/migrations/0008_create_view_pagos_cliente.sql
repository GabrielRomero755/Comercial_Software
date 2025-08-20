-- 0008_create_view_pagos_cliente.sql
PRAGMA foreign_keys = ON;

-- Alias para reportes (consistencia semántica)
DROP VIEW IF EXISTS pagos_cliente;
CREATE VIEW pagos_cliente AS
SELECT id, cliente_id, monto, fecha, descripcion
FROM pagos_credito;
