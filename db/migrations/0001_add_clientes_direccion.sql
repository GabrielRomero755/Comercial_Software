-- 0001_add_clientes_direccion.sql
PRAGMA foreign_keys = ON;

-- Agrega campo de dirección a clientes
ALTER TABLE clientes ADD COLUMN direccion TEXT;
