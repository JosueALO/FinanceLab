-- =============================================================================
-- FINANCE LAB — Esquema de Base de Datos
-- Migración desde Google Sheets a PostgreSQL
-- Josué Axel López de la O
-- =============================================================================

-- ── EXTENSIONES ──
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- TABLAS DE CATÁLOGO (Lookup Tables)
-- =============================================================================

-- CATEGORÍAS DE GASTO
CREATE TABLE categorias (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(150) NOT NULL UNIQUE,
    icono       VARCHAR(10),
    activo      BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- MÉTODOS DE PAGO
CREATE TABLE metodos_pago (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(100) NOT NULL UNIQUE,
    es_credito  BOOLEAN NOT NULL DEFAULT false,
    activo      BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- TIPOS DE GASTO (Cómo se divide: 50/50, personal, proporcional)
CREATE TABLE tipos_gasto (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(100) NOT NULL UNIQUE,
    descripcion TEXT,
    activo      BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- REGISTRADORES (Quién registró el gasto)
CREATE TABLE registradores (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(80) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- TABLAS PRINCIPALES
-- =============================================================================

-- GASTOS (Tabla principal)
CREATE TABLE gastos (
    id_unico            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fecha_compra        DATE NOT NULL,
    fecha_registro      DATE NOT NULL DEFAULT CURRENT_DATE,
    registrador_id      INTEGER REFERENCES registradores(id),
    compra              VARCHAR(255) NOT NULL,
    categoria_id        INTEGER REFERENCES categorias(id),
    monto_total         DECIMAL(12,2) NOT NULL CHECK (monto_total >= 0),
    monto_parcial       DECIMAL(12,2) CHECK (monto_parcial >= 0),
    msi_status          DATE,           -- fecha fin MSI; NULL o '2026-01-01' = sin MSI
    metodo_pago_id      INTEGER REFERENCES metodos_pago(id),
    tipo_gasto_id       INTEGER REFERENCES tipos_gasto(id),
    periodo_pago        DATE,           -- periodo contable al que pertenece
    participacion_josue DECIMAL(12,2) NOT NULL DEFAULT 0 CHECK (participacion_josue >= 0),
    participacion_abi   DECIMAL(12,2) NOT NULL DEFAULT 0 CHECK (participacion_abi >= 0),
    notas               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Índices para gastos
CREATE INDEX idx_gastos_fecha_compra ON gastos(fecha_compra);
CREATE INDEX idx_gastos_fecha_registro ON gastos(fecha_registro);
CREATE INDEX idx_gastos_categoria ON gastos(categoria_id);
CREATE INDEX idx_gastos_periodo ON gastos(periodo_pago);
CREATE INDEX idx_gastos_metodo_pago ON gastos(metodo_pago_id);
CREATE INDEX idx_gastos_tipo ON gastos(tipo_gasto_id);
CREATE INDEX idx_gastos_registrador ON gastos(registrador_id);

-- PAPELERA DE GASTOS (Auditoría de eliminados)
CREATE TABLE gastos_borrados (
    id                  SERIAL PRIMARY KEY,
    id_unico            UUID NOT NULL,
    fecha_compra        DATE,
    fecha_registro      DATE,
    registrador         VARCHAR(80),
    compra              VARCHAR(255),
    categoria           VARCHAR(150),
    monto_total         DECIMAL(12,2),
    monto_parcial       DECIMAL(12,2),
    msi_status          DATE,
    metodo_pago         VARCHAR(100),
    tipo_gasto          VARCHAR(100),
    periodo_pago        DATE,
    participacion_josue DECIMAL(12,2),
    participacion_abi   DECIMAL(12,2),
    notas               TEXT,
    fecha_borrado       TIMESTAMPTZ NOT NULL DEFAULT now(),
    borrado_por         VARCHAR(80)
);

-- PRESUPUESTOS (Configuración de presupuesto por ámbito y categoría)
CREATE TABLE presupuestos (
    id              SERIAL PRIMARY KEY,
    ambito          VARCHAR(20) NOT NULL CHECK (ambito IN ('Compartido', 'Josue', 'Abi')),
    categoria_id    INTEGER REFERENCES categorias(id),
    monto           DECIMAL(12,2) NOT NULL DEFAULT 0 CHECK (monto >= 0),
    periodo_inicio  DATE,
    periodo_fin     DATE,
    activo          BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(ambito, categoria_id)
);

-- =============================================================================
-- TRIGGER: updated_at automático
-- =============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_gastos_updated_at
    BEFORE UPDATE ON gastos
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_presupuestos_updated_at
    BEFORE UPDATE ON presupuestos
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- FUNCIONES ÚTILES
-- =============================================================================

-- Trigger para mover gastos a la papelera en vez de borrar
CREATE OR REPLACE FUNCTION soft_delete_gasto(target_id UUID, quien VARCHAR)
RETURNS VOID AS $$
DECLARE
    rec RECORD;
BEGIN
    SELECT INTO rec
        g.id_unico, g.fecha_compra, g.fecha_registro,
        r.nombre AS reg_nombre, g.compra,
        c.nombre AS cat_nombre, g.monto_total, g.monto_parcial,
        g.msi_status, mp.nombre AS met_nombre,
        tg.nombre AS tip_nombre, g.periodo_pago,
        g.participacion_josue, g.participacion_abi, g.notas
    FROM gastos g
    LEFT JOIN registradores r ON g.registrador_id = r.id
    LEFT JOIN categorias c ON g.categoria_id = c.id
    LEFT JOIN metodos_pago mp ON g.metodo_pago_id = mp.id
    LEFT JOIN tipos_gasto tg ON g.tipo_gasto_id = tg.id
    WHERE g.id_unico = target_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Gasto con ID % no encontrado', target_id;
    END IF;

    INSERT INTO gastos_borrados (
        id_unico, fecha_compra, fecha_registro, registrador,
        compra, categoria, monto_total, monto_parcial,
        msi_status, metodo_pago, tipo_gasto, periodo_pago,
        participacion_josue, participacion_abi, notas,
        borrado_por
    ) VALUES (
        rec.id_unico, rec.fecha_compra, rec.fecha_registro, rec.reg_nombre,
        rec.compra, rec.cat_nombre, rec.monto_total, rec.monto_parcial,
        rec.msi_status, rec.met_nombre, rec.tip_nombre, rec.periodo_pago,
        rec.participacion_josue, rec.participacion_abi, rec.notas,
        quien
    );

    DELETE FROM gastos WHERE id_unico = target_id;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- VISTAS (Views) para reportes comunes
-- =============================================================================

-- Vista: Gastos con nombres de catálogos resueltos
CREATE VIEW v_gastos AS
SELECT
    g.id_unico,
    g.fecha_compra,
    g.fecha_registro,
    r.nombre AS registrador,
    g.compra,
    c.nombre AS categoria,
    c.icono AS categoria_icono,
    g.monto_total,
    g.monto_parcial,
    CASE
        WHEN g.msi_status IS NULL OR g.msi_status = '2026-01-01' THEN false
        ELSE true
    END AS es_msi,
    g.msi_status AS msi_fin,
    mp.nombre AS metodo_pago,
    tg.nombre AS tipo_gasto,
    g.periodo_pago,
    g.participacion_josue,
    g.participacion_abi,
    g.notas,
    g.created_at,
    g.updated_at
FROM gastos g
LEFT JOIN registradores r ON g.registrador_id = r.id
LEFT JOIN categorias c ON g.categoria_id = c.id
LEFT JOIN metodos_pago mp ON g.metodo_pago_id = mp.id
LEFT JOIN tipos_gasto tg ON g.tipo_gasto_id = tg.id;

-- Vista: Resumen por período
CREATE VIEW v_resumen_periodo AS
SELECT
    periodo_pago,
    categoria,
    COUNT(*) AS num_gastos,
    SUM(monto_total) AS total_gastado,
    SUM(participacion_josue) AS total_josue,
    SUM(participacion_abi) AS total_abi,
    SUM(monto_total) - SUM(participacion_josue) - SUM(participacion_abi) AS diferencia_split
FROM v_gastos
GROUP BY periodo_pago, categoria
ORDER BY periodo_pago DESC, total_gastado DESC;

-- Vista: Presupuesto vs Gasto Real (por ámbito y categoría)
CREATE VIEW v_presupuesto_vs_real AS
SELECT
    p.ambito,
    c.nombre AS categoria,
    p.monto AS presupuesto,
    COALESCE(
        CASE p.ambito
            WHEN 'Compartido' THEN SUM(g.monto_total) / 2.0
            WHEN 'Josue' THEN SUM(g.participacion_josue)
            WHEN 'Abi' THEN SUM(g.participacion_abi)
        END,
        0
    ) AS gasto_real,
    p.monto - COALESCE(
        CASE p.ambito
            WHEN 'Compartido' THEN SUM(g.monto_total) / 2.0
            WHEN 'Josue' THEN SUM(g.participacion_josue)
            WHEN 'Abi' THEN SUM(g.participacion_abi)
        END,
        0
    ) AS restante,
    CASE
        WHEN p.monto > 0 THEN
            ROUND((COALESCE(
                CASE p.ambito
                    WHEN 'Compartido' THEN SUM(g.monto_total) / 2.0
                    WHEN 'Josue' THEN SUM(g.participacion_josue)
                    WHEN 'Abi' THEN SUM(g.participacion_abi)
                END,
                0
            ) / p.monto) * 100, 1)
        ELSE 0
    END AS porcentaje_usado
FROM presupuestos p
JOIN categorias c ON p.categoria_id = c.id
LEFT JOIN v_gastos g ON g.categoria = c.nombre
GROUP BY p.ambito, c.nombre, p.monto
ORDER BY p.ambito, c.nombre;

-- Vista: Resumen mensual global
CREATE VIEW v_resumen_mensual AS
SELECT
    DATE_TRUNC('month', fecha_compra)::DATE AS mes,
    COUNT(*) AS num_gastos,
    SUM(monto_total) AS total_gastado,
    SUM(participacion_josue) AS total_josue,
    SUM(participacion_abi) AS total_abi,
    SUM(CASE WHEN tipo_gasto = 'Compartido (50/50)' THEN monto_total ELSE 0 END) AS compartido_50,
    SUM(CASE WHEN tipo_gasto = 'Proporcional (53/47)' THEN monto_total ELSE 0 END) AS compartido_proporcional,
    SUM(CASE WHEN tipo_gasto LIKE 'Personal%' THEN monto_total ELSE 0 END) AS personal
FROM v_gastos
GROUP BY DATE_TRUNC('month', fecha_compra)
ORDER BY mes DESC;

-- Vista: Gastos por método de pago
CREATE VIEW v_gastos_por_metodo AS
SELECT
    metodo_pago,
    COUNT(*) AS num_gastos,
    SUM(monto_total) AS total,
    AVG(monto_total) AS promedio
FROM v_gastos
GROUP BY metodo_pago
ORDER BY total DESC;
