BEGIN;

-- Solo agrega la columna si no existe todavía
ALTER TABLE pagos_proveedores
ADD COLUMN deuda_proveedor_id INTEGER REFERENCES deudas_proveedores(id);

COMMIT;
