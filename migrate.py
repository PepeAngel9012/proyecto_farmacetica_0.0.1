"""
Migración v2 — Nexus ERP CEDIS
Agrega todas las tablas nuevas sin borrar datos existentes.
Ejecutar: sudo docker cp migrate.py nexus_web:/app/migrate.py && sudo docker exec -it nexus_web python migrate.py
O directo en postgres:
sudo docker exec -it nexus_db psql -U nexus_admin -d nexus_db -f /migrate.sql
"""
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://nexus_admin:nexus_password123@localhost:5432/nexus_db")
engine = create_engine(DATABASE_URL)

migraciones = [
    # Tablas nuevas
    "CREATE TABLE IF NOT EXISTS farmacias (id SERIAL PRIMARY KEY, nombre VARCHAR UNIQUE, direccion VARCHAR, contacto VARCHAR, activa BOOLEAN DEFAULT TRUE, fecha_registro TIMESTAMP DEFAULT NOW())",
    "CREATE TABLE IF NOT EXISTS pedidos_farmacia (id SERIAL PRIMARY KEY, farmacia_id INTEGER REFERENCES farmacias(id), estado VARCHAR DEFAULT 'PENDIENTE', fecha_pedido TIMESTAMP DEFAULT NOW(), fecha_entrega_estimada DATE, notas TEXT)",
    "CREATE TABLE IF NOT EXISTS items_pedido (id SERIAL PRIMARY KEY, pedido_id INTEGER REFERENCES pedidos_farmacia(id), medicamento VARCHAR, cantidad_solicitada INTEGER, cantidad_surtida INTEGER DEFAULT 0, estado VARCHAR DEFAULT 'PENDIENTE')",
    "CREATE TABLE IF NOT EXISTS picking_lists (id SERIAL PRIMARY KEY, pedido_id INTEGER UNIQUE REFERENCES pedidos_farmacia(id), almacenista VARCHAR, estado VARCHAR DEFAULT 'PENDIENTE', fecha_generacion TIMESTAMP DEFAULT NOW(), fecha_completado TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS rutas_entrega (id SERIAL PRIMARY KEY, pedido_id INTEGER UNIQUE REFERENCES pedidos_farmacia(id), rutero VARCHAR, estado VARCHAR DEFAULT 'PENDIENTE', fecha_salida TIMESTAMP, fecha_entrega TIMESTAMP, temperatura_salida FLOAT, temperatura_llegada FLOAT, notas_entrega TEXT)",
    "CREATE TABLE IF NOT EXISTS devoluciones (id SERIAL PRIMARY KEY, farmacia_id INTEGER REFERENCES farmacias(id), medicamento VARCHAR, numero_lote VARCHAR, cantidad INTEGER, motivo VARCHAR, destino VARCHAR DEFAULT 'CUARENTENA', estado VARCHAR DEFAULT 'PENDIENTE', fecha TIMESTAMP DEFAULT NOW(), aprobado_por VARCHAR)",
    "CREATE TABLE IF NOT EXISTS lotes_cuarentena (id SERIAL PRIMARY KEY, numero_lote VARCHAR, medicamento VARCHAR, cantidad INTEGER, motivo VARCHAR, estado VARCHAR DEFAULT 'EN_REVISION', fecha_ingreso TIMESTAMP DEFAULT NOW(), fecha_resolucion TIMESTAMP, resuelto_por VARCHAR, notas TEXT)",
    # Columnas nuevas en usuarios
    "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS farmacia_id INTEGER REFERENCES farmacias(id)",
    # Columnas BPA en catálogo (por si acaso no existen)
    "ALTER TABLE catalogo ADD COLUMN IF NOT EXISTS temp_min FLOAT DEFAULT 15.0",
    "ALTER TABLE catalogo ADD COLUMN IF NOT EXISTS temp_max FLOAT DEFAULT 25.0",
    "ALTER TABLE catalogo ADD COLUMN IF NOT EXISTS requiere_refrigeracion BOOLEAN DEFAULT FALSE",
    "ALTER TABLE catalogo ADD COLUMN IF NOT EXISTS controlado BOOLEAN DEFAULT FALSE",
    "ALTER TABLE catalogo ADD COLUMN IF NOT EXISTS clasificacion_abc VARCHAR DEFAULT 'C'",
]

with engine.connect() as conn:
    for sql in migraciones:
        try:
            conn.execute(text(sql))
            conn.commit()
            print(f"✅ OK: {sql[:70]}...")
        except Exception as e:
            print(f"⚠️  SKIP: {str(e)[:80]}")

print("\n✅ Migración v2 completada.")
