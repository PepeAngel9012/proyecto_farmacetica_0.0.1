from pydantic import BaseModel
from datetime import date

class LoginReq(BaseModel): username: str; password: str
class EntradaReq(BaseModel): nombre_medicamento: str; numero_lote: str; cantidad: int; fecha_caducidad: date; zona: str; origen: str
class SalidaReq(BaseModel): nombre_medicamento: str; cantidad_requerida: int; destino: str
class FinanzaReq(BaseModel): tipo: str; monto: float; concepto: str
class UsuarioReq(BaseModel): username: str; password: str; rol: str
class ProveedorReq(BaseModel): nombre: str; contacto: str
class OrdenReq(BaseModel): proveedor_id: int; medicamento: str; cantidad: int; costo_total: float
class RecibirOrdenReq(BaseModel): numero_lote: str; fecha_caducidad: date