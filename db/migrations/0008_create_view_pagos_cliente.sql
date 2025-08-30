-- 0008_create_view_pagos_cliente.sql
PRAGMA foreign_keys = OFF;

DROP TABLE IF EXISTS pagos_cliente;  -- por si quedó como tabla
DROP VIEW  IF EXISTS pagos_cliente;

PRAGMA foreign_keys = ON;

CREATE VIEW pagos_cliente AS
SELECT 
    id, 
    cliente_id, 
    monto, 
    fecha, 
    descripcion
FROM pagos_credito;
