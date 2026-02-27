from fastapi import FastAPI, HTTPException, Depends, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import jwt
import models, schemas
from database import engine, get_db, Base

SECRET_KEY = "fenix_secret_2026"
ALGORITHM = "HS256"

models.Base.metadata.create_all(bind=engine)
app = FastAPI(title="Fénix ERP - SCM Integrado")

# --- SINCRONIZACIÓN EN TIEMPO REAL ---
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

# --- SEGURIDAD ---
def verificar_token(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try: return jwt.decode(authorization.split(" ")[1], SECRET_KEY, algorithms=[ALGORITHM])
    except: raise HTTPException(status_code=401)

def rol_requerido(roles: list):
    def verificador(user: dict = Depends(verificar_token)):
        if user.get("rol") not in roles: raise HTTPException(status_code=403)
        return user
    return verificador

@app.on_event("startup")
def startup():
    db = next(get_db())
    if not db.query(models.Usuario).filter(models.Usuario.username == "admin").first():
        db.add(models.Usuario(username="admin", password="123", rol="ADMIN")); db.commit()

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: manager.disconnect(ws)

# --- AUTH & DASHBOARD ---
@app.post("/api/login")
def login(req: schemas.LoginReq, db: Session = Depends(get_db)):
    u = db.query(models.Usuario).filter(models.Usuario.username==req.username, models.Usuario.password==req.password).first()
    if not u: raise HTTPException(status_code=401)
    token = jwt.encode({"sub": u.username, "rol": u.rol, "exp": datetime.utcnow()+timedelta(hours=8)}, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "rol": u.rol, "username": u.username}

@app.get("/api/dashboard", dependencies=[Depends(verificar_token)])
def get_dash(db: Session = Depends(get_db)):
    # Cálculos base
    total_lotes = db.query(models.Lote).filter(models.Lote.cantidad > 0).count()
    ingresos = sum(f.monto for f in db.query(models.Finanza).filter(models.Finanza.tipo=="INGRESO").all()) or 0
    gastos = sum(f.monto for f in db.query(models.Finanza).filter(models.Finanza.tipo=="GASTO").all()) or 0
    utilidad = ingresos - gastos # Cálculo de utilidad neta
    
    en_riesgo = db.query(models.Lote).filter(models.Lote.cantidad > 0, models.Lote.fecha_caducidad <= datetime.utcnow().date() + timedelta(days=30)).count()

    # NUEVO: Inteligencia de Ventas (Best Sellers)
    # Analizamos las SALIDAS en el Kárdex para ver qué se mueve más
    movimientos = db.query(models.Movimiento).filter(models.Movimiento.tipo == "SALIDA").all()
    conteo_ventas = {}
    for m in movimientos:
        nombre = m.lote.medicamento.nombre if m.lote else "Desconocido"
        conteo_ventas[nombre] = conteo_ventas.get(nombre, 0) + m.cantidad
    
    # Ordenar y tomar los 5 más vendidos
    best_sellers = sorted(conteo_ventas.items(), key=lambda x: x[1], reverse=True)[:5]
    top_productos = [{"nombre": n, "ventas": v} for n, v in best_sellers]

    # Alertas de stock bajo (se mantiene de la fase anterior)
    inventario = db.query(models.Lote).filter(models.Lote.cantidad > 0).all()
    resumen_stock = {}
    for l in inventario:
        resumen_stock[l.medicamento.nombre] = resumen_stock.get(l.medicamento.nombre, 0) + l.cantidad
    alertas = [{"medicamento": m, "stock": s} for m, s in resumen_stock.items() if s < 10]

    return {
        "total_lotes": total_lotes, 
        "ingresos": ingresos, 
        "gastos": gastos, 
        "utilidad": utilidad,
        "en_riesgo": en_riesgo,
        "alertas_stock": alertas,
        "top_productos": top_productos
    }

# --- ALMACÉN (WMS) ---
@app.post("/api/entradas", dependencies=[Depends(verificar_token)])
async def entrada(req: schemas.EntradaReq, db: Session = Depends(get_db)):
    cat = db.query(models.Catalogo).filter(models.Catalogo.nombre==req.nombre_medicamento).first()
    if not cat: cat = models.Catalogo(nombre=req.nombre_medicamento); db.add(cat); db.commit(); db.refresh(cat)
    lote = db.query(models.Lote).filter(models.Lote.numero_lote == req.numero_lote).first()
    if lote: lote.cantidad += req.cantidad
    else: lote = models.Lote(numero_lote=req.numero_lote, catalogo_id=cat.id, cantidad=req.cantidad, fecha_caducidad=req.fecha_caducidad); db.add(lote)
    db.commit(); db.add(models.Movimiento(lote_id=lote.id, tipo="ENTRADA", cantidad=req.cantidad, destino_origen=req.origen)); db.commit()
    await manager.broadcast("update"); return {"msg": "OK"}

@app.post("/api/salidas", dependencies=[Depends(verificar_token)])
async def salida(req: schemas.SalidaReq, db: Session = Depends(get_db)):
    cat = db.query(models.Catalogo).filter(models.Catalogo.nombre == req.nombre_medicamento).first()
    if not cat: raise HTTPException(status_code=404)
    lotes = db.query(models.Lote).filter(models.Lote.catalogo_id == cat.id, models.Lote.cantidad > 0).order_by(models.Lote.fecha_caducidad).all()
    if sum(l.cantidad for l in lotes) < req.cantidad_requerida: raise HTTPException(status_code=400)
    cant = req.cantidad_requerida
    for l in lotes:
        if cant <= 0: break
        t = min(l.cantidad, cant); l.cantidad -= t; cant -= t
        db.add(models.Movimiento(lote_id=l.id, tipo="SALIDA", cantidad=t, destino_origen=req.destino))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/inventario", dependencies=[Depends(verificar_token)])
def inv(db: Session = Depends(get_db)):
    return [{"medicamento": l.medicamento.nombre, "lote": l.numero_lote, "stock": l.cantidad, "caducidad": l.fecha_caducidad} for l in db.query(models.Lote).filter(models.Lote.cantidad > 0).all()]

@app.get("/api/movimientos", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
def get_movs(db: Session = Depends(get_db)):
    movs = db.query(models.Movimiento).order_by(models.Movimiento.fecha.desc()).limit(100).all()
    return [{"fecha": m.fecha.strftime("%Y-%m-%d %H:%M"), "tipo": m.tipo, "medicamento": m.lote.medicamento.nombre if m.lote else "N/A", "lote": m.lote.numero_lote if m.lote else "N/A", "cantidad": m.cantidad, "destino_origen": m.destino_origen} for m in movs]

# --- SCM (PROVEEDORES Y COMPRAS) ---
@app.post("/api/proveedores", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
async def post_prov(req: schemas.ProveedorReq, db: Session = Depends(get_db)):
    db.add(models.Proveedor(nombre=req.nombre, contacto=req.contacto)); db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/proveedores", dependencies=[Depends(verificar_token)])
def get_provs(db: Session = Depends(get_db)):
    return [{"id": p.id, "nombre": p.nombre, "contacto": p.contacto} for p in db.query(models.Proveedor).all()]

@app.post("/api/compras", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
async def crear_oc(req: schemas.OrdenReq, db: Session = Depends(get_db)):
    db.add(models.OrdenCompra(proveedor_id=req.proveedor_id, medicamento=req.medicamento, cantidad=req.cantidad, costo_total=req.costo_total))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/compras", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
def get_ocs(db: Session = Depends(get_db)):
    return [{"id": o.id, "proveedor": o.proveedor.nombre if o.proveedor else "N/A", "medicamento": o.medicamento, "cantidad": o.cantidad, "costo_total": o.costo_total, "estado": o.estado, "fecha": o.fecha_orden.strftime("%Y-%m-%d")} for o in db.query(models.OrdenCompra).all()]

@app.put("/api/compras/{id}/recibir", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
async def recibir_oc(id: int, req: schemas.RecibirOrdenReq, db: Session = Depends(get_db)):
    oc = db.query(models.OrdenCompra).filter(models.OrdenCompra.id == id, models.OrdenCompra.estado == "PENDIENTE").first()
    if not oc: raise HTTPException(status_code=404)
    oc.estado = "COMPLETADA"
    db.add(models.Finanza(tipo="GASTO", monto=oc.costo_total, concepto=f"Compra OC#{oc.id}"))
    cat = db.query(models.Catalogo).filter(models.Catalogo.nombre == oc.medicamento).first()
    if not cat: cat = models.Catalogo(nombre=oc.medicamento); db.add(cat); db.commit(); db.refresh(cat)
    lote = models.Lote(numero_lote=req.numero_lote, catalogo_id=cat.id, cantidad=oc.cantidad, fecha_caducidad=req.fecha_caducidad); db.add(lote); db.commit()
    db.add(models.Movimiento(lote_id=lote.id, tipo="ENTRADA", cantidad=oc.cantidad, destino_origen=f"Compra OC#{oc.id}")); db.commit()
    await manager.broadcast("update"); return {"msg": "OK"}

# --- FINANZAS Y USUARIOS ---
@app.post("/api/finanzas", dependencies=[Depends(rol_requerido(["ADMIN"]))])
async def post_fin(req: schemas.FinanzaReq, db: Session = Depends(get_db)):
    db.add(models.Finanza(tipo=req.tipo, monto=req.monto, concepto=req.concepto)); db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/finanzas", dependencies=[Depends(rol_requerido(["ADMIN"]))])
def get_fin(db: Session = Depends(get_db)):
    return db.query(models.Finanza).order_by(models.Finanza.fecha.desc()).all()

@app.post("/api/usuarios", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
async def post_usr(req: schemas.UsuarioReq, db: Session = Depends(get_db)):
    db.add(models.Usuario(username=req.username, password=req.password, rol=req.rol)); db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/usuarios", dependencies=[Depends(rol_requerido(["ADMIN", "SUPERVISOR"]))])
def get_usrs(db: Session = Depends(get_db)):
    return [{"username": u.username, "rol": u.rol} for u in db.query(models.Usuario).all()]

@app.delete("/api/usuarios/{u}", dependencies=[Depends(rol_requerido(["ADMIN"]))])
async def del_usr(u: str, db: Session = Depends(get_db)):
    usr = db.query(models.Usuario).filter(models.Usuario.username == u).first()
    if usr and usr.username != 'admin': db.delete(usr); db.commit(); await manager.broadcast("update")
    return {"msg": "OK"}

@app.get("/", response_class=HTMLResponse)
def index():
    with open("index.html", "r", encoding="utf-8") as f: return f.read()