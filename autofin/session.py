from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List
from uuid import uuid4

from autofin.memory import SessionMemory


JsonDict = Dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_message(role: str, content: str, metadata: JsonDict | None = None) -> JsonDict:
    return {
        "role": role,
        "content": content,
        "metadata": metadata or {},
        "timestamp": utc_now(),
    }


@dataclass
class ConversationSession:
    id: str
    title: str = "New session"
    messages: List[JsonDict] = field(default_factory=list)
    memory: SessionMemory = field(default_factory=SessionMemory)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def public_view(self, include_messages: bool = False) -> JsonDict:
        payload = {
            "id": self.id,
            "title": self.title,
            "summary": self.memory.summary,
            "working_entities": self.memory.working_entities,
            "active_task_id": self.memory.active_task_id,
            "pending_action": self.memory.pending_action,
            "task_summaries": self.memory.task_summaries,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
        }
        if include_messages:
            payload["messages"] = self.messages
        return payload

    def to_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "title": self.title,
            "messages": self.messages,
            "memory": self.memory.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: JsonDict) -> "ConversationSession":
        return cls(
            id=str(payload["id"]),
            title=str(payload.get("title") or "New session"),
            messages=list(payload.get("messages") or []),
            memory=SessionMemory.from_dict(payload.get("memory")),
            created_at=str(payload.get("created_at") or utc_now()),
            updated_at=str(payload.get("updated_at") or utc_now()),
        )


class SessionStore:
    def __init__(self, root: str | Path = ".autofin/sessions", persist: bool = True) -> None:
        self.root = Path(root)
        self.persist = persist
        self._lock = Lock()
        self._sessions: Dict[str, ConversationSession] = {}
        if self.persist:
            self._load()

    def create_session(self, title: str = "New session") -> ConversationSession:
        session = ConversationSession(id=f"session-{uuid4()}", title=title)
        with self._lock:
            self._sessions[session.id] = session
            self._persist(session)
        return session

    def get_or_create(self, session_id: str | None = None) -> ConversationSession:
        with self._lock:
            if session_id and session_id in self._sessions:
                return self._sessions[session_id]
            if session_id:
                session = ConversationSession(id=session_id)
            else:
                session = ConversationSession(id=f"session-{uuid4()}")
            self._sessions[session.id] = session
            self._persist(session)
            return session

    def get(self, session_id: str) -> ConversationSession:
        with self._lock:
            try:
                return self._sessions[session_id]
            except KeyError as exc:
                raise KeyError(f"Unknown session: {session_id}") from exc

    def list_sessions(self) -> List[JsonDict]:
        with self._lock:
            sessions = sorted(self._sessions.values(), key=lambda item: item.updated_at, reverse=True)
            return [session.public_view() for session in sessions]

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Unknown session: {session_id}")
            del self._sessions[session_id]
            self._delete_files(session_id)

    def delete_all_sessions(self) -> int:
        with self._lock:
            count = len(self._sessions)
            session_ids = list(self._sessions.keys())
            self._sessions.clear()
            for session_id in session_ids:
                self._delete_files(session_id)
            return count

    def append_message(self, session_id: str, role: str, content: str, metadata: JsonDict | None = None) -> JsonDict:
        message = make_message(role, content, metadata)
        with self._lock:
            session = self._sessions[session_id]
            if session.title == "New session" and role == "user" and content.strip():
                session.title = self._title_from_message(content)
            session.messages.append(message)
            session.memory.update_summary(session.messages)
            session.updated_at = utc_now()
            self._persist(session)
            self._append_transcript(session.id, message)
        return message

    def update_memory_from_route(self, session_id: str, routed_intent: JsonDict, policy_decision: JsonDict) -> None:
        with self._lock:
            session = self._sessions[session_id]
            session.memory.update_from_route(routed_intent, policy_decision)
            session.updated_at = utc_now()
            self._persist(session)

    def set_active_task(self, session_id: str, task_id: str) -> None:
        with self._lock:
            session = self._sessions[session_id]
            session.memory.set_active_task(task_id)
            session.updated_at = utc_now()
            self._persist(session)

    def add_task_summary(self, session_id: str, task_summary: JsonDict) -> None:
        with self._lock:
            session = self._sessions[session_id]
            session.memory.add_task_summary(task_summary)
            session.updated_at = utc_now()
            self._persist(session)

    def context_for(self, session_id: str) -> str:
        with self._lock:
            session = self._sessions[session_id]
            return session.memory.to_prompt_context(session.messages)

    def public_view(self, session_id: str, include_messages: bool = False) -> JsonDict:
        with self._lock:
            return self._sessions[session_id].public_view(include_messages=include_messages)

    def _load(self) -> None:
        if not self.root.exists():
            return
        for file_path in self.root.glob("*.json"):
            try:
                with file_path.open("r", encoding="utf-8") as handle:
                    session = ConversationSession.from_dict(json.load(handle))
                self._sessions[session.id] = session
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                continue

    def _persist(self, session: ConversationSession) -> None:
        if not self.persist:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with self._session_path(session.id).open("w", encoding="utf-8") as handle:
            json.dump(session.to_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    def _append_transcript(self, session_id: str, message: JsonDict) -> None:
        if not self.persist:
            return
        transcript_dir = self.root / "transcripts"
        transcript_dir.mkdir(parents=True, exist_ok=True)
        with (transcript_dir / f"{self._safe_id(session_id)}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message, ensure_ascii=False) + "\n")

    def _session_path(self, session_id: str) -> Path:
        return self.root / f"{self._safe_id(session_id)}.json"

    def _transcript_path(self, session_id: str) -> Path:
        return self.root / "transcripts" / f"{self._safe_id(session_id)}.jsonl"

    def _delete_files(self, session_id: str) -> None:
        if not self.persist:
            return
        for path in [self._session_path(session_id), self._transcript_path(session_id)]:
            try:
                path.unlink()
            except FileNotFoundError:
                continue

    def _safe_id(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", value)

    def _title_from_message(self, message: str) -> str:
        title = " ".join(message.strip().split())
        return title[:44] if title else "New session"
