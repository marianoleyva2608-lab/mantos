# Panel de Checador — Hikvision DS-K1T343 (Maravillas)

Panel independiente (dentro del repo mantos, carpeta `checador/`) que recibe las
checadas del checador por **HTTP Listening**, las guarda en **Supabase** (misma
instancia que mantos, vía la API REST por Kong) y las muestra con filtros + CSV.

```
Checador --HTTPS POST /checador--> este panel --REST(Kong)--> Supabase --> tabla checadas
```

## 1. Crear la tabla (una vez)
En Supabase Studio → SQL Editor, pega y ejecuta `schema_checadas.sql`.

## 2. Desplegar en Easypanel (como servicio nuevo del proyecto `manto`)
Al estar en el mismo proyecto comparte red con Supabase y puede usar la URL
interna de Kong (igual que la app adpack).

1. Proyecto **manto** → **+** (nueva app) → nombre `checador`.
2. Fuente: GitHub → repo `marianoleyva2608-lab/mantos`, rama `main`,
   **Build Path / subcarpeta = `checador`** (para que use el Dockerfile de esta carpeta).
3. Variables de entorno (copiar de la app adpack):
   - `SUPABASE_INTERNAL_URL` = `http://manto_supabase_kong:8000`
   - `SUPABASE_SERVICE_KEY`  = (el mismo service key que usa adpack)
   - `APP_TITLE` = `Panel de Checador`  (opcional)
   - `NAME_MAP` = opcional, si el aparato manda número sin nombre:
     `1001=Juan Perez;1002=Maria Lopez`
4. Puerto: `8080`.
5. Deploy → Easypanel asigna un dominio (ej. `checador-xxxx.easypanel.host`)
   con HTTPS. Abre `https://TU-DOMINIO/health` → debe decir `supabase: ok`.

## 3. Configurar el checador (HTTP Listening)
System Configuration → Network → Network Service → HTTP(S) → **HTTP Listening**:

| Campo | Valor |
|---|---|
| Event Alarm IP/Domain Name | el dominio del panel (NO el de adpack) |
| URL | `/checador` |
| Port | `443` |
| Protocol | HTTPS |

Guardar. Luego desactivar **"Save Picture When Auth"** en el checador
(si está activo, el envío de eventos se traba).

## 4. Probar
Alguien checa en el aparato → en segundos aparece la fila en el panel.
Si no, revisar los logs del servicio en Easypanel.
