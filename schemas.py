from pydantic import BaseModel
from datetime import date
from typing import Optional, List

# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------
class LoginReq(BaseModel): username: str; password: str

# ---------------------------------------------------------------------------
# ALMACÉN
# ---------------------------------------------------------------------------
class EntradaReq(BaseModel):
    nombre_medicamento: str; numero_lote: str; cantidad: int
    fecha_caducidad: date; zona: str; origen: str

class SalidaReq(BaseModel):
    nombre_medicamento: str; cantidad_requerida: int; destino: str

class ActualizarCatalogoReq(BaseModel):
    zona_almacenaje: Optional[str] = None
    temp_min: Optional[float] = None
    temp_max: Optional[float] = None
    requiere_refrigeracion: Optional[bool] = None
    controlado: Optional[bool] = None

# ---------------------------------------------------------------------------
# FINANZAS
# ---------------------------------------------------------------------------
class FinanzaReq(BaseModel): tipo: str; monto: float; concepto: str

# ---------------------------------------------------------------------------
# USUARIOS
# ---------------------------------------------------------------------------
class UsuarioReq(BaseModel):
    username: str; password: str; rol: str
    farmacia_id: Optional[int] = None

# ---------------------------------------------------------------------------
# PROVEEDORES / COMPRAS
# ---------------------------------------------------------------------------
class ProveedorReq(BaseModel): nombre: str; contacto: str
class OrdenReq(BaseModel): proveedor_id: int; medicamento: str; cantidad: int; costo_total: float
class RecibirOrdenReq(BaseModel): numero_lote: str; fecha_caducidad: date

# ---------------------------------------------------------------------------
# FARMACIAS
# ---------------------------------------------------------------------------
class FarmaciaReq(BaseModel):
    nombre: str; direccion: str; contacto: str

# ---------------------------------------------------------------------------
# PEDIDOS
# ---------------------------------------------------------------------------
class ItemPedidoReq(BaseModel):
    medicamento: str
    cantidad_solicitada: int

class PedidoReq(BaseModel):
    farmacia_id: int
    items: List[ItemPedidoReq]
    fecha_entrega_estimada: Optional[date] = None
    notas: Optional[str] = None

# ---------------------------------------------------------------------------
# PICKING
# ---------------------------------------------------------------------------
class CompletarPickingReq(BaseModel):
    almacenista: str

# ---------------------------------------------------------------------------
# RUTAS
# ---------------------------------------------------------------------------
class SalidaRutaReq(BaseModel):
    rutero: str
    temperatura_salida: Optional[float] = None

class ConfirmarEntregaReq(BaseModel):
    temperatura_llegada: Optional[float] = None
    notas_entrega: Optional[str] = None

class RechazarEntregaReq(BaseModel):
    notas_entrega: str

# ---------------------------------------------------------------------------
# DEVOLUCIONES
# ---------------------------------------------------------------------------
class DevolucionReq(BaseModel):
    farmacia_id: int
    medicamento: str
    numero_lote: str
    cantidad: int
    motivo: str   # PROXIMO_VENCER / ERROR_PEDIDO / PRODUCTO_DANADO / OTRO
    destino: str  # CUARENTENA / RESTOCK / DESTRUCCION

class AprobarDevolucionReq(BaseModel):
    aprobado: bool
    notas: Optional[str] = None

# ---------------------------------------------------------------------------
# CUARENTENA
# ---------------------------------------------------------------------------
class CuarentenaReq(BaseModel):
    numero_lote: str
    medicamento: str
    cantidad: int
    motivo: str  # RECEPCION_PENDIENTE / DEVOLUCION / SOSPECHA_CALIDAD / VENCIDO
    notas: Optional[str] = None

class ResolverCuarentenaReq(BaseModel):
    decision: str  # APROBADO / RECHAZADO
    notas: Optional[str] = None
