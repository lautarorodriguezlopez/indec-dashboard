"""Sondea URLs candidatas de planillas del INDEC y muestra cómo arma los links una página de tema."""
import json, re, sys, urllib.request
H = {"User-Agent": "indec-dashboard/1.0 (+https://github.com/lautarorodriguezlopez/indec-dashboard)"}
B = "https://www.indec.gob.ar/ftp/cuadros/economia/"
cands = ["serie_etn_sam.xlsx","serie_etn_industria.xlsx","serie_etn_industria_manufacturera.xlsx","serie_etn_im.xlsx",
 "serie_supermercados.xlsx","serie_mayoristas.xlsx","serie_centros_compras.xlsx","serie_shoppings.xlsx",
 "cin_II_2026.xls","cin_I_2026.xls","cin_II_2026.xlsx","sh_bal_pag_anual.xls","sh_deuda_externa.xls",
 "sh_isac.xls","sh_isac_permisos.xls","serie_permisos_edificacion.xlsx","sh_permisos_edificacion.xls","isac_cuadros.xls","sh_isac_anexo.xls",
 "eoh_serie.xls","serie_eoh.xlsx","eoh_pernoctes_serie.xlsx","eoh_anexo_cuadros_2025.xlsx","eoh_cuadros_2025.xls"]
out = {"sondeo": {}, "links": {}}
def get(u, n=None):
    req = urllib.request.Request(u, headers=H)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.status, r.headers.get("Content-Type"), (r.read(n) if n else r.read())
for c in cands:
    try:
        s, ct, b = get(B + c, 8); out["sondeo"][c] = [s, ct, b[:8].hex()]
    except Exception as e:
        out["sondeo"][c] = str(e)[:80]
for p in ["https://www.indec.gob.ar/Nivel4/Tema/3/13/56", "https://www.indec.gob.ar/Nivel4/Tema/3/42/131",
          "https://www.indec.gob.ar/Nivel4/Tema/3/35/45", "https://www.indec.gob.ar/Nivel4/Tema/3/3/42",
          "https://www.indec.gob.ar/Nivel4/Tema/3/1/34", "https://www.indec.gob.ar/Nivel4/Tema/3/6/46"]:
    try:
        _, _, b = get(p); h = b.decode("utf-8", "replace")
        out["links"][p] = sorted(set(re.findall(r'''["'(]([^"'()\s]*?\.xlsx?)["')]''', h, re.I)))[:80] + \
            [m for m in re.findall(r'''(?:src|href)=["']([^"']+\.js[^"']*)''', h)][:5]
    except Exception as e:
        out["links"][p] = str(e)[:80]
print(json.dumps(out, ensure_ascii=False))
