from sqlalchemy import Column, Integer, String, Date, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String) 
    rol = Column(String)

class Proveedor(Base):
    __tablename__ = "proveedores"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, unique=True)
    contacto = Column(String)
    ordenes = relationship("OrdenCompra", back_populates="proveedor")

class OrdenCompra(Base):
    __tablename__ = "ordenes_compra"
    id = Column(Integer, primary_key=True, index=True)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"))
    medicamento = Column(String)
    cantidad = Column(Integer)
    costo_total = Column(Float)
    estado = Column(String, default="PENDIENTE") # PENDIENTE o COMPLETADA
    fecha_orden = Column(DateTime, default=datetime.utcnow)
    proveedor = relationship("Proveedor", back_populates="ordenes")

class Finanza(Base):
    __tablename__ = "finanzas"
    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(String)
    monto = Column(Float)
    concepto = Column(String)
    fecha = Column(DateTime, default=datetime.utcnow)

class Catalogo(Base):
    __tablename__ = "catalogo"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, unique=True)
    zona_almacenaje = Column(String, default="General")
    lotes = relationship("Lote", back_populates="medicamento")

class Lote(Base):
    __tablename__ = "lotes"
    id = Column(Integer, primary_key=True, index=True)
    numero_lote = Column(String, unique=True)
    catalogo_id = Column(Integer, ForeignKey("catalogo.id"))
    cantidad = Column(Integer, default=0)
    fecha_caducidad = Column(Date)
    medicamento = relationship("Catalogo", back_populates="lotes")
    movimientos = relationship("Movimiento", back_populates="lote")

class Movimiento(Base):
    __tablename__ = "movimientos"
    id = Column(Integer, primary_key=True, index=True)
    lote_id = Column(Integer, ForeignKey("lotes.id"))
    tipo = Column(String)
    cantidad = Column(Integer)
    fecha = Column(DateTime, default=datetime.utcnow)
    destino_origen = Column(String)
    lote = relationship("Lote", back_populates="movimientos")