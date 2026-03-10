from fastapi import FastAPI, HTTPException, Depends, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import jwt
import models, schemas
from database import engine, get_db
from passlib.context import CryptContext

SECRET_KEY = "nexus_secret_2026"
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

models.Base.metadata.create_all(bind=engine)
app = FastAPI(title="Nexus ERP")

# ---------------------------------------------------------------------------
# UTILIDADES DE SEGURIDAD
# ---------------------------------------------------------------------------
def obtener_hash(password: str): return pwd_context.hash(password)
def verificar_password(plana, hash_bd): return pwd_context.verify(plana, hash_bd)

class ConnectionManager:
    def __init__(self): self.active_connections = []
    async def connect(self, ws: WebSocket): await ws.accept(); self.active_connections.append(ws)
    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections: self.active_connections.remove(ws)
    async def broadcast(self, msg: str):
        for c in self.active_connections:
            try: await c.send_text(msg)
            except: pass

manager = ConnectionManager()

def verificar_token(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try: return jwt.decode(authorization.split(" ")[1], SECRET_KEY, algorithms=[ALGORITHM])
    except: raise HTTPException(status_code=401)

def rol_requerido(roles: list):
    def verificador(user: dict = Depends(verificar_token)):
        if user.get("rol") not in roles: raise HTTPException(status_code=403)
        return user
    return verificador

# ---------------------------------------------------------------------------
# LÓGICA ABC
# Clasifica medicamentos por rotación acumulada de salidas (Pareto 80/95/100)
# Actualiza zona de slotting automáticamente
# ---------------------------------------------------------------------------
def calcular_abc(db: Session) -> dict:
    movs = db.query(models.Movimiento).filter(models.Movimiento.tipo == "SALIDA").all()
    ventas = {}
    for m in movs:
        if m.lote:
            cid = m.lote.catalogo_id
            ventas[cid] = ventas.get(cid, 0) + m.cantidad

    if not ventas:
        return {}

    total = sum(ventas.values())
    ordenado = sorted(ventas.items(), key=lambda x: x[1], reverse=True)
    acum = 0
    resultado = {}
    for cid, cant in ordenado:
        acum += cant
        pct = acum / total
        if pct <= 0.80:   resultado[cid] = "A"
        elif pct <= 0.95: resultado[cid] = "B"
        else:             resultado[cid] = "C"

    # Persistir clasificación y slotting
    for cid, clase in resultado.items():
        cat = db.query(models.Catalogo).filter(models.Catalogo.id == cid).first()
        if cat:
            cat.clasificacion_abc = clase
            if clase == "A":   cat.zona_almacenaje = "Zona-A (Acceso Inmediato)"
            elif clase == "B": cat.zona_almacenaje = "Zona-B (Media Rotación)"
            else:              cat.zona_almacenaje = "Zona-C (Baja Rotación)"
    db.commit()
    return resultado

# ---------------------------------------------------------------------------
# STARTUP
# ---------------------------------------------------------------------------
@app.on_event("startup")
def startup():
    db = next(get_db())
    if not db.query(models.Usuario).filter(models.Usuario.username == "admin").first():
        db.add(models.Usuario(username="admin", password=obtener_hash("123"), rol="ADMIN"))
        db.commit()

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: manager.disconnect(ws)

# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------
@app.post("/api/login")
def login(req: schemas.LoginReq, db: Session = Depends(get_db)):
    u = db.query(models.Usuario).filter(models.Usuario.username == req.username).first()
    if not u or not verificar_password(req.password, u.password):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    token = jwt.encode(
        {"sub": u.username, "rol": u.rol, "exp": datetime.utcnow() + timedelta(hours=8)},
        SECRET_KEY, algorithm=ALGORITHM
    )
    return {"access_token": token, "rol": u.rol, "username": u.username}

# ---------------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------------
@app.get("/api/dashboard", dependencies=[Depends(verificar_token)])
def get_dash(db: Session = Depends(get_db)):
    ing = sum(f.monto for f in db.query(models.Finanza).filter(models.Finanza.tipo == "INGRESO").all()) or 0
    gas = sum(f.monto for f in db.query(models.Finanza).filter(models.Finanza.tipo == "GASTO").all()) or 0

    lotes = db.query(models.Lote).filter(models.Lote.cantidad > 0).all()
    resumen = {}
    for l in lotes:
        resumen[l.medicamento.nombre] = resumen.get(l.medicamento.nombre, 0) + l.cantidad
    alertas_stock = [{"medicamento": m, "stock": s} for m, s in resumen.items() if s < 10]

    calcular_abc(db)

    movs = db.query(models.Movimiento).filter(models.Movimiento.tipo == "SALIDA").all()
    ventas = {}
    for m in movs:
        n = m.lote.medicamento.nombre if m.lote else "N/A"
        ventas[n] = ventas.get(n, 0) + m.cantidad
    top = [{"nombre": k, "ventas": v} for k, v in sorted(ventas.items(), key=lambda x: x[1], reverse=True)[:5]]

    # BPA — 3 niveles de alerta por caducidad
    hoy = datetime.utcnow().date()
    alertas_bpa = []
    for l in db.query(models.Lote).filter(models.Lote.cantidad > 0).all():
        dias = (l.fecha_caducidad - hoy).days
        if dias < 0:       nivel = "VENCIDO"
        elif dias <= 30:   nivel = "CRITICO"
        elif dias <= 90:   nivel = "ALERTA"
        else:              continue
        alertas_bpa.append({
            "medicamento": l.medicamento.nombre,
            "lote": l.numero_lote,
            "dias": dias,
            "nivel": nivel
        })
    alertas_bpa.sort(key=lambda x: x["dias"])

    catalogos = db.query(models.Catalogo).all()
    abc_resumen = {"A": 0, "B": 0, "C": 0}
    for c in catalogos:
        if c.clasificacion_abc in abc_resumen:
            abc_resumen[c.clasificacion_abc] += 1

    return {
        "total_lotes": len(lotes),
        "ingresos": ing,
        "gastos": gas,
        "utilidad": ing - gas,
        "en_riesgo": db.query(models.Lote).filter(
            models.Lote.cantidad > 0,
            models.Lote.fecha_caducidad <= hoy + timedelta(days=30)
        ).count(),
        "alertas_stock": alertas_stock,
        "alertas_bpa": alertas_bpa,
        "top_productos": top,
        "abc_resumen": abc_resumen,
    }

# ---------------------------------------------------------------------------
# ALMACÉN
# ---------------------------------------------------------------------------
@app.post("/api/entradas", dependencies=[Depends(verificar_token)])
async def entrada(req: schemas.EntradaReq, db: Session = Depends(get_db)):
    cat = db.query(models.Catalogo).filter(models.Catalogo.nombre == req.nombre_medicamento).first()
    if not cat:
        cat = models.Catalogo(nombre=req.nombre_medicamento, zona_almacenaje=req.zona)
        db.add(cat); db.commit(); db.refresh(cat)
    lote = db.query(models.Lote).filter(models.Lote.numero_lote == req.numero_lote).first()
    if lote:
        lote.cantidad += req.cantidad
    else:
        lote = models.Lote(
            numero_lote=req.numero_lote, catalogo_id=cat.id,
            cantidad=req.cantidad, fecha_caducidad=req.fecha_caducidad
        )
        db.add(lote)
    db.commit()
    db.add(models.Movimiento(lote_id=lote.id, tipo="ENTRADA", cantidad=req.cantidad, destino_origen=req.origen))
    db.commit()
    await manager.broadcast("update")
    return {"msg": "OK"}

@app.post("/api/salidas", dependencies=[Depends(verificar_token)])
async def salida(req: schemas.SalidaReq, db: Session = Depends(get_db)):
    cat = db.query(models.Catalogo).filter(models.Catalogo.nombre == req.nombre_medicamento).first()
    if not cat: raise HTTPException(status_code=404, detail="Medicamento no encontrado")
    # FEFO: primero los que vencen antes — BPA: excluir lotes ya vencidos
    hoy = datetime.utcnow().date()
    lotes = db.query(models.Lote).filter(
        models.Lote.catalogo_id == cat.id,
        models.Lote.cantidad > 0,
        models.Lote.fecha_caducidad >= hoy
    ).order_by(models.Lote.fecha_caducidad).all()

    disponible = sum(l.cantidad for l in lotes)
    if disponible < req.cantidad_requerida:
        raise HTTPException(status_code=400, detail=f"Stock insuficiente. Disponible: {disponible}")

    cant = req.cantidad_requerida
    for l in lotes:
        if cant <= 0: break
        t = min(l.cantidad, cant)
        l.cantidad -= t; cant -= t
        db.add(models.Movimiento(lote_id=l.id, tipo="SALIDA", cantidad=t, destino_origen=req.destino))
    db.commit()
    await manager.broadcast("update")
    return {"msg": "OK"}

@app.get("/api/inventario", dependencies=[Depends(verificar_token)])
def inv(db: Session = Depends(get_db)):
    hoy = datetime.utcnow().date()
    resultado = []
    for l in db.query(models.Lote).filter(models.Lote.cantidad > 0).all():
        dias = (l.fecha_caducidad - hoy).days
        if dias < 0:       estado_bpa = "VENCIDO"
        elif dias <= 30:   estado_bpa = "CRITICO"
        elif dias <= 90:   estado_bpa = "ALERTA"
        else:              estado_bpa = "OK"
        resultado.append({
            "medicamento": l.medicamento.nombre,
            "lote": l.numero_lote,
            "stock": l.cantidad,
            "caducidad": l.fecha_caducidad,
            "zona": l.medicamento.zona_almacenaje,
            "abc": l.medicamento.clasificacion_abc,
            "refrigeracion": l.medicamento.requiere_refrigeracion,
            "controlado": l.medicamento.controlado,
            "estado_bpa": estado_bpa,
            "dias_caducidad": dias,
        })
    return resultado

@app.get("/api/movimientos", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
def get_movimientos(db: Session = Depends(get_db)):
    movs = db.query(models.Movimiento).order_by(models.Movimiento.fecha.desc()).all()
    return [
        {
            "fecha": m.fecha.strftime("%Y-%m-%d %H:%M"),
            "tipo": m.tipo,
            "medicamento": m.lote.medicamento.nombre if m.lote else "N/A",
            "lote": m.lote.numero_lote if m.lote else "N/A",
            "cantidad": m.cantidad,
            "destino_origen": m.destino_origen,
        } for m in movs
    ]

# ---------------------------------------------------------------------------
# ABC — endpoint dedicado
# ---------------------------------------------------------------------------
@app.get("/api/abc", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
def get_abc(db: Session = Depends(get_db)):
    calcular_abc(db)
    movs = db.query(models.Movimiento).filter(models.Movimiento.tipo == "SALIDA").all()
    ventas = {}
    for m in movs:
        if m.lote:
            n = m.lote.medicamento.nombre
            ventas[n] = ventas.get(n, 0) + m.cantidad

    resultado = []
    for c in db.query(models.Catalogo).all():
        resultado.append({
            "id": c.id,
            "nombre": c.nombre,
            "clasificacion": c.clasificacion_abc,
            "zona": c.zona_almacenaje,
            "salidas_totales": ventas.get(c.nombre, 0),
            "refrigeracion": c.requiere_refrigeracion,
            "controlado": c.controlado,
            "temp_min": c.temp_min,
            "temp_max": c.temp_max,
        })
    resultado.sort(key=lambda x: (x["clasificacion"], -x["salidas_totales"]))
    return resultado

# ---------------------------------------------------------------------------
# BPA — actualizar condiciones de almacenamiento de un medicamento
# ---------------------------------------------------------------------------
@app.put("/api/catalogo/{catalogo_id}/bpa", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
async def actualizar_bpa(catalogo_id: int, req: schemas.ActualizarCatalogoReq, db: Session = Depends(get_db)):
    cat = db.query(models.Catalogo).filter(models.Catalogo.id == catalogo_id).first()
    if not cat: raise HTTPException(status_code=404)
    if req.zona_almacenaje is not None:       cat.zona_almacenaje = req.zona_almacenaje
    if req.temp_min is not None:              cat.temp_min = req.temp_min
    if req.temp_max is not None:              cat.temp_max = req.temp_max
    if req.requiere_refrigeracion is not None: cat.requiere_refrigeracion = req.requiere_refrigeracion
    if req.controlado is not None:            cat.controlado = req.controlado
    db.commit()
    await manager.broadcast("update")
    return {"msg": "OK"}

# ---------------------------------------------------------------------------
# FINANZAS
# ---------------------------------------------------------------------------
@app.post("/api/finanzas", dependencies=[Depends(rol_requerido(["ADMIN"]))])
async def post_fin(req: schemas.FinanzaReq, db: Session = Depends(get_db)):
    db.add(models.Finanza(tipo=req.tipo, monto=req.monto, concepto=req.concepto))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/finanzas", dependencies=[Depends(rol_requerido(["ADMIN"]))])
def get_fin(db: Session = Depends(get_db)):
    return [
        {"fecha": f.fecha.strftime("%Y-%m-%d %H:%M"), "tipo": f.tipo, "concepto": f.concepto, "monto": f.monto}
        for f in db.query(models.Finanza).order_by(models.Finanza.fecha.desc()).all()
    ]

# ---------------------------------------------------------------------------
# USUARIOS
# ---------------------------------------------------------------------------
@app.post("/api/usuarios", dependencies=[Depends(rol_requerido(["ADMIN"]))])
async def post_usr(req: schemas.UsuarioReq, db: Session = Depends(get_db)):
    if db.query(models.Usuario).filter(models.Usuario.username == req.username).first():
        raise HTTPException(status_code=400, detail="Usuario ya existe")
    db.add(models.Usuario(username=req.username, password=obtener_hash(req.password), rol=req.rol))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/usuarios", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
def get_usr(db: Session = Depends(get_db)):
    return [{"username": u.username, "rol": u.rol} for u in db.query(models.Usuario).all()]

@app.delete("/api/usuarios/{username}", dependencies=[Depends(rol_requerido(["ADMIN"]))])
async def del_usr(username: str, db: Session = Depends(get_db)):
    if username == "admin": raise HTTPException(status_code=403, detail="No se puede eliminar al admin")
    u = db.query(models.Usuario).filter(models.Usuario.username == username).first()
    if not u: raise HTTPException(status_code=404)
    db.delete(u); db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

# ---------------------------------------------------------------------------
# PROVEEDORES
# ---------------------------------------------------------------------------
@app.post("/api/proveedores", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
async def post_prov(req: schemas.ProveedorReq, db: Session = Depends(get_db)):
    db.add(models.Proveedor(nombre=req.nombre, contacto=req.contacto))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/proveedores", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
def get_prov(db: Session = Depends(get_db)):
    return [{"id": p.id, "nombre": p.nombre, "contacto": p.contacto} for p in db.query(models.Proveedor).all()]

# ---------------------------------------------------------------------------
# COMPRAS
# ---------------------------------------------------------------------------
@app.post("/api/compras", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
async def post_compra(req: schemas.OrdenReq, db: Session = Depends(get_db)):
    prov = db.query(models.Proveedor).filter(models.Proveedor.id == req.proveedor_id).first()
    if not prov: raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    db.add(models.OrdenCompra(
        proveedor_id=req.proveedor_id, medicamento=req.medicamento,
        cantidad=req.cantidad, costo_total=req.costo_total
    ))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/compras", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
def get_compras(db: Session = Depends(get_db)):
    return [
        {
            "id": o.id,
            "fecha": o.fecha_orden.strftime("%Y-%m-%d %H:%M"),
            "proveedor": o.proveedor.nombre,
            "medicamento": o.medicamento,
            "cantidad": o.cantidad,
            "costo_total": o.costo_total,
            "estado": o.estado,
        } for o in db.query(models.OrdenCompra).order_by(models.OrdenCompra.fecha_orden.desc()).all()
    ]

@app.put("/api/compras/{orden_id}/recibir", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
async def recibir_compra(orden_id: int, req: schemas.RecibirOrdenReq, db: Session = Depends(get_db)):
    orden = db.query(models.OrdenCompra).filter(models.OrdenCompra.id == orden_id).first()
    if not orden: raise HTTPException(status_code=404)
    if orden.estado == "COMPLETADA": raise HTTPException(status_code=400, detail="Orden ya recibida")

    cat = db.query(models.Catalogo).filter(models.Catalogo.nombre == orden.medicamento).first()
    if not cat:
        cat = models.Catalogo(nombre=orden.medicamento); db.add(cat); db.commit(); db.refresh(cat)
    lote = db.query(models.Lote).filter(models.Lote.numero_lote == req.numero_lote).first()
    if lote:
        lote.cantidad += orden.cantidad
    else:
        lote = models.Lote(
            numero_lote=req.numero_lote, catalogo_id=cat.id,
            cantidad=orden.cantidad, fecha_caducidad=req.fecha_caducidad
        )
        db.add(lote)
    db.commit()
    db.add(models.Movimiento(
        lote_id=lote.id, tipo="ENTRADA", cantidad=orden.cantidad,
        destino_origen=f"OC#{orden_id} - {orden.proveedor.nombre}"
    ))
    db.add(models.Finanza(
        tipo="GASTO", monto=orden.costo_total,
        concepto=f"OC#{orden_id} - {orden.medicamento} ({orden.proveedor.nombre})"
    ))
    orden.estado = "COMPLETADA"
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

# ---------------------------------------------------------------------------
# FRONTEND
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    with open("index.html", "r", encoding="utf-8") as f: return f.read()
