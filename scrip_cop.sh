#!/usr/bin/env bash

# ==========================================
# VARIABLES DE CONFIGURACIÓN
# ==========================================
CONTAINER_NAME="nexus_db"
# Este es el superusuario de tu Postgres (suele ser postgres, 
# a menos que en tu docker-compose.yml pusieras otro en POSTGRES_USER)
DB_SUPERADMIN="postgres" 

# Datos de tu app FastAPI
APP_USUARIO="usuario_nexus"
APP_PASSWORD="password123"

# Nombres de las bases de datos
OLD_DB="nexus_db"
NEW_DB="nexus_db_nueva"

echo "=== Iniciando Operación de Respaldo y Configuración ==="

# ==========================================
# PASO 1: CREAR USUARIO (CONDICIONAL)
# ==========================================
echo "1. Verificando/Creando el usuario '$APP_USUARIO'..."
docker exec -i $CONTAINER_NAME psql -U $DB_SUPERADMIN -d postgres <<EOF
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$APP_USUARIO') THEN
    CREATE ROLE $APP_USUARIO WITH LOGIN PASSWORD '$APP_PASSWORD';
    ALTER ROLE $APP_USUARIO CREATEDB;
    RAISE NOTICE '¡Usuario creado exitosamente!';
  ELSE
    RAISE NOTICE 'El usuario ya existe. Saltando creación.';
  END IF;
END
\$\$;
EOF

# ==========================================
# PASO 2: CREAR BASE DE DATOS NUEVA
# ==========================================
echo "2. Creando la base de datos '$NEW_DB'..."
# Intentamos crearla. Si ya existe, tirará un error leve pero el script continuará.
docker exec -i $CONTAINER_NAME psql -U $DB_SUPERADMIN -c "CREATE DATABASE $NEW_DB OWNER $APP_USUARIO;" 2>/dev/null || echo "(La base de datos probablemente ya existe, continuando...)"

# ==========================================
# PASO 3: COPIAR LOS DATOS
# ==========================================
echo "3. Copiando estructura y datos de '$OLD_DB' a '$NEW_DB'..."
docker exec -i $CONTAINER_NAME pg_dump -U $DB_SUPERADMIN -d $OLD_DB | docker exec -i $CONTAINER_NAME psql -U $DB_SUPERADMIN -d $NEW_DB

echo "=== ¡Todo listo xd! ==="
