"""Ponowne przetworzenie książki nie może unieważniać zapisanych odpowiedzi.

Wydarzyło się naprawdę: po poprawce odczytu PDF-a obie książki zostały
przetworzone na nowo, akapity dostały nowe numery i wszystkie 58 przypisów
w zapisanych rozmowach wskazywało w pustkę. Klikanie cyferki nie pokazywało
niczego.
"""

from app.db.base import SessionLocal
from app.db.models import Chunk, Conflict, ConflictOption, Conversation, Message, Page, Source
from app.ingest.pipeline import _odepnij_konflikty, _przypnij_konflikty, przepnij_odnosniki

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


def test_konflikt_przetrwa_ponowne_przetworzenie_jednej_ze_stron():
    """Wydarzyło się naprawdę: ConflictOption.chunk_id ma klucz obcy bez
    ON DELETE CASCADE, więc kasowanie starych akapitów przy ponownym
    przetworzeniu źródła wywalało się na bazie, jeśli którykolwiek z nich
    był stroną (choćby już rozstrzygniętego) sporu."""
    db = SessionLocal()
    zrodlo_a = Source(title="pytest-konflikt-a", kind="text", object_key="pytest/a", status="ready")
    zrodlo_b = Source(title="pytest-konflikt-b", kind="text", object_key="pytest/b", status="ready")
    db.add_all([zrodlo_a, zrodlo_b])
    db.flush()
    strona_a = Page(source_id=zrodlo_a.id, number=1)
    strona_b = Page(source_id=zrodlo_b.id, number=1)
    db.add_all([strona_a, strona_b])
    db.flush()
    stary_a = Chunk(source_id=zrodlo_a.id, page_id=strona_a.id, seq=0, text="Odczyn gleby pH 5,5-6,5.")
    chunk_b = Chunk(source_id=zrodlo_b.id, page_id=strona_b.id, seq=0, text="Odczyn gleby pH 7,0-7,5.")
    db.add_all([stary_a, chunk_b])
    db.flush()

    konflikt = Conflict(subject="pytest-spor", fingerprint="pytest-fp-1", status="resolved", resolved_value="6,0")
    konflikt.options = [
        ConflictOption(chunk_id=stary_a.id, value="5,5-6,5", quote="Odczyn gleby pH 5,5-6,5."),
        ConflictOption(chunk_id=chunk_b.id, value="7,0-7,5", quote="Odczyn gleby pH 7,0-7,5."),
    ]
    db.add(konflikt)
    db.commit()
    konflikt_id = konflikt.id

    try:
        # Ponowne przetworzenie zrodla A: stary akapit znika, ten sam tekst
        # wraca pod nowym id - dokladnie to, co process_source robi naprawde.
        zdjete = _odepnij_konflikty(db, [stary_a.id])
        assert len(zdjete) == 1

        db.delete(db.get(Chunk, stary_a.id))
        db.flush()
        nowy_a = Chunk(source_id=zrodlo_a.id, page_id=strona_a.id, seq=0, text="Odczyn gleby pH 5,5-6,5.")
        db.add(nowy_a)
        db.commit()

        _przypnij_konflikty(db, zrodlo_a.id, zdjete)

        db.expire_all()
        po = db.get(Conflict, konflikt_id)
        assert po is not None, "rozstrzygniety spor nie moze zniknac, gdy cytat da sie odnalezc"
        assert po.resolved_value == "6,0"
        wartosci = {o.value: o.chunk_id for o in po.options}
        assert wartosci["5,5-6,5"] == nowy_a.id
        assert wartosci["7,0-7,5"] == chunk_b.id, "strona nietknietego zrodla ma zostac bez zmian"
    finally:
        db.query(ConflictOption).filter_by(conflict_id=konflikt_id).delete()
        db.query(Conflict).filter_by(id=konflikt_id).delete()
        db.query(Chunk).filter(Chunk.source_id.in_([zrodlo_a.id, zrodlo_b.id])).delete(synchronize_session=False)
        db.query(Page).filter(Page.source_id.in_([zrodlo_a.id, zrodlo_b.id])).delete(synchronize_session=False)
        db.query(Source).filter(Source.id.in_([zrodlo_a.id, zrodlo_b.id])).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_konflikt_znika_gdy_cytatu_nie_da_sie_juz_odnalezc():
    """Tresc zrodla naprawde sie zmienila, nie tylko przesunela - polowiczny
    spor bez jednej ze stron nie ma czego pokazac redaktorowi."""
    db = SessionLocal()
    zrodlo_a = Source(title="pytest-konflikt-c", kind="text", object_key="pytest/c", status="ready")
    zrodlo_b = Source(title="pytest-konflikt-d", kind="text", object_key="pytest/d", status="ready")
    db.add_all([zrodlo_a, zrodlo_b])
    db.flush()
    strona_a = Page(source_id=zrodlo_a.id, number=1)
    strona_b = Page(source_id=zrodlo_b.id, number=1)
    db.add_all([strona_a, strona_b])
    db.flush()
    stary_a = Chunk(source_id=zrodlo_a.id, page_id=strona_a.id, seq=0, text="Odczyn gleby pH 5,5-6,5.")
    chunk_b = Chunk(source_id=zrodlo_b.id, page_id=strona_b.id, seq=0, text="Odczyn gleby pH 7,0-7,5.")
    db.add_all([stary_a, chunk_b])
    db.flush()

    konflikt = Conflict(subject="pytest-spor-2", fingerprint="pytest-fp-2", status="open")
    konflikt.options = [
        ConflictOption(chunk_id=stary_a.id, value="5,5-6,5", quote="Odczyn gleby pH 5,5-6,5."),
        ConflictOption(chunk_id=chunk_b.id, value="7,0-7,5", quote="Odczyn gleby pH 7,0-7,5."),
    ]
    db.add(konflikt)
    db.commit()
    konflikt_id = konflikt.id

    try:
        zdjete = _odepnij_konflikty(db, [stary_a.id])
        db.delete(db.get(Chunk, stary_a.id))
        db.flush()
        # Zupelnie inna tresc - poprzedni cytat nigdzie juz nie wystepuje.
        db.add(Chunk(source_id=zrodlo_a.id, page_id=strona_a.id, seq=0, text="Rozstaw sadzenia 60 cm."))
        db.commit()

        _przypnij_konflikty(db, zrodlo_a.id, zdjete)

        db.expire_all()
        assert db.get(Conflict, konflikt_id) is None
        assert db.query(ConflictOption).filter_by(chunk_id=chunk_b.id).count() == 0
    finally:
        db.query(ConflictOption).filter_by(conflict_id=konflikt_id).delete()
        db.query(Conflict).filter_by(id=konflikt_id).delete()
        db.query(Chunk).filter(Chunk.source_id.in_([zrodlo_a.id, zrodlo_b.id])).delete(synchronize_session=False)
        db.query(Page).filter(Page.source_id.in_([zrodlo_a.id, zrodlo_b.id])).delete(synchronize_session=False)
        db.query(Source).filter(Source.id.in_([zrodlo_a.id, zrodlo_b.id])).delete(synchronize_session=False)
        db.commit()
        db.close()
