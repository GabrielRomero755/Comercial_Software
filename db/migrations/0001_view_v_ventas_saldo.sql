-- 0001_view_v_ventas_saldo.sql
CREATE VIEW IF NOT EXISTS v_ventas_saldo AS
SELECT
  v.id              AS venta_id,
  v.fecha,
  v.cliente_id,
  v.producto_id,
  v.tipo_venta,
  IFNULL(v.total, v.kilos * v.precio) AS total_venta,
  (SELECT IFNULL(SUM(monto),0) FROM pagos_cliente pc WHERE pc.venta_id = v.id) AS total_pagado,
  ROUND( (IFNULL(v.total, v.kilos * v.precio)) - 
         (SELECT IFNULL(SUM(monto),0) FROM pagos_cliente pc WHERE pc.venta_id = v.id), 2) AS saldo,
  CASE
    WHEN UPPER(IFNULL(v.estado,'')) = 'CANCELADA' THEN 'CANCELADA'
    WHEN ROUND( (IFNULL(v.total, v.kilos * v.precio)) - 
                (SELECT IFNULL(SUM(monto),0) FROM pagos_cliente pc WHERE pc.venta_id = v.id), 2) <= 0
         THEN 'PAGADA'
    ELSE 'PENDIENTE'
  END AS estatus
FROM ventas v
WHERE LOWER(IFNULL(v.tipo_venta,'')) = 'credito';
