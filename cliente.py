"""
cliente.py — Cliente para Nexus ERP CEDIS
Interactúa con la API y guarda una copia local en data.json
"""

import json
import requests
from datetime import datetime
from pathlib import Path

# ──────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
DATA_FILE = Path(__file__).parent / "data.json"


# ──────────────────────────────────────────────
# Helpers JSON local
# ──────────────────────────────────────────────
def _leer_datos() -> dict:
    if not DATA_FILE.exists():
        return {"meta": {}, "usuarios": [], "farmacias": [], "pedidos": [], "catalogo": [], "movimientos": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _guardar_datos(data: dict) -> None:
    data["meta"]["ultima_actualizacion"] = datetime.utcnow().isoformat()
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def _upsert_lista(lista: list, nuevo: dict, campo_id: str = "id") -> list:
    """Inserta o actualiza un elemento en la lista por su id."""
    for i, item in enumerate(lista):
        if item.get(campo_id) == nuevo.get(campo_id):
            lista[i] = nuevo
            return lista
    lista.append(nuevo)
    return lista


# ──────────────────────────────────────────────
# Cliente
# ──────────────────────────────────────────────
class NexusCliente:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None
        self.session = requests.Session()

    # ── Autenticación ─────────────────────────
    def login(self, username: str, password: str) -> bool:
        """Inicia sesión y guarda el token."""
        resp = self.session.post(
            f"{self.base_url}/api/login",
            json={"username": username, "password": password},
        )
        if resp.status_code == 200:
            self.token = resp.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
            print(f"✔ Sesión iniciada como '{username}'")
            return True
        print(f"✘ Login fallido ({resp.status_code}): {resp.text}")
        return False

    def _get(self, path: str, **kwargs):
        return self.session.get(f"{self.base_url}/api{path}", **kwargs)

    def _post(self, path: str, **kwargs):
        return self.session.post(f"{self.base_url}/api{path}", **kwargs)

    def _put(self, path: str, **kwargs):
        return self.session.put(f"{self.base_url}/api{path}", **kwargs)

    # ── Farmacias ─────────────────────────────
    def listar_farmacias(self) -> list:
        resp = self._get("/farmacias")
        if resp.status_code == 200:
            farmacias = resp.json()
            data = _leer_datos()
            for f in farmacias:
                data["farmacias"] = _upsert_lista(data["farmacias"], f)
            _guardar_datos(data)
            return farmacias
        print(f"Error al obtener farmacias: {resp.status_code}")
        return []

    def crear_farmacia(self, nombre: str, direccion: str, contacto: str) -> dict | None:
        payload = {"nombre": nombre, "direccion": direccion, "contacto": contacto}
        resp = self._post("/farmacias", json=payload)
        if resp.status_code in (200, 201):
            farmacia = resp.json()
            data = _leer_datos()
            data["farmacias"] = _upsert_lista(data["farmacias"], farmacia)
            _guardar_datos(data)
            print(f"✔ Farmacia creada: {farmacia.get('nombre')} (id={farmacia.get('id')})")
            return farmacia
        print(f"Error al crear farmacia: {resp.status_code} — {resp.text}")
        return None

    # ── Pedidos ───────────────────────────────
    def listar_pedidos(self) -> list:
        resp = self._get("/pedidos")
        if resp.status_code == 200:
            pedidos = resp.json()
            data = _leer_datos()
            for p in pedidos:
                data["pedidos"] = _upsert_lista(data["pedidos"], p)
            _guardar_datos(data)
            return pedidos
        print(f"Error al obtener pedidos: {resp.status_code}")
        return []

    def crear_pedido(self, farmacia_id: int, items: list[dict], notas: str = "") -> dict | None:
        """
        items: lista de dicts con {"medicamento": str, "cantidad_solicitada": int}
        """
        payload = {"farmacia_id": farmacia_id, "items": items, "notas": notas}
        resp = self._post("/pedidos", json=payload)
        if resp.status_code in (200, 201):
            pedido = resp.json()
            data = _leer_datos()
            data["pedidos"] = _upsert_lista(data["pedidos"], pedido)
            _guardar_datos(data)
            print(f"✔ Pedido creado id={pedido.get('id')} para farmacia {farmacia_id}")
            return pedido
        print(f"Error al crear pedido: {resp.status_code} — {resp.text}")
        return None

    # ── Catálogo ──────────────────────────────
    def listar_catalogo(self) -> list:
        resp = self._get("/inventario")
        if resp.status_code == 200:
            items = resp.json()
            data = _leer_datos()
            for item in items:
                data["catalogo"] = _upsert_lista(data["catalogo"], item)
            _guardar_datos(data)
            return items
        print(f"Error al obtener catálogo: {resp.status_code}")
        return []

    # ── Movimientos ───────────────────────────
    def listar_movimientos(self) -> list:
        resp = self._get("/movimientos")
        if resp.status_code == 200:
            movs = resp.json()
            data = _leer_datos()
            for m in movs:
                data["movimientos"] = _upsert_lista(data["movimientos"], m)
            _guardar_datos(data)
            return movs
        print(f"Error al obtener movimientos: {resp.status_code}")
        return []

    # ── Datos locales (sin conexión) ──────────
    def datos_locales(self) -> dict:
        """Devuelve los datos guardados localmente en data.json."""
        return _leer_datos()

    def sincronizar(self) -> None:
        """Descarga y guarda todos los datos disponibles."""
        print("🔄 Sincronizando datos...")
        self.listar_farmacias()
        self.listar_pedidos()
        self.listar_catalogo()
        self.listar_movimientos()
        print("✔ Sincronización completa.")


# ──────────────────────────────────────────────
# Ejemplo de uso
# ──────────────────────────────────────────────
if __name__ == "__main__":
    cliente = NexusCliente()

    if cliente.login("admin", "123"):
        # Sincronizar todo
        cliente.sincronizar()

        # Ejemplo: listar farmacias
        farmacias = cliente.listar_farmacias()
        print(f"\nFarmacias registradas: {len(farmacias)}")
        for f in farmacias:
            print(f"  [{f['id']}] {f['nombre']} — {f.get('direccion', '')}")

        # Ejemplo: crear una farmacia
        # nueva = cliente.crear_farmacia("Farmacia San Juan", "Av. Principal 123", "555-0001")

        # Ejemplo: crear un pedido
        # pedido = cliente.crear_pedido(
        #     farmacia_id=1,
        #     items=[
        #         {"medicamento": "Paracetamol 500mg", "cantidad_solicitada": 100},
        #         {"medicamento": "Amoxicilina 500mg", "cantidad_solicitada": 50},
        #     ],
        #     notas="Urgente"
        # )
