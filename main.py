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
app = FastAPI(title="Nexus ERP - CEDIS")

# ---------------------------------------------------------------------------
# SEGURIDAD
# ---------------------------------------------------------------------------
def obtener_hash(p): return pwd_context.hash(p)
def verificar_password(plana, hashed): return pwd_context.verify(plana, hashed)

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

ROLES_CEDIS = ["ADMIN", "SUPERVISOR", "OPERADOR", "QFR"]
ROLES_GESTION = ["ADMIN", "SUPERVISOR"]
ROLES_QFR = ["ADMIN", "QFR"]

# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------
def calcular_abc(db: Session):
    try:
        movs = db.query(models.Movimiento).filter(models.Movimiento.tipo == "SALIDA").all()
        ventas = {}
        for m in movs:
            if m.lote:
                cid = m.lote.catalogo_id
                ventas[cid] = ventas.get(cid, 0) + m.cantidad
        if not ventas: return {}
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
        for cid, clase in resultado.items():
            cat = db.query(models.Catalogo).filter(models.Catalogo.id == cid).first()
            if cat:
                cat.clasificacion_abc = clase
                if clase == "A":   cat.zona_almacenaje = "Zona-A (Acceso Inmediato)"
                elif clase == "B": cat.zona_almacenaje = "Zona-B (Media Rotación)"
                else:              cat.zona_almacenaje = "Zona-C (Baja Rotación)"
        db.commit()
        return resultado
    except: return {}

# ---------------------------------------------------------------------------
# STARTUP — crea usuario admin y datos iniciales
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
        {"sub": u.username, "rol": u.rol, "exp": datetime.utcnow() + timedelta(hours=8),
         "farmacia_id": u.farmacia_id},
        SECRET_KEY, algorithm=ALGORITHM
    )
    return {"access_token": token, "rol": u.rol, "username": u.username,
            "farmacia_id": u.farmacia_id}

# ---------------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------------
@app.get("/api/dashboard", dependencies=[Depends(verificar_token)])
def get_dash(db: Session = Depends(get_db)):
    ing = sum(f.monto for f in db.query(models.Finanza).filter(models.Finanza.tipo == "INGRESO").all()) or 0
    gas = sum(f.monto for f in db.query(models.Finanza).filter(models.Finanza.tipo == "GASTO").all()) or 0
    lotes = db.query(models.Lote).filter(models.Lote.cantidad > 0).all()
    resumen = {}
    for l in lotes: resumen[l.medicamento.nombre] = resumen.get(l.medicamento.nombre, 0) + l.cantidad
    alertas_stock = [{"medicamento": m, "stock": s} for m, s in resumen.items() if s < 10]
    calcular_abc(db)
    movs = db.query(models.Movimiento).filter(models.Movimiento.tipo == "SALIDA").all()
    ventas = {}
    for m in movs:
        n = m.lote.medicamento.nombre if m.lote else "N/A"
        ventas[n] = ventas.get(n, 0) + m.cantidad
    top = [{"nombre": k, "ventas": v} for k, v in sorted(ventas.items(), key=lambda x: x[1], reverse=True)[:5]]
    hoy = datetime.utcnow().date()
    alertas_bpa = []
    try:
        for l in db.query(models.Lote).filter(models.Lote.cantidad > 0).all():
            dias = (l.fecha_caducidad - hoy).days
            if dias < 0: nivel = "VENCIDO"
            elif dias <= 30: nivel = "CRITICO"
            elif dias <= 90: nivel = "ALERTA"
            else: continue
            alertas_bpa.append({"medicamento": l.medicamento.nombre, "lote": l.numero_lote, "dias": dias, "nivel": nivel})
        alertas_bpa.sort(key=lambda x: x["dias"])
    except: pass
    abc_resumen = {"A": 0, "B": 0, "C": 0}
    try:
        for c in db.query(models.Catalogo).all():
            if c.clasificacion_abc in abc_resumen: abc_resumen[c.clasificacion_abc] += 1
    except: pass
    # Métricas CEDIS nuevas
    pedidos_pendientes = db.query(models.PedidoFarmacia).filter(models.PedidoFarmacia.estado.in_(["PENDIENTE","EN_PICKING","LISTO"])).count()
    en_ruta = db.query(models.PedidoFarmacia).filter(models.PedidoFarmacia.estado == "EN_RUTA").count()
    en_cuarentena = db.query(models.LoteCuarentena).filter(models.LoteCuarentena.estado == "EN_REVISION").count()
    return {
        "total_lotes": len(lotes), "ingresos": ing, "gastos": gas, "utilidad": ing - gas,
        "en_riesgo": db.query(models.Lote).filter(models.Lote.cantidad > 0, models.Lote.fecha_caducidad <= hoy + timedelta(days=30)).count(),
        "alertas_stock": alertas_stock, "alertas_bpa": alertas_bpa, "top_productos": top,
        "abc_resumen": abc_resumen, "pedidos_pendientes": pedidos_pendientes,
        "en_ruta": en_ruta, "en_cuarentena": en_cuarentena,
    }

# ---------------------------------------------------------------------------
# ALMACÉN
# ---------------------------------------------------------------------------
@app.post("/api/entradas", dependencies=[Depends(rol_requerido(ROLES_CEDIS))])
async def entrada(req: schemas.EntradaReq, db: Session = Depends(get_db)):
    cat = db.query(models.Catalogo).filter(models.Catalogo.nombre == req.nombre_medicamento).first()
    if not cat:
        cat = models.Catalogo(nombre=req.nombre_medicamento, zona_almacenaje=req.zona)
        db.add(cat); db.commit(); db.refresh(cat)
    lote = db.query(models.Lote).filter(models.Lote.numero_lote == req.numero_lote).first()
    if lote: lote.cantidad += req.cantidad
    else:
        lote = models.Lote(numero_lote=req.numero_lote, catalogo_id=cat.id, cantidad=req.cantidad, fecha_caducidad=req.fecha_caducidad)
        db.add(lote)
    db.commit()
    db.add(models.Movimiento(lote_id=lote.id, tipo="ENTRADA", cantidad=req.cantidad, destino_origen=req.origen))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.post("/api/salidas", dependencies=[Depends(rol_requerido(ROLES_CEDIS))])
async def salida(req: schemas.SalidaReq, db: Session = Depends(get_db)):
    cat = db.query(models.Catalogo).filter(models.Catalogo.nombre == req.nombre_medicamento).first()
    if not cat: raise HTTPException(status_code=404, detail="Medicamento no encontrado")
    hoy = datetime.utcnow().date()
    lotes = db.query(models.Lote).filter(
        models.Lote.catalogo_id == cat.id, models.Lote.cantidad > 0,
        models.Lote.fecha_caducidad >= hoy
    ).order_by(models.Lote.fecha_caducidad).all()
    disponible = sum(l.cantidad for l in lotes)
    if disponible < req.cantidad_requerida:
        raise HTTPException(status_code=400, detail=f"Stock insuficiente. Disponible: {disponible}")
    cant = req.cantidad_requerida
    for l in lotes:
        if cant <= 0: break
        t = min(l.cantidad, cant); l.cantidad -= t; cant -= t
        db.add(models.Movimiento(lote_id=l.id, tipo="SALIDA", cantidad=t, destino_origen=req.destino))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/inventario", dependencies=[Depends(verificar_token)])
def inv(db: Session = Depends(get_db)):
    hoy = datetime.utcnow().date()
    resultado = []
    for l in db.query(models.Lote).filter(models.Lote.cantidad > 0).all():
        dias = (l.fecha_caducidad - hoy).days
        if dias < 0: estado_bpa = "VENCIDO"
        elif dias <= 30: estado_bpa = "CRITICO"
        elif dias <= 90: estado_bpa = "ALERTA"
        else: estado_bpa = "OK"
        resultado.append({
            "medicamento": l.medicamento.nombre, "lote": l.numero_lote,
            "stock": l.cantidad, "caducidad": l.fecha_caducidad,
            "zona": getattr(l.medicamento, "zona_almacenaje", "General"),
            "abc": getattr(l.medicamento, "clasificacion_abc", "C"),
            "refrigeracion": getattr(l.medicamento, "requiere_refrigeracion", False),
            "controlado": getattr(l.medicamento, "controlado", False),
            "estado_bpa": estado_bpa, "dias_caducidad": dias,
        })
    return resultado

@app.get("/api/movimientos", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR", "QFR"]))])
def get_movimientos(db: Session = Depends(get_db)):
    return [{"fecha": m.fecha.strftime("%Y-%m-%d %H:%M"), "tipo": m.tipo,
             "medicamento": m.lote.medicamento.nombre if m.lote else "N/A",
             "lote": m.lote.numero_lote if m.lote else "N/A",
             "cantidad": m.cantidad, "destino_origen": m.destino_origen}
            for m in db.query(models.Movimiento).order_by(models.Movimiento.fecha.desc()).all()]

# ---------------------------------------------------------------------------
# ABC / BPA
# ---------------------------------------------------------------------------
@app.get("/api/abc", dependencies=[Depends(rol_requerido(ROLES_GESTION + ["QFR"]))])
def get_abc(db: Session = Depends(get_db)):
    calcular_abc(db)
    movs = db.query(models.Movimiento).filter(models.Movimiento.tipo == "SALIDA").all()
    ventas = {}
    for m in movs:
        if m.lote: ventas[m.lote.medicamento.nombre] = ventas.get(m.lote.medicamento.nombre, 0) + m.cantidad
    return sorted([{
        "id": c.id, "nombre": c.nombre, "clasificacion": c.clasificacion_abc,
        "zona": c.zona_almacenaje, "salidas_totales": ventas.get(c.nombre, 0),
        "refrigeracion": c.requiere_refrigeracion, "controlado": c.controlado,
        "temp_min": c.temp_min, "temp_max": c.temp_max,
    } for c in db.query(models.Catalogo).all()], key=lambda x: (x["clasificacion"], -x["salidas_totales"]))

@app.put("/api/catalogo/{catalogo_id}/bpa", dependencies=[Depends(rol_requerido(ROLES_GESTION + ["QFR"]))])
async def actualizar_bpa(catalogo_id: int, req: schemas.ActualizarCatalogoReq, db: Session = Depends(get_db)):
    cat = db.query(models.Catalogo).filter(models.Catalogo.id == catalogo_id).first()
    if not cat: raise HTTPException(status_code=404)
    if req.zona_almacenaje is not None: cat.zona_almacenaje = req.zona_almacenaje
    if req.temp_min is not None: cat.temp_min = req.temp_min
    if req.temp_max is not None: cat.temp_max = req.temp_max
    if req.requiere_refrigeracion is not None: cat.requiere_refrigeracion = req.requiere_refrigeracion
    if req.controlado is not None: cat.controlado = req.controlado
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

# ---------------------------------------------------------------------------
# FINANZAS
# ---------------------------------------------------------------------------
@app.post("/api/finanzas", dependencies=[Depends(rol_requerido(["ADMIN"]))])
async def post_fin(req: schemas.FinanzaReq, db: Session = Depends(get_db)):
    db.add(models.Finanza(tipo=req.tipo, monto=req.monto, concepto=req.concepto))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/finanzas", dependencies=[Depends(rol_requerido(["ADMIN"]))])
def get_fin(db: Session = Depends(get_db)):
    return [{"fecha": f.fecha.strftime("%Y-%m-%d %H:%M"), "tipo": f.tipo, "concepto": f.concepto, "monto": f.monto}
            for f in db.query(models.Finanza).order_by(models.Finanza.fecha.desc()).all()]

# ---------------------------------------------------------------------------
# USUARIOS
# ---------------------------------------------------------------------------
@app.post("/api/usuarios", dependencies=[Depends(rol_requerido(["ADMIN"]))])
async def post_usr(req: schemas.UsuarioReq, db: Session = Depends(get_db)):
    if db.query(models.Usuario).filter(models.Usuario.username == req.username).first():
        raise HTTPException(status_code=400, detail="Usuario ya existe")
    db.add(models.Usuario(username=req.username, password=obtener_hash(req.password),
                          rol=req.rol, farmacia_id=req.farmacia_id))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/usuarios", dependencies=[Depends(rol_requerido(ROLES_GESTION))])
def get_usr(db: Session = Depends(get_db)):
    return [{"username": u.username, "rol": u.rol, "farmacia_id": u.farmacia_id}
            for u in db.query(models.Usuario).all()]

@app.delete("/api/usuarios/{username}", dependencies=[Depends(rol_requerido(["ADMIN"]))])
async def del_usr(username: str, db: Session = Depends(get_db)):
    if username == "admin": raise HTTPException(status_code=403)
    u = db.query(models.Usuario).filter(models.Usuario.username == username).first()
    if not u: raise HTTPException(status_code=404)
    db.delete(u); db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

# ---------------------------------------------------------------------------
# PROVEEDORES
# ---------------------------------------------------------------------------
@app.post("/api/proveedores", dependencies=[Depends(rol_requerido(ROLES_GESTION))])
async def post_prov(req: schemas.ProveedorReq, db: Session = Depends(get_db)):
    db.add(models.Proveedor(nombre=req.nombre, contacto=req.contacto))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/proveedores", dependencies=[Depends(rol_requerido(ROLES_GESTION))])
def get_prov(db: Session = Depends(get_db)):
    return [{"id": p.id, "nombre": p.nombre, "contacto": p.contacto} for p in db.query(models.Proveedor).all()]

# ---------------------------------------------------------------------------
# COMPRAS
# ---------------------------------------------------------------------------
@app.post("/api/compras", dependencies=[Depends(rol_requerido(ROLES_GESTION))])
async def post_compra(req: schemas.OrdenReq, db: Session = Depends(get_db)):
    prov = db.query(models.Proveedor).filter(models.Proveedor.id == req.proveedor_id).first()
    if not prov: raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    db.add(models.OrdenCompra(proveedor_id=req.proveedor_id, medicamento=req.medicamento,
                              cantidad=req.cantidad, costo_total=req.costo_total))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/compras", dependencies=[Depends(rol_requerido(ROLES_GESTION))])
def get_compras(db: Session = Depends(get_db)):
    return [{"id": o.id, "fecha": o.fecha_orden.strftime("%Y-%m-%d %H:%M"),
             "proveedor": o.proveedor.nombre, "medicamento": o.medicamento,
             "cantidad": o.cantidad, "costo_total": o.costo_total, "estado": o.estado}
            for o in db.query(models.OrdenCompra).order_by(models.OrdenCompra.fecha_orden.desc()).all()]

@app.put("/api/compras/{orden_id}/recibir", dependencies=[Depends(rol_requerido(ROLES_GESTION))])
async def recibir_compra(orden_id: int, req: schemas.RecibirOrdenReq, db: Session = Depends(get_db)):
    orden = db.query(models.OrdenCompra).filter(models.OrdenCompra.id == orden_id).first()
    if not orden: raise HTTPException(status_code=404)
    if orden.estado == "COMPLETADA": raise HTTPException(status_code=400, detail="Orden ya recibida")
    cat = db.query(models.Catalogo).filter(models.Catalogo.nombre == orden.medicamento).first()
    if not cat:
        cat = models.Catalogo(nombre=orden.medicamento); db.add(cat); db.commit(); db.refresh(cat)
    lote = db.query(models.Lote).filter(models.Lote.numero_lote == req.numero_lote).first()
    if lote: lote.cantidad += orden.cantidad
    else:
        lote = models.Lote(numero_lote=req.numero_lote, catalogo_id=cat.id,
                           cantidad=orden.cantidad, fecha_caducidad=req.fecha_caducidad)
        db.add(lote)
    db.commit()
    db.add(models.Movimiento(lote_id=lote.id, tipo="ENTRADA", cantidad=orden.cantidad,
                             destino_origen=f"OC#{orden_id} - {orden.proveedor.nombre}"))
    db.add(models.Finanza(tipo="GASTO", monto=orden.costo_total,
                          concepto=f"OC#{orden_id} - {orden.medicamento} ({orden.proveedor.nombre})"))
    orden.estado = "COMPLETADA"
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

# ---------------------------------------------------------------------------
# FARMACIAS
# ---------------------------------------------------------------------------
@app.post("/api/farmacias", dependencies=[Depends(rol_requerido(["ADMIN"]))])
async def post_farmacia(req: schemas.FarmaciaReq, db: Session = Depends(get_db)):
    db.add(models.Farmacia(nombre=req.nombre, direccion=req.direccion, contacto=req.contacto))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/farmacias", dependencies=[Depends(verificar_token)])
def get_farmacias(db: Session = Depends(get_db)):
    return [{"id": f.id, "nombre": f.nombre, "direccion": f.direccion,
             "contacto": f.contacto, "activa": f.activa}
            for f in db.query(models.Farmacia).all()]

@app.delete("/api/farmacias/{farmacia_id}", dependencies=[Depends(rol_requerido(["ADMIN"]))])
async def del_farmacia(farmacia_id: int, db: Session = Depends(get_db)):
    f = db.query(models.Farmacia).filter(models.Farmacia.id == farmacia_id).first()
    if not f: raise HTTPException(status_code=404)
    f.activa = False
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

# ---------------------------------------------------------------------------
# PEDIDOS DE FARMACIA
# ---------------------------------------------------------------------------
@app.post("/api/pedidos")
async def crear_pedido(req: schemas.PedidoReq, user: dict = Depends(verificar_token), db: Session = Depends(get_db)):
    # Farmacia solo puede crear pedidos para su propia farmacia
    if user["rol"] == "FARMACIA" and user.get("farmacia_id") != req.farmacia_id:
        raise HTTPException(status_code=403, detail="Solo puedes crear pedidos para tu farmacia")
    farmacia = db.query(models.Farmacia).filter(models.Farmacia.id == req.farmacia_id).first()
    if not farmacia: raise HTTPException(status_code=404, detail="Farmacia no encontrada")
    pedido = models.PedidoFarmacia(
        farmacia_id=req.farmacia_id,
        fecha_entrega_estimada=req.fecha_entrega_estimada,
        notas=req.notas
    )
    db.add(pedido); db.commit(); db.refresh(pedido)
    for item in req.items:
        db.add(models.ItemPedido(pedido_id=pedido.id, medicamento=item.medicamento,
                                  cantidad_solicitada=item.cantidad_solicitada))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK", "pedido_id": pedido.id}

@app.get("/api/pedidos")
def get_pedidos(user: dict = Depends(verificar_token), db: Session = Depends(get_db)):
    query = db.query(models.PedidoFarmacia)
    # Farmacia solo ve sus propios pedidos
    if user["rol"] == "FARMACIA":
        query = query.filter(models.PedidoFarmacia.farmacia_id == user.get("farmacia_id"))
    # Rutero solo ve pedidos LISTOS o EN_RUTA
    elif user["rol"] == "RUTERO":
        query = query.filter(models.PedidoFarmacia.estado.in_(["LISTO", "EN_RUTA"]))
    pedidos = query.order_by(models.PedidoFarmacia.fecha_pedido.desc()).all()
    resultado = []
    for p in pedidos:
        resultado.append({
            "id": p.id,
            "farmacia": p.farmacia.nombre,
            "farmacia_id": p.farmacia_id,
            "estado": p.estado,
            "fecha_pedido": p.fecha_pedido.strftime("%Y-%m-%d %H:%M"),
            "fecha_entrega_estimada": str(p.fecha_entrega_estimada) if p.fecha_entrega_estimada else None,
            "notas": p.notas,
            "items": [{"medicamento": i.medicamento, "cantidad_solicitada": i.cantidad_solicitada,
                       "cantidad_surtida": i.cantidad_surtida, "estado": i.estado} for i in p.items],
            "picking": {"estado": p.picking.estado, "almacenista": p.picking.almacenista} if p.picking else None,
            "ruta": {"estado": p.ruta.estado, "rutero": p.ruta.rutero,
                     "temperatura_salida": p.ruta.temperatura_salida,
                     "temperatura_llegada": p.ruta.temperatura_llegada} if p.ruta else None,
        })
    return resultado

@app.put("/api/pedidos/{pedido_id}/cancelar")
async def cancelar_pedido(pedido_id: int, user: dict = Depends(verificar_token), db: Session = Depends(get_db)):
    p = db.query(models.PedidoFarmacia).filter(models.PedidoFarmacia.id == pedido_id).first()
    if not p: raise HTTPException(status_code=404)
    if user["rol"] == "FARMACIA" and p.farmacia_id != user.get("farmacia_id"):
        raise HTTPException(status_code=403)
    if p.estado not in ["PENDIENTE"]:
        raise HTTPException(status_code=400, detail="Solo se puede cancelar un pedido PENDIENTE")
    p.estado = "CANCELADO"
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

# ---------------------------------------------------------------------------
# PICKING LIST
# ---------------------------------------------------------------------------
@app.post("/api/pedidos/{pedido_id}/picking", dependencies=[Depends(rol_requerido(ROLES_CEDIS))])
async def generar_picking(pedido_id: int, db: Session = Depends(get_db)):
    pedido = db.query(models.PedidoFarmacia).filter(models.PedidoFarmacia.id == pedido_id).first()
    if not pedido: raise HTTPException(status_code=404)
    if pedido.estado != "PENDIENTE":
        raise HTTPException(status_code=400, detail="El pedido no está en estado PENDIENTE")
    if pedido.picking:
        raise HTTPException(status_code=400, detail="Ya existe un picking para este pedido")
    db.add(models.PickingList(pedido_id=pedido_id))
    pedido.estado = "EN_PICKING"
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.put("/api/pedidos/{pedido_id}/picking/completar", dependencies=[Depends(rol_requerido(ROLES_CEDIS))])
async def completar_picking(pedido_id: int, req: schemas.CompletarPickingReq, db: Session = Depends(get_db)):
    pedido = db.query(models.PedidoFarmacia).filter(models.PedidoFarmacia.id == pedido_id).first()
    if not pedido or not pedido.picking: raise HTTPException(status_code=404)
    hoy = datetime.utcnow().date()
    # Surtir cada item con FEFO
    for item in pedido.items:
        cat = db.query(models.Catalogo).filter(models.Catalogo.nombre == item.medicamento).first()
        if not cat:
            item.estado = "SIN_STOCK"; continue
        lotes = db.query(models.Lote).filter(
            models.Lote.catalogo_id == cat.id, models.Lote.cantidad > 0,
            models.Lote.fecha_caducidad >= hoy
        ).order_by(models.Lote.fecha_caducidad).all()
        disponible = sum(l.cantidad for l in lotes)
        if disponible == 0:
            item.estado = "SIN_STOCK"; continue
        cant = min(item.cantidad_solicitada, disponible)
        item.cantidad_surtida = cant
        restante = cant
        for l in lotes:
            if restante <= 0: break
            t = min(l.cantidad, restante); l.cantidad -= t; restante -= t
            db.add(models.Movimiento(lote_id=l.id, tipo="SALIDA", cantidad=t,
                                     destino_origen=f"Pedido#{pedido_id} - {pedido.farmacia.nombre}"))
        item.estado = "SURTIDO" if item.cantidad_surtida >= item.cantidad_solicitada else "PARCIAL"
    pedido.picking.almacenista = req.almacenista
    pedido.picking.estado = "COMPLETADO"
    pedido.picking.fecha_completado = datetime.utcnow()
    pedido.estado = "LISTO"
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

# ---------------------------------------------------------------------------
# RUTAS DE ENTREGA
# ---------------------------------------------------------------------------
@app.post("/api/pedidos/{pedido_id}/ruta/salida", dependencies=[Depends(rol_requerido(ROLES_CEDIS + ["RUTERO"]))])
async def salida_ruta(pedido_id: int, req: schemas.SalidaRutaReq, db: Session = Depends(get_db)):
    pedido = db.query(models.PedidoFarmacia).filter(models.PedidoFarmacia.id == pedido_id).first()
    if not pedido: raise HTTPException(status_code=404)
    if pedido.estado != "LISTO":
        raise HTTPException(status_code=400, detail="El pedido debe estar LISTO para salir")
    db.add(models.RutaEntrega(pedido_id=pedido_id, rutero=req.rutero,
                              estado="EN_RUTA", fecha_salida=datetime.utcnow(),
                              temperatura_salida=req.temperatura_salida))
    pedido.estado = "EN_RUTA"
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.put("/api/pedidos/{pedido_id}/ruta/entregar", dependencies=[Depends(rol_requerido(ROLES_CEDIS + ["RUTERO", "FARMACIA"]))])
async def confirmar_entrega(pedido_id: int, req: schemas.ConfirmarEntregaReq, db: Session = Depends(get_db)):
    pedido = db.query(models.PedidoFarmacia).filter(models.PedidoFarmacia.id == pedido_id).first()
    if not pedido or not pedido.ruta: raise HTTPException(status_code=404)
    if pedido.estado != "EN_RUTA":
        raise HTTPException(status_code=400, detail="El pedido no está EN_RUTA")
    pedido.ruta.estado = "ENTREGADO"
    pedido.ruta.fecha_entrega = datetime.utcnow()
    pedido.ruta.temperatura_llegada = req.temperatura_llegada
    pedido.ruta.notas_entrega = req.notas_entrega
    pedido.estado = "ENTREGADO"
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.put("/api/pedidos/{pedido_id}/ruta/rechazar", dependencies=[Depends(rol_requerido(ROLES_CEDIS + ["RUTERO", "FARMACIA"]))])
async def rechazar_entrega(pedido_id: int, req: schemas.RechazarEntregaReq, db: Session = Depends(get_db)):
    pedido = db.query(models.PedidoFarmacia).filter(models.PedidoFarmacia.id == pedido_id).first()
    if not pedido or not pedido.ruta: raise HTTPException(status_code=404)
    pedido.ruta.estado = "RECHAZADO"
    pedido.ruta.notas_entrega = req.notas_entrega
    pedido.estado = "LISTO"  # Regresa a LISTO para reenvío
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

# ---------------------------------------------------------------------------
# DEVOLUCIONES
# ---------------------------------------------------------------------------
@app.post("/api/devoluciones")
async def crear_devolucion(req: schemas.DevolucionReq, user: dict = Depends(verificar_token), db: Session = Depends(get_db)):
    if user["rol"] == "FARMACIA" and user.get("farmacia_id") != req.farmacia_id:
        raise HTTPException(status_code=403)
    db.add(models.Devolucion(
        farmacia_id=req.farmacia_id, medicamento=req.medicamento,
        numero_lote=req.numero_lote, cantidad=req.cantidad,
        motivo=req.motivo, destino=req.destino
    ))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/devoluciones", dependencies=[Depends(rol_requerido(ROLES_GESTION + ["QFR"]))])
def get_devoluciones(db: Session = Depends(get_db)):
    return [{"id": d.id, "farmacia": d.farmacia.nombre, "medicamento": d.medicamento,
             "lote": d.numero_lote, "cantidad": d.cantidad, "motivo": d.motivo,
             "destino": d.destino, "estado": d.estado,
             "fecha": d.fecha.strftime("%Y-%m-%d %H:%M"), "aprobado_por": d.aprobado_por}
            for d in db.query(models.Devolucion).order_by(models.Devolucion.fecha.desc()).all()]

@app.put("/api/devoluciones/{dev_id}/resolver", dependencies=[Depends(rol_requerido(ROLES_QFR))])
async def resolver_devolucion(dev_id: int, req: schemas.AprobarDevolucionReq,
                               user: dict = Depends(verificar_token), db: Session = Depends(get_db)):
    dev = db.query(models.Devolucion).filter(models.Devolucion.id == dev_id).first()
    if not dev: raise HTTPException(status_code=404)
    if req.aprobado:
        dev.estado = "APROBADA"
        dev.aprobado_por = user["sub"]
        if dev.destino == "RESTOCK":
            # Reintegrar al inventario
            cat = db.query(models.Catalogo).filter(models.Catalogo.nombre == dev.medicamento).first()
            if cat:
                lote = db.query(models.Lote).filter(models.Lote.numero_lote == dev.numero_lote).first()
                if lote:
                    lote.cantidad += dev.cantidad
                    db.add(models.Movimiento(lote_id=lote.id, tipo="ENTRADA", cantidad=dev.cantidad,
                                             destino_origen=f"Devolución#{dev_id} - {dev.farmacia.nombre}"))
        elif dev.destino == "CUARENTENA":
            db.add(models.LoteCuarentena(numero_lote=dev.numero_lote, medicamento=dev.medicamento,
                                          cantidad=dev.cantidad, motivo="DEVOLUCION",
                                          notas=f"Devolución#{dev_id} de {dev.farmacia.nombre}"))
    else:
        dev.estado = "RECHAZADA"
        dev.aprobado_por = user["sub"]
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

# ---------------------------------------------------------------------------
# CUARENTENA
# ---------------------------------------------------------------------------
@app.post("/api/cuarentena", dependencies=[Depends(rol_requerido(ROLES_CEDIS))])
async def agregar_cuarentena(req: schemas.CuarentenaReq, db: Session = Depends(get_db)):
    db.add(models.LoteCuarentena(numero_lote=req.numero_lote, medicamento=req.medicamento,
                                  cantidad=req.cantidad, motivo=req.motivo, notas=req.notas))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/cuarentena", dependencies=[Depends(rol_requerido(ROLES_CEDIS + ["QFR"]))])
def get_cuarentena(db: Session = Depends(get_db)):
    return [{"id": c.id, "numero_lote": c.numero_lote, "medicamento": c.medicamento,
             "cantidad": c.cantidad, "motivo": c.motivo, "estado": c.estado,
             "fecha_ingreso": c.fecha_ingreso.strftime("%Y-%m-%d %H:%M"),
             "resuelto_por": c.resuelto_por, "notas": c.notas}
            for c in db.query(models.LoteCuarentena).order_by(models.LoteCuarentena.fecha_ingreso.desc()).all()]

@app.put("/api/cuarentena/{cuar_id}/resolver", dependencies=[Depends(rol_requerido(ROLES_QFR))])
async def resolver_cuarentena(cuar_id: int, req: schemas.ResolverCuarentenaReq,
                               user: dict = Depends(verificar_token), db: Session = Depends(get_db)):
    c = db.query(models.LoteCuarentena).filter(models.LoteCuarentena.id == cuar_id).first()
    if not c: raise HTTPException(status_code=404)
    if c.estado != "EN_REVISION":
        raise HTTPException(status_code=400, detail="Ya fue resuelto")
    c.estado = req.decision  # APROBADO o RECHAZADO
    c.resuelto_por = user["sub"]
    c.fecha_resolucion = datetime.utcnow()
    c.notas = req.notas
    if req.decision == "APROBADO":
        # Pasar al stock activo
        cat = db.query(models.Catalogo).filter(models.Catalogo.nombre == c.medicamento).first()
        if not cat:
            cat = models.Catalogo(nombre=c.medicamento); db.add(cat); db.commit(); db.refresh(cat)
        lote = db.query(models.Lote).filter(models.Lote.numero_lote == c.numero_lote).first()
        if lote:
            lote.cantidad += c.cantidad
        else:
            lote = models.Lote(numero_lote=c.numero_lote, catalogo_id=cat.id,
                                cantidad=c.cantidad, fecha_caducidad=datetime.utcnow().date())
            db.add(lote)
        db.commit()
        db.add(models.Movimiento(lote_id=lote.id, tipo="ENTRADA", cantidad=c.cantidad,
                                  destino_origen=f"Cuarentena#{cuar_id} aprobada por QFR"))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

# ---------------------------------------------------------------------------
# FRONTEND
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    with open("index.html", "r", encoding="utf-8") as f: return f.read()
