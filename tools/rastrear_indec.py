"""Busca las planillas (xls/xlsx) que publica el INDEC en sus páginas de temas.
Solo lectura; usado para planificar la fase 2."""
import json, re, sys, time, urllib.request
from html import unescape

H = {"User-Agent": "indec-dashboard/1.0 (+https://github.com/lautarorodriguezlopez/indec-dashboard)"}
BASE = "https://www.indec.gob.ar"
def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"ERR {url} {e}", file=sys.stderr); return ""

paginas = [f"{BASE}/indec/web/Nivel3-Tema-3-{i}" for i in range(1, 46)]
vistas, links = set(), {}
cola = list(paginas)
while cola and len(vistas) < 160:
    u = cola.pop(0)
    if u in vistas: continue
    vistas.add(u)
    html = get(u); time.sleep(0.6)
    titulo = re.search(r"<title>(.*?)</title>", html, re.S)
    for m in re.finditer(r'href="([^"]+?\.(?:xls|xlsx))"', html, re.I):
        href = m.group(1)
        href = href if href.startswith("http") else BASE + "/" + href.lstrip("/")
        ctx = re.sub(r"<[^>]+>", " ", html[max(0, m.start()-300):m.end()+200])
        links.setdefault(href, {"pagina": u, "contexto": " ".join(unescape(ctx).split())[-220:]})
    if "Nivel3" in u:
        for m in re.finditer(r'href="(/indec/web/Nivel4-Tema-3-[0-9-]+)"', html):
            cola.append(BASE + m.group(1))
print(json.dumps({"paginas": len(vistas), "planillas": links}, ensure_ascii=False))
