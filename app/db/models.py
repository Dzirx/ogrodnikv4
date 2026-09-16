"""Model danych. Dziewiec tabel zamiast dwudziestu osmiu z pierwszej wersji.

Nie ma tu pojec, wymiarow warunkow ani podpisow kontekstu. Znaczenie zdan
rozstrzyga model jezykowy w momencie, w ktorym jest potrzebne - nie budujemy
slownika, ktory i tak zasmiecal sie duplikatami ("temperature", "temperatura",
"soil_temperature" jako trzy osobne wymiary).

Jednostka wszystkiego jest Chunk: akapit zrodla. To on jest wyszukiwany,
cytowany i pokazywany w podgladzie PDF. Cytat nie jest rekordem w bazie, tylko
fragmentem akapitu - dlatego nie da sie go zgubic ani zdublowac.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Source(Base):
    """Ksiazka, prezentacja, transkrypcja albo wklejony tekst."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # kind: pdf | text
    kind: Mapped[str] = mapped_column(String(16))
    object_key: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # pending | ready | error
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    labels: Mapped[list["Label"]] = relationship(secondary="source_labels", lazy="selectin")
    pages: Mapped[list["Page"]] = relationship(back_populates="source", cascade="all, delete-orphan")


class Label(Base):
    """Etykieta tematyczna. Jedno zrodlo moze miec ich kilka - redaktor pytal
    wprost, czy dodane do pomidora widac w pietruszce."""

    __tablename__ = "labels"
    __table_args__ = (UniqueConstraint("code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))


class SourceLabel(Base):
    __tablename__ = "source_labels"

    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    label_id: Mapped[int] = mapped_column(ForeignKey("labels.id"), primary_key=True)


class Page(Base):
    """Strona zrodla. Dla wklejonego tekstu jedna, numer 1.

    Numer strony jest tym, co redaktor widzi przy cytacie i czego uzywa podglad
    PDF (#page=N), wiec musi istniec zawsze."""

    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("source_id", "number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    # Tekst tej strony odczytany z obrazu, nie z warstwy tekstowej. Cytat stad
    # jest mniej pewny - na pomiarach 94-98% slow sie zgadza, a polskie znaki
    # potrafia sie przekrecic ("lodyga" na "todyga").
    z_obrazu: Mapped[bool] = mapped_column(Boolean, default=False)

    source: Mapped["Source"] = relationship(back_populates="pages")


class Chunk(Base):
    """Akapit - jednostka wyszukiwania i cytowania.

    Wszystko, co program mowi, musi dac sie wskazac w konkretnym akapicie.
    Cytat to jego fragment, nie osobny rekord."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class Conversation(Base):
    """Watek rozmowy wraz z wyborem zrodel, z ktorych wolno czerpac.

    Jak w NotebookLM: redaktor zaznacza ksiazki, ktore maja byc brane pod
    uwage, i pyta tylko o nie. Etykiety sluza do szybkiego zaznaczania
    ("wszystko z pomidora"), ale zakres jest zapisany jako konkretne zrodla -
    dodanie nowej ksiazki nie zmienia w locie tego, na czym opieraly sie
    wczesniejsze odpowiedzi.

    Brak wyboru = wszystkie zrodla."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sources: Mapped[list["Source"]] = relationship(
        secondary="conversation_sources", lazy="selectin"
    )


class ConversationSource(Base):
    __tablename__ = "conversation_sources"

    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), primary_key=True)


class Message(Base):
    """Wiadomosc w watku.

    `answer_json` trzyma odpowiedz w postaci, ktora widzi redaktor: zdania wraz
    z przypisanymi do nich cytatami i numerami stron. Bez tego nie da sie
    pokazac podgladu PDF obok tekstu ani zbudowac PDF-a odpowiedzi."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    # user | assistant
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    answer_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Tekst poprawiony recznie przez redaktora. Gdy jest, pokazujemy jego
    # zamiast zdan od modelu - ale zrodla zostaja, bo tresc nadal na nich
    # sie opiera.
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # pending | ready | error - odpowiedz powstaje w tle
    status: Mapped[str] = mapped_column(String(16), default="ready")


class Conflict(Base):
    """Dwa zrodla podaja inna wartosc tej samej rzeczy.

    JEDYNE miejsce, w ktorym program pyta redaktora o cokolwiek.

    `subject` to opis wlasnymi slowami ("optymalny odczyn gleby dla pomidora"),
    nie kod ze slownika - wykrywa go model, nie kod, wiec nie ma slownika do
    zasmiecenia."""

    __tablename__ = "conflicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(512))
    # Odcisk tematu - zeby ten sam konflikt nie wrocil po ponownym przetworzeniu.
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # open | resolved
    status: Mapped[str] = mapped_column(String(16), default="open")
    resolved_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # source | editorial - czy przyjeta wartosc pochodzi ze zrodla, czy od redaktora
    resolved_origin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    options: Mapped[list["ConflictOption"]] = relationship(
        back_populates="conflict", cascade="all, delete-orphan", lazy="selectin"
    )


class ConflictOption(Base):
    """Jedna z wartosci podanych przez zrodla, wraz z cytatem, ktory ja potwierdza."""

    __tablename__ = "conflict_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conflict_id: Mapped[int] = mapped_column(ForeignKey("conflicts.id"), index=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("chunks.id"))
    value: Mapped[str] = mapped_column(String(255))
    quote: Mapped[str] = mapped_column(Text)

    conflict: Mapped["Conflict"] = relationship(back_populates="options")
