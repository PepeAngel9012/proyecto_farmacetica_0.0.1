from sqlalchemy import Column, Integer, String, Date, ForeignKey, DateTime, Float, Boolean, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

# ---------------------------------------------------------------------------
# USUARIOS
# ---------------------------------------------------------------------------
class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    rol = Column(String)
    # FARMACIA y RUTERO tienen entidad asociada
    farmacia_id = Column(Integer, ForeignKey("farmacias.id"), nullable=True)
    farmacia = relationship("Farmacia", back_populates="usuarios")

# ---------------------------------------------------------------------------
# FARMACIAS CLIENTES
# ---------------------------------------------------------------------------
class Farmacia(Base):
    __tablename__ = "farmacias"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, unique=True)
    direccion = Column(String)
    contacto = Column(String)
    activa = Column(Boolean, default=True)
    fecha_registro = Column(DateTime, default=datetime.utcnow)
    usuarios = relationship("Usuario", back_populates="farmacia")
    pedidos = relationship("PedidoFarmacia", back_populates="farmacia")

# ---------------------------------------------------------------------------
# PEDIDOS DE FARMACIA
# ---------------------------------------------------------------------------
class PedidoFarmacia(Base):
    __tablename__ = "pedidos_farmacia"
    id = Column(Integer, primary_key=True, index=True)
    farmacia_id = Column(Integer, ForeignKey("farmacias.id"))
    estado = Column(String, default="PENDIENTE")
    # PENDIENTE → EN_PICKING → LISTO → EN_RUTA → ENTREGADO → CANCELADO
    fecha_pedido = Column(DateTime, default=datetime.utcnow)
    fecha_entrega_estimada = Column(Date, nullable=True)
    notas = Column(Text, nullable=True)
    farmacia = relationship("Farmacia", back_populates="pedidos")
    items = relationship("ItemPedido", back_populates="pedido")
    picking = relationship("PickingList", back_populates="pedido", uselist=False)
    ruta = relationship("RutaEntrega", back_populates="pedido", uselist=False)

class ItemPedido(Base):
    __tablename__ = "items_pedido"
    id = Column(Integer, primary_key=True, index=True)
    pedido_id = Column(Integer, ForeignKey("pedidos_farmacia.id"))
    medicamento = Column(String)
    cantidad_solicitada = Column(Integer)
    cantidad_surtida = Column(Integer, default=0)
    estado = Column(String, default="PENDIENTE")  # PENDIENTE / SURTIDO / SIN_STOCK
    pedido = relationship("PedidoFarmacia", back_populates="items")

# ---------------------------------------------------------------------------
# PICKING LIST
# ---------------------------------------------------------------------------
class PickingList(Base):
    __tablename__ = "picking_lists"
    id = Column(Integer, primary_key=True, index=True)
    pedido_id = Column(Integer, ForeignKey("pedidos_farmacia.id"), unique=True)
    almacenista = Column(String, nullable=True)
    estado = Column(String, default="PENDIENTE")  # PENDIENTE / EN_PROCESO / COMPLETADO
    fecha_generacion = Column(DateTime, default=datetime.utcnow)
    fecha_completado = Column(DateTime, nullable=True)
    pedido = relationship("PedidoFarmacia", back_populates="picking")

# ---------------------------------------------------------------------------
# RUTAS DE ENTREGA (RUTERO)
# ---------------------------------------------------------------------------
class RutaEntrega(Base):
    __tablename__ = "rutas_entrega"
    id = Column(Integer, primary_key=True, index=True)
    pedido_id = Column(Integer, ForeignKey("pedidos_farmacia.id"), unique=True)
    rutero = Column(String, nullable=True)
    estado = Column(String, default="PENDIENTE")  # PENDIENTE / EN_RUTA / ENTREGADO / RECHAZADO
    fecha_salida = Column(DateTime, nullable=True)
    fecha_entrega = Column(DateTime, nullable=True)
    temperatura_salida = Column(Float, nullable=True)   # BPD — cadena de frío
    temperatura_llegada = Column(Float, nullable=True)
    notas_entrega = Column(Text, nullable=True)
    pedido = relationship("PedidoFarmacia", back_populates="ruta")

# ---------------------------------------------------------------------------
# DEVOLUCIONES
# ---------------------------------------------------------------------------
class Devolucion(Base):
    __tablename__ = "devoluciones"
    id = Column(Integer, primary_key=True, index=True)
    farmacia_id = Column(Integer, ForeignKey("farmacias.id"))
    medicamento = Column(String)
    numero_lote = Column(String)
    cantidad = Column(Integer)
    motivo = Column(String)
    # MOTIVO: PROXIMO_VENCER / ERROR_PEDIDO / PRODUCTO_DANADO / OTRO
    destino = Column(String, default="CUARENTENA")
    # DESTINO: CUARENTENA / RESTOCK / DESTRUCCION
    estado = Column(String, default="PENDIENTE")
    # PENDIENTE → aprobada por QFR → ejecutada
    fecha = Column(DateTime, default=datetime.utcnow)
    aprobado_por = Column(String, nullable=True)  # username del QFR
    farmacia = relationship("Farmacia")

# ---------------------------------------------------------------------------
# CUARENTENA — lotes en espera de aprobación QFR
# ---------------------------------------------------------------------------
class LoteCuarentena(Base):
    __tablename__ = "lotes_cuarentena"
    id = Column(Integer, primary_key=True, index=True)
    numero_lote = Column(String)
    medicamento = Column(String)
    cantidad = Column(Integer)
    motivo = Column(String)
    # MOTIVO: RECEPCION_PENDIENTE / DEVOLUCION / SOSPECHA_CALIDAD / VENCIDO
    estado = Column(String, default="EN_REVISION")
    # EN_REVISION → APROBADO (pasa a stock) / RECHAZADO (va a destrucción)
    fecha_ingreso = Column(DateTime, default=datetime.utcnow)
    fecha_resolucion = Column(DateTime, nullable=True)
    resuelto_por = Column(String, nullable=True)  # username del QFR
    notas = Column(Text, nullable=True)

# ---------------------------------------------------------------------------
# PROVEEDORES
# ---------------------------------------------------------------------------
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
    estado = Column(String, default="PENDIENTE")
    fecha_orden = Column(DateTime, default=datetime.utcnow)
    proveedor = relationship("Proveedor", back_populates="ordenes")

# ---------------------------------------------------------------------------
# FINANZAS
# ---------------------------------------------------------------------------
class Finanza(Base):
    __tablename__ = "finanzas"
    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(String)
    monto = Column(Float)
    concepto = Column(String)
    fecha = Column(DateTime, default=datetime.utcnow)

# ---------------------------------------------------------------------------
# CATÁLOGO + LOTES + MOVIMIENTOS
# ---------------------------------------------------------------------------
class Catalogo(Base):
    __tablename__ = "catalogo"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, unique=True)
    zona_almacenaje = Column(String, default="General")
    temp_min = Column(Float, default=15.0)
    temp_max = Column(Float, default=25.0)
    requiere_refrigeracion = Column(Boolean, default=False)
    controlado = Column(Boolean, default=False)
    clasificacion_abc = Column(String, default="C")
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
