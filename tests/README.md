# Tests del Edge (pytest)

Suite de pruebas del servicio edge. Cubre la lógica de dominio, el contrato HTTP
de la API Flask y la orquestación de sincronización con el backend.

## Estructura

| Archivo | Capa | Qué prueba |
|---|---|---|
| `conftest.py` | — | Fixtures compartidas (`db_session`, `app_client`). |
| `test_domain_services.py` | Dominio | Reglas puras: normalización de lecturas, rangos físicos, validación de umbrales, estado + `actuatorCommand` + alertas por variable. |
| `test_edge_api.py` | API (HTTP) | Endpoints Flask: health, auth, lecturas, umbrales por defecto, sensor OFFLINE, sync, announce. |
| `test_account_onboarding.py` | API (HTTP) | Onboarding de cuenta `/api/v1/edge/account` (mockea `sign_in`). |
| `test_sync_services.py` | Application | Sync worker: outbox (push), dispositivos sin lote, rechazos 4xx, pull de umbrales. |

## Instalación (una sola vez)

Desde la raíz del repo (`edge-clean`):

```powershell
pip install -r requirements-dev.txt
```

Trae las dependencias de runtime (`requirements.txt`) **más** `pytest`.

> **Recomendado:** usar un entorno virtual para no ensuciar el Python global.
>
> ```powershell
> python -m venv .venv
> .\.venv\Scripts\Activate.ps1
> pip install -r requirements-dev.txt
> ```

## Cómo correrlos

Siempre desde la raíz del repo:

| Comando | Para qué |
|---|---|
| `python -m pytest` | Corre toda la suite. |
| `python -m pytest -q` | Salida compacta (una línea de puntos). |
| `python -m pytest -v` | Verbose: nombre de cada test + PASSED/FAILED. |
| `python -m pytest tests/test_edge_api.py` | Solo un archivo. |
| `python -m pytest tests/test_edge_api.py::test_sync_requires_device_credentials` | Un solo test. |
| `python -m pytest -k "sync or account"` | Filtra por subcadena del nombre. |
| `python -m pytest -x` | Se detiene en el **primer** fallo. |
| `python -m pytest --lf` | Re-corre solo los que fallaron la última vez (*last-failed*). |
| `python -m pytest -s` | Muestra los `print()` (no captura stdout). |

> Usa `python -m pytest` en vez de `pytest` a secas: garantiza que se use el
> Python/entorno correcto y que la raíz del proyecto quede en el `sys.path` (así
> los `import iam...` funcionan).

## Cómo leer un fallo

Cuando algo falla, pytest muestra el bloque de la aserción con `assert`, el valor
izquierdo (obtenido) y el derecho (esperado), y un resumen `short test summary`.
La rutina: mira la última línea (`FAILED tests/...::nombre`), sube al `assert` que
reventó, y compara *obtenido vs esperado*.

## Buenas prácticas (aplicadas en esta suite)

1. **Aislar el estado — cada test parte de cero.** El fixture `db_session` crea una
   **SQLite nueva en `tmp_path`** por test y la cierra al terminar; nunca toca
   `edge_clean.db` real. Un test no debe depender de que otro haya corrido antes.

2. **No salir a la red ni tocar servicios reales.** Dos técnicas:
   - `monkeypatch.setattr(BackendClient, "sign_in", ...)` sustituye la llamada al
     backend (ver `test_account_onboarding.py`).
   - *Fakes* inyectados: `SuccessfulBackendClient` / `RejectingBackendClient` se
     pasan al constructor (`TelemetrySyncService(backend_client=...)`), gracias a
     que el código usa **inyección de dependencias**.
   - En `conftest.py` se neutraliza el worker: `sync_worker.start`/`notify` → no-op.

3. **Nombrar por comportamiento, no por método.** `test_sync_skips_unassigned_device_and_reports_pending`
   dice *qué* se verifica; cuando falla, ya sabes qué se rompió sin leer el cuerpo.

4. **Arrange–Act–Assert.** Prepara datos → ejecuta una sola acción → afirma el
   resultado. Una sola "acción" por test.

5. **Probar el camino feliz *y* los bordes.** Umbrales: caso válido + casos límite
   (`-41`, `81`, `101`). Cuenta: válida, campos faltantes (400), credenciales
   malas (401), backend caído (502).

6. **Parametrizar en lugar de copiar-pegar.** `@pytest.mark.parametrize` corre el
   mismo test con muchos inputs (ver `test_domain_services.py`). Un caso nuevo es
   una fila más, no una función nueva.

7. **Testear la capa correcta.**
   - Reglas de negocio puras → **dominio** (sin DB ni Flask): rápido y directo.
   - Contrato HTTP (status codes, JSON, auth) → **API** con `app_client`.
   - Orquestación (outbox, pull) → **application** con fakes.
   Pirámide: muchos tests de dominio (baratos), menos de API (integración).

8. **Un `assert` por concepto.** Varios `assert` está bien si validan una misma
   respuesta (status + campos del JSON); no mezcles dos comportamientos distintos.

## Fixtures disponibles (`conftest.py`)

| Fixture | Da | Uso |
|---|---|---|
| `db_session` | Base SQLite temporal ya inicializada + dispositivo de desarrollo (`tracksilo-001`). | Tests de repositorios / application. |
| `app_client` | Cliente de test de Flask (`app.test_client()`) con el worker neutralizado. Depende de `db_session`. | Tests de endpoints HTTP. |

## Áreas sin cubrir todavía

- `POST /api/v1/edge/devices/{id}/assign` y `/reset` (asignación de lotes).
- `GET /api/v1/edge/lots` (requiere mockear `get_coffee_lots`).
- Dashboard (`build_snapshot`, stream SSE).
- Re-firmado ante `401` en `BackendClient._request`.
