-- 0002_create_empleados.sql
PRAGMA foreign_keys = ON;

-- Tabla de empleados (CRUD para salarios u otros gastos)
CREATE TABLE IF NOT EXISTS empleados (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre    TEXT NOT NULL,
    telefono  TEXT,
    direccion TEXT
);
CREATE INDEX IF NOT EXISTS idx_empleados_nombre ON empleados(nombre);
