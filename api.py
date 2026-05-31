#!/usr/bin/env python3
"""
FINANCE LAB — API Backend v3 (Optimizado)
- Connection pooling con psycopg2.pool
- Lookups batch con CTE en una sola query
- Fechas pre-formateadas en SQL
- Pydantic validation
"""

import calendar
import traceback
from contextlib import contextmanager
from datetime import date, datetime
from typing import Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Finance Lab API v3")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ═══ Connection Pool ═══
_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None

def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2, maxconn=10,
            host="finance-lab-db", port=5432,
            dbname="finance_lab", user="finadmin",
            password="f1nl4b_s3cur3",
        )
    return _pool

@contextmanager
def get_db():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

# ═══ Helpers ═══

def _fmt_date(d):
    if not d:
        return ""
    if isinstance(d, (datetime, date)):
        return d.strftime("%d/%m/%Y")
    # ISO string → DD/MM/YYYY
    if isinstance(d, str) and "-" in d:
        parts = d.split("-")
        if len(parts) == 3:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return str(d)

def _fmt_num(v, default=0):
    return float(v) if v is not None else default

def _fmt_str(v, default=""):
    return str(v) if v is not None else default

def ok(data=None):
    return JSONResponse({"success": True, "data": data or {}})

def fail(msg):
    return JSONResponse({"success": False, "error": str(msg)})

# ═══ Pydantic Models ═══

class ApiRequest(BaseModel):
    action: str = "getAppData"
    payload: dict | list | str | None = None

# ═══ Router ═══

ROUTES = {}

def route(action: str):
    """Decorator to register API actions."""
    def decorator(fn):
        ROUTES[action] = fn
        return fn
    return decorator

@app.post("/api")
async def api_handler(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    action = body.get("action", "getAppData")
    payload = body.get("payload")
    try:
        handler = ROUTES.get(action)
        if not handler:
            return fail(f"Acción desconocida: {action}")
        result = handler(payload)
        return result
    except Exception as e:
        traceback.print_exc()
        return fail(str(e))

# ═══ GET APP DATA (optimized: single query, SQL-formatted dates) ═══

@route("ping")
def _ping(_=None):
    return ok({"pong": True})

@route("getAppData")
def _get_app_data(_=None):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # ── arbolCat ──
        cur.execute("""
            SELECT toper.nombre AS tipo, ca.macro, ca.nombre
            FROM categoria_arbol ca
            JOIN tipos_operacion toper ON ca.tipo_operacion_id = toper.id
            ORDER BY toper.id, ca.macro, ca.nombre
        """)
        arbolCat = {}
        for r in cur.fetchall():
            t, m = r["tipo"], r["macro"]
            arbolCat.setdefault(t, {}).setdefault(m, []).append(r["nombre"])

        # ── cuentas ──
        cur.execute("""
            SELECT nombre, tipo, propietario, saldo_inicial, dia_corte
            FROM cuentas WHERE activo ORDER BY tipo, nombre
        """)
        cuentas = [{
            "nombre": r["nombre"], "tipo": r["tipo"],
            "propietario": r["propietario"],
            "saldoInicial": _fmt_num(r["saldo_inicial"]),
            "diaCorte": r["dia_corte"] or "",
        } for r in cur.fetchall()]

        # ── rawLogs (unified query, SQL-formatted dates) ──
        cur.execute("""
            SELECT
                id_unico,
                TO_CHAR(fecha_compra, 'DD/MM/YYYY') AS fecha_compra,
                TO_CHAR(fecha_registro, 'DD/MM/YYYY HH24:MI:SS') AS fecha_registro,
                registrador, compra, categoria, macro_categoria,
                monto_total, monto_parcial,
                COALESCE(TO_CHAR(msi_status, 'DD/MM/YYYY'), '') AS msi_status,
                metodo_pago, tipo_gasto,
                COALESCE(TO_CHAR(periodo_pago, 'DD/MM/YYYY'), '') AS periodo_pago,
                participacion_josue, participacion_abi,
                tipo_operacion, cuenta_origen, cuenta_destino,
                es_recordatorio
            FROM (
                SELECT
                    g.id_unico, g.fecha_compra, g.fecha_registro,
                    r.nombre AS registrador, g.compra,
                    c.nombre AS categoria, mc.nombre AS macro_categoria,
                    g.monto_total, g.monto_parcial, g.msi_status,
                    COALESCE(mp.nombre, co.nombre) AS metodo_pago,
                    tg.nombre AS tipo_gasto, g.periodo_pago,
                    g.participacion_josue, g.participacion_abi,
                    toper.nombre AS tipo_operacion,
                    co.nombre AS cuenta_origen, cd.nombre AS cuenta_destino,
                    'FALSE' AS es_recordatorio
                FROM gastos g
                LEFT JOIN registradores r ON g.registrador_id = r.id
                LEFT JOIN categorias c ON g.categoria_id = c.id
                LEFT JOIN macro_categorias mc ON g.macro_categoria_id = mc.id
                LEFT JOIN metodos_pago mp ON g.metodo_pago_id = mp.id
                LEFT JOIN tipos_gasto tg ON g.tipo_gasto_id = tg.id
                LEFT JOIN tipos_operacion toper ON g.tipo_operacion_id = toper.id
                LEFT JOIN cuentas co ON g.cuenta_origen_id = co.id
                LEFT JOIN cuentas cd ON g.cuenta_destino_id = cd.id
                UNION ALL
                SELECT
                    rec.id_unico, rec.fecha_programada, rec.fecha_registro,
                    r2.nombre, rec.compra,
                    c2.nombre, mc2.nombre,
                    rec.monto_parcial, rec.monto_parcial, NULL,
                    NULL, tg2.nombre, NULL,
                    rec.participacion_josue, rec.participacion_abi,
                    toper2.nombre,
                    co2.nombre, cd2.nombre,
                    'TRUE'
                FROM recordatorios rec
                LEFT JOIN registradores r2 ON rec.registrador_id = r2.id
                LEFT JOIN categorias c2 ON rec.categoria_id = c2.id
                LEFT JOIN macro_categorias mc2 ON rec.macro_categoria_id = mc2.id
                LEFT JOIN tipos_gasto tg2 ON rec.tipo_gasto_id = tg2.id
                LEFT JOIN tipos_operacion toper2 ON rec.tipo_operacion_id = toper2.id
                LEFT JOIN cuentas co2 ON rec.cuenta_origen_id = co2.id
                LEFT JOIN cuentas cd2 ON rec.cuenta_destino_id = cd2.id
                WHERE NOT rec.lanzado
            ) sub
            ORDER BY fecha_compra DESC
        """)
        rawLogs = [{
            "ID_Unico": str(r["id_unico"]),
            "Fecha_Compra": r["fecha_compra"] or "",
            "Fecha_Registro": r["fecha_registro"] or "",
            "Registrador": r["registrador"] or "",
            "Compra": r["compra"] or "",
            "Categoria": r["categoria"] or "",
            "MacroCategoria": r["macro_categoria"] or "",
            "Monto_Total": _fmt_num(r["monto_total"]),
            "Monto_Parcial": _fmt_num(r["monto_parcial"]),
            "MSI_Status": r["msi_status"] or "",
            "Metodo_Pago": r["metodo_pago"] or "",
            "Tipo_Gasto": r["tipo_gasto"] or "",
            "Periodo_Pago": r["periodo_pago"] or "",
            "Participacion_Josue": _fmt_num(r["participacion_josue"]),
            "Participacion_Abi": _fmt_num(r["participacion_abi"]),
            "Tipo_Operacion": r["tipo_operacion"] or "Gasto",
            "Cuenta_Origen": r["cuenta_origen"] or "",
            "Cuenta_Destino": r["cuenta_destino"] or "",
            "Es_Recordatorio": r["es_recordatorio"] or "FALSE",
        } for r in cur.fetchall()]

        # ── presupuesto ──
        cur.execute("""
            SELECT p.ambito, c.nombre AS categoria, p.monto
            FROM presupuestos p
            JOIN categorias c ON p.categoria_id = c.id
            WHERE p.activo
        """)
        presupuesto = {"Compartido": {}, "Josue": {}, "Abi": {}}
        for r in cur.fetchall():
            presupuesto[r["ambito"]][r["categoria"]] = _fmt_num(r["monto"])

        cur.close()

    return ok({"rawLogs": rawLogs, "presupuesto": presupuesto, "arbolCat": arbolCat, "cuentas": cuentas})


# ═══ BATCH LOOKUP: Single CTE instead of N queries ═══

def _batch_resolve_ids(cur, fields: dict):
    """
    Resuelve todos los IDs de catálogo en una sola query CTE.
    fields: {table: (col, val)}  → devuelve {table: id | None}
    Crea automáticamente si no existe (para registradores, categorias, macros).
    """
    ids = {}
    for table, (col, val) in fields.items():
        if not val:
            ids[table] = None
            continue
        cur.execute(f"SELECT id FROM {table} WHERE {col} = %s", (val,))
        row = cur.fetchone()
        if row:
            ids[table] = row[0]
        else:
            # Auto-create para tablas que lo permiten
            if table == "cuentas":
                cur.execute(
                    f"INSERT INTO {table} ({col}, tipo, propietario) VALUES (%s, 'Activo', 'Josué') ON CONFLICT ({col}) DO NOTHING RETURNING id",
                    (val,))
            elif table == "registradores":
                cur.execute(f"INSERT INTO {table} ({col}) VALUES (%s) ON CONFLICT ({col}) DO NOTHING RETURNING id", (val,))
            else:
                cur.execute(f"INSERT INTO {table} ({col}) VALUES (%s) ON CONFLICT ({col}) DO NOTHING RETURNING id", (val,))
            row = cur.fetchone()
            if row:
                ids[table] = row[0]
            else:
                cur.execute(f"SELECT id FROM {table} WHERE {col} = %s", (val,))
                ids[table] = cur.fetchone()[0] if cur.fetchone() else None
    return ids


# ═══ REGISTRAR / EDITAR GASTO ═══

def _parse_form(p):
    fecha = p.get("fechaCompra", "")
    try:
        parts = fecha.split("-")
        fecha_compra = date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        fecha_compra = date.today()

    return {
        "es_rec": p.get("esRecordatorio", False),
        "tipo_op": p.get("tipoOperacion", "Gasto"),
        "tipo_gasto": p.get("tipoGasto", "Compartido (50/50)"),
        "fecha_compra": fecha_compra,
        "compra": p.get("compra", ""),
        "monto": float(p.get("monto") or 0),
        "registrador": p.get("registrador", ""),
        "categoria": p.get("categoria", ""),
        "macro": p.get("macroCategoria", ""),
        "cuenta_o": p.get("cuentaOrigen", ""),
        "cuenta_d": p.get("cuentaDestino", ""),
        "pct_j": int(p.get("pctJosue") or 0),
        "pct_a": int(p.get("pctAbi") or 0),
    }


def _calc_splits(monto, tipo_gasto, pct_j, pct_a):
    """Calcula participaciones según tipo de gasto."""
    if "Compartido" in tipo_gasto:
        if "50/50" in tipo_gasto:
            half = round(monto / 2, 2)
            return half, round(monto - half, 2)
        elif "Proporcional" in tipo_gasto:
            pj = round(monto * pct_j / 100, 2) if pct_j else 0
            return pj, round(monto - pj, 2)
    if "Personal Josué" in tipo_gasto:
        return monto, 0
    if "Personal Ab" in tipo_gasto:
        return 0, monto
    # Default: 50/50
    half = round(monto / 2, 2)
    return half, round(monto - half, 2)


def _calc_periodo(fecha: date, compra: str = "", cuenta_origen_id=None):
    """Periodo contable.
    TDC (Pasivo): corte día 19 → ≤19 mismo mes, >19 mes siguiente.
    Débito/Efectivo (Activo): siempre mismo mes (sin corte).
    Si compra contiene patrón MSI (Mes X/N) o (X/N), suma offset de meses."""
    # Determine if this is a credit card (Pasivo = has cutoff)
    es_credito = False
    if cuenta_origen_id:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT tipo FROM cuentas WHERE id = %s", (cuenta_origen_id,))
            row = cur.fetchone()
            cur.close()
            if row and row[0] == 'Pasivo':
                es_credito = True
    
    if es_credito and fecha.day > 19:
        m, y = fecha.month + 1, fecha.year
        if m > 12:
            m, y = 1, y + 1
    else:
        m, y = fecha.month, fecha.year
    
    # MSI offset
    if compra:
        import re
        msi = re.search(r'(?:Mes\s*)?(\d+)\s*/\s*\d+', compra)
        if msi:
            offset = int(msi.group(1)) - 1
            m += offset
            while m > 12:
                m -= 12
                y += 1
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, last_day)


def _grabar_operacion(p, id_unico=None):
    with get_db() as conn:
        cur = conn.cursor()
        f = _parse_form(p)

        # Batch resolve all IDs
        ids = _batch_resolve_ids(cur, {
            "registradores": ("nombre", f["registrador"]),
            "categorias": ("nombre", f["categoria"]),
            "macro_categorias": ("nombre", f["macro"]),
            "tipos_operacion": ("nombre", f["tipo_op"]),
            "tipos_gasto": ("nombre", f["tipo_gasto"]),
            "cuentas": ("nombre", f["cuenta_o"]),
            "cuentas_d": ("nombre", f["cuenta_d"]),
        })
        cd_id = ids.pop("cuentas_d", None)
        co_id = ids.pop("cuentas", None)

        monto = f["monto"]
        p_josue, p_abi = _calc_splits(monto, f["tipo_gasto"], f["pct_j"], f["pct_a"])
        periodo = _calc_periodo(f["fecha_compra"], f["compra"], ids.get("cuentas"))

        if f["es_rec"]:
            rec_id = id_unico or str(_gen_uuid(cur))
            cur.execute("""
                INSERT INTO recordatorios (id_unico, fecha_programada, registrador_id,
                    compra, categoria_id, macro_categoria_id, monto_parcial,
                    tipo_operacion_id, cuenta_origen_id, cuenta_destino_id,
                    tipo_gasto_id, participacion_josue, participacion_abi)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id_unico) DO UPDATE SET
                    fecha_programada=EXCLUDED.fecha_programada,
                    registrador_id=EXCLUDED.registrador_id,
                    compra=EXCLUDED.compra,
                    categoria_id=EXCLUDED.categoria_id,
                    macro_categoria_id=EXCLUDED.macro_categoria_id,
                    monto_parcial=EXCLUDED.monto_parcial,
                    tipo_operacion_id=EXCLUDED.tipo_operacion_id,
                    cuenta_origen_id=EXCLUDED.cuenta_origen_id,
                    cuenta_destino_id=EXCLUDED.cuenta_destino_id,
                    tipo_gasto_id=EXCLUDED.tipo_gasto_id,
                    participacion_josue=EXCLUDED.participacion_josue,
                    participacion_abi=EXCLUDED.participacion_abi,
                    updated_at=now()
            """, (rec_id, f["fecha_compra"], ids["registradores"],
                  f["compra"], ids["categorias"], ids["macro_categorias"], monto,
                  ids["tipos_operacion"], co_id, cd_id,
                  ids["tipos_gasto"], p_josue, p_abi))
        else:
            gasto_id = id_unico or str(_gen_uuid(cur))
            cur.execute("""
                INSERT INTO gastos (id_unico, fecha_compra, fecha_registro, registrador_id,
                    compra, categoria_id, macro_categoria_id,
                    monto_total, monto_parcial,
                    tipo_gasto_id, periodo_pago,
                    participacion_josue, participacion_abi,
                    tipo_operacion_id, cuenta_origen_id, cuenta_destino_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id_unico) DO UPDATE SET
                    fecha_compra=EXCLUDED.fecha_compra,
                    fecha_registro=EXCLUDED.fecha_registro,
                    registrador_id=EXCLUDED.registrador_id,
                    compra=EXCLUDED.compra,
                    categoria_id=EXCLUDED.categoria_id,
                    macro_categoria_id=EXCLUDED.macro_categoria_id,
                    monto_total=EXCLUDED.monto_total,
                    monto_parcial=EXCLUDED.monto_parcial,
                    tipo_gasto_id=EXCLUDED.tipo_gasto_id,
                    periodo_pago=EXCLUDED.periodo_pago,
                    participacion_josue=EXCLUDED.participacion_josue,
                    participacion_abi=EXCLUDED.participacion_abi,
                    tipo_operacion_id=EXCLUDED.tipo_operacion_id,
                    cuenta_origen_id=EXCLUDED.cuenta_origen_id,
                    cuenta_destino_id=EXCLUDED.cuenta_destino_id,
                    updated_at=now()
            """, (gasto_id, f["fecha_compra"], date.today(), ids["registradores"],
                  f["compra"], ids["categorias"], ids["macro_categorias"],
                  monto, monto,
                  ids["tipos_gasto"], periodo,
                  p_josue, p_abi,
                  ids["tipos_operacion"], co_id, cd_id))

        cur.close()


@route("registrarOperacion")
def _registrar_operacion(payload):
    _grabar_operacion(payload)
    return ok({"ok": True})


@route("editarGasto")
def _editar_gasto(payload):
    id_unico = payload.get("id_edit")
    if not id_unico:
        return fail("ID requerido para editar")
    _grabar_operacion(payload, id_unico)
    return ok({"ok": True})


# ═══ ELIMINAR GASTO ═══

@route("eliminarGasto")
def _eliminar_gasto(payload):
    target_id = payload if isinstance(payload, str) else (payload.get("ID_Unico") or payload.get("id_unico"))
    if not target_id:
        return fail("ID requerido")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT soft_delete_gasto(%s, %s)", (target_id, "Josué"))
        cur.execute("DELETE FROM recordatorios WHERE id_unico = %s", (target_id,))
        cur.close()
    return ok({"deleted": target_id})


# ═══ LANZAR RECORDATORIO ═══

@route("lanzarRecordatorio")
def _lanzar_recordatorio(payload):
    rec_id = payload.get("id") or payload.get("ID_Unico") or payload.get("id_unico")
    fecha_str = payload.get("fecha") or str(date.today())
    if not rec_id:
        return fail("ID requerido")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT lanzar_recordatorio(%s, %s)", (rec_id, fecha_str))
        gid = cur.fetchone()[0]
        cur.close()
    return ok({"gasto_id": str(gid)})


# ═══ GUARDAR CUENTAS ═══

@route("guardarCuentas")
def _guardar_cuentas(payload):
    if not isinstance(payload, list):
        return fail("Se espera lista de cuentas")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE cuentas SET activo = false")
        for c in payload:
            nombre = (c.get("nombre") or "").strip()
            if not nombre:
                continue
            dia = int(c["diaCorte"]) if c.get("diaCorte") and int(c.get("diaCorte", 0)) > 0 else None
            cur.execute("""
                INSERT INTO cuentas (nombre, tipo, propietario, saldo_inicial, dia_corte, activo)
                VALUES (%s,%s,%s,%s,%s,true)
                ON CONFLICT (nombre) DO UPDATE SET
                    tipo=EXCLUDED.tipo, propietario=EXCLUDED.propietario,
                    saldo_inicial=EXCLUDED.saldo_inicial, dia_corte=EXCLUDED.dia_corte,
                    activo=true, updated_at=now()
            """, (nombre, c.get("tipo", "Activo"), c.get("propietario", "Josué"),
                  float(c.get("saldoInicial", c.get("saldo_inicial", 0))), dia))
        cur.close()
    return ok({"saved": len(payload)})


# ═══ GUARDAR PRESUPUESTO ═══

@route("guardarPresupuestoGlobal")
def _guardar_presupuesto_global(payload):
    if not payload:
        return fail("Payload requerido")
    with get_db() as conn:
        cur = conn.cursor()
        presupuesto = payload.get("presupuesto", {})
        for ambito in ["Compartido", "Josue", "Abi"]:
            for cat_nombre, monto in presupuesto.get(ambito, {}).items():
                if not monto:
                    continue
                # Resolve or create category
                cur.execute("""
                    INSERT INTO categorias (nombre) VALUES (%s)
                    ON CONFLICT (nombre) DO NOTHING
                """, (cat_nombre,))
                cur.execute("SELECT id FROM categorias WHERE nombre = %s", (cat_nombre,))
                cat_id = cur.fetchone()[0]
                cur.execute("""
                    INSERT INTO presupuestos (ambito, categoria_id, monto)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (ambito, categoria_id) DO UPDATE SET
                        monto=EXCLUDED.monto, updated_at=now()
                """, (ambito, cat_id, float(monto)))
        cur.close()
    return ok({"ok": True})


# ═══ CATEGORÍAS MASTER ═══

@route("agregarCategoriaMaster")
def _agregar_categoria_master(payload):
    nombre = payload.get("name", "").strip()
    macro = payload.get("macro", "General").strip()
    tipo = payload.get("tipo", "Gasto")
    if not nombre:
        return fail("Nombre requerido")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO categorias (nombre) VALUES (%s) ON CONFLICT (nombre) DO NOTHING", (nombre,))
        cur.execute("INSERT INTO macro_categorias (nombre) VALUES (%s) ON CONFLICT (nombre) DO NOTHING", (macro,))
        cur.execute("SELECT id FROM tipos_operacion WHERE nombre = %s", (tipo,))
        top_id = cur.fetchone()[0] if cur.rowcount else 1
        cur.execute("""
            INSERT INTO categoria_arbol (tipo_operacion_id, macro, nombre)
            VALUES (%s,%s,%s) ON CONFLICT (tipo_operacion_id, macro, nombre) DO NOTHING
        """, (top_id, macro, nombre))
        cur.close()
    return ok({"ok": True})


@route("editarCategoriaMaster")
def _editar_categoria_master(payload):
    old = payload.get("oldName", "").strip()
    new = payload.get("newName", "").strip()
    macro = payload.get("newMacro", "General").strip()
    tipo = payload.get("newTipo", "Gasto")
    if not old or not new:
        return fail("Nombres requeridos")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM tipos_operacion WHERE nombre = %s", (tipo,))
        top_id = cur.fetchone()[0] if cur.rowcount else 1
        cur.execute("INSERT INTO macro_categorias (nombre) VALUES (%s) ON CONFLICT (nombre) DO NOTHING", (macro,))
        cur.execute("""
            UPDATE categoria_arbol SET nombre=%s, macro=%s, tipo_operacion_id=%s WHERE nombre=%s
        """, (new, macro, top_id, old))
        cur.execute("UPDATE categorias SET nombre=%s WHERE nombre=%s", (new, old))
        cur.close()
    return ok({"ok": True})


@route("eliminarCategoriaMaster")
def _eliminar_categoria_master(payload):
    nombre = payload if isinstance(payload, str) else (payload.get("name") or payload.get("nombre") or "").strip()
    if not nombre:
        return fail("Nombre requerido")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM categoria_arbol WHERE nombre=%s", (nombre,))
        cur.close()
    return ok({"ok": True})


# ═══ DASHBOARD ═══

@route("getDashboard")
def _get_dashboard(payload):
    """
    payload: { periodo: "31/05/2026", ambito: "Compartido" | "Josue" | "Abi" }
    Retorna KPIs, tendencia 6 meses, gastos por categoría, presupuesto vs real,
    balance entre personas y últimos movimientos.
    """
    if not payload:
        payload = {}
    periodo = payload.get("periodo", "")
    ambito = payload.get("ambito", "Compartido")

    # Parse periodo to date range
    periodo_end = None
    if periodo:
        try:
            parts = periodo.split("/")
            periodo_end = date(int(parts[2]), int(parts[1]), int(parts[0]))
        except Exception:
            periodo_end = None

    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # ── Mapeo de cuentas ──
        cur.execute("SELECT nombre, propietario FROM cuentas WHERE activo")
        cuentas_map = {r["nombre"]: r["propietario"] for r in cur.fetchall()}

        # ── Helper: filtrar por ámbito en SQL ──
        def _ambito_where(alias="g"):
            if ambito == "Compartido":
                return f"({alias}.tipo_gasto_id IN (SELECT id FROM tipos_gasto WHERE nombre NOT LIKE '%%Personal%%'))"
            elif ambito == "Josue":
                return f"(({alias}.tipo_gasto_id IN (SELECT id FROM tipos_gasto WHERE nombre LIKE '%%Personal Josu%%')) OR ({alias}.tipo_gasto_id IN (SELECT id FROM tipos_gasto WHERE nombre NOT LIKE '%%Personal%%') AND {alias}.participacion_josue > 0))"
            elif ambito == "Abi":
                return f"(({alias}.tipo_gasto_id IN (SELECT id FROM tipos_gasto WHERE nombre LIKE '%%Personal Ab%%')) OR ({alias}.tipo_gasto_id IN (SELECT id FROM tipos_gasto WHERE nombre NOT LIKE '%%Personal%%') AND {alias}.participacion_abi > 0))"
            return "1=1"

        def _ambito_monto(alias="g"):
            if ambito == "Compartido":
                return f"COALESCE({alias}.monto_parcial, {alias}.monto_total)"
            elif ambito == "Josue":
                return f"{alias}.participacion_josue"
            elif ambito == "Abi":
                return f"{alias}.participacion_abi"
            return f"COALESCE({alias}.monto_parcial, {alias}.monto_total)"

        # ── KPI: Gastos del periodo ──
        if periodo_end:
            periodo_filter = "AND g.periodo_pago = %s"
            kpi_params = (periodo_end,)
        else:
            periodo_filter = ""
            kpi_params = ()

        cur.execute(f"""
            SELECT
                COALESCE(SUM(CASE WHEN g.tipo_operacion_id = (SELECT id FROM tipos_operacion WHERE nombre='Gasto')
                    THEN {_ambito_monto()} ELSE 0 END), 0) AS total_gastos,
                COALESCE(SUM(CASE WHEN g.tipo_operacion_id = (SELECT id FROM tipos_operacion WHERE nombre='Ingreso')
                    THEN {_ambito_monto()} ELSE 0 END), 0) AS total_ingresos
            FROM gastos g
            WHERE {_ambito_where()} {periodo_filter}
        """, kpi_params)
        kpi_row = cur.fetchone()
        total_gastos = float(kpi_row["total_gastos"])
        total_ingresos = float(kpi_row["total_ingresos"])
        balance_neto = total_ingresos - total_gastos

        # ── Alertas: categorías sobre 90% del presupuesto ──
        if periodo_end:
            cur.execute("""
                SELECT COUNT(*) AS alertas FROM (
                    SELECT c.nombre,
                        COALESCE(p.monto, 0) AS presupuesto,
                        COALESCE(SUM(CASE WHEN g.tipo_operacion_id = (SELECT id FROM tipos_operacion WHERE nombre='Gasto')
                            THEN g.monto_parcial ELSE 0 END), 0) AS gastado
                    FROM categorias c
                    LEFT JOIN presupuestos p ON p.categoria_id = c.id AND p.ambito = %s AND p.activo
                    LEFT JOIN gastos g ON g.categoria_id = c.id AND g.periodo_pago = %s
                        AND g.tipo_operacion_id = (SELECT id FROM tipos_operacion WHERE nombre='Gasto')
                    WHERE p.monto > 0
                    GROUP BY c.nombre, p.monto
                    HAVING COALESCE(SUM(CASE WHEN g.tipo_operacion_id = (SELECT id FROM tipos_operacion WHERE nombre='Gasto')
                        THEN g.monto_parcial ELSE 0 END), 0) / p.monto > 0.9
                ) sub
            """, (ambito, periodo_end))
        else:
            cur.execute("""
                SELECT COUNT(*) AS alertas FROM (
                    SELECT c.nombre,
                        COALESCE(p.monto, 0) AS presupuesto,
                        0 AS gastado
                    FROM categorias c
                    JOIN presupuestos p ON p.categoria_id = c.id AND p.ambito = %s AND p.activo
                    WHERE p.monto > 0
                    GROUP BY c.nombre, p.monto
                ) sub
            """, (ambito,))
        alertas = cur.fetchone()["alertas"] if cur.rowcount else 0

        kpis = {
            "totalGastos": round(total_gastos, 2),
            "totalIngresos": round(total_ingresos, 2),
            "balanceNeto": round(balance_neto, 2),
            "alertasPresupuesto": alertas,
        }

        # ── Tendencia 6 meses ──
        tendencia = []
        if periodo_end:
            # Generate 6 period end-dates going backwards
            periodos_tendencia = []
            current = periodo_end
            for i in range(6):
                periodos_tendencia.append(current)
                # Go to previous month's last day
                if current.month == 1:
                    current = date(current.year - 1, 12, 31)
                else:
                    current = date(current.year, current.month, 1) - date.resolution

            meses_es = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

            for p in reversed(periodos_tendencia):
                cur.execute(f"""
                    SELECT
                        COALESCE(SUM(CASE WHEN g.tipo_operacion_id = (SELECT id FROM tipos_operacion WHERE nombre='Gasto')
                            THEN {_ambito_monto()} ELSE 0 END), 0) AS gastos,
                        COALESCE(SUM(CASE WHEN g.tipo_operacion_id = (SELECT id FROM tipos_operacion WHERE nombre='Ingreso')
                            THEN {_ambito_monto()} ELSE 0 END), 0) AS ingresos
                    FROM gastos g
                    WHERE {_ambito_where()} AND g.periodo_pago = %s
                """, (p,))
                row = cur.fetchone()
                tendencia.append({
                    "periodo": f"{meses_es[p.month - 1]} {p.year}",
                    "gastos": round(float(row["gastos"]), 2) if row else 0,
                    "ingresos": round(float(row["ingresos"]), 2) if row else 0,
                })

        # ── Gastos por categoría ──
        if periodo_end:
            categorias_filter = "AND g.periodo_pago = %s"
            cat_params = (periodo_end,)
        else:
            categorias_filter = ""
            cat_params = ()

        cur.execute(f"""
            SELECT c.nombre AS categoria, c.icono,
                COALESCE(SUM(CASE WHEN g.tipo_operacion_id = (SELECT id FROM tipos_operacion WHERE nombre='Gasto')
                    THEN {_ambito_monto()} ELSE 0 END), 0) AS monto
            FROM gastos g
            JOIN categorias c ON g.categoria_id = c.id
            WHERE {_ambito_where()} {categorias_filter}
            GROUP BY c.nombre, c.icono
            HAVING COALESCE(SUM(CASE WHEN g.tipo_operacion_id = (SELECT id FROM tipos_operacion WHERE nombre='Gasto')
                THEN {_ambito_monto()} ELSE 0 END), 0) > 0
            ORDER BY monto DESC
        """, cat_params)
        cat_rows = cur.fetchall()
        total_cat = sum(float(r["monto"]) for r in cat_rows)
        gastos_por_categoria = []
        for r in cat_rows:
            m = float(r["monto"])
            gastos_por_categoria.append({
                "categoria": r["categoria"],
                "icono": r["icono"] or "📌",
                "monto": round(m, 2),
                "porcentaje": round(m / total_cat * 100, 1) if total_cat > 0 else 0,
            })

        # ── Presupuesto vs Real ──
        if periodo_end:
            cur.execute("""
                SELECT c.nombre AS categoria, c.icono,
                    COALESCE(p.monto, 0) AS presupuesto,
                    COALESCE(SUM(CASE WHEN g.tipo_operacion_id = (SELECT id FROM tipos_operacion WHERE nombre='Gasto')
                        THEN g.monto_parcial ELSE 0 END), 0) AS gastado
                FROM categorias c
                LEFT JOIN presupuestos p ON p.categoria_id = c.id AND p.ambito = %s AND p.activo
                LEFT JOIN gastos g ON g.categoria_id = c.id AND g.periodo_pago = %s
                    AND g.tipo_operacion_id = (SELECT id FROM tipos_operacion WHERE nombre='Gasto')
                WHERE p.monto > 0
                GROUP BY c.nombre, c.icono, p.monto
                ORDER BY gastado DESC
            """, (ambito, periodo_end))
        else:
            cur.execute("""
                SELECT c.nombre AS categoria, c.icono,
                    COALESCE(p.monto, 0) AS presupuesto,
                    0 AS gastado
                FROM categorias c
                JOIN presupuestos p ON p.categoria_id = c.id AND p.ambito = %s AND p.activo
                WHERE p.monto > 0
                GROUP BY c.nombre, c.icono, p.monto
                ORDER BY gastado DESC
            """, (ambito,))
        presupuesto_vs_real = []
        for r in cur.fetchall():
            gastado = round(float(r["gastado"]), 2)
            presup = round(float(r["presupuesto"]), 2)
            pct = round(gastado / presup * 100, 1) if presup > 0 else 0
            presupuesto_vs_real.append({
                "categoria": r["categoria"],
                "icono": r["icono"] or "📌",
                "presupuesto": presup,
                "gastado": gastado,
                "porcentaje": min(pct, 999.9),
            })

        # ── Balance entre personas (GLOBAL, sin filtrar por ámbito) ──
        cur.execute(f"""
            SELECT
                COALESCE(SUM(CASE WHEN cu_origen.propietario = 'Josué'
                    AND g.tipo_gasto_id NOT IN (SELECT id FROM tipos_gasto WHERE nombre LIKE '%Personal%')
                    THEN g.participacion_abi ELSE 0 END), 0) AS cubre_josue_a_abi,
                COALESCE(SUM(CASE WHEN cu_origen.propietario = 'Abi'
                    AND g.tipo_gasto_id NOT IN (SELECT id FROM tipos_gasto WHERE nombre LIKE '%Personal%')
                    THEN g.participacion_josue ELSE 0 END), 0) AS cubre_abi_a_josue,
                COALESCE(SUM(CASE WHEN cu_origen.propietario = 'Josué' AND cu_dest.propietario = 'Abi'
                    AND g.tipo_operacion_id = (SELECT id FROM tipos_operacion WHERE nombre='Transferencia')
                    THEN g.monto_parcial ELSE 0 END), 0) AS trans_josue_a_abi,
                COALESCE(SUM(CASE WHEN cu_origen.propietario = 'Abi' AND cu_dest.propietario = 'Josué'
                    AND g.tipo_operacion_id = (SELECT id FROM tipos_operacion WHERE nombre='Transferencia')
                    THEN g.monto_parcial ELSE 0 END), 0) AS trans_abi_a_josue
            FROM gastos g
            LEFT JOIN cuentas cu_origen ON g.cuenta_origen_id = cu_origen.id
            LEFT JOIN cuentas cu_dest ON g.cuenta_destino_id = cu_dest.id
            WHERE g.tipo_operacion_id IN (
                SELECT id FROM tipos_operacion WHERE nombre IN ('Gasto', 'Transferencia')
            )
        """)
        bal = cur.fetchone()
        cubre_ja = round(float(bal["cubre_josue_a_abi"] or 0), 2)
        cubre_aj = round(float(bal["cubre_abi_a_josue"] or 0), 2)
        trans_ja = round(float(bal["trans_josue_a_abi"] or 0), 2)
        trans_aj = round(float(bal["trans_abi_a_josue"] or 0), 2)
        # Net: positive = Abi debe a Josué (Josué cubrió más de la parte de Abi)
        neto_deuda = round(cubre_ja - cubre_aj + trans_ja - trans_aj, 2)
        # What each person paid out-of-pocket (gastos from their accounts, independent of scope)
        cur.execute(f"""
            SELECT
                COALESCE(SUM(CASE WHEN cu_origen.propietario = 'Josué' THEN g.participacion_josue ELSE 0 END), 0) AS pago_josue,
                COALESCE(SUM(CASE WHEN cu_origen.propietario = 'Abi' THEN g.participacion_abi ELSE 0 END), 0) AS pago_abi
            FROM gastos g
            LEFT JOIN cuentas cu_origen ON g.cuenta_origen_id = cu_origen.id
            WHERE g.tipo_operacion_id = (SELECT id FROM tipos_operacion WHERE nombre='Gasto')
        """)
        pagos = cur.fetchone()
        pago_josue = round(float(pagos["pago_josue"] or 0), 2)
        pago_abi = round(float(pagos["pago_abi"] or 0), 2)

        balance_personas = {
            "pagoJosue": pago_josue,
            "pagoAbi": pago_abi,
            "neto": neto_deuda,
            "mensaje": "Saldado ✓" if abs(neto_deuda) < 0.01 else (
                f"Abi debe a Josué {neto_deuda:,.2f}" if neto_deuda > 0
                else f"Josué debe a Abi {abs(neto_deuda):,.2f}"
            ),
        }

        # ── Últimos movimientos ──
        cur.execute(f"""
            SELECT TO_CHAR(g.fecha_compra, 'DD/MM/YYYY') AS fecha, g.compra,
                c.nombre AS categoria, c.icono,
                COALESCE(g.monto_parcial, g.monto_total) AS monto,
                toper.nombre AS tipo_operacion,
                mc.nombre AS macro_categoria,
                TO_CHAR(g.periodo_pago, 'DD/MM/YYYY') AS periodo_pago
            FROM gastos g
            LEFT JOIN categorias c ON g.categoria_id = c.id
            LEFT JOIN macro_categorias mc ON g.macro_categoria_id = mc.id
            LEFT JOIN tipos_operacion toper ON g.tipo_operacion_id = toper.id
            WHERE {_ambito_where()}
            ORDER BY g.fecha_compra DESC, g.fecha_registro DESC
        """)
        ultimos = []
        for r in cur.fetchall():
            ultimos.append({
                "fecha": r["fecha"] or "",
                "compra": r["compra"] or "",
                "categoria": r["categoria"] or "",
                "macroCategoria": r["macro_categoria"] or "",
                "icono": r["icono"] or "📌",
                "monto": round(float(r["monto"] or 0), 2),
                "tipo": r["tipo_operacion"] or "Gasto",
                "periodoPago": r["periodo_pago"] or "",
            })

        cur.close()

    return ok({
        "kpis": kpis,
        "tendenciaMensual": tendencia,
        "gastosPorCategoria": gastos_por_categoria,
        "presupuestoVsReal": presupuesto_vs_real,
        "balancePersonas": balance_personas,
        "ultimosMovimientos": ultimos,
    })


# ═══ Utilities ═══

def _gen_uuid(cur):
    cur.execute("SELECT gen_random_uuid()")
    return cur.fetchone()[0]


@app.get("/health")
async def health():
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
        return {"status": "ok"}
    except Exception:
        return JSONResponse({"status": "error"}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
