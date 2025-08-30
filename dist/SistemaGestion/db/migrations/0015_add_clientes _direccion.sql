-- 0015_add_proveedores_direccion.sql
PRAGMA foreign_keys = ON;
ALTER TABLE proveedores ADD COLUMN direccion TEXT;
