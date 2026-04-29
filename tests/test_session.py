from autofin.session import SessionStore


def test_session_store_persists_messages_and_memory(tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    session = store.create_session()

    store.append_message(session.id, "user", "帮我分析 AAPL 最近的 10-K")
    store.update_memory_from_route(
        session.id,
        {
            "intent": "research_sec_filing",
            "ticker": "AAPL",
            "filing_type": "10-K",
            "focus": ["cash flow"],
        },
        {"action": "show_run_research_card", "requires_confirmation": True},
    )

    reloaded = SessionStore(root=tmp_path / "sessions")
    loaded = reloaded.get(session.id)

    assert loaded.messages[0]["role"] == "user"
    assert loaded.memory.working_entities["ticker"] == "AAPL"
    assert loaded.memory.pending_action["action"] == "show_run_research_card"


def test_session_context_includes_recent_messages_and_entities():
    store = SessionStore(persist=False)
    session = store.create_session()

    store.append_message(session.id, "user", "Analyze MSFT 10-Q")
    store.update_memory_from_route(
        session.id,
        {"intent": "research_sec_filing", "ticker": "MSFT", "filing_type": "10-Q"},
        {"action": "show_run_research_card", "requires_confirmation": True},
    )

    context = store.context_for(session.id)

    assert "Analyze MSFT 10-Q" in context
    assert "MSFT" in context
    assert "Pending action" in context


def test_session_memory_adds_task_summary_to_context():
    store = SessionStore(persist=False)
    session = store.create_session()

    store.add_task_summary(
        session.id,
        {
            "task_id": "task-1",
            "ticker": "AAPL",
            "filing_type": "10-K",
            "summary": "Found SEC filing metadata.",
            "evidence_count": 2,
        },
    )

    context = store.context_for(session.id)

    assert "Recent task summaries" in context
    assert "task-1" in context
    assert "AAPL" in context


def test_session_store_deletes_session_files(tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    session = store.create_session()
    store.append_message(session.id, "user", "hello")

    store.delete_session(session.id)
    reloaded = SessionStore(root=tmp_path / "sessions")

    assert reloaded.list_sessions() == []


def test_session_store_deletes_all_sessions(tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    store.create_session()
    store.create_session()

    deleted_count = store.delete_all_sessions()

    assert deleted_count == 2
    assert store.list_sessions() == []
