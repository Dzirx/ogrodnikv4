"""Zadania w tle. Kolejka, bo przetworzenie ksiazki i ulozenie odpowiedzi
trwaja minuty, a przegladarka tyle nie czeka."""

from redis import Redis
from rq import Queue

from app.config import settings

queue = Queue("ogrodnik", connection=Redis.from_url(settings.redis_url))


def przetworz_zrodlo(source_id: int) -> None:
    from app.ingest.pipeline import process_source

    process_source(source_id)


def odpowiedz_na_pytanie(message_id: int) -> None:
    from app.answer.build import answer_question
    from app.db.base import SessionLocal
    from app.db.models import Conversation, Message

    db = SessionLocal()
    try:
        message = db.get(Message, message_id)
        if message is None:
            return

        wczesniejsze = (
            db.query(Message)
            .filter(Message.conversation_id == message.conversation_id, Message.id < message.id)
            .order_by(Message.id)
            .all()
        )
        pytanie = next((m for m in reversed(wczesniejsze) if m.role == "user"), None)
        # Historia BEZ ostatniego pytania - ono idzie osobno. Bez tego model
        # dostawalby je dwa razy.
        historia = [
            (m.role, m.text)
            for m in wczesniejsze
            if m.text and (pytanie is None or m.id != pytanie.id)
        ]

        rozmowa = db.get(Conversation, message.conversation_id)
        zakres = [s.id for s in rozmowa.sources] if rozmowa else []

        try:
            message.answer_json = answer_question(
                pytanie.text if pytanie else "", source_ids=zakres, historia=historia
            )
            # Tekst odpowiedzi zapisujemy osobno: historia rozmowy korzysta z
            # niego przy przepisywaniu kolejnego pytania.
            message.text = " ".join(
                z["text"] for z in message.answer_json.get("sentences", [])
            ) or (message.answer_json.get("note") or "")
            message.status = "ready"
        except Exception as exc:
            message.answer_json = {"sentences": [], "sources": [], "note": f"Nie udało się: {exc}"}
            message.status = "error"
        db.commit()
    finally:
        db.close()
