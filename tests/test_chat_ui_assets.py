from pathlib import Path


def test_chat_ui_clear_conversation_action_is_wired() -> None:
    app_js = Path("web/static/app.js").read_text(encoding="utf-8")
    index_html = Path("web/static/index.html").read_text(encoding="utf-8")
    assert "/api/memory/conversations/clear" in app_js
    assert "Clear Conversation" in index_html


def test_chat_history_renders_latest_messages_first() -> None:
    app_js = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "const displayRows = rows.slice().reverse();" in app_js
    assert "el.memoryChatHistory.scrollTop = 0;" in app_js


def test_chat_sync_preserves_local_messages_while_refreshing_conversations() -> None:
    app_js = Path("web/static/app.js").read_text(encoding="utf-8")
    assert 'source: "conversation"' in app_js
    assert '.filter((row) => String(row?.source || "local") !== "conversation")' in app_js
    assert "function voiceSttRecoveryHint(errorMessage)" in app_js


def test_voice_ui_includes_browser_stt_fallback_hooks() -> None:
    app_js = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "function browserSpeechRecognitionCtor()" in app_js
    assert "function resolveVoiceSttFallback()" in app_js
    assert "startBrowserSpeechListening" in app_js
    assert "Auto (VAD) requires local STT. Switched to Manual mode with browser speech fallback." in app_js
