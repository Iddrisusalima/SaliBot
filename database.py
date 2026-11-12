from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import hmac
import secrets

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

Path("data").mkdir(exist_ok=True)

DATABASE_URL = "sqlite:///data/chatbot_memory.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String, unique=True, index=True)
    title = Column(String, default="New Chat")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    # SaliBot upgrade: who owns this chat, and is it pinned?
    user_id = Column(Integer, index=True, nullable=True)
    pinned = Column(Boolean, default=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String, index=True)
    role = Column(String)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class LongTermMemory(Base):
    __tablename__ = "long_term_memory"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String, index=True)
    memory = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------
# SaliBot upgrade: user accounts
# ---------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class LoginSession(Base):
    __tablename__ = "login_sessions"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True)
    user_id = Column(Integer, index=True)
    expires_at = Column(DateTime)


SESSION_DAYS = 30
PASSWORD_ROUNDS = 200_000


def init_db():
    Base.metadata.create_all(bind=engine)

    # SaliBot upgrade: add the new columns to an existing chats table
    columns = {c["name"] for c in inspect(engine).get_columns("conversations")}
    with engine.begin() as conn:
        if "user_id" not in columns:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN user_id INTEGER"))
        if "pinned" not in columns:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN pinned BOOLEAN DEFAULT 0"))


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PASSWORD_ROUNDS)
    return f"pbkdf2${PASSWORD_ROUNDS}${salt}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds))
        return hmac.compare_digest(digest.hex(), expected)
    except Exception:
        return False


def create_user(name: str, email: str, password: str):
    """Returns the new user, or None if the email is already registered."""
    db = SessionLocal()

    try:
        if db.query(User).filter(User.email == email).first():
            return None

        is_first_user = db.query(User).count() == 0

        user = User(
            name=name,
            email=email,
            password_hash=hash_password(password),
            created_at=datetime.utcnow()
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # The very first account keeps the chats made before accounts existed
        if is_first_user:
            db.query(Conversation).filter(Conversation.user_id.is_(None)).update({"user_id": user.id})
            db.commit()
            db.refresh(user)

        db.expunge(user)
        return user

    finally:
        db.close()


def authenticate_user(email: str, password: str):
    db = SessionLocal()

    try:
        user = db.query(User).filter(User.email == email).first()

        if user and check_password(password, user.password_hash):
            db.expunge(user)
            return user

        return None

    finally:
        db.close()


def create_login_session(user_id: int) -> str:
    db = SessionLocal()

    try:
        token = secrets.token_urlsafe(32)
        db.add(LoginSession(
            token=token,
            user_id=user_id,
            expires_at=datetime.utcnow() + timedelta(days=SESSION_DAYS)
        ))
        db.commit()
        return token

    finally:
        db.close()


def get_user_by_token(token: str | None):
    if not token:
        return None

    db = SessionLocal()

    try:
        session = db.query(LoginSession).filter(LoginSession.token == token).first()

        if not session or session.expires_at < datetime.utcnow():
            return None

        user = db.query(User).filter(User.id == session.user_id).first()

        if user:
            db.expunge(user)

        return user

    finally:
        db.close()


def delete_login_session(token: str):
    db = SessionLocal()

    try:
        db.query(LoginSession).filter(LoginSession.token == token).delete()
        db.commit()

    finally:
        db.close()


# ---------------------------------------------------------------
# SaliBot upgrade: chat ownership, rename, pin, delete
# ---------------------------------------------------------------

def get_conversation_owner(thread_id: str):
    """Returns (exists, user_id) for a chat."""
    db = SessionLocal()

    try:
        conversation = db.query(Conversation).filter(Conversation.thread_id == thread_id).first()
        return (conversation is not None, conversation.user_id if conversation else None)

    finally:
        db.close()


def claim_conversation(thread_id: str, user_id: int):
    db = SessionLocal()

    try:
        db.query(Conversation).filter(Conversation.thread_id == thread_id).update({"user_id": user_id})
        db.commit()

    finally:
        db.close()


def rename_conversation(thread_id: str, title: str):
    db = SessionLocal()

    try:
        db.query(Conversation).filter(Conversation.thread_id == thread_id).update({"title": title})
        db.commit()

    finally:
        db.close()


def set_conversation_pinned(thread_id: str, pinned: bool):
    db = SessionLocal()

    try:
        db.query(Conversation).filter(Conversation.thread_id == thread_id).update({"pinned": pinned})
        db.commit()

    finally:
        db.close()


def delete_conversation(thread_id: str):
    """Deletes the chat, its messages and its saved memories."""
    db = SessionLocal()

    try:
        db.query(ChatMessage).filter(ChatMessage.thread_id == thread_id).delete()
        db.query(LongTermMemory).filter(LongTermMemory.thread_id == thread_id).delete()
        db.query(Conversation).filter(Conversation.thread_id == thread_id).delete()
        db.commit()

    finally:
        db.close()


def create_or_update_conversation(thread_id: str, first_message: str | None = None):
    db = SessionLocal()

    try:
        conversation = (
            db.query(Conversation)
            .filter(Conversation.thread_id == thread_id)
            .first()
        )

        if not conversation:
            title = "New Chat"

            if first_message:
                title = first_message.strip()[:40]
                if len(first_message.strip()) > 40:
                    title += "..."

            conversation = Conversation(
                thread_id=thread_id,
                title=title,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(conversation)

        else:
            conversation.updated_at = datetime.utcnow()

        db.commit()

    finally:
        db.close()


def list_conversations(user_id: int | None = None):
    db = SessionLocal()

    try:
        query = db.query(Conversation)

        # SaliBot upgrade: only this user's chats, pinned chats first
        if user_id is not None:
            query = query.filter(Conversation.user_id == user_id)

        return (
            query
            .order_by(Conversation.pinned.desc(), Conversation.updated_at.desc())
            .all()
        )

    finally:
        db.close()


def save_chat_message(thread_id: str, role: str, content: str):
    db = SessionLocal()

    try:
        msg = ChatMessage(
            thread_id=thread_id,
            role=role,
            content=content,
            created_at=datetime.utcnow()
        )

        db.add(msg)

        conversation = (
            db.query(Conversation)
            .filter(Conversation.thread_id == thread_id)
            .first()
        )

        if conversation:
            conversation.updated_at = datetime.utcnow()

        db.commit()

    finally:
        db.close()


def get_chat_history(thread_id: str):
    db = SessionLocal()

    try:
        return (
            db.query(ChatMessage)
            .filter(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )

    finally:
        db.close()


def save_memory(thread_id: str, memory: str):
    db = SessionLocal()

    try:
        item = LongTermMemory(
            thread_id=thread_id,
            memory=memory,
            created_at=datetime.utcnow()
        )

        db.add(item)
        db.commit()

        return "Memory saved successfully."

    finally:
        db.close()


def search_memory(thread_id: str, query: str):
    db = SessionLocal()

    try:
        memories = (
            db.query(LongTermMemory)
            .filter(LongTermMemory.thread_id == thread_id)
            .order_by(LongTermMemory.created_at.desc())
            .limit(20)
            .all()
        )

        if not memories:
            return "No saved memory found."

        return "\n".join([f"- {m.memory}" for m in memories])

    finally:
        db.close()
