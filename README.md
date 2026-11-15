# indec-dashboard

Dashboard con las estadísticas oficiales del INDEC, tomadas del [Catálogo API-INDEC](https://api.indec.gob.ar/) (en beta). Se actualiza cada día hábil a las 17:13 (hora argentina), una hora después de que el INDEC publica sus informes.

Fuente de los datos: INDEC.

**Sitio:** https://lautarorodriguezlopez.github.io/indec-dashboard/

## Usalo vos

Hay tres formas, de la más simple a la más completa:

1. **Mirar el sitio:** https://lautarorodriguezlopez.github.io/indec-dashboard/. En la pestaña *Explorador* podés filtrar y graficar cualquiera de los 19 datasets y bajar el resultado en CSV, todo dentro de tu navegador.
2. **Bajar los datos:** los 19 servicios están en Parquet en el [release `datos`](https://github.com/lautarorodriguezlopez/indec-dashboard/releases/tag/datos) y en la sección *Datos* del sitio. Se abren con pandas, R, DuckDB o Power BI, sin token:

   ```python
   import pandas as pd
   url = "https://lautarorodriguezlopez.github.io/indec-dashboard/datos/ipc.parquet"
   ipc = pd.read_parquet(url)
   ```

3. **Tener tu propia copia:** hacé un fork, sacá tu token gratis en [api.indec.gob.ar](https://api.indec.gob.ar/), cargalo como secreto `INDEC_API_TOKEN` (*Settings → Secrets and variables → Actions*), activá *Settings → Pages → Source: GitHub Actions* y habilitá los workflows en la pestaña *Actions*. Después corré **Ingesta INDEC** a mano con *Pasada completa* tildado.

Los datos son del INDEC, que permite copiarlos, reutilizarlos y redistribuirlos siempre que se cite la fuente.

## Cómo funciona

1. **Ingesta** (`.github/workflows/ingesta-semanal.yml`): de lunes a viernes a las 17:13 (hora argentina) baja los 19 servicios con `ingesta/ingestar.py`, en modo incremental (pasada completa el primer lunes de cada mes). Guarda los datos en Parquet en el release `datos`.
2. **Más indicadores** (`ingesta/series_tiempo.py`): en la misma corrida baja 38 series que no están en la API del INDEC (consumo, construcción, industria, turismo, PIB, Gini y servicios públicos del INDEC; empleo registrado del SIPA; RIPTE, salario mínimo y jubilación mínima; recaudación y resultado primario del Ministerio de Economía) desde la [API de Series de Tiempo de datos.gob.ar](https://datos.gob.ar/series/api), sin token. La lista está en `ingesta/series.json`, y cada serie se marca como atrasada si su último dato es más viejo de lo esperable. Además, `ingesta/planillas.py` lee 15 series que el INDEC solo publica en planillas Excel junto a sus informes: permisos de edificación, ocupación hotelera, confianza empresarial, balanza de pagos y deuda externa.
3. **BCRA** (`ingesta/bcra.py`): en la misma corrida baja 16 variables de la [API pública de Estadísticas Monetarias v4 del BCRA](https://www.bcra.gob.ar/en/central-bank-api-catalog/), sin token ni costo: dólar mayorista y minorista, bandas cambiarias, reservas, tasas (BADLAR, TAMAR, plazo fijo, préstamos personales), base monetaria, depósitos, préstamos, M2, inflación esperada (REM), UVA e ICL. La lista está en `ingesta/bcra.json`. El sitio las muestra en la pestaña *Dólar y tasas* con datos semanales para que cargue rápido.
4. **Publicación** (`.github/workflows/publicar.yml`): `ingesta/sitio.py` arma los JSON del sitio y lo publica en GitHub Pages.
5. **Avisos:** si falla un servicio, una serie o una variable del BCRA, o al token le quedan menos de 15 días, la corrida falla y GitHub manda un mail. Las series atrasadas se avisan una vez por semana, los lunes.

## Correr la prueba de ingesta en tu compu

1. Copiá `.env.example` como `.env` y pegá tu token después del `=`. El `.env` no se sube al repo.
2. Instalá las dependencias e iniciá la prueba:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python ingesta/prueba_ingesta.py
   ```

La prueba baja IPC, EMAE e índice de salarios desde 2023. Los guarda en `data/indec.duckdb` y escribe un resumen en `salida/`. Las dos carpetas quedan fuera del repo.

## Correrla en GitHub

Pestaña **Actions** → **Prueba de ingesta INDEC** → **Run workflow**. Usa el secreto `INDEC_API_TOKEN` del repo, y los resultados quedan como artifact durante 7 días.

## Seguridad

El diseño sigue OWASP Top 10 y OWASP API Security Top 10: no hay servidor propio, el token nunca llega al navegador, las consultas del explorador están parametrizadas y el sitio tiene una Content-Security-Policy estricta. El detalle y cómo reportar vulnerabilidades están en [SECURITY.md](SECURITY.md).

## Licencia

El código está bajo licencia [MIT](LICENSE). Los datos son del INDEC: se pueden reutilizar citando la fuente.
