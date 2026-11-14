# Seguridad

Este proyecto publica datos públicos del INDEC. No guarda datos personales, no tiene cuentas de usuario ni servidor propio. Igual se diseñó siguiendo el [OWASP Top 10 (2021)](https://owasp.org/Top10/) y el [OWASP API Security Top 10 (2023)](https://owasp.org/API-Security/editions/2023/en/0x11-t10/), porque la superficie que existe (el token de la API, el pipeline y el sitio) merece el mismo cuidado.

## Reportar una vulnerabilidad

Si encontrás un problema de seguridad, **no abras un issue público**. Usá *Security → Report a vulnerability* en este repositorio (reporte privado de GitHub). Respondo dentro de 7 días.

## Arquitectura en una línea

GitHub Actions baja los datos con el token (secreto del repo) → los guarda en Parquet y en una base DuckDB de solo lectura → GitHub Pages sirve un sitio estático. **El navegador nunca ve el token ni habla con la API del INDEC.**

## Cómo se aplica OWASP Top 10 (2021)

| Riesgo | Cómo se mitiga acá |
|---|---|
| **A01 Control de acceso** | No hay áreas privadas ni datos de usuarios: todo lo publicado es público por diseño. Los workflows solo corren por horario o a mano (`workflow_dispatch`, que solo pueden disparar quienes tienen permisos de escritura); ninguno se ejecuta con `pull_request` de terceros, así que un fork no puede leer el secreto. Cada workflow pide el mínimo de permisos de `GITHUB_TOKEN`. |
| **A02 Fallas criptográficas / secretos** | El token JWT del INDEC vive solo en *Actions secrets* y en un `.env` local excluido por `.gitignore`. Nunca se imprime (el script lee su fecha de vencimiento sin mostrarlo) y GitHub lo enmascara en los logs. Secret scanning y push protection activados en el repositorio. HTTPS obligatorio (GitHub Pages). |
| **A03 Inyección (SQL, HTML, CSV)** | **SQL:** el explorador usa sentencias preparadas: todo valor elegido por el usuario va como parámetro `?`, nunca concatenado. Tablas y columnas salen de una lista blanca (`explorador.json`) y además se validan con `^[a-z][a-z0-9_]{0,62}$`. **HTML/XSS:** el texto que viene de los datos se inserta con `textContent` o se escapa con `esc()`. **CSV:** las celdas que empiezan con `= + - @` tab o CR se neutralizan con `'` (inyección de fórmulas). **Shell:** los inputs de los workflows llegan por variable de entorno, no interpolados. |
| **A04 Diseño inseguro** | Sin backend: no hay servidor, base de datos remota ni API propia que atacar. La base del explorador se abre en **solo lectura**; después se desactivan la carga de extensiones y el acceso a archivos externos (`enable_external_access = false`) y se bloquea la configuración (`lock_configuration = true`). Aun con una inyección, no se podría leer otra cosa ni cambiar esos ajustes. |
| **A05 Configuración insegura** | Content-Security-Policy estricta (`default-src 'none'`, scripts, estilos, conexiones y workers solo del propio sitio, sin `unsafe-inline` ni `unsafe-eval`; solo `wasm-unsafe-eval` para el motor WebAssembly), `base-uri 'none'`, `form-action 'none'`, `object-src 'none'` y `Referrer-Policy: no-referrer`. Sin estilos ni scripts en línea. |
| **A06 Componentes vulnerables** | Versiones fijadas: `pyindec==0.1.0`, `@duckdb/duckdb-wasm@1.32.0` (estable, no *dev*) y `esbuild` exacto, con `package-lock.json`. El build corre `npm audit` y falla ante vulnerabilidades altas. Dependabot abre PRs semanales para acciones, pip y npm. |
| **A07 Autenticación** | El sitio no tiene login. El único secreto (token del INDEC) se rota desde el perfil de la API; generar uno nuevo revoca el anterior. La corrida falla y avisa por mail 15 días antes de que venza. |
| **A08 Integridad de software y datos** | El motor del explorador (DuckDB-WASM) se **sirve desde el propio sitio**, construido en el pipeline con dependencias fijadas e `npm ci --ignore-scripts` (sin scripts de instalación de terceros). El build registra el SHA-256 de cada binario publicado. El navegador no descarga código de CDNs ni extensiones de terceros. |
| **A09 Registro y monitoreo** | Cada corrida deja un resumen (servicios OK, filas, último período) y un `estado.json`. Si falla un servicio o el token está por vencer, la corrida falla y GitHub envía un mail. |
| **A10 SSRF** | No aplica: no hay servidor que haga pedidos a URLs elegidas por el usuario. El motor del navegador solo lee `datos/explorador.duckdb`, registrado por el código. |

## OWASP API Security Top 10 (2023)

El proyecto **consume** una API (la del INDEC) y **expone** archivos estáticos.

| Riesgo | Cómo se mitiga |
|---|---|
| **API1 / API3 / API5 Autorización (objetos, propiedades, funciones)** | No hay API propia ni objetos por usuario: todo lo expuesto es público. |
| **API2 Autenticación rota** | El token se usa solo del lado del servidor (Actions), con esquema Bearer sobre HTTPS contra `https://api.indec.gob.ar/v1`. |
| **API4 Consumo de recursos sin límite** | Hacia el INDEC: ingesta incremental (solo desde el año anterior), una corrida por día hábil, reintentos con espera ante 429. En el explorador: tabla de a 100 filas, descarga máxima de 200.000 filas, una consulta a la vez. |
| **API6 Acceso irrestricto a flujos sensibles** | No hay flujos sensibles (sin compras, cuentas ni formularios). |
| **API7 SSRF** | Ver A10. |
| **API8 Configuración insegura** | Ver A05. |
| **API9 Inventario** | Los 19 servicios consumidos están listados en `ingesta/ingestar.py` y en la sección *Datos* del sitio. |
| **API10 Consumo inseguro de APIs** | Lo que devuelve la API del INDEC se trata como no confiable: se valida (filas > 0, tipos), se guarda como datos y se escapa al mostrarlo. Si un servicio falla, se conserva la versión anterior. |

## Límites conocidos

- GitHub Pages no permite enviar cabeceras HTTP propias: la CSP va como `<meta>`, así que `frame-ancestors` (protección contra *clickjacking*) no se puede aplicar. El sitio no tiene acciones sensibles que se puedan secuestrar con un clic.
- El worker de DuckDB-WASM no hereda la CSP de la página. Por eso, además, se desactivan las extensiones y el acceso externo dentro del motor.
- `pyindec` es una librería de terceros que maneja el token mientras corre. Está fijada a una versión exacta y Dependabot avisa de cambios.
