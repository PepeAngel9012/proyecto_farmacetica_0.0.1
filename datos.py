"""
datos.py — Seed de datos de demostración para Nexus ERP v2.0
Ejecutar: python datos.py
O dentro del contenedor: sudo docker exec -it nexus_web python datos.py
"""

import os, sys, time
from datetime import datetime, date, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext

# ── Esperar a que la DB esté lista ──────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://nexus_admin:nexus_password123@localhost:5432/nexus_db")
engine = create_engine(DATABASE_URL)

print("⏳  Conectando a la base de datos...")
for intento in range(15):
    try:
        with engine.connect() as c: c.execute(text("SELECT 1"))
        print("✅  Conexión establecida.")
        break
    except Exception as e:
        print(f"   Reintento {intento+1}/15 — {e}")
        time.sleep(2)

# ── Importar modelos ─────────────────────────────────────────────────────────
sys.path.insert(0, "/app")
try:
    import models
    from database import Base
except ImportError:
    # Ejecución local
    from database import Base, engine as eng
    import models

Base.metadata.create_all(bind=engine)
Session = sessionmaker(bind=engine)
db = Session()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def h(p): return pwd_context.hash(p)

hoy = date.today()

print("\n🌱  Iniciando carga de datos de demostración...\n")

# ════════════════════════════════════════════════════════════════════════════
# 1. LIMPIAR DATOS PREVIOS (orden inverso por FK)
# ════════════════════════════════════════════════════════════════════════════
print("🗑️   Limpiando datos previos...")
for tabla in ["lotes_cuarentena","devoluciones","rutas_entrega","picking_lists",
              "items_pedido","pedidos_farmacia","movimientos","lotes","catalogo",
              "ordenes_compra","proveedores","finanzas","usuarios","farmacias"]:
    try:
        db.execute(text(f"DELETE FROM {tabla}"))
        db.execute(text(f"ALTER SEQUENCE IF EXISTS {tabla}_id_seq RESTART WITH 1"))
    except Exception as e:
        db.rollback()
        print(f"   ⚠️  {tabla}: {e}")
db.commit()
print("   ✅  Limpieza completada.\n")

# ════════════════════════════════════════════════════════════════════════════
# 2. FARMACIAS
# ════════════════════════════════════════════════════════════════════════════
print("🏪  Creando farmacias...")
farmacias_data = [
    ("Farmacia Zona Río",         "Blvd. Sánchez Taboada 10488, Zona Río, Tijuana, BC",          "Dr. Carlos Mendoza — 664-123-4567"),
    ("Farmacia La Mesa",          "Blvd. Díaz Ordaz 1250, Col. La Mesa, Tijuana, BC",            "Lic. Ana Torres — 664-234-5678"),
    ("Farmacia Playas TJ",        "Paseo Ensenada 480, Playas de Tijuana, BC",                   "Dra. Patricia Ruiz — 664-345-6789"),
    ("Farmacia Otay",             "Blvd. Insurgentes 13579, Col. Otay Universidad, Tijuana, BC", "Dr. Jorge Salinas — 664-456-7890"),
    ("Farmacia El Florido",       "Av. El Florido 2345, Fracc. El Florido, Tijuana, BC",         "Lic. Sofía Herrera — 664-567-8901"),
    ("Farmacia Garita Otay",      "Calle Internacional 890, Col. Garita Otay, Tijuana, BC",      "Dr. Miguel Ángel Vega — 664-678-9012"),
]
farmacias = []
for nom, dir_, con in farmacias_data:
    f = models.Farmacia(nombre=nom, direccion=dir_, contacto=con)
    db.add(f); db.flush(); farmacias.append(f)
db.commit()
print(f"   ✅  {len(farmacias)} farmacias creadas.\n")

# ════════════════════════════════════════════════════════════════════════════
# 3. USUARIOS
# ════════════════════════════════════════════════════════════════════════════
print("👥  Creando usuarios...")
usuarios_data = [
    ("admin",        "123",        "ADMIN",      None),
    ("supervisor1",  "nexus2026",  "SUPERVISOR", None),
    ("operador1",    "nexus2026",  "OPERADOR",   None),
    ("operador2",    "nexus2026",  "OPERADOR",   None),
    ("qfr_drlopez",  "nexus2026",  "QFR",        None),
    ("rutero_juan",  "nexus2026",  "RUTERO",     None),
    ("rutero_pedro", "nexus2026",  "RUTERO",     None),
    ("farm_zonario",  "nexus2026",  "FARMACIA",   1),
    ("farm_lamesa",   "nexus2026",  "FARMACIA",   2),
    ("farm_playas",   "nexus2026",  "FARMACIA",   3),
    ("farm_otay",     "nexus2026",  "FARMACIA",   4),
]
for uname, pwd, rol, fid in usuarios_data:
    u = models.Usuario(username=uname, password=h(pwd), rol=rol, farmacia_id=fid)
    db.add(u)
db.commit()
print(f"   ✅  {len(usuarios_data)} usuarios creados.\n")
print("   📋  Credenciales de acceso:")
print("   ┌──────────────────┬──────────────┬────────────┬─────────────────────┐")
print("   │ Usuario          │ Contraseña   │ Rol        │ Nota                │")
print("   ├──────────────────┼──────────────┼────────────┼─────────────────────┤")
for uname, pwd, rol, fid in usuarios_data:
    nota = f"Farmacia #{fid}" if fid else "—"
    print(f"   │ {uname:<16} │ {pwd:<12} │ {rol:<10} │ {nota:<19} │")
print("   └──────────────────┴──────────────┴────────────┴─────────────────────┘\n")

# ════════════════════════════════════════════════════════════════════════════
# 4. CATÁLOGO + LOTES
# ════════════════════════════════════════════════════════════════════════════
print("💊  Creando catálogo de medicamentos y lotes...")

medicamentos = [
    # (nombre, zona, temp_min, temp_max, refrig, controlado, abc, lotes)
    # lotes = [(numero, cantidad, dias_a_vencer)]

    # ── CLASE A — Alta rotación ───────────────────────────────────────────
    ("Paracetamol 500mg Tab",       "Zona-A (Acceso Inmediato)", 15, 25, False, False, "A", [
        ("PARA-2024-001", 850, 180), ("PARA-2024-002", 620, 90), ("PARA-2024-003", 400, 20)]),
    ("Amoxicilina 500mg Cap",       "Zona-A (Acceso Inmediato)", 15, 25, False, False, "A", [
        ("AMOX-2024-001", 700, 200), ("AMOX-2024-002", 450, 60)]),
    ("Ibuprofeno 400mg Tab",        "Zona-A (Acceso Inmediato)", 15, 25, False, False, "A", [
        ("IBU-2024-001", 920, 300), ("IBU-2024-002", 380, 45)]),
    ("Omeprazol 20mg Cap",          "Zona-A (Acceso Inmediato)", 15, 25, False, False, "A", [
        ("OME-2024-001", 650, 240), ("OME-2024-002", 310, 35)]),
    ("Metformina 850mg Tab",        "Zona-A (Acceso Inmediato)", 15, 25, False, False, "A", [
        ("MET-2024-001", 800, 180), ("MET-2024-002", 500, 75)]),
    ("Atorvastatina 20mg Tab",      "Zona-A (Acceso Inmediato)", 15, 25, False, False, "A", [
        ("ATOR-2024-001", 550, 210), ("ATOR-2024-002", 290, 50)]),
    ("Losartán 50mg Tab",           "Zona-A (Acceso Inmediato)", 15, 25, False, False, "A", [
        ("LOS-2024-001", 480, 195), ("LOS-2024-002", 320, 80)]),
    ("Azitromicina 500mg Tab",      "Zona-A (Acceso Inmediato)", 15, 25, False, False, "A", [
        ("AZI-2024-001", 400, 150), ("AZI-2024-002", 200, 30)]),

    # ── CLASE B — Media rotación ──────────────────────────────────────────
    ("Insulina Glargina 100UI/mL",  "Refrigeración",            2,  8,  True,  False, "B", [
        ("INS-2024-001", 150, 120), ("INS-2024-002", 90, 25)]),
    ("Warfarina 5mg Tab",           "Zona-B (Media Rotación)",  15, 25, False, False, "B", [
        ("WAR-2024-001", 300, 160), ("WAR-2024-002", 180, 55)]),
    ("Enalapril 10mg Tab",          "Zona-B (Media Rotación)",  15, 25, False, False, "B", [
        ("ENA-2024-001", 420, 175), ("ENA-2024-002", 210, 40)]),
    ("Levotiroxina 50mcg Tab",      "Zona-B (Media Rotación)",  15, 25, False, False, "B", [
        ("LEVO-2024-001", 350, 200), ("LEVO-2024-002", 160, 65)]),
    ("Ciprofloxacino 500mg Tab",    "Zona-B (Media Rotación)",  15, 25, False, False, "B", [
        ("CIPRO-2024-001", 280, 140), ("CIPRO-2024-002", 120, 28)]),
    ("Metronidazol 500mg Tab",      "Zona-B (Media Rotación)",  15, 25, False, False, "B", [
        ("METRO-2024-001", 340, 165)]),
    ("Amlodipino 5mg Tab",          "Zona-B (Media Rotación)",  15, 25, False, False, "B", [
        ("AML-2024-001", 380, 190), ("AML-2024-002", 190, 70)]),
    ("Prednisona 5mg Tab",          "Zona-B (Media Rotación)",  15, 25, False, False, "B", [
        ("PRED-2024-001", 260, 155), ("PRED-2024-002", 130, 42)]),

    # ── CLASE C — Baja rotación ───────────────────────────────────────────
    ("Alprazolam 0.5mg Tab",        "Controlados (Seguridad)",  15, 25, False, True,  "C", [
        ("ALP-2024-001", 200, 300), ("ALP-2024-002", 100, 120)]),
    ("Morfina 10mg/mL Iny",         "Controlados (Seguridad)",  15, 25, False, True,  "C", [
        ("MOR-2024-001", 80, 365)]),
    ("Tramadol 100mg Cap",          "Controlados (Seguridad)",  15, 25, False, True,  "C", [
        ("TRAM-2024-001", 150, 270), ("TRAM-2024-002", 75, 90)]),
    ("Vacuna Influenza 0.5mL",      "Refrigeración",            2,  8,  True,  False, "C", [
        ("VAC-2024-001", 60, 180)]),
    ("Eritropoyetina 4000UI Iny",   "Refrigeración",            2,  8,  True,  False, "C", [
        ("EPO-2024-001", 40, 90)]),
    ("Clonazepam 2mg Tab",          "Controlados (Seguridad)",  15, 25, False, True,  "C", [
        ("CLO-2024-001", 180, 240), ("CLO-2024-002", 90, 60)]),
    ("Dexametasona 4mg/mL Iny",     "Zona-C (Baja Rotación)",   15, 25, False, False, "C", [
        ("DEX-2024-001", 120, 210)]),
    ("Ranitidina 150mg Tab",        "Zona-C (Baja Rotación)",   15, 25, False, False, "C", [
        ("RAN-2024-001", 220, 180)]),
    ("Furosemida 40mg Tab",         "Zona-C (Baja Rotación)",   15, 25, False, False, "C", [
        ("FUR-2024-001", 300, 195), ("FUR-2024-002", 150, 15)]),  # uno casi vencido
]

lotes_creados = []
for med in medicamentos:
    nom, zona, tmin, tmax, ref, ctrl, abc, lotes = med
    cat = models.Catalogo(nombre=nom, zona_almacenaje=zona, temp_min=tmin, temp_max=tmax,
                          requiere_refrigeracion=ref, controlado=ctrl, clasificacion_abc=abc)
    db.add(cat); db.flush()
    for num_lote, cant, dias in lotes:
        cad = hoy + timedelta(days=dias)
        lote = models.Lote(numero_lote=num_lote, catalogo_id=cat.id, cantidad=cant, fecha_caducidad=cad)
        db.add(lote); db.flush()
        # Entrada inicial en Kárdex
        db.add(models.Movimiento(lote_id=lote.id, tipo="ENTRADA", cantidad=cant,
                                  destino_origen="Carga inicial — seed datos.py",
                                  fecha=datetime.now() - timedelta(days=60)))
        lotes_creados.append((cat, lote))

db.commit()
print(f"   ✅  {len(medicamentos)} medicamentos con {sum(len(m[7]) for m in medicamentos)} lotes creados.\n")

# ════════════════════════════════════════════════════════════════════════════
# 5. PROVEEDORES
# ════════════════════════════════════════════════════════════════════════════
print("🏢  Creando proveedores...")
proveedores_data = [
    ("Laboratorios Pisa S.A.",         "Lic. Roberto Garza — ventas@pisa.com.mx"),
    ("Laboratorios Senosiain",          "Ing. Diana Flores — dflores@senosiain.com"),
    ("Sanofi México",                   "Dr. Carlos Ramos — cramos@sanofi.com"),
    ("Pfizer México S.A. de C.V.",      "Lic. María Pérez — mperez@pfizer.com"),
    ("Bayer de México",                 "Ing. Luis Hernández — lhernandez@bayer.com"),
    ("Distribuidora Farma Baja California", "Lic. Elena Martínez — elena@distrifabc.mx"),
]
proveedores = []
for nom, con in proveedores_data:
    p = models.Proveedor(nombre=nom, contacto=con)
    db.add(p); db.flush(); proveedores.append(p)
db.commit()
print(f"   ✅  {len(proveedores)} proveedores creados.\n")

# ════════════════════════════════════════════════════════════════════════════
# 6. ÓRDENES DE COMPRA
# ════════════════════════════════════════════════════════════════════════════
print("🛒  Creando órdenes de compra...")
ordenes_data = [
    (1, "Paracetamol 500mg Tab",    1000, 4500.00,  "COMPLETADA", -45),
    (2, "Amoxicilina 500mg Cap",     500, 8750.00,  "COMPLETADA", -30),
    (3, "Insulina Glargina 100UI/mL",100, 22000.00, "COMPLETADA", -20),
    (4, "Ibuprofeno 400mg Tab",      800, 3200.00,  "COMPLETADA", -15),
    (1, "Metformina 850mg Tab",      600, 5400.00,  "COMPLETADA", -10),
    (5, "Alprazolam 0.5mg Tab",      200, 6800.00,  "COMPLETADA", -8),
    (2, "Atorvastatina 20mg Tab",    400, 12000.00, "COMPLETADA", -5),
    (4, "Ciprofloxacino 500mg Tab",  300, 9600.00,  "PENDIENTE",  -2),
    (3, "Vacuna Influenza 0.5mL",     80, 15200.00, "PENDIENTE",  -1),
    (6, "Omeprazol 20mg Cap",        500, 6250.00,  "PENDIENTE",   0),
]
for prov_id, med, cant, costo, estado, dias in ordenes_data:
    oc = models.OrdenCompra(proveedor_id=prov_id, medicamento=med, cantidad=cant,
                             costo_total=costo, estado=estado,
                             fecha_orden=datetime.now() + timedelta(days=dias))
    db.add(oc)
db.commit()
print(f"   ✅  {len(ordenes_data)} órdenes de compra creadas.\n")

# ════════════════════════════════════════════════════════════════════════════
# 7. FINANZAS
# ════════════════════════════════════════════════════════════════════════════
print("💰  Creando registros financieros...")
finanzas_data = [
    ("GASTO",   4500.00,  "OC#1 — Paracetamol 500mg Tab (Laboratorios Pisa)",        -45),
    ("GASTO",   8750.00,  "OC#2 — Amoxicilina 500mg Cap (Laboratorios Senosiain)",   -30),
    ("GASTO",  22000.00,  "OC#3 — Insulina Glargina (Sanofi México)",                -20),
    ("GASTO",   3200.00,  "OC#4 — Ibuprofeno 400mg Tab (Pfizer México)",             -15),
    ("GASTO",   5400.00,  "OC#5 — Metformina 850mg Tab (Laboratorios Pisa)",         -10),
    ("GASTO",   6800.00,  "OC#6 — Alprazolam 0.5mg Tab (Bayer de México)",            -8),
    ("GASTO",  12000.00,  "OC#7 — Atorvastatina 20mg Tab (Laboratorios Senosiain)",   -5),
    ("INGRESO", 35000.00, "Venta mensual — Farmacia Zona Río (Febrero)",            -30),
    ("INGRESO", 28500.00, "Venta mensual — Farmacia La Mesa (Febrero)",             -30),
    ("INGRESO", 22000.00, "Venta mensual — Farmacia Playas TJ (Febrero)",             -30),
    ("INGRESO", 18000.00, "Venta mensual — Farmacia Otay (Febrero)",     -28),
    ("INGRESO", 41000.00, "Venta mensual — Farmacia Zona Río (Marzo)",               -5),
    ("INGRESO", 31500.00, "Venta mensual — Farmacia La Mesa (Marzo)",                -5),
    ("INGRESO", 19500.00, "Venta mensual — Farmacia El Florido (Marzo)",                -4),
    ("INGRESO", 25000.00, "Venta mensual — Farmacia Garita Otay (Marzo)",                 -3),
    ("GASTO",   1800.00,  "Mantenimiento cámara de refrigeración",                    -7),
    ("GASTO",    950.00,  "Insumos de empaque y etiquetado",                          -6),
    ("GASTO",   3200.00,  "Servicio de transporte refrigerado — Marzo",               -2),
]
for tipo, monto, concepto, dias in finanzas_data:
    db.add(models.Finanza(tipo=tipo, monto=monto, concepto=concepto,
                           fecha=datetime.now() + timedelta(days=dias)))
db.commit()
print(f"   ✅  {len(finanzas_data)} registros financieros creados.\n")

# ════════════════════════════════════════════════════════════════════════════
# 8. SALIDAS HISTÓRICAS (para que el ABC tenga base real)
# ════════════════════════════════════════════════════════════════════════════
print("📤  Generando historial de salidas para análisis ABC...")

salidas_hist = [
    # (nombre_medicamento, lote, cantidad, destino, dias_atras)
    ("Paracetamol 500mg Tab",    "PARA-2024-001", 120, "Farmacia Zona Río",        55),
    ("Paracetamol 500mg Tab",    "PARA-2024-001", 95,  "Farmacia La Mesa",         50),
    ("Paracetamol 500mg Tab",    "PARA-2024-001", 110, "Farmacia Playas TJ",         45),
    ("Paracetamol 500mg Tab",    "PARA-2024-001", 80,  "Farmacia Otay", 40),
    ("Paracetamol 500mg Tab",    "PARA-2024-001", 130, "Farmacia Zona Río",        35),
    ("Amoxicilina 500mg Cap",    "AMOX-2024-001", 85,  "Farmacia Zona Río",        52),
    ("Amoxicilina 500mg Cap",    "AMOX-2024-001", 70,  "Farmacia La Mesa",         47),
    ("Amoxicilina 500mg Cap",    "AMOX-2024-001", 95,  "Farmacia Playas TJ",         42),
    ("Ibuprofeno 400mg Tab",     "IBU-2024-001",  140, "Farmacia Zona Río",        53),
    ("Ibuprofeno 400mg Tab",     "IBU-2024-001",  115, "Farmacia La Mesa",         48),
    ("Ibuprofeno 400mg Tab",     "IBU-2024-001",  100, "Farmacia Otay", 43),
    ("Omeprazol 20mg Cap",       "OME-2024-001",  90,  "Farmacia Zona Río",        51),
    ("Omeprazol 20mg Cap",       "OME-2024-001",  75,  "Farmacia Playas TJ",         46),
    ("Metformina 850mg Tab",     "MET-2024-001",  100, "Farmacia Zona Río",        54),
    ("Metformina 850mg Tab",     "MET-2024-001",  88,  "Farmacia Otay", 49),
    ("Atorvastatina 20mg Tab",   "ATOR-2024-001", 72,  "Farmacia La Mesa",         50),
    ("Losartán 50mg Tab",        "LOS-2024-001",  68,  "Farmacia Zona Río",        53),
    ("Azitromicina 500mg Tab",   "AZI-2024-001",  55,  "Farmacia Playas TJ",         48),
    ("Insulina Glargina 100UI/mL","INS-2024-001", 30,  "Farmacia Zona Río",        40),
    ("Warfarina 5mg Tab",        "WAR-2024-001",  45,  "Farmacia La Mesa",         38),
    ("Enalapril 10mg Tab",       "ENA-2024-001",  60,  "Farmacia Otay", 36),
    ("Levotiroxina 50mcg Tab",   "LEVO-2024-001", 50,  "Farmacia Playas TJ",         34),
    ("Ciprofloxacino 500mg Tab", "CIPRO-2024-001",40,  "Farmacia Zona Río",        32),
    ("Metronidazol 500mg Tab",   "METRO-2024-001",38,  "Farmacia La Mesa",         30),
    ("Amlodipino 5mg Tab",       "AML-2024-001",  55,  "Farmacia El Florido",         28),
    ("Prednisona 5mg Tab",       "PRED-2024-001", 35,  "Farmacia Garita Otay",          26),
    ("Alprazolam 0.5mg Tab",     "ALP-2024-001",  20,  "Farmacia Zona Río",        20),
    ("Tramadol 100mg Cap",       "TRAM-2024-001", 25,  "Farmacia Otay", 18),
    ("Furosemida 40mg Tab",      "FUR-2024-001",  42,  "Farmacia La Mesa",         15),
    ("Ranitidina 150mg Tab",     "RAN-2024-001",  30,  "Farmacia Playas TJ",         12),
]

for nom_med, num_lote, cant, destino, dias_atras in salidas_hist:
    lote = db.query(models.Lote).filter(models.Lote.numero_lote == num_lote).first()
    if lote and lote.cantidad >= cant:
        lote.cantidad -= cant
        db.add(models.Movimiento(lote_id=lote.id, tipo="SALIDA", cantidad=cant,
                                  destino_origen=destino,
                                  fecha=datetime.now() - timedelta(days=dias_atras)))
db.commit()
print(f"   ✅  {len(salidas_hist)} movimientos históricos generados.\n")

# ════════════════════════════════════════════════════════════════════════════
# 9. PEDIDOS DE FARMACIA (varios estados)
# ════════════════════════════════════════════════════════════════════════════
print("📋  Creando pedidos de farmacia...")

def crear_pedido(farmacia_id, items, estado, dias_atras, picking_alm=None,
                  rutero=None, temp_sal=None, temp_lle=None, entregado=False):
    p = models.PedidoFarmacia(
        farmacia_id=farmacia_id, estado=estado,
        fecha_pedido=datetime.now() - timedelta(days=dias_atras),
        fecha_entrega_estimada=hoy + timedelta(days=1),
        notas="Pedido de demostración"
    )
    db.add(p); db.flush()
    for med, cant_sol, cant_sur, est_item in items:
        db.add(models.ItemPedido(pedido_id=p.id, medicamento=med,
                                  cantidad_solicitada=cant_sol, cantidad_surtida=cant_sur,
                                  estado=est_item))
    if picking_alm:
        pk = models.PickingList(pedido_id=p.id, almacenista=picking_alm,
                                 estado="COMPLETADO" if estado != "EN_PICKING" else "EN_PROCESO",
                                 fecha_completado=datetime.now() - timedelta(days=dias_atras-1) if estado != "EN_PICKING" else None)
        db.add(pk)
    if rutero:
        r = models.RutaEntrega(pedido_id=p.id, rutero=rutero,
                                estado="ENTREGADO" if entregado else "EN_RUTA",
                                fecha_salida=datetime.now() - timedelta(days=dias_atras-1),
                                fecha_entrega=datetime.now() - timedelta(hours=2) if entregado else None,
                                temperatura_salida=temp_sal, temperatura_llegada=temp_lle)
        db.add(r)
    db.flush()
    return p

# Pedidos ENTREGADOS (historial)
crear_pedido(1, [("Paracetamol 500mg Tab",200,200,"SURTIDO"),("Amoxicilina 500mg Cap",100,100,"SURTIDO"),("Ibuprofeno 400mg Tab",150,150,"SURTIDO")], "ENTREGADO", 15, "Almacenista López", "Juan Ramírez", 7.2, 7.8, True)
crear_pedido(2, [("Metformina 850mg Tab",120,120,"SURTIDO"),("Atorvastatina 20mg Tab",80,80,"SURTIDO")], "ENTREGADO", 12, "Almacenista García", "Pedro Soto", 8.1, 8.5, True)
crear_pedido(3, [("Insulina Glargina 100UI/mL",20,20,"SURTIDO"),("Warfarina 5mg Tab",60,60,"SURTIDO")], "ENTREGADO", 10, "Almacenista López", "Juan Ramírez", 3.5, 4.1, True)
crear_pedido(4, [("Losartán 50mg Tab",90,90,"SURTIDO"),("Enalapril 10mg Tab",70,70,"SURTIDO"),("Amlodipino 5mg Tab",50,50,"SURTIDO")], "ENTREGADO", 8, "Almacenista García", "Pedro Soto", 7.9, 8.2, True)
crear_pedido(5, [("Paracetamol 500mg Tab",100,100,"SURTIDO"),("Omeprazol 20mg Cap",80,80,"SURTIDO")], "ENTREGADO", 6, "Almacenista López", "Juan Ramírez", None, None, True)

# Pedido EN RUTA
crear_pedido(1, [("Azitromicina 500mg Tab",60,60,"SURTIDO"),("Ciprofloxacino 500mg Tab",40,40,"SURTIDO")], "EN_RUTA", 1, "Almacenista García", "Pedro Soto", 7.5, None, False)

# Pedido LISTO para despacho
crear_pedido(2, [("Metronidazol 500mg Tab",50,50,"SURTIDO"),("Prednisona 5mg Tab",30,30,"SURTIDO")], "LISTO", 1, "Almacenista López")

# Pedido EN_PICKING
crear_pedido(3, [("Levotiroxina 50mcg Tab",40,0,"PENDIENTE"),("Furosemida 40mg Tab",60,0,"PENDIENTE")], "EN_PICKING", 0, "Almacenista García")

# Pedidos PENDIENTES
crear_pedido(4, [("Paracetamol 500mg Tab",200,0,"PENDIENTE"),("Ibuprofeno 400mg Tab",150,0,"PENDIENTE"),("Omeprazol 20mg Cap",100,0,"PENDIENTE")], "PENDIENTE", 0)
crear_pedido(5, [("Amoxicilina 500mg Cap",80,0,"PENDIENTE"),("Tramadol 100mg Cap",30,0,"PENDIENTE")], "PENDIENTE", 0)
crear_pedido(6, [("Amlodipino 5mg Tab",60,0,"PENDIENTE"),("Losartán 50mg Tab",90,0,"PENDIENTE")], "PENDIENTE", 0)

db.commit()
print(f"   ✅  12 pedidos creados (5 entregados, 1 en ruta, 1 listo, 1 en picking, 4 pendientes).\n")

# ════════════════════════════════════════════════════════════════════════════
# 10. DEVOLUCIONES
# ════════════════════════════════════════════════════════════════════════════
print("🔄  Creando devoluciones...")
devoluciones_data = [
    (1, "Paracetamol 500mg Tab",  "PARA-2024-003", 30, "PROXIMO_VENCER",  "CUARENTENA",  "APROBADA",  "qfr_drlopez"),
    (2, "Ibuprofeno 400mg Tab",   "IBU-2024-002",  20, "ERROR_PEDIDO",    "RESTOCK",     "APROBADA",  "qfr_drlopez"),
    (3, "Amoxicilina 500mg Cap",  "AMOX-2024-002", 15, "PRODUCTO_DANADO", "DESTRUCCION", "APROBADA",  "qfr_drlopez"),
    (4, "Omeprazol 20mg Cap",     "OME-2024-002",  10, "PROXIMO_VENCER",  "CUARENTENA",  "PENDIENTE", None),
    (5, "Metformina 850mg Tab",   "MET-2024-002",  25, "ERROR_PEDIDO",    "RESTOCK",     "PENDIENTE", None),
    (1, "Azitromicina 500mg Tab", "AZI-2024-002",   8, "OTRO",            "CUARENTENA",  "PENDIENTE", None),
]
for farm_id, med, lote, cant, motivo, destino, estado, aprobado_por in devoluciones_data:
    db.add(models.Devolucion(farmacia_id=farm_id, medicamento=med, numero_lote=lote,
                              cantidad=cant, motivo=motivo, destino=destino,
                              estado=estado, aprobado_por=aprobado_por))
db.commit()
print(f"   ✅  {len(devoluciones_data)} devoluciones creadas (3 resueltas, 3 pendientes QFR).\n")

# ════════════════════════════════════════════════════════════════════════════
# 11. CUARENTENA
# ════════════════════════════════════════════════════════════════════════════
print("🔴  Creando lotes en cuarentena...")
cuarentena_data = [
    ("PARA-2024-003", "Paracetamol 500mg Tab",      30, "DEVOLUCION",          "EN_REVISION", None,          None,         "Devolución aprobada de Farmacia Zona Río — próximo a vencer"),
    ("OME-2024-002",  "Omeprazol 20mg Cap",          10, "DEVOLUCION",          "EN_REVISION", None,          None,         "Devolución pendiente de Farmacia Otay"),
    ("AZI-2024-002",  "Azitromicina 500mg Tab",       8, "DEVOLUCION",          "EN_REVISION", None,          None,         "Devolución pendiente de Farmacia Zona Río"),
    ("INS-2024-002",  "Insulina Glargina 100UI/mL",   5, "SOSPECHA_CALIDAD",    "EN_REVISION", None,          None,         "Se detectó posible interrupción de cadena de frío durante transporte"),
    ("ALP-2024-002",  "Alprazolam 0.5mg Tab",        10, "RECEPCION_PENDIENTE", "EN_REVISION", None,          None,         "Documentación COFEPRIS en revisión por QFR"),
    ("FUR-2024-002",  "Furosemida 40mg Tab",          15, "VENCIDO",             "RECHAZADO",  "qfr_drlopez", datetime.now()-timedelta(days=2), "Lote vencido detectado en conteo físico. Destino: destrucción."),
]
for num_lote, med, cant, motivo, estado, resuelto_por, fecha_res, notas in cuarentena_data:
    db.add(models.LoteCuarentena(numero_lote=num_lote, medicamento=med, cantidad=cant,
                                  motivo=motivo, estado=estado, resuelto_por=resuelto_por,
                                  fecha_resolucion=fecha_res, notas=notas))
db.commit()
print(f"   ✅  {len(cuarentena_data)} lotes en cuarentena (5 en revisión, 1 rechazado).\n")

# ════════════════════════════════════════════════════════════════════════════
# RESUMEN FINAL
# ════════════════════════════════════════════════════════════════════════════
print("=" * 60)
print("✅  SEED COMPLETADO — NEXUS ERP v2.0")
print("=" * 60)
print(f"  🏪  Farmacias:          {len(farmacias_data)}")
print(f"  👥  Usuarios:           {len(usuarios_data)}")
print(f"  💊  Medicamentos:       {len(medicamentos)}")
print(f"  📦  Lotes:              {sum(len(m[7]) for m in medicamentos)}")
print(f"  🏢  Proveedores:        {len(proveedores_data)}")
print(f"  🛒  Órdenes de compra:  {len(ordenes_data)}")
print(f"  💰  Registros finanzas: {len(finanzas_data)}")
print(f"  📤  Movimientos hist.:  {len(salidas_hist)}")
print(f"  📋  Pedidos:            12")
print(f"  🔄  Devoluciones:       {len(devoluciones_data)}")
print(f"  🔴  Cuarentena:         {len(cuarentena_data)}")
print("=" * 60)
print("\n  🔑  Acceso rápido:")
print("  URL: http://localhost:8000")
print("  admin / 123  (acceso total)")
print("  qfr_drlopez / nexus2026  (QFR)")
print("  rutero_juan / nexus2026  (Rutero)")
print("  farm_zonario / nexus2026  (Farmacia Zona Río)")
print()
