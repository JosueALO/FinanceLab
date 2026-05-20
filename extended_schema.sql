-- =============================================================================
-- FINANCE LAB — Extensión de Esquema (Cuentas, Recordatorios, Tipos Operación)
-- =============================================================================

-- TIPOS DE OPERACIÓN (Ingreso, Gasto, Transferencia)
CREATE TABLE tipos_operacion (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(50) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO tipos_operacion (nombre) VALUES ('Gasto'), ('Ingreso'), ('Transferencia')
ON CONFLICT (nombre) DO NOTHING;

-- MACRO CATEGORÍAS (agrupación superior)
CREATE TABLE macro_categorias (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(150) NOT NULL UNIQUE,
    icono       VARCHAR(10),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- CUENTAS (métodos de pago con tracking de saldo)
CREATE TABLE cuentas (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL UNIQUE,
    tipo            VARCHAR(20) NOT NULL CHECK (tipo IN ('Activo', 'Pasivo')),
    propietario     VARCHAR(20) NOT NULL CHECK (propietario IN ('Josué', 'Abi', 'Hogar')),
    saldo_inicial   DECIMAL(14,2) DEFAULT 0,
    dia_corte       INTEGER CHECK (dia_corte IS NULL OR (dia_corte >= 1 AND dia_corte <= 31)),
    activo          BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Extender gastos con las nuevas columnas
ALTER TABLE gastos 
    ADD COLUMN IF NOT EXISTS tipo_operacion_id INTEGER REFERENCES tipos_operacion(id),
    ADD COLUMN IF NOT EXISTS cuenta_origen_id INTEGER REFERENCES cuentas(id),
    ADD COLUMN IF NOT EXISTS cuenta_destino_id INTEGER REFERENCES cuentas(id),
    ADD COLUMN IF NOT EXISTS macro_categoria_id INTEGER REFERENCES macro_categorias(id);

-- Actualizar v_gastos para incluir nuevos campos
CREATE OR REPLACE VIEW v_gastos AS
SELECT
    g.id_unico,
    g.fecha_compra,
    g.fecha_registro,
    r.nombre AS registrador,
    g.compra,
    c.nombre AS categoria,
    c.icono AS categoria_icono,
    mc.nombre AS macro_categoria,
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
    toper.nombre AS tipo_operacion,
    co.nombre AS cuenta_origen,
    cd.nombre AS cuenta_destino,
    g.notas,
    g.created_at,
    g.updated_at
FROM gastos g
LEFT JOIN registradores r ON g.registrador_id = r.id
LEFT JOIN categorias c ON g.categoria_id = c.id
LEFT JOIN macro_categorias mc ON g.macro_categoria_id = mc.id
LEFT JOIN metodos_pago mp ON g.metodo_pago_id = mp.id
LEFT JOIN tipos_gasto tg ON g.tipo_gasto_id = tg.id
LEFT JOIN tipos_operacion toper ON g.tipo_operacion_id = toper.id
LEFT JOIN cuentas co ON g.cuenta_origen_id = co.id
LEFT JOIN cuentas cd ON g.cuenta_destino_id = cd.id;

-- RECORDATORIOS (gastos programados / planeados a futuro)
CREATE TABLE recordatorios (
    id_unico            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fecha_programada    DATE NOT NULL,
    fecha_registro      DATE NOT NULL DEFAULT CURRENT_DATE,
    registrador_id      INTEGER REFERENCES registradores(id),
    compra              VARCHAR(255) NOT NULL,
    categoria_id        INTEGER REFERENCES categorias(id),
    macro_categoria_id  INTEGER REFERENCES macro_categorias(id),
    monto_parcial       DECIMAL(12,2) DEFAULT 0 CHECK (monto_parcial >= 0),
    tipo_operacion_id   INTEGER REFERENCES tipos_operacion(id),
    cuenta_origen_id    INTEGER REFERENCES cuentas(id),
    cuenta_destino_id   INTEGER REFERENCES cuentas(id),
    tipo_gasto_id       INTEGER REFERENCES tipos_gasto(id),
    participacion_josue DECIMAL(12,2) DEFAULT 0,
    participacion_abi   DECIMAL(12,2) DEFAULT 0,
    lanzado             BOOLEAN DEFAULT false,
    lanzado_fecha       DATE,
    gasto_id            UUID REFERENCES gastos(id_unico),
    notas               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_rec_fecha ON recordatorios(fecha_programada);
CREATE INDEX idx_rec_lanzado ON recordatorios(lanzado);

-- Vista: Recordatorios con nombres resueltos
CREATE VIEW v_recordatorios AS
SELECT
    rec.id_unico,
    rec.fecha_programada AS fecha_compra,
    rec.fecha_registro,
    r.nombre AS registrador,
    rec.compra,
    c.nombre AS categoria,
    mc.nombre AS macro_categoria,
    rec.monto_parcial,
    toper.nombre AS tipo_operacion,
    co.nombre AS cuenta_origen,
    cd.nombre AS cuenta_destino,
    tg.nombre AS tipo_gasto,
    rec.participacion_josue,
    rec.participacion_abi,
    rec.lanzado,
    rec.lanzado_fecha,
    rec.gasto_id,
    rec.notas
FROM recordatorios rec
LEFT JOIN registradores r ON rec.registrador_id = r.id
LEFT JOIN categorias c ON rec.categoria_id = c.id
LEFT JOIN macro_categorias mc ON rec.macro_categoria_id = mc.id
LEFT JOIN tipos_operacion toper ON rec.tipo_operacion_id = toper.id
LEFT JOIN cuentas co ON rec.cuenta_origen_id = co.id
LEFT JOIN cuentas cd ON rec.cuenta_destino_id = cd.id
LEFT JOIN tipos_gasto tg ON rec.tipo_gasto_id = tg.id;

-- Función: Lanzar recordatorio (convertir en gasto real)
CREATE OR REPLACE FUNCTION lanzar_recordatorio(
    p_id_unico UUID,
    p_fecha_lanzamiento DATE
) RETURNS UUID AS $$
DECLARE
    rec RECORD;
    v_gasto_id UUID;
BEGIN
    SELECT INTO rec * FROM v_recordatorios WHERE id_unico = p_id_unico;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Recordatorio % no encontrado', p_id_unico;
    END IF;

    v_gasto_id := gen_random_uuid();

    INSERT INTO gastos (
        id_unico, fecha_compra, fecha_registro, registrador_id,
        compra, categoria_id, macro_categoria_id,
        monto_total, monto_parcial,
        tipo_operacion_id, cuenta_origen_id, cuenta_destino_id,
        tipo_gasto_id, participacion_josue, participacion_abi,
        notas
    )
    SELECT
        v_gasto_id, p_fecha_lanzamiento, CURRENT_DATE, reg.id,
        rec.compra, cat.id, mcat.id,
        rec.monto_parcial, rec.monto_parcial,
        toper.id, co.id, cd.id,
        tg.id, rec.participacion_josue, rec.participacion_abi,
        rec.notas
    FROM recordatorios rec2
    LEFT JOIN registradores reg ON reg.nombre = rec.registrador
    LEFT JOIN categorias cat ON cat.nombre = rec.categoria
    LEFT JOIN macro_categorias mcat ON mcat.nombre = rec.macro_categoria
    LEFT JOIN tipos_operacion toper ON toper.nombre = rec.tipo_operacion
    LEFT JOIN cuentas co ON co.nombre = rec.cuenta_origen
    LEFT JOIN cuentas cd ON cd.nombre = rec.cuenta_destino
    LEFT JOIN tipos_gasto tg ON tg.nombre = rec.tipo_gasto
    WHERE rec2.id_unico = p_id_unico;

    UPDATE recordatorios
    SET lanzado = true, lanzado_fecha = p_fecha_lanzamiento, gasto_id = v_gasto_id, updated_at = now()
    WHERE id_unico = p_id_unico;

    RETURN v_gasto_id;
END;
$$ LANGUAGE plpgsql;
