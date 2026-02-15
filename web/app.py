from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request, send_file, send_from_directory, stream_with_context

from agent.config import AgentConfig, load_config
from web.control_center import DavidControlCenter, create_control_center


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
    app.config["MAX_CONTENT_LENGTH"] = 128 * 1024
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
            }
            if request.path.startswith("/api/approval/") or request.path.startswith("/api/run/"):
                protected.add(request.path)
            if request.path.startswith("/api/workspace/"):
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

    def _sse(event_name: str, payload: dict[str, Any]) -> str:
        return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"

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

    @app.get("/api/memory")
    def api_memory():
        return jsonify({"ok": True, "data": center.memory_snapshot()})

    @app.get("/api/telemetry/tail")
    def api_telemetry_tail():
        try:
            limit = int(request.args.get("limit", "100"))
        except ValueError:
            limit = 100
        return jsonify({"ok": True, "data": center.telemetry_tail(limit=limit)})

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
