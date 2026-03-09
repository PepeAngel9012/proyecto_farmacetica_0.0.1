from fastapi import FastAPI, HTTPException, Depends, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import jwt
import models, schemas
from database import engine, get_db
from passlib.context import CryptContext # Para encriptación segura

SECRET_KEY = "nexus_secret_2026"
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

models.Base.metadata.create_all(bind=engine)
app = FastAPI(title="Nexus ERP")

# --- UTILIDADES DE SEGURIDAD ---
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

@app.on_event("startup")
def startup():
    db = next(get_db())
    if not db.query(models.Usuario).filter(models.Usuario.username == "admin").first():
        # Admin inicial con contraseña encriptada
        db.add(models.Usuario(username="admin", password=obtener_hash("123"), rol="ADMIN"))
        db.commit()

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: manager.disconnect(ws)

# --- AUTH & DASHBOARD ---
@app.post("/api/login")
def login(req: schemas.LoginReq, db: Session = Depends(get_db)):
    u = db.query(models.Usuario).filter(models.Usuario.username==req.username).first()
    if not u or not verificar_password(req.password, u.password): 
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    token = jwt.encode({"sub": u.username, "rol": u.rol, "exp": datetime.utcnow()+timedelta(hours=8)}, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "rol": u.rol, "username": u.username}

@app.get("/api/dashboard", dependencies=[Depends(verificar_token)])
def get_dash(db: Session = Depends(get_db)):
    ing = sum(f.monto for f in db.query(models.Finanza).filter(models.Finanza.tipo=="INGRESO").all()) or 0
    gas = sum(f.monto for f in db.query(models.Finanza).filter(models.Finanza.tipo=="GASTO").all()) or 0
    lotes = db.query(models.Lote).filter(models.Lote.cantidad > 0).all()
    resumen = {}
    for l in lotes: resumen[l.medicamento.nombre] = resumen.get(l.medicamento.nombre, 0) + l.cantidad
    alertas = [{"medicamento": m, "stock": s} for m, s in resumen.items() if s < 10]
    
    movs = db.query(models.Movimiento).filter(models.Movimiento.tipo == "SALIDA").all()
    ventas = {}
    for m in movs:
        n = m.lote.medicamento.nombre if m.lote else "N/A"
        ventas[n] = ventas.get(n, 0) + m.cantidad
    top = [{"nombre": k, "ventas": v} for k, v in sorted(ventas.items(), key=lambda x: x[1], reverse=True)[:5]]

    return {
        "total_lotes": len(lotes), "ingresos": ing, "gastos": gas, "utilidad": ing - gas,
        "en_riesgo": db.query(models.Lote).filter(models.Lote.cantidad > 0, models.Lote.fecha_caducidad <= datetime.utcnow().date() + timedelta(days=30)).count(),
        "alertas_stock": alertas, "top_productos": top
    }

# --- ALMACÉN ---
@app.post("/api/entradas")
async def entrada(req: schemas.EntradaReq, db: Session = Depends(get_db)):
    cat = db.query(models.Catalogo).filter(models.Catalogo.nombre==req.nombre_medicamento).first()
    if not cat: cat = models.Catalogo(nombre=req.nombre_medicamento); db.add(cat); db.commit(); db.refresh(cat)
    lote = db.query(models.Lote).filter(models.Lote.numero_lote == req.numero_lote).first()
    if lote: lote.cantidad += req.cantidad
    else: lote = models.Lote(numero_lote=req.numero_lote, catalogo_id=cat.id, cantidad=req.cantidad, fecha_caducidad=req.fecha_caducidad); db.add(lote)
    db.commit(); db.add(models.Movimiento(lote_id=lote.id, tipo="ENTRADA", cantidad=req.cantidad, destino_origen=req.origen)); db.commit()
    await manager.broadcast("update"); return {"msg": "OK"}

@app.post("/api/salidas")
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

@app.get("/api/inventario")
def inv(db: Session = Depends(get_db)):
    return [{"medicamento": l.medicamento.nombre, "lote": l.numero_lote, "stock": l.cantidad, "caducidad": l.fecha_caducidad} for l in db.query(models.Lote).filter(models.Lote.cantidad > 0).all()]

# --- FINANZAS & USUARIOS ---
@app.post("/api/finanzas", dependencies=[Depends(rol_requerido(["ADMIN"]))])
async def post_fin(req: schemas.FinanzaReq, db: Session = Depends(get_db)):
    db.add(models.Finanza(tipo=req.tipo, monto=req.monto, concepto=req.concepto)); db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/api/finanzas", dependencies=[Depends(rol_requerido(["ADMIN"]))])
def get_fin(db: Session = Depends(get_db)):
    return db.query(models.Finanza).order_by(models.Finanza.fecha.desc()).all()

@app.post("/api/usuarios", dependencies=[Depends(rol_requerido(["ADMIN"]))])
async def post_usr(req: schemas.UsuarioReq, db: Session = Depends(get_db)):
    db.add(models.Usuario(username=req.username, password=obtener_hash(req.password), rol=req.rol))
    db.commit(); await manager.broadcast("update"); return {"msg": "OK"}

@app.get("/", response_class=HTMLResponse)
def index():
    with open("index.html", "r", encoding="utf-8") as f: return f.read()