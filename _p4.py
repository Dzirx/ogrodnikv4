import time
import fitz
from app.db.base import SessionLocal
from app.db.models import Source
from app.ingest.pipeline import _extract_pages
from app.ingest.storage import download_bytes
db = SessionLocal()
s = db.query(Source).filter(Source.title.like("Sułek%")).first()
o = fitz.open(stream=download_bytes(s.object_key), filetype="pdf")
skan = fitz.open()
strony = (30, 31, 32, 37)
for nr in strony:
    r = o[nr-1].rect
    px = o[nr-1].get_pixmap(dpi=200)
    p = skan.new_page(width=r.width, height=r.height)
    p.insert_image(p.rect, pixmap=px)
t = time.time()
wynik = _extract_pages("pdf", skan.tobytes())
czas = time.time() - t
print("%d stron w %.0f s -> %.1f s/stronę | z obrazu: %d" % (len(wynik), czas, czas/len(wynik), sum(1 for _t, z, _tab in wynik if z)))
for nr, (tekst, z, _tab) in zip(strony, wynik):
    print("   strona %d | z obrazu: %-5s | znaków %d" % (nr, z, len(tekst.strip())))
o.close(); skan.close(); db.close()
