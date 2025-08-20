-- 0010_recompute_deudas_clientes_y_proveedores.sql
PRAGMA foreign_keys = ON;
BEGIN TRANSACTION;

-- Recalcula deudas de clientes = ventas a crédito activas - pagos
UPDATE clientes AS c
SET deuda_total = ROUND(
    IFNULL((
        SELECT SUM(v.total)
        FROM ventas v
        WHERE v.cliente_id = c.id
          AND v.tipo_venta = 'credito'
          AND v.estado = 'ACTIVA'
    ), 0)
    -
    IFNULL((
        SELECT SUM(p.monto)
        FROM pagos_credito p
        WHERE p.cliente_id = c.id
    ), 0)
, 2);

-- Recalcula deudas de proveedores = compras a crédito - pagos a proveedor
UPDATE proveedores AS pr
SET deuda_total = ROUND(
    IFNULL((
        SELECT SUM(co.total)
        FROM compras co
        WHERE co.proveedor_id = pr.id
          AND co.tipo_compra = 'credito'
    ), 0)
    -
    IFNULL((
        SELECT SUM(pp.monto)
        FROM pagos_proveedor pp
        WHERE pp.proveedor_id = pr.id
    ), 0)
, 2);

COMMIT;
