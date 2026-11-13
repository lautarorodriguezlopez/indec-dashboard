# indec-dashboard

Dashboard con las estadísticas oficiales del INDEC, tomadas del [Catálogo API-INDEC](https://api.indec.gob.ar/) (en beta). Se actualiza cada día hábil a las 17:13 (hora argentina), una hora después de que el INDEC publica sus informes.

Fuente de los datos: INDEC.

**Sitio:** https://lautarorodriguezlopez.github.io/indec-dashboard/

## Cómo funciona

1. **Ingesta** (`.github/workflows/ingesta-semanal.yml`): de lunes a viernes a las 17:13 (hora argentina) baja los 19 servicios con `ingesta/ingestar.py`, en modo incremental (pasada completa el primer lunes de cada mes). Guarda los datos en Parquet en el release `datos`.
2. **Publicación** (`.github/workflows/publicar.yml`): `ingesta/sitio.py` arma los JSON del sitio y lo publica en GitHub Pages.
3. **Avisos:** si falla un servicio o al token le quedan menos de 15 días, la corrida falla y GitHub manda un mail.

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
