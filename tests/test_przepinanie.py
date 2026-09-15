"""Ponowne przetworzenie książki nie może unieważniać zapisanych odpowiedzi.

Wydarzyło się naprawdę: po poprawce odczytu PDF-a obie książki zostały
przetworzone na nowo, akapity dostały nowe numery i wszystkie 58 przypisów
w zapisanych rozmowach wskazywało w pustkę. Klikanie cyferki nie pokazywało
niczego.
"""

from app.db.base import SessionLocal
from app.db.models import Chunk, Conversation, Message, Page, Source
from app.ingest.pipeline import przepnij_odnosniki

AKAPIT = "Pomidory podlewamy bardzo wczesnym rankiem albo wieczorem, nie mocząc liści."


def test_odnosnik_wskazujacy_w_pustke_zostaje_odnaleziony_po_tresci():
    db = SessionLocal()
    source = Source(title="pytest-przepinanie", kind="pdf", object_key="pytest/x", status="ready")
    db.add(source)
    db.flush()
    page = Page(source_id=source.id, number=7)
    db.add(page)
    db.flush()
    stary = Chunk(source_id=source.id, page_id=page.id, seq=0, text=AKAPIT)
    db.add(stary)
    db.flush()
    stary_id = stary.id

    rozmowa = Conversation(title="pytest-przepinanie")
    db.add(rozmowa)
    db.flush()
    wiadomosc = Message(
        conversation_id=rozmowa.id,
        role="assistant",
        text="x",
        answer_json={
            "sentences": [{"text": "x", "verified": True, "sources": [{"chunk_id": stary_id, "marker": 1}]}],
            "sources": [{"marker": 1, "chunk_id": stary_id, "source_id": source.id, "page": 7, "text": AKAPIT}],
        },
    )
    db.add(wiadomosc)
    db.commit()

    try:
        # ponowne przetworzenie: stary akapit znika, wraca ten sam tekst pod nowym numerem
        db.delete(db.get(Chunk, stary_id))
        db.flush()
        nowy = Chunk(source_id=source.id, page_id=page.id, seq=0, text=AKAPIT)
        db.add(nowy)
        db.commit()

        assert przepnij_odnosniki(db, source.id) == 1

        db.expire_all()
        dane = db.get(Message, wiadomosc.id).answer_json
        assert dane["sources"][0]["chunk_id"] == nowy.id
        assert dane["sentences"][0]["sources"][0]["chunk_id"] == nowy.id
    finally:
        db.query(Message).filter_by(conversation_id=rozmowa.id).delete()
        db.query(Conversation).filter_by(id=rozmowa.id).delete()
        db.query(Chunk).filter_by(source_id=source.id).delete()
        db.query(Page).filter_by(source_id=source.id).delete()
        db.query(Source).filter_by(id=source.id).delete()
        db.commit()
        db.close()


def test_odnosnik_do_innej_ksiazki_zostaje_nietkniety():
    """Przepinamy tylko to, co dotyczy przetwarzanego źródła."""
    db = SessionLocal()
    source = Source(title="pytest-przepinanie-2", kind="pdf", object_key="pytest/y", status="ready")
    db.add(source)
    db.flush()
    rozmowa = Conversation(title="pytest-przepinanie-2")
    db.add(rozmowa)
    db.flush()
    wiadomosc = Message(
        conversation_id=rozmowa.id,
        role="assistant",
        text="x",
        answer_json={"sentences": [], "sources": [{"marker": 1, "chunk_id": 999999, "source_id": -1, "page": 1, "text": AKAPIT}]},
    )
    db.add(wiadomosc)
    db.commit()

    try:
        assert przepnij_odnosniki(db, source.id) == 0
        assert db.get(Message, wiadomosc.id).answer_json["sources"][0]["chunk_id"] == 999999
    finally:
        db.query(Message).filter_by(conversation_id=rozmowa.id).delete()
        db.query(Conversation).filter_by(id=rozmowa.id).delete()
        db.query(Source).filter_by(id=source.id).delete()
        db.commit()
        db.close()
