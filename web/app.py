from __future__ import annotations

import base64
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request, send_file, send_from_directory, stream_with_context

from agent.config import AgentConfig, load_config
from web.control_center import DavidControlCenter, create_control_center
from web.voice_service import (
    split_response_text,
    synthesize_text_chunk,
    transcribe_audio_bytes,
    voice_config_from_settings,
)

MAX_VOICE_TEXT_CHARS = 4000


def create_app(
    config: AgentConfig | None = None,
    control_center: DavidControlCenter | None = None,
    data_root: Path | None = None,
) -> Flask:
    app = Flask(
        __name__,
        static_folder="static",
        static_url_path="/static",
    )

    cfg = config
    if cfg is None and control_center is not None:
        cfg = getattr(control_center, "config", None)
    if cfg is None:
        cfg = load_config()
    center = control_center or create_control_center(config=cfg, data_root=data_root)
    app.config["DAVID_CENTER"] = center
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    state_change_hits: dict[str, float] = {}

    def _is_local_request() -> bool:
        remote = request.remote_addr or ""
        return remote in {"127.0.0.1", "::1", "localhost"}

    @app.before_request
    def _security_guards():
        if not _is_local_request():
            return _json_error("Local-only server.", status=403)

        if request.method == "POST" and not app.testing:
            protected = {
                "/api/run",
                "/api/stop",
                "/api/settings",
                "/api/ask",
                "/api/teach",
                "/api/chat",
                "/api/voice/transcribe",
                "/api/voice/tts",
                "/api/voice/chat/stream",
                "/api/memory/confirm_overwrite",
                "/api/self_improvements/propose",
                "/api/legacy_archive",
                "/api/demo/load",
                "/api/demo/reset",
                "/api/bundles/import",
                "/api/uploads/analyze",
            }
            if request.path.startswith("/api/approval/") or request.path.startswith("/api/run/"):
                protected.add(request.path)
            if request.path.startswith("/api/workspace/"):
                protected.add(request.path)
            if request.path.startswith("/api/self_improvements/"):
                protected.add(request.path)
            if request.path.startswith("/api/legacy_archive/"):
                protected.add(request.path)
            if request.path.startswith("/api/uploads/"):
                protected.add(request.path)
            if request.path in protected or request.path.startswith("/api/approval/") or request.path.startswith("/api/workspace/"):
                token = request.headers.get("X-CSRF-Token", "").strip()
                if token != center.get_csrf_token():
                    return _json_error("CSRF token missing or invalid.", status=403)

            key = f"{request.remote_addr}:{request.path}"
            now = time.monotonic()
            last = state_change_hits.get(key, 0.0)
            if now - last < 0.2:
                return _json_error("Too many state changes. Slow down.", status=429)
            state_change_hits[key] = now

    def _json_error(message: str, status: int = 400):
        return jsonify({"ok": False, "error": message}), status

    def _parse_optional_bool(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        lowered = str(value).strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return None

    def _sse(event_name: str, payload: dict[str, Any]) -> str:
        return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"

    def _assistant_text_from_chat_payload(chat_payload: dict[str, Any]) -> str:
        if not isinstance(chat_payload, dict):
            return ""
        response = chat_payload.get("response")
        response_data = response if isinstance(response, dict) else {}
        text = str(chat_payload.get("assistant_turn", {}).get("text", "")).strip() if isinstance(chat_payload.get("assistant_turn"), dict) else ""
        if text:
            return text
        for key in ("answer", "reply", "message"):
            value = str(response_data.get(key, "")).strip()
            if value:
                return value
        if str(response_data.get("status", "")).strip() == "confirmation_required":
            return "Teach is pending confirmation. Enable Confirm Teach save and send again."
        return "Completed."

    def _voice_mode_enabled(settings: dict[str, Any]) -> bool:
        return bool(settings.get("voice_mode_enabled", False))

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/status")
    def api_status():
        return jsonify({"ok": True, "data": center.get_status()})

    @app.post("/api/run")
    def api_run():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        try:
            ok, data = center.start_run(payload)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        if not ok:
            return _json_error(str(data.get("error", "Failed to start run.")), status=409)
        return jsonify({"ok": True, "data": data})

    @app.post("/api/ask")
    def api_ask():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        question = str(payload.get("question", payload.get("message", ""))).strip()
        actor = str(payload.get("actor", "web_ui")).strip() or "web_ui"
        try:
            data = center.ask_memory(question, actor=actor)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return jsonify({"ok": True, "data": data})

    @app.post("/api/chat")
    def api_chat():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        message = str(payload.get("message", payload.get("text", ""))).strip()
        intent = str(payload.get("intent", "")).strip().lower()
        actor = str(payload.get("actor", "web_ui")).strip() or "web_ui"
        session_id = str(payload.get("session_id", "")).strip()
        confirm_save = bool(payload.get("confirm_save", False))
        parent_teaching_mode = bool(payload.get("parent_teaching_mode", False))
        try:
            data = center.chat_message(
                message,
                intent=intent,
                confirm_save=confirm_save,
                parent_teaching_mode=parent_teaching_mode,
                session_id=session_id,
                actor=actor,
            )
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return jsonify({"ok": True, "data": data})

    @app.post("/api/voice/transcribe")
    def api_voice_transcribe():
        actor = str(request.form.get("actor", "web_voice")).strip() or "web_voice"
        session_id = str(request.form.get("session_id", "")).strip()
        mime_type = ""
        audio_bytes = b""

        upload = request.files.get("audio")
        if upload is not None:
            mime_type = str(getattr(upload, "mimetype", "") or getattr(upload, "content_type", "") or "").strip()
            audio_bytes = upload.read()
        else:
            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                return _json_error("Voice transcription requires multipart audio upload or JSON body.")
            actor = str(payload.get("actor", actor)).strip() or actor
            session_id = str(payload.get("session_id", session_id)).strip()
            mime_type = str(payload.get("mime_type", "audio/webm")).strip()
            audio_b64 = str(payload.get("audio_base64", "")).strip()
            if audio_b64.startswith("data:") and "," in audio_b64:
                _, _, raw_part = audio_b64.partition(",")
                audio_b64 = raw_part.strip()
            try:
                audio_bytes = base64.b64decode(audio_b64, validate=True) if audio_b64 else b""
            except ValueError:
                return _json_error("Invalid base64 audio payload.", status=400)

        if not audio_bytes:
            return _json_error("Audio payload is empty.", status=400)

        settings = center.get_settings()
        safe_settings = settings if isinstance(settings, dict) else {}
        if not _voice_mode_enabled(safe_settings):
            return _json_error("Voice mode is disabled. Enable Voice Mode in Settings.", status=409)
        voice_config = voice_config_from_settings(safe_settings)
        try:
            result = transcribe_audio_bytes(
                audio_bytes,
                mime_type=mime_type,
                config=voice_config,
            )
        except ValueError as exc:
            return _json_error(str(exc), status=400)

        result["actor"] = actor
        result["session_id"] = session_id
        result["timestamp_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return jsonify({"ok": True, "data": result})

    @app.post("/api/voice/tts")
    def api_voice_tts():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        text = str(payload.get("text", "")).strip()
        if not text:
            return _json_error("text cannot be empty.", status=400)
        if len(text) > MAX_VOICE_TEXT_CHARS:
            return _json_error(f"text exceeds max length ({MAX_VOICE_TEXT_CHARS} characters).", status=400)

        settings = center.get_settings()
        safe_settings = settings if isinstance(settings, dict) else {}
        if not _voice_mode_enabled(safe_settings):
            return _json_error("Voice mode is disabled. Enable Voice Mode in Settings.", status=409)
        voice_config = voice_config_from_settings(safe_settings)
        style = str(payload.get("voice_style", safe_settings.get("voice_style", voice_config.voice_style))).strip().lower() or voice_config.voice_style
        try:
            speech_rate = int(payload.get("voice_rate", safe_settings.get("voice_rate", voice_config.voice_rate)))
        except (TypeError, ValueError):
            speech_rate = voice_config.voice_rate
        speech_rate = max(60, min(180, speech_rate))
        try:
            result = synthesize_text_chunk(
                text,
                config=voice_config,
                voice_style=style,
                speech_rate=speech_rate,
            )
        except ValueError as exc:
            return _json_error(str(exc), status=400)

        result["text"] = text
        result["timestamp_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return jsonify({"ok": True, "data": result})

    @app.post("/api/voice/chat/stream")
    def api_voice_chat_stream():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        message = str(payload.get("message", payload.get("text", ""))).strip()
        intent = str(payload.get("intent", "")).strip().lower()
        actor = str(payload.get("actor", "web_voice")).strip() or "web_voice"
        session_id = str(payload.get("session_id", "")).strip()
        confirm_save = bool(payload.get("confirm_save", False))
        parent_teaching_mode = bool(payload.get("parent_teaching_mode", False))
        confirm_sensitive = bool(payload.get("confirm_sensitive", False))
        mute = bool(payload.get("mute", False))
        turn_id = str(payload.get("turn_id", "")).strip()
        if not message:
            return _json_error("message cannot be empty.", status=400)
        if len(message) > MAX_VOICE_TEXT_CHARS:
            return _json_error(f"message exceeds max length ({MAX_VOICE_TEXT_CHARS} characters).", status=400)

        settings = center.get_settings()
        safe_settings = settings if isinstance(settings, dict) else {}
        if not _voice_mode_enabled(safe_settings):
            return _json_error("Voice mode is disabled. Enable Voice Mode in Settings.", status=409)
        voice_config = voice_config_from_settings(safe_settings)
        text_only_mode = bool(payload.get("text_only_mode", safe_settings.get("voice_text_only_mode", False)))
        style = str(payload.get("voice_style", safe_settings.get("voice_style", voice_config.voice_style))).strip().lower() or voice_config.voice_style
        try:
            speech_rate = int(payload.get("voice_rate", safe_settings.get("voice_rate", voice_config.voice_rate)))
        except (TypeError, ValueError):
            speech_rate = voice_config.voice_rate
        speech_rate = max(60, min(180, speech_rate))
        try:
            chunk_chars = int(payload.get("chunk_chars", safe_settings.get("voice_chunk_chars", voice_config.chunk_chars)))
        except (TypeError, ValueError):
            chunk_chars = voice_config.chunk_chars
        chunk_chars = max(80, min(400, chunk_chars))

        def _selected_intent() -> str:
            normalized = intent if intent in {"ask", "teach", "goal", "chat"} else ""
            if normalized:
                return normalized
            classify = getattr(center, "classify_chat_intent", None)
            if callable(classify):
                try:
                    detected = classify(message)
                    selected = str((detected or {}).get("intent", "")).strip().lower()
                    if selected in {"ask", "teach", "goal", "chat"}:
                        return selected
                except Exception:
                    return "chat"
            return "chat"

        def _call_chat_message() -> dict[str, Any]:
            try:
                return center.chat_message(
                    message,
                    intent=selected_intent,
                    confirm_save=confirm_save,
                    parent_teaching_mode=parent_teaching_mode,
                    session_id=session_id,
                    actor=actor,
                    publish_events=False,
                )
            except TypeError:
                return center.chat_message(
                    message,
                    intent=selected_intent,
                    confirm_save=confirm_save,
                    parent_teaching_mode=parent_teaching_mode,
                    session_id=session_id,
                    actor=actor,
                )

        selected_intent = _selected_intent()

        def generate():
            yield _sse(
                "connected",
                {
                    "stream": "voice_chat",
                    "selected_intent": selected_intent,
                    "session_id": session_id,
                    "turn_id": turn_id,
                },
            )
            if selected_intent == "goal" and not confirm_sensitive:
                yield _sse(
                    "confirmation_required",
                    {
                        "message": "Voice goal execution requires explicit confirmation.",
                        "selected_intent": selected_intent,
                        "turn_id": turn_id,
                    },
                )
                return
            try:
                result = _call_chat_message()
                assistant_text = _assistant_text_from_chat_payload(result)
                chunks = split_response_text(assistant_text, max_chars=chunk_chars)
                assembled = ""
                for idx, chunk in enumerate(chunks):
                    assembled = f"{assembled} {chunk}".strip()
                    audio_payload = {
                        "engine": voice_config.tts_engine,
                        "mime_type": "",
                        "audio_base64": "",
                        "style": style,
                        "rate": speech_rate,
                    }
                    if not text_only_mode and not mute:
                        try:
                            audio_payload = synthesize_text_chunk(
                                chunk,
                                config=voice_config,
                                voice_style=style,
                                speech_rate=speech_rate,
                            )
                        except ValueError as exc:
                            audio_payload = {
                                "engine": voice_config.tts_engine,
                                "mime_type": "",
                                "audio_base64": "",
                                "style": style,
                                "rate": speech_rate,
                                "error": str(exc),
                            }
                    yield _sse(
                        "assistant_partial",
                        {
                            "index": idx,
                            "chunk": chunk,
                            "assembled": assembled,
                            "selected_intent": selected_intent,
                            "turn_id": turn_id,
                            **audio_payload,
                        },
                    )

                crisis_support = bool(result.get("crisis_support")) or bool(
                    re.search(r"\b(988|immediate danger|hurt yourself|self-harm)\b", assistant_text, flags=re.IGNORECASE)
                )
                yield _sse(
                    "assistant_final",
                    {
                        "assistant_text": assistant_text,
                        "selected_intent": selected_intent,
                        "crisis_support": crisis_support,
                        "chunk_count": len(chunks),
                        "turn_id": turn_id,
                        "result": result,
                    },
                )
            except ValueError as exc:
                yield _sse("error", {"error": str(exc), "turn_id": turn_id})
            except Exception as exc:  # pragma: no cover - defensive stream fallback
                yield _sse("error", {"error": f"Voice stream failed: {exc}", "turn_id": turn_id})

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/voice/diagnostics")
    def api_voice_diagnostics():
        settings = center.get_settings()
        safe_settings = settings if isinstance(settings, dict) else {}
        voice_config = voice_config_from_settings(safe_settings)
        voice_enabled = _voice_mode_enabled(safe_settings)

        def _command_available(name: str) -> bool:
            return bool(name and shutil.which(name))

        stt_ready = True
        stt_error = ""
        if voice_config.stt_engine == "none":
            stt_ready = False
            stt_error = "Voice STT engine is disabled."
        elif voice_config.stt_engine == "whisper_cpp":
            if not voice_config.whisper_cpp_model_path:
                stt_ready = False
                stt_error = "whisper.cpp model path is missing."
            elif not Path(voice_config.whisper_cpp_model_path).expanduser().exists():
                stt_ready = False
                stt_error = "whisper.cpp model path not found."
            elif not _command_available(voice_config.whisper_cpp_command):
                stt_ready = False
                stt_error = f"whisper.cpp command not found: {voice_config.whisper_cpp_command}"
        else:
            if not _command_available(voice_config.stt_command):
                stt_ready = False
                stt_error = f"Whisper CLI command not found: {voice_config.stt_command}"

        tts_ready = True
        tts_error = ""
        if voice_config.tts_engine == "none":
            tts_ready = False
            tts_error = "Voice TTS engine is disabled."
        elif voice_config.tts_engine == "piper":
            if not voice_config.tts_model_path:
                tts_ready = False
                tts_error = "Piper model path is missing."
            elif not Path(voice_config.tts_model_path).expanduser().exists():
                tts_ready = False
                tts_error = "Piper model path not found."
            elif not _command_available(voice_config.tts_command):
                tts_ready = False
                tts_error = f"Piper command not found: {voice_config.tts_command}"

        if not voice_enabled:
            stt_ready = False
            tts_ready = False
            stt_error = stt_error or "Voice mode is disabled."
            tts_error = tts_error or "Voice mode is disabled."

        payload = {
            "voice_mode_enabled": voice_enabled,
            "stt": {
                "engine": voice_config.stt_engine,
                "ready": stt_ready,
                "error": stt_error,
                "command": voice_config.stt_command,
                "model": voice_config.stt_model,
                "language": voice_config.stt_language,
                "whisper_cpp_command": voice_config.whisper_cpp_command,
                "whisper_cpp_model_path": voice_config.whisper_cpp_model_path,
            },
            "tts": {
                "engine": voice_config.tts_engine,
                "ready": tts_ready,
                "error": tts_error,
                "command": voice_config.tts_command,
                "model_path": voice_config.tts_model_path,
            },
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        return jsonify({"ok": True, "data": payload})

    @app.get("/api/voice/stream/ping")
    def api_voice_stream_ping():
        def generate():
            yield _sse("connected", {"stream": "voice_diag", "ts": time.time()})
            yield _sse("done", {"ok": True})

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/teach")
    def api_teach():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        message = str(payload.get("message", payload.get("teach", ""))).strip()
        actor = str(payload.get("actor", "web_ui")).strip() or "web_ui"
        confirm_conflict = bool(payload.get("confirm_conflict", False))
        try:
            data = center.teach_memory(message, confirm_conflict=confirm_conflict, actor=actor)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return jsonify({"ok": True, "data": data})

    @app.post("/api/memory/confirm_overwrite")
    def api_memory_confirm_overwrite():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        overwrite_id = str(payload.get("overwrite_id", payload.get("id", ""))).strip()
        decision = str(payload.get("decision", "approve")).strip().lower()
        actor = str(payload.get("actor", "web_ui")).strip() or "web_ui"
        ok, data = center.confirm_memory_overwrite(overwrite_id, decision=decision, actor=actor)
        if not ok:
            return _json_error(str(data.get("error", "Failed to confirm overwrite.")), status=409)
        return jsonify({"ok": True, "data": data})

    @app.post("/api/stop")
    def api_stop():
        result = center.stop_active_run()
        status = 200 if result.get("stopped") else 409
        return jsonify({"ok": bool(result.get("stopped")), "data": result}), status

    @app.get("/api/runs")
    def api_runs():
        search = str(request.args.get("search", ""))
        status = str(request.args.get("status", ""))
        try:
            limit = int(request.args.get("limit", "100"))
        except ValueError:
            limit = 100
        rows = center.get_runs(search=search, status=status, limit=limit)
        return jsonify({"ok": True, "data": rows})

    @app.get("/api/run/<run_id>")
    def api_run_details(run_id: str):
        payload = center.get_run(run_id)
        if not payload:
            return _json_error("Run not found.", status=404)
        return jsonify({"ok": True, "data": payload})

    @app.get("/api/run/<run_id>/timeline")
    def api_run_timeline(run_id: str):
        try:
            limit = int(request.args.get("limit", "1000"))
        except ValueError:
            limit = 1000
        payload = center.get_run_timeline(run_id, limit=limit)
        if payload is None:
            return _json_error("Run not found.", status=404)
        return jsonify({"ok": True, "data": payload})

    @app.get("/api/run/<run_id>/files")
    def api_run_files(run_id: str):
        payload = center.get_run_files(run_id)
        if payload is None:
            return _json_error("Run not found.", status=404)
        return jsonify({"ok": True, "data": payload})

    @app.get("/api/workspace/tree")
    def api_workspace_tree():
        try:
            limit = int(request.args.get("limit", "20000"))
        except ValueError:
            limit = 20000
        payload = center.workspace_tree(limit=limit)
        return jsonify({"ok": True, "data": payload})

    @app.post("/api/workspace/file/edit")
    def api_workspace_file_edit():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        path = str(payload.get("path", "")).strip()
        content = str(payload.get("content", ""))
        actor = str(payload.get("actor", "web_ui")).strip() or "web_ui"
        try:
            data = center.workspace_edit_file(path, content=content, actor=actor)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return jsonify({"ok": True, "data": data})

    @app.post("/api/workspace/path/delete")
    def api_workspace_path_delete():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        path = str(payload.get("path", "")).strip()
        actor = str(payload.get("actor", "web_ui")).strip() or "web_ui"
        try:
            data = center.workspace_delete_path(path, actor=actor)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return jsonify({"ok": True, "data": data})

    @app.post("/api/workspace/path/rename")
    def api_workspace_path_rename():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        path = str(payload.get("path", "")).strip()
        new_path = str(payload.get("new_path", "")).strip()
        actor = str(payload.get("actor", "web_ui")).strip() or "web_ui"
        try:
            data = center.workspace_rename_path(path, new_relative_path=new_path, actor=actor)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return jsonify({"ok": True, "data": data})

    @app.get("/api/run/<run_id>/audit")
    def api_run_audit(run_id: str):
        try:
            limit = int(request.args.get("limit", "1000"))
        except ValueError:
            limit = 1000
        payload = center.get_run_audit(run_id, limit=limit)
        if payload is None:
            return _json_error("Run not found.", status=404)
        return jsonify({"ok": True, "data": payload})

    @app.get("/api/run/<run_id>/replay")
    def api_run_replay(run_id: str):
        try:
            iteration = int(request.args.get("iteration", "1"))
        except ValueError:
            iteration = 1
        payload = center.get_run_replay(run_id, iteration=iteration)
        if payload is None:
            return _json_error("Run not found.", status=404)
        return jsonify({"ok": True, "data": payload})

    @app.get("/api/run/<run_id>/compare")
    def api_run_compare(run_id: str):
        try:
            iteration = int(request.args.get("iteration", "1"))
        except ValueError:
            iteration = 1
        payload = center.compare_iterations(run_id, iteration=iteration)
        if payload is None:
            return _json_error("Run not found.", status=404)
        return jsonify({"ok": True, "data": payload})

    @app.post("/api/run/<run_id>/retry")
    def api_run_retry(run_id: str):
        ok, result = center.retry_run(run_id)
        if not ok:
            return _json_error(str(result.get("error", "Retry failed.")), status=409)
        return jsonify({"ok": True, "data": result})

    @app.get("/api/run/<run_id>/bundle")
    def api_run_bundle(run_id: str):
        bundle = center.run_bundle_zip(run_id)
        if not bundle:
            return _json_error("Run not found.", status=404)
        return send_file(
            bundle,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{run_id}.zip",
        )

    @app.post("/api/bundles/import")
    def api_bundle_import():
        actor = str(request.form.get("actor", "web_ui")).strip() or "web_ui"
        upload = request.files.get("bundle")
        if upload is None:
            payload = request.get_json(silent=True) or {}
            if isinstance(payload, dict):
                actor = str(payload.get("actor", actor)).strip() or actor
            return _json_error("Missing bundle upload. Use multipart/form-data with field `bundle`.", status=400)
        filename = str(getattr(upload, "filename", "") or "").strip() or "bundle.zip"
        content = upload.read()
        ok, data = center.import_run_bundle(file_name=filename, content=content, actor=actor)
        if not ok:
            return _json_error(str(data.get("error", "Failed to import bundle.")), status=409)
        return jsonify({"ok": True, "data": data})

    @app.get("/api/bundles/imports")
    def api_bundle_imports():
        try:
            limit = int(request.args.get("limit", "120"))
        except ValueError:
            limit = 120
        return jsonify({"ok": True, "data": center.list_imported_bundles(limit=limit)})

    @app.get("/api/bundles/import/<import_id>")
    def api_bundle_import_details(import_id: str):
        payload = center.get_imported_bundle(import_id)
        if not payload:
            return _json_error("Imported bundle not found.", status=404)
        return jsonify({"ok": True, "data": payload})

    @app.get("/api/bundles/import/<import_id>/timeline")
    def api_bundle_import_timeline(import_id: str):
        try:
            limit = int(request.args.get("limit", "1000"))
        except ValueError:
            limit = 1000
        payload = center.get_imported_bundle_timeline(import_id, limit=limit)
        if payload is None:
            return _json_error("Imported bundle not found.", status=404)
        return jsonify({"ok": True, "data": payload})

    @app.get("/api/bundles/import/<import_id>/files")
    def api_bundle_import_files(import_id: str):
        payload = center.get_imported_bundle_files(import_id)
        if payload is None:
            return _json_error("Imported bundle not found.", status=404)
        return jsonify({"ok": True, "data": payload})

    @app.get("/api/bundles/import/<import_id>/audit")
    def api_bundle_import_audit(import_id: str):
        try:
            limit = int(request.args.get("limit", "1000"))
        except ValueError:
            limit = 1000
        payload = center.get_imported_bundle_audit(import_id, limit=limit)
        if payload is None:
            return _json_error("Imported bundle not found.", status=404)
        return jsonify({"ok": True, "data": payload})

    @app.get("/api/bundles/import/<import_id>/replay")
    def api_bundle_import_replay(import_id: str):
        try:
            iteration = int(request.args.get("iteration", "1"))
        except ValueError:
            iteration = 1
        payload = center.get_imported_bundle_replay(import_id, iteration=iteration)
        if payload is None:
            return _json_error("Imported bundle not found.", status=404)
        return jsonify({"ok": True, "data": payload})

    @app.get("/api/bundles/import/<import_id>/compare")
    def api_bundle_import_compare(import_id: str):
        try:
            iteration = int(request.args.get("iteration", "1"))
        except ValueError:
            iteration = 1
        payload = center.get_imported_bundle_compare(import_id, iteration=iteration)
        if payload is None:
            return _json_error("Imported bundle not found.", status=404)
        return jsonify({"ok": True, "data": payload})

    @app.post("/api/uploads/analyze")
    def api_upload_analyze():
        actor = str(request.form.get("actor", "web_ui")).strip() or "web_ui"
        use_vision = _parse_optional_bool(request.form.get("use_vision"))
        vision_model = str(request.form.get("vision_model", "")).strip()
        upload = request.files.get("file")
        if upload is None:
            payload = request.get_json(silent=True) or {}
            if isinstance(payload, dict):
                actor = str(payload.get("actor", actor)).strip() or actor
                use_vision = _parse_optional_bool(payload.get("use_vision")) if "use_vision" in payload else use_vision
                vision_model = str(payload.get("vision_model", vision_model)).strip()
            return _json_error("Missing file upload. Use multipart/form-data with field `file`.", status=400)
        file_name = str(getattr(upload, "filename", "") or "").strip() or "upload.bin"
        content_type = str(getattr(upload, "mimetype", "") or getattr(upload, "content_type", "") or "").strip()
        content = upload.read()
        ok, data = center.upload_and_analyze_file(
            file_name=file_name,
            content=content,
            content_type=content_type,
            actor=actor,
            use_vision=use_vision,
            vision_model=vision_model,
        )
        if not ok:
            return _json_error(str(data.get("error", "Failed to analyze uploaded file.")), status=409)
        return jsonify({"ok": True, "data": data})

    @app.get("/api/uploads")
    def api_upload_list():
        try:
            limit = int(request.args.get("limit", "120"))
        except ValueError:
            limit = 120
        return jsonify({"ok": True, "data": center.list_uploaded_files(limit=limit)})

    @app.get("/api/uploads/<upload_id>")
    def api_upload_get(upload_id: str):
        payload = center.get_uploaded_file(upload_id)
        if not payload:
            return _json_error("Uploaded file not found.", status=404)
        return jsonify({"ok": True, "data": payload})

    @app.post("/api/uploads/<upload_id>/ask")
    def api_upload_ask(upload_id: str):
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        question = str(payload.get("question", payload.get("message", ""))).strip()
        actor = str(payload.get("actor", "web_ui")).strip() or "web_ui"
        ok, data = center.ask_uploaded_file(upload_id, question=question, actor=actor)
        if not ok:
            error = str(data.get("error", "Failed to answer upload question."))
            status = 404 if "not found" in error.lower() else 400
            return _json_error(error, status=status)
        return jsonify({"ok": True, "data": data})

    @app.get("/api/memory")
    def api_memory():
        return jsonify({"ok": True, "data": center.memory_snapshot()})

    @app.get("/api/memory/facts")
    def api_memory_facts():
        query = str(request.args.get("query", ""))
        try:
            limit = int(request.args.get("limit", "500"))
        except ValueError:
            limit = 500
        return jsonify({"ok": True, "data": center.memory_facts(query=query, limit=limit)})

    @app.get("/api/memory/conversations")
    def api_memory_conversations():
        session_id = str(request.args.get("session_id", ""))
        try:
            limit = int(request.args.get("limit", "500"))
        except ValueError:
            limit = 500
        return jsonify({"ok": True, "data": center.memory_conversations(session_id=session_id, limit=limit)})

    @app.get("/api/chat/sessions")
    def api_chat_sessions():
        try:
            limit = int(request.args.get("limit", "120"))
        except ValueError:
            limit = 120
        return jsonify({"ok": True, "data": center.chat_sessions(limit=limit)})

    @app.get("/api/telemetry/tail")
    def api_telemetry_tail():
        try:
            limit = int(request.args.get("limit", "100"))
        except ValueError:
            limit = 100
        return jsonify({"ok": True, "data": center.telemetry_tail(limit=limit)})

    @app.get("/api/growth_timeline")
    def api_growth_timeline():
        try:
            limit = int(request.args.get("limit", "120"))
        except ValueError:
            limit = 120
        return jsonify({"ok": True, "data": center.growth_timeline(limit=limit)})

    @app.get("/api/logs/tail")
    def api_logs_tail():
        try:
            limit = int(request.args.get("limit", "200"))
        except ValueError:
            limit = 200
        return jsonify({"ok": True, "data": center.logs_tail(limit=limit)})

    @app.get("/api/settings")
    def api_settings_get():
        return jsonify({"ok": True, "data": center.get_settings()})

    @app.get("/api/legacy_archive")
    def api_legacy_archive_list():
        try:
            limit = int(request.args.get("limit", "200"))
        except ValueError:
            limit = 200
        return jsonify({"ok": True, "data": center.list_legacy_archive(limit=limit)})

    @app.post("/api/legacy_archive")
    def api_legacy_archive_mark():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        actor = str(payload.get("actor", "web_ui")).strip() or "web_ui"
        ok, data = center.mark_legacy_moment(payload, actor=actor)
        if not ok:
            return _json_error(str(data.get("error", "Failed to save archive entry.")), status=409)
        return jsonify({"ok": True, "data": data})

    @app.post("/api/legacy_archive/<entry_id>/remove")
    def api_legacy_archive_remove(entry_id: str):
        payload = request.get_json(silent=True) or {}
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        actor = str(payload.get("actor", "web_ui")).strip() or "web_ui"
        ok, data = center.remove_legacy_moment(entry_id, actor=actor)
        if not ok:
            return _json_error(str(data.get("error", "Failed to remove archive entry.")), status=409)
        return jsonify({"ok": True, "data": data})

    @app.get("/api/self_improvements")
    def api_self_improvements_list():
        try:
            limit = int(request.args.get("limit", "160"))
        except ValueError:
            limit = 160
        return jsonify({"ok": True, "data": center.list_self_improvements(limit=limit)})

    @app.post("/api/self_improvements/propose")
    def api_self_improvements_propose():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        actor = str(payload.get("actor", "david_agent")).strip() or "david_agent"
        ok, data = center.propose_self_improvement(payload, actor=actor)
        if not ok:
            return _json_error(str(data.get("error", "Failed to create proposal.")), status=409)
        return jsonify({"ok": True, "data": data})

    @app.post("/api/self_improvements/autonomous_cycle")
    def api_self_improvements_autonomous_cycle():
        payload = request.get_json(silent=True) or {}
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        trigger = str(payload.get("trigger", "manual")).strip() or "manual"
        trigger_id = str(payload.get("trigger_id", "")).strip()
        actor = str(payload.get("actor", "david_autonomous")).strip() or "david_autonomous"
        data = center.autonomous_self_improvement_cycle(trigger=trigger, trigger_id=trigger_id, actor=actor)
        status_text = str(data.get("status", "")).strip().lower()
        if status_text == "error":
            return _json_error(str(data.get("error", "Autonomous self-improvement cycle failed.")), status=409)
        return jsonify({"ok": True, "data": data})

    @app.post("/api/self_improvements/<proposal_id>/decision")
    def api_self_improvements_decision(proposal_id: str):
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        decision = str(payload.get("decision", "")).strip().lower()
        actor = str(payload.get("actor", "web_ui")).strip() or "web_ui"
        note = str(payload.get("note", "")).strip()
        ok, data = center.decide_self_improvement(proposal_id, decision=decision, actor=actor, note=note)
        if not ok:
            status = 400 if "decision must" in str(data.get("error", "")).lower() else 409
            return _json_error(str(data.get("error", "Failed to update proposal.")), status=status)
        return jsonify({"ok": True, "data": data})

    @app.get("/api/models")
    def api_models():
        return jsonify({"ok": True, "data": {"models": center.list_ollama_models()}})

    @app.post("/api/settings")
    def api_settings_post():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        try:
            data = center.update_settings(payload)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return jsonify({"ok": True, "data": data})

    @app.post("/api/demo/load")
    def api_demo_load():
        payload = request.get_json(silent=True) or {}
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        actor = str(payload.get("actor", "web_ui")).strip() or "web_ui"
        confirm_overwrite = bool(payload.get("confirm_overwrite", payload.get("force", False)))
        ok, data = center.load_demo_data(force=confirm_overwrite, actor=actor)
        if not ok:
            response = {
                "ok": False,
                "error": str(data.get("error", "Failed to load demo fixtures.")),
            }
            if bool(data.get("requires_confirmation", False)):
                response["requires_confirmation"] = True
            return jsonify(response), 409
        return jsonify({"ok": True, "data": data})

    @app.post("/api/demo/reset")
    def api_demo_reset():
        payload = request.get_json(silent=True) or {}
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        actor = str(payload.get("actor", "web_ui")).strip() or "web_ui"
        ok, data = center.reset_demo_data(actor=actor)
        if not ok:
            return _json_error(str(data.get("error", "Failed to reset demo fixtures.")), status=409)
        return jsonify({"ok": True, "data": data})

    @app.get("/api/approvals")
    def api_approvals():
        return jsonify({"ok": True, "data": center.list_approvals()})

    @app.post("/api/approval/<approval_id>")
    def api_approval_decision(approval_id: str):
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        decision = str(payload.get("decision", "")).strip()
        note = str(payload.get("note", "")).strip()
        actor = str(payload.get("actor", "local_user")).strip() or "local_user"
        confirmation = str(payload.get("confirmation", "")).strip()
        ok, data = center.submit_approval(
            approval_id,
            decision=decision,
            note=note,
            actor=actor,
            confirmation=confirmation,
        )
        if not ok:
            return _json_error(str(data.get("error", "Approval update failed.")), status=409)
        return jsonify({"ok": True, "data": data})

    @app.get("/api/stream/status")
    def api_stream_status():
        def generate():
            q = center.subscribe("status")
            try:
                yield _sse("connected", {"stream": "status", "csrf_token": center.get_csrf_token()})
                while True:
                    try:
                        event = q.get(timeout=15)
                        yield _sse("status", event)
                    except Exception:
                        yield _sse("heartbeat", {"stream": "status", "ts": time.time()})
            finally:
                center.unsubscribe("status", q)

        return Response(stream_with_context(generate()), mimetype="text/event-stream")

    @app.get("/api/stream/logs")
    def api_stream_logs():
        def generate():
            q = center.subscribe("logs")
            try:
                yield _sse("connected", {"stream": "logs"})
                while True:
                    try:
                        event = q.get(timeout=15)
                        yield _sse("logs", event)
                    except Exception:
                        snapshot = center.logs_tail(limit=20)
                        yield _sse("logs_snapshot", {"stream": "logs", "snapshot": snapshot})
            finally:
                center.unsubscribe("logs", q)

        return Response(stream_with_context(generate()), mimetype="text/event-stream")

    @app.get("/api/stream/run/<run_id>")
    def api_stream_run(run_id: str):
        if center.get_run_timeline(run_id, limit=1) is None:
            return _json_error("Run not found.", status=404)
        channel = f"run:{run_id}"

        def generate():
            q = center.subscribe(channel)
            try:
                yield _sse("connected", {"stream": channel, "run_id": run_id})
                while True:
                    try:
                        event = q.get(timeout=15)
                        yield _sse("run", event)
                    except Exception:
                        tail = center.get_run_timeline(run_id, limit=10) or []
                        yield _sse("run_tail", {"run_id": run_id, "timeline": tail})
            finally:
                center.unsubscribe(channel, q)

        return Response(stream_with_context(generate()), mimetype="text/event-stream")

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "status": "up"})

    @app.errorhandler(404)
    def not_found(_: Any):
        return _json_error("Not found.", status=404)

    return app


def main() -> None:
    app = create_app()
    app.run(host="127.0.0.1", port=8787, debug=False)


if __name__ == "__main__":
    main()
