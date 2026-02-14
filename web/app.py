from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_file, send_from_directory

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

    def _json_error(message: str, status: int = 400):
        return jsonify({"ok": False, "error": message}), status

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
        ok, data = center.start_run(payload)
        if not ok:
            return _json_error(str(data.get("error", "Failed to start run.")), status=409)
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

    @app.post("/api/settings")
    def api_settings_post():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object.")
        data = center.update_settings(payload)
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
        ok, data = center.submit_approval(approval_id, decision=decision, note=note)
        if not ok:
            return _json_error(str(data.get("error", "Approval update failed.")), status=409)
        return jsonify({"ok": True, "data": data})

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
