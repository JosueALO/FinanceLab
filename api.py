#!/usr/bin/env python3
"""
FINANCE LAB — API Backend v2
Reemplazo exacto de Google Apps Script para el frontend React
Campos en PascalCase, fechas DD/MM/YYYY, estructura idéntica
"""

import json
import traceback
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="Finance Lab API v2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_CONFIG = {
    "host": "finance-lab-db",
    "port": 5432,
    "dbname": "finance_lab",
    "user": "finadmin",
    "password": "f1nl4b_s3cur3",
}

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

# ── Helpers ──

def _fmt_date(d):
    """Date → DD/MM/YYYY"""
    if not d:
        return ""
    if isinstance(d, str):
        # Try to parse ISO → DD/MM/YYYY
        try:
            parts = d.split("-")
            if len(parts) == 3:
                return f"{parts[2]}/{parts[1]}/{parts[0]}"
        except:
            pass
        return d
    if isinstance(d, (datetime, date)):
        return d.strftime("%d/%m/%Y")
    return str(d)

def _fmt_num(v, default=0):
    if v is None:
        return default
    return float(v)

def _fmt_str(v, default=""):
    return str(v) if v is not None else default

def success(data):
    return JSONResponse({"success": True, "data": data})

def error(msg):
    return JSONResponse({"success": False, "error": str(msg)})

# ── API Router ──

@app.post("/api")
async def api_handler(request: Request):
    try:
        body = await request.json()
    except:
        body = {}

    action = body.get("action", "getAppData")
    payload = body.get("payload")

    try:
        handlers = {
            "getAppData": lambda: _get_app_data(),
            "registrarOperacion": lambda: _registrar_operacion(payload),
            "editarGasto": lambda: _editar_gasto(payload),
            "eliminarGasto": lambda: _eliminar_gasto(payload),
            "lanzarRecordatorio": lambda: _lanzar_recordatorio(payload),
            "guardarCuentas": lambda: _guardar_cuentas(payload),
            "guardarPresupuestoGlobal": lambda: _guardar_presupuesto_global(payload),
            "agregarCategoriaMaster": lambda: _agregar_categoria_master(payload),
            "editarCategoriaMaster": lambda: _editar_categoria_master(payload),
            "eliminarCategoriaMaster": lambda: _eliminar_categoria_master(payload),
        }
        if action in handlers:
            return handlers[action]()
        return error(f"Acción desconocida: {action}")
    except Exception as e:
        traceback.print_exc()
        return error(str(e))


# ── getAppData ──

def _get_app_data():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ── arbolCat {Gasto: {macro: [cat1, cat2]}, Ingreso: {macro: [...]}} ──
    cur.execute("""
        SELECT toper.nombre AS tipo, ca.macro, ca.nombre
        FROM categoria_arbol ca
        JOIN tipos_operacion toper ON ca.tipo_operacion_id = toper.id
        ORDER BY toper.id, ca.macro, ca.nombre
    """)
    arbolCat = {"Gasto": {}, "Ingreso": {}, "Transferencia": {}}
    for r in cur.fetchall():
        t = r["tipo"]
        m = r["macro"]
        if t not in arbolCat:
            arbolCat[t] = {}
        if m not in arbolCat[t]:
            arbolCat[t][m] = []
        arbolCat[t][m].append(r["nombre"])

    # ── cuentas ──
    cur.execute("SELECT nombre, tipo, propietario, saldo_inicial, dia_corte FROM cuentas WHERE activo ORDER BY tipo, nombre")
    cuentas = []
    for r in cur.fetchall():
        cuentas.append({
            "nombre": r["nombre"],
            "tipo": r["tipo"],
            "propietario": r["propietario"],
            "saldoInicial": _fmt_num(r["saldo_inicial"]),
            "diaCorte": r["dia_corte"] or "",
        })

    # ── rawLogs (gastos + recordatorios activos) ──
    cur.execute("""
        SELECT 
            g.id_unico AS id_unico,
            g.fecha_compra,
            g.fecha_registro,
            r.nombre AS registrador,
            g.compra,
            c.nombre AS categoria,
            mc.nombre AS macro_categoria,
            g.monto_total,
            g.monto_parcial,
            g.msi_status,
            COALESCE(mp.nombre, co.nombre) AS metodo_pago,
            tg.nombre AS tipo_gasto,
            g.periodo_pago,
            g.participacion_josue,
            g.participacion_abi,
            toper.nombre AS tipo_operacion,
            co.nombre AS cuenta_origen,
            cd.nombre AS cuenta_destino,
            CAST('FALSE' AS TEXT) AS es_recordatorio
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
            rec.id_unico AS id_unico,
            rec.fecha_programada AS fecha_compra,
            rec.fecha_registro,
            r2.nombre AS registrador,
            rec.compra,
            c2.nombre AS categoria,
            mc2.nombre AS macro_categoria,
            rec.monto_parcial AS monto_total,
            rec.monto_parcial,
            NULL AS msi_status,
            NULL AS metodo_pago,
            tg2.nombre AS tipo_gasto,
            NULL AS periodo_pago,
            rec.participacion_josue,
            rec.participacion_abi,
            toper2.nombre AS tipo_operacion,
            co2.nombre AS cuenta_origen,
            cd2.nombre AS cuenta_destino,
            CAST('TRUE' AS TEXT) AS es_recordatorio
        FROM recordatorios rec
        LEFT JOIN registradores r2 ON rec.registrador_id = r2.id
        LEFT JOIN categorias c2 ON rec.categoria_id = c2.id
        LEFT JOIN macro_categorias mc2 ON rec.macro_categoria_id = mc2.id
        LEFT JOIN tipos_gasto tg2 ON rec.tipo_gasto_id = tg2.id
        LEFT JOIN tipos_operacion toper2 ON rec.tipo_operacion_id = toper2.id
        LEFT JOIN cuentas co2 ON rec.cuenta_origen_id = co2.id
        LEFT JOIN cuentas cd2 ON rec.cuenta_destino_id = cd2.id
        WHERE NOT rec.lanzado
        
        ORDER BY fecha_compra DESC
    """)
    rawLogs = []
    for r in cur.fetchall():
        rawLogs.append({
            "ID_Unico": str(r["id_unico"]),
            "Fecha_Compra": _fmt_date(r["fecha_compra"]),
            "Fecha_Registro": _fmt_date(r["fecha_registro"]),
            "Registrador": _fmt_str(r["registrador"]),
            "Compra": _fmt_str(r["compra"]),
            "Categoria": _fmt_str(r["categoria"]),
            "MacroCategoria": _fmt_str(r["macro_categoria"]),
            "Monto_Total": _fmt_num(r["monto_total"]),
            "Monto_Parcial": _fmt_num(r["monto_parcial"]),
            "MSI_Status": _fmt_date(r["msi_status"]),
            "Metodo_Pago": _fmt_str(r["metodo_pago"]),
            "Tipo_Gasto": _fmt_str(r["tipo_gasto"]),
            "Periodo_Pago": _fmt_date(r["periodo_pago"]),
            "Participacion_Josue": _fmt_num(r["participacion_josue"]),
            "Participacion_Abi": _fmt_num(r["participacion_abi"]),
            "Tipo_Operacion": _fmt_str(r["tipo_operacion"], "Gasto"),
            "Cuenta_Origen": _fmt_str(r["cuenta_origen"]),
            "Cuenta_Destino": _fmt_str(r["cuenta_destino"]),
            "Es_Recordatorio": _fmt_str(r["es_recordatorio"], "FALSE"),
        })

    # ── presupuesto {Compartido: {cat: monto}, Josue: {cat: monto}, Abi: {cat: monto}} ──
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
    conn.close()

    return success({
        "rawLogs": rawLogs,
        "presupuesto": presupuesto,
        "arbolCat": arbolCat,
        "cuentas": cuentas,
    })


# ── registrarOperacion + editarGasto ──

def _parse_form(p):
    """Extrae campos comunes del formulario React → valores DB"""
    es_rec = p.get("esRecordatorio", False)
    tipo_op = p.get("tipoOperacion", "Gasto")
    tipo_gasto = p.get("tipoGasto", "Compartido (50/50)")
    fecha = p.get("fechaCompra", "")
    # Convertir YYYY-MM-DD (html date input) → date
    if fecha:
        try:
            parts = fecha.split("-")
            fecha_compra = date(int(parts[0]), int(parts[1]), int(parts[2]))
        except:
            fecha_compra = date.today()
    else:
        fecha_compra = date.today()

    return {
        "es_recordatorio": es_rec,
        "tipo_operacion": tipo_op,
        "tipo_gasto": tipo_gasto,
        "fecha_compra": fecha_compra,
        "compra": p.get("compra", ""),
        "monto": float(p.get("monto") or 0),
        "registrador": p.get("registrador", ""),
        "categoria": p.get("categoria", ""),
        "macro_categoria": p.get("macroCategoria", ""),
        "cuenta_origen": p.get("cuentaOrigen", ""),
        "cuenta_destino": p.get("cuentaDestino", ""),
        "msi": p.get("msi", "1"),
        "pct_josue": int(p.get("pctJosue") or 0),
        "pct_abi": int(p.get("pctAbi") or 0),
    }


def _grabar_operacion(p, id_unico=None):
    conn = get_conn()
    cur = conn.cursor()

    f = _parse_form(p)

    # Lookup IDs
    reg_id = _find_or_create(cur, "registradores", "nombre", f["registrador"])
    cat_id = _find_or_create(cur, "categorias", "nombre", f["categoria"])
    mcat_id = _find_or_create(cur, "macro_categorias", "nombre", f["macro_categoria"])
    top_id = _find_id(cur, "tipos_operacion", "nombre", f["tipo_operacion"])
    tg_id = _find_id(cur, "tipos_gasto", "nombre", f["tipo_gasto"])
    co_id = _find_id(cur, "cuentas", "nombre", f["cuenta_origen"])
    cd_id = _find_id(cur, "cuentas", "nombre", f["cuenta_destino"])

    monto = f["monto"]
    total = 100
    p_josue = round(monto * f["pct_josue"] / total, 2) if f["pct_josue"] else 0
    p_abi = round(monto * f["pct_abi"] / total, 2) if f["pct_abi"] else 0

    # Calcular splits según tipo
    if "Compartido" in f["tipo_gasto"]:
        if "50/50" in f["tipo_gasto"]:
            p_josue = round(monto / 2, 2)
            p_abi = round(monto / 2, 2)
        elif "Proporcional" in f["tipo_gasto"]:
            # Ya calculado con pct
            pass
    elif "Personal Josué" in f["tipo_gasto"]:
        p_josue = monto
        p_abi = 0
    elif "Personal Abi" in f["tipo_gasto"] or "Personal Ab" in f["tipo_gasto"]:
        p_josue = 0
        p_abi = monto

    # Ensure splits match
    if abs(p_josue + p_abi - monto) > 0.01:
        p_abi = round(monto - p_josue, 2)

    # Determinar periodo_pago
    hoy = date.today()
    if f["fecha_compra"].day <= 19:
        mes_periodo = f["fecha_compra"].month
    else:
        mes_periodo = f["fecha_compra"].month + 1
    if mes_periodo > 12:
        mes_periodo -= 12
    import calendar
    ultimo_dia = calendar.monthrange(f["fecha_compra"].year if mes_periodo >= f["fecha_compra"].month else f["fecha_compra"].year + 1, mes_periodo)[1]
    periodo_pago = date(f["fecha_compra"].year if mes_periodo >= f["fecha_compra"].month else f["fecha_compra"].year + 1, mes_periodo, ultimo_dia)

    if f["es_recordatorio"]:
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
        """, (rec_id, f["fecha_compra"], reg_id,
              f["compra"], cat_id, mcat_id, monto,
              top_id, co_id, cd_id,
              tg_id, p_josue, p_abi))
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
        """, (gasto_id, f["fecha_compra"], date.today(), reg_id,
              f["compra"], cat_id, mcat_id,
              monto, monto,
              tg_id, periodo_pago,
              p_josue, p_abi,
              top_id, co_id, cd_id))

    conn.commit()
    cur.close()
    conn.close()


def _registrar_operacion(payload):
    _grabar_operacion(payload)
    return success({"ok": True})


def _editar_gasto(payload):
    id_unico = payload.get("id_edit")
    if not id_unico:
        return error("ID requerido para editar")
    _grabar_operacion(payload, id_unico)
    return success({"ok": True})


# ── eliminarGasto ──

def _eliminar_gasto(payload):
    target_id = payload if isinstance(payload, str) else (payload.get("ID_Unico") or payload.get("id_unico"))
    if not target_id:
        return error("ID requerido")
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT soft_delete_gasto(%s, %s)", (target_id, "Josué"))
        # Also try deleting a recordatorio
        cur.execute("DELETE FROM recordatorios WHERE id_unico = %s", (target_id,))
        conn.commit()
    except Exception:
        conn.rollback()
    cur.close()
    conn.close()
    return success({"deleted": target_id})


# ── lanzarRecordatorio ──

def _lanzar_recordatorio(payload):
    rec_id = payload.get("id") or payload.get("ID_Unico") or payload.get("id_unico")
    fecha_str = payload.get("fecha") or str(date.today())

    if not rec_id:
        return error("ID requerido")

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT lanzar_recordatorio(%s, %s)", (rec_id, fecha_str))
        gid = cur.fetchone()[0]
        conn.commit()
        return success({"gasto_id": str(gid)})
    except Exception as e:
        conn.rollback()
        return error(str(e))
    finally:
        cur.close()
        conn.close()


# ── guardarCuentas ──

def _guardar_cuentas(payload):
    if not isinstance(payload, list):
        return error("Se espera lista de cuentas")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE cuentas SET activo = false")

    for c in payload:
        nombre = (c.get("nombre") or "").strip()
        if not nombre:
            continue
        cur.execute("""
            INSERT INTO cuentas (nombre, tipo, propietario, saldo_inicial, dia_corte, activo)
            VALUES (%s,%s,%s,%s,%s,true)
            ON CONFLICT (nombre) DO UPDATE SET
                tipo=EXCLUDED.tipo, propietario=EXCLUDED.propietario,
                saldo_inicial=EXCLUDED.saldo_inicial, dia_corte=EXCLUDED.dia_corte,
                activo=true, updated_at=now()
        """, (
            nombre,
            c.get("tipo", "Activo"),
            c.get("propietario", "Josué"),
            float(c.get("saldoInicial", c.get("saldo_inicial", 0))),
            int(c.get("diaCorte") or 0) if c.get("diaCorte") else None,
        ))

    conn.commit()
    cur.close()
    conn.close()
    return success({"saved": len(payload)})


# ── guardarPresupuestoGlobal ──

def _guardar_presupuesto_global(payload):
    if not payload:
        return error("Payload requerido")

    conn = get_conn()
    cur = conn.cursor()

    presupuesto = payload.get("presupuesto", {})
    for ambito in ["Compartido", "Josue", "Abi"]:
        cats = presupuesto.get(ambito, {})
        for cat_nombre, monto in cats.items():
            if not monto:
                continue
            cat_id = _find_or_create(cur, "categorias", "nombre", cat_nombre)
            m = float(monto)
            cur.execute("""
                INSERT INTO presupuestos (ambito, categoria_id, monto)
                VALUES (%s,%s,%s)
                ON CONFLICT (ambito, categoria_id) DO UPDATE SET
                    monto=EXCLUDED.monto, updated_at=now()
            """, (ambito, cat_id, m))

    conn.commit()
    cur.close()
    conn.close()
    return success({"ok": True})


# ── Categorías Master ──

def _agregar_categoria_master(payload):
    nombre = payload.get("name", "").strip()
    macro = payload.get("macro", "General").strip()
    tipo = payload.get("tipo", "Gasto")
    if not nombre:
        return error("Nombre requerido")

    conn = get_conn()
    cur = conn.cursor()

    # Añadir categoría
    _find_or_create(cur, "categorias", "nombre", nombre)
    # Añadir macro_categoria si no existe
    _find_or_create(cur, "macro_categorias", "nombre", macro)

    # Añadir al árbol
    top_id = _find_id(cur, "tipos_operacion", "nombre", tipo) or 1
    cur.execute("""
        INSERT INTO categoria_arbol (tipo_operacion_id, macro, nombre)
        VALUES (%s, %s, %s)
        ON CONFLICT (tipo_operacion_id, macro, nombre) DO NOTHING
    """, (top_id, macro, nombre))

    conn.commit()
    cur.close()
    conn.close()
    return success({"ok": True})


def _editar_categoria_master(payload):
    old_name = payload.get("oldName", "").strip()
    new_name = payload.get("newName", "").strip()
    new_macro = payload.get("newMacro", "General").strip()
    new_tipo = payload.get("newTipo", "Gasto")

    if not old_name or not new_name:
        return error("Nombres requeridos")

    conn = get_conn()
    cur = conn.cursor()

    top_id = _find_id(cur, "tipos_operacion", "nombre", new_tipo) or 1
    _find_or_create(cur, "macro_categorias", "nombre", new_macro)

    cur.execute("""
        UPDATE categoria_arbol
        SET nombre=%s, macro=%s, tipo_operacion_id=%s
        WHERE nombre=%s
    """, (new_name, new_macro, top_id, old_name))

    # Update categorias table too
    cur.execute("UPDATE categorias SET nombre=%s WHERE nombre=%s", (new_name, old_name))

    conn.commit()
    cur.close()
    conn.close()
    return success({"ok": True})


def _eliminar_categoria_master(payload):
    nombre = payload if isinstance(payload, str) else (payload.get("name") or payload.get("nombre") or "").strip()
    if not nombre:
        return error("Nombre requerido")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM categoria_arbol WHERE nombre=%s", (nombre,))
    conn.commit()
    cur.close()
    conn.close()
    return success({"ok": True})


# ── Utilities ──

def _gen_uuid(cur):
    cur.execute("SELECT gen_random_uuid()")
    return cur.fetchone()[0]


def _find_id(cur, table, col, val):
    if not val:
        return None
    cur.execute(f"SELECT id FROM {table} WHERE {col} = %s", (val,))
    row = cur.fetchone()
    return row[0] if row else None


def _find_or_create(cur, table, col, val):
    if not val:
        return None
    cur.execute(f"SELECT id FROM {table} WHERE {col} = %s", (val,))
    row = cur.fetchone()
    if row:
        return row[0]
    # Create
    extras = ""
    if table == "cuentas":
        extras = ", tipo, propietario"
        cur.execute(f"INSERT INTO {table} ({col}{extras}) VALUES (%s, 'Activo', 'Josué') ON CONFLICT ({col}) DO NOTHING RETURNING id", (val,))
    elif table == "registradores":
        cur.execute(f"INSERT INTO {table} ({col}) VALUES (%s) ON CONFLICT ({col}) DO NOTHING RETURNING id", (val,))
    else:
        cur.execute(f"INSERT INTO {table} ({col}) VALUES (%s) ON CONFLICT ({col}) DO NOTHING RETURNING id", (val,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(f"SELECT id FROM {table} WHERE {col} = %s", (val,))
    row = cur.fetchone()
    return row[0] if row else None


# ── Health ──

@app.get("/health")
async def health():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return {"status": "ok"}
    except:
        return JSONResponse({"status": "error"}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
