-- 0007_alter_gastos_add_empleado_y_cliente.sql
PRAGMA foreign_keys = ON;

-- Reconstituye 'gastos' para agregar FKs a empleados y clientes
DROP TABLE IF EXISTS gastos_new;

CREATE TABLE gastos_new (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo         TEXT    NOT NULL,
    monto        REAL    NOT NULL CHECK (monto >= 0),
    descripcion  TEXT,
    fecha        TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    empleado_id  INTEGER,
    cliente_id   INTEGER,
    FOREIGN KEY (empleado_id) REFERENCES empleados(id),
    FOREIGN KEY (cliente_id)  REFERENCES clientes(id)
);

INSERT INTO gastos_new (id, tipo, monto, descripcion, fecha, empleado_id, cliente_id)
SELECT id, tipo, monto, descripcion, fecha, NULL, NULL
FROM gastos;

DROP TABLE gastos;
ALTER TABLE gastos_new RENAME TO gastos;

CREATE INDEX IF NOT EXISTS idx_gastos_fecha     ON gastos(fecha);
CREATE INDEX IF NOT EXISTS idx_gastos_tipo      ON gastos(tipo);
CREATE INDEX IF NOT EXISTS idx_gastos_empleado  ON gastos(empleado_id);
CREATE INDEX IF NOT EXISTS idx_gastos_cliente   ON gastos(cliente_id);
