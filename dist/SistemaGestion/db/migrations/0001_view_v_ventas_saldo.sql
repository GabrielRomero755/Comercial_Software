-- 0001_view_v_ventas_saldo.sql
-- Crea/recrea una vista con el saldo de clientes = ventas a crédito activas - pagos.
-- Idempotente y SIN BEGIN/COMMIT (el runner se encarga de la transacción).

PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_ventas_saldo;

CREATE VIEW v_ventas_saldo AS
WITH ventas_credito AS (
  SELECT
    c.id AS cliente_id,
    COALESCE(SUM(v.total), 0) AS total_credito
  FROM clientes c
  LEFT JOIN ventas v
    ON v.cliente_id = c.id
   AND v.tipo_venta = 'credito'
   AND (v.estado IS NULL OR v.estado <> 'CANCELADA')
  GROUP BY c.id
),
pagos AS (
  SELECT
    c.id AS cliente_id,
    COALESCE(SUM(p.monto), 0) AS total_pagado
  FROM clientes c
  LEFT JOIN pagos_credito p
    ON p.cliente_id = c.id
  GROUP BY c.id
)
SELECT
  c.id                           AS cliente_id,
  c.nombre                       AS cliente_nombre,
  COALESCE(vc.total_credito, 0)  AS total_credito,
  COALESCE(pg.total_pagado, 0)   AS total_pagado,
  (COALESCE(vc.total_credito, 0) - COALESCE(pg.total_pagado, 0)) AS saldo
FROM clientes c
LEFT JOIN ventas_credito vc ON vc.cliente_id = c.id
LEFT JOIN pagos pg          ON pg.cliente_id = c.id;
