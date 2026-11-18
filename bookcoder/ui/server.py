from __future__ import annotations

import json
import queue
import tempfile
import threading
import traceback
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_file,
)

from ..core.audio import ensure_ffmpeg, normalize_output_format
from ..core.ebook_parser import ParseError, detect_format, validate_file
from ..core.language_detection import detect_language_for_book
from ..core.models import Book, Chapter, Language, NarrationSettings, ProgressUpdate
from ..core.pipeline import AudiobookPipeline, CancelledError, GenerationConfig, PipelineError
from ..core.settings import SettingsStore
from ..core.tts.registry import TTSRegistry


APP_TITLE = "BookCoder — AI Audiobook Studio"


def create_app() -> Flask:
    base_dir = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
    )
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1GB uploads

    state = AppState()

    @app.get("/")
    def index():
        return render_template("index.html", app_title=APP_TITLE)

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "ffmpeg": bool(ensure_ffmpeg())})

    @app.get("/api/providers")
    def list_providers():
        lang = _parse_language(request.args.get("language"))
        providers = []
        for p in state.tts_registry.providers():
            ok, reason = p.is_available()
            info = {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "available": ok,
                "reason": reason,
                "supports_pitch": p.supports_pitch,
                "supports_styles": p.supports_styles,
                "requires_api_key": p.requires_api_key,
            }
            # Extra info for piper
            if p.id == "piper" and state.tts_registry.piper_manager:
                try:
                    statuses = state.tts_registry.piper_manager.list_statuses(lang)
                    info["downloaded_voice_count"] = sum(1 for s in statuses if s.downloaded)
                    info["catalog_voice_count"] = len(statuses)
                except Exception:
                    pass
            providers.append(info)
        return jsonify({"ok": True, "providers": providers})

    @app.get("/api/settings")
    def get_settings():
        lang = _parse_language(request.args.get("language"))
        ns = state.settings_store.get_narration_settings(lang)
        data = _settings_to_json(ns)
        return jsonify({"ok": True, "settings": data, "last_output_dir": state.settings_store.get("last_output_dir", "")})

    @app.post("/api/settings")
    def save_settings():
        payload = request.get_json(silent=True) or {}
        lang = _parse_language(payload.get("language"))
        ns = _settings_from_json(payload)
        state.settings_store.save_narration_settings(ns, lang)
        if "last_output_dir" in payload and isinstance(payload["last_output_dir"], str):
            state.settings_store.set("last_output_dir", payload["last_output_dir"])
        return jsonify({"ok": True})

    @app.get("/api/offline-models")
    def list_offline_models():
        lang = _parse_language(request.args.get("language"))
        manager = state.tts_registry.piper_manager
        if not manager:
            return jsonify({"ok": False, "error": "Offline model manager is not available.", "models": []}), 200
        try:
            statuses = manager.list_statuses(lang)
            models = []
            for s in statuses:
                d = asdict(s)
                # merge live download progress
                prog = state.download_progress.get(s.key)
                if prog:
                    d.update(prog)
                models.append(d)
            return jsonify({
                "ok": True,
                "models_dir": str(manager.models_dir),
                "models": models,
            })
        except Exception as e:
            traceback.print_exc()
            return jsonify({"ok": False, "error": str(e), "models": []}), 200

    @app.post("/api/offline-models/<key>/download")
    def download_offline_model(key: str):
        manager = state.tts_registry.piper_manager
        if not manager:
            return jsonify({"ok": False, "error": "Offline model manager is not available."}), 400
        # check if already downloading
        prog = state.download_progress.get(key, {})
        if prog.get("status") == "downloading":
            return jsonify({"ok": True, "status": "downloading", "message": "Download already in progress."})

        def run_download():
            state.download_progress[key] = {
                "status": "downloading",
                "progress": 0,
                "message": "Starting download...",
                "downloaded_bytes": 0,
                "total_bytes": -1,
            }

            def cb(downloaded: int, total: int, message: str):
                pct = 0
                if total and total > 0:
                    pct = int(max(0, min(100, (downloaded / total) * 100)))
                elif downloaded > 0:
                    pct = 0
                state.download_progress[key] = {
                    "status": "downloading",
                    "progress": pct,
                    "message": message,
                    "downloaded_bytes": downloaded,
                    "total_bytes": total,
                }

            try:
                manager.download(key, progress=cb)
                state.download_progress[key] = {
                    "status": "done",
                    "progress": 100,
                    "message": "Download complete.",
                    "downloaded_bytes": 0,
                    "total_bytes": 0,
                }
            except Exception as e:
                traceback.print_exc()
                state.download_progress[key] = {
                    "status": "error",
                    "progress": 0,
                    "message": str(e),
                    "downloaded_bytes": 0,
                    "total_bytes": 0,
                }

        t = threading.Thread(target=run_download, daemon=True)
        t.start()
        return jsonify({"ok": True, "status": "downloading", "message": "Download started."})

    @app.get("/api/offline-models/<key>/status")
    def offline_model_status(key: str):
        prog = state.download_progress.get(key)
        manager = state.tts_registry.piper_manager
        status = None
        if manager:
            try:
                from ..core.tts.piper_catalog import get_by_key
                m = get_by_key(key)
                if m:
                    status = asdict(manager.get_status(m))
            except Exception:
                pass
        return jsonify({"ok": True, "download": prog, "model": status})

    @app.post("/api/offline-models/<key>/delete")
    def delete_offline_model(key: str):
        manager = state.tts_registry.piper_manager
        if not manager:
            return jsonify({"ok": False, "error": "Offline model manager is not available."}), 400
        try:
            st = manager.delete(key)
            state.download_progress.pop(key, None)
            return jsonify({"ok": True, "model": asdict(st)})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.post("/api/upload")
    def upload():
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "No file was uploaded."}), 400
        f = request.files["file"]
        if not f or not f.filename:
            return jsonify({"ok": False, "error": "No file selected."}), 400

        filename = Path(f.filename).name
        try:
            fmt = detect_format(Path(filename))
        except ParseError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        upload_dir = state.ensure_upload_dir()
        stored_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        stored_path = upload_dir / stored_name
        try:
            f.save(str(stored_path))
        except Exception as e:
            return jsonify({"ok": False, "error": f"Failed to save uploaded file: {e}"}), 500

        try:
            _, size = validate_file(stored_path)
        except ParseError as e:
            try:
                stored_path.unlink(missing_ok=True)
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(e)}), 400

        file_id = str(uuid.uuid4())
        entry = {
            "id": file_id,
            "filename": filename,
            "stored_path": str(stored_path),
            "size": size,
            "format": fmt.value,
        }
        state.uploads[file_id] = entry

        try:
            pipeline = AudiobookPipeline()
            book = pipeline.load_book(stored_path)
            book_id = str(uuid.uuid4())
            state.books[book_id] = {"book": book, "file_id": file_id}
            state.last_book_id = book_id

            lang = book.effective_language or Language.ENGLISH
            ns = state.settings_store.get_narration_settings(lang)
            provider = _resolve_provider(state, ns.provider_id, lang)
            if provider and not ns.provider_id:
                ns.provider_id = provider.id
            if provider and not ns.voice_id:
                dv = provider.default_voice(lang)
                if dv:
                    ns.voice_id = dv.id
                    ns.provider_id = provider.id

            return jsonify({
                "ok": True,
                "file": {"id": file_id, "filename": filename, "size": size, "format": fmt.value},
                "book": _book_to_json(book, book_id),
                "settings": _settings_to_json(ns),
            })
        except (ParseError, PipelineError) as e:
            try:
                stored_path.unlink(missing_ok=True)
            except Exception:
                pass
            state.uploads.pop(file_id, None)
            return jsonify({"ok": False, "error": str(e)}), 400
        except Exception as e:
            traceback.print_exc()
            try:
                stored_path.unlink(missing_ok=True)
            except Exception:
                pass
            state.uploads.pop(file_id, None)
            return jsonify({"ok": False, "error": f"Unexpected error while processing file: {e}"}), 500

    @app.post("/api/book/<book_id>/language")
    def set_language(book_id: str):
        info = state.books.get(book_id)
        if not info:
            return jsonify({"ok": False, "error": "Book not found."}), 404
        payload = request.get_json(silent=True) or {}
        lang = _parse_language(payload.get("language"))
        if not lang:
            return jsonify({"ok": False, "error": "Invalid language."}), 400
        book: Book = info["book"]
        book.selected_language = lang
        ns = state.settings_store.get_narration_settings(lang)
        provider = _resolve_provider(state, ns.provider_id or payload.get("provider_id", ""), lang)
        if provider and not ns.provider_id:
            ns.provider_id = provider.id
        # try to keep voice valid for provider/lang
        if provider and ns.voice_id:
            if not _voice_exists(provider, ns.voice_id):
                dv = provider.default_voice(lang)
                if dv:
                    ns.voice_id = dv.id
        elif provider:
            dv = provider.default_voice(lang)
            if dv:
                ns.voice_id = dv.id
        return jsonify({"ok": True, "book": _book_to_json(book, book_id), "settings": _settings_to_json(ns)})

    @app.post("/api/book/<book_id>/chapters")
    def update_chapters(book_id: str):
        info = state.books.get(book_id)
        if not info:
            return jsonify({"ok": False, "error": "Book not found."}), 404
        payload = request.get_json(silent=True) or {}
        updates = payload.get("chapters", [])
        if not isinstance(updates, list):
            return jsonify({"ok": False, "error": "Invalid chapters payload."}), 400
        book: Book = info["book"]
        by_id = {c.id: c for c in book.chapters}
        ordered_ids = []
        for u in updates:
            if not isinstance(u, dict):
                continue
            cid = u.get("id")
            if cid not in by_id:
                continue
            c = by_id[cid]
            if "included" in u:
                c.included = bool(u["included"])
            if "title" in u and isinstance(u["title"], str) and u["title"].strip():
                c.title = u["title"].strip()[:200]
            ordered_ids.append(cid)
        if ordered_ids:
            book.reorder_chapters(ordered_ids)
        return jsonify({"ok": True, "book": _book_to_json(book, book_id)})

    @app.post("/api/book/<book_id>/remove")
    def remove_book(book_id: str):
        info = state.books.pop(book_id, None)
        if not info:
            return jsonify({"ok": True})
        file_id = info.get("file_id")
        if file_id:
            fentry = state.uploads.pop(file_id, None)
            if fentry:
                try:
                    Path(fentry["stored_path"]).unlink(missing_ok=True)
                except Exception:
                    pass
        if state.last_book_id == book_id:
            state.last_book_id = None
        return jsonify({"ok": True})

    @app.get("/api/voices")
    def list_voices():
        lang = _parse_language(request.args.get("language"))
        provider_id = (request.args.get("provider") or request.args.get("provider_id") or "").strip()
        provider = _resolve_provider(state, provider_id, lang)
        if not provider:
            return jsonify({"ok": False, "error": "No TTS provider available.", "voices": [], "providers": []}), 200
        ok, reason = provider.is_available()
        if not ok:
            return jsonify({
                "ok": False,
                "error": reason,
                "voices": [],
                "provider": _provider_info(provider),
            }), 200
        try:
            voices = provider.list_voices(lang)
            payload = {
                "ok": True,
                "provider": _provider_info(provider),
                "voices": [_voice_to_json(v) for v in voices],
            }
            # Helpful hint for Piper with no downloaded voices
            if provider.id == "piper" and not voices:
                payload["hint"] = "No offline voices downloaded yet. Download a Piper voice model below to use offline narration."
            return jsonify(payload)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"ok": False, "error": f"Failed to list voices: {e}", "voices": [], "provider": _provider_info(provider)}), 200

    @app.post("/api/preview")
    def preview_voice():
        payload = request.get_json(silent=True) or {}
        voice_id = (payload.get("voice_id") or "").strip()
        lang = _parse_language(payload.get("language")) or Language.ENGLISH
        provider_id = (payload.get("provider_id") or "").strip()
        speed = _to_float(payload.get("speed"), 1.0)
        pitch = _to_float(payload.get("pitch"), 0.0)
        if not voice_id:
            return jsonify({"ok": False, "error": "voice_id is required."}), 400

        provider = _resolve_provider_for_voice(state, provider_id, voice_id, lang)
        if not provider:
            return jsonify({"ok": False, "error": "No TTS provider available."}), 500
        ok, reason = provider.is_available()
        if not ok:
            return jsonify({"ok": False, "error": reason}), 400

        voice = _find_voice(provider, voice_id, lang)
        if not voice:
            # try to find across providers
            provider, voice = _find_voice_any_provider(state, voice_id, lang)
        if not voice or not provider:
            return jsonify({"ok": False, "error": "Selected voice not found. If this is an offline voice, make sure it is downloaded."}), 404

        ns = NarrationSettings(provider_id=provider.id, voice_id=voice.id, language=voice.language or lang, speed=speed, pitch=pitch, style="Natural Audiobook Narration")
        try:
            tmp_path = provider.synthesize_preview(voice, settings=ns)
            resp = send_file(str(tmp_path), mimetype="audio/mpeg", as_attachment=False, download_name="preview.mp3")

            @resp.call_on_close
            def _cleanup():
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

            return resp
        except Exception as e:
            traceback.print_exc()
            return jsonify({"ok": False, "error": f"Preview failed: {e}"}), 500

    @app.post("/api/generate")
    def generate():
        payload = request.get_json(silent=True) or {}
        book_id = payload.get("book_id")
        info = state.books.get(book_id) if book_id else None
        if not info:
            return jsonify({"ok": False, "error": "Book not found. Please upload a file first."}), 404
        book: Book = info["book"]

        chapter_updates = payload.get("chapters")
        if isinstance(chapter_updates, list):
            by_id = {c.id: c for c in book.chapters}
            ordered_ids = []
            for u in chapter_updates:
                if not isinstance(u, dict) or u.get("id") not in by_id:
                    continue
                c = by_id[u["id"]]
                if "included" in u:
                    c.included = bool(u["included"])
                ordered_ids.append(c.id)
            if ordered_ids:
                book.reorder_chapters(ordered_ids)

        if not book.included_chapters:
            return jsonify({"ok": False, "error": "No chapters selected. Please include at least one chapter."}), 400

        lang = _parse_language(payload.get("language")) or book.effective_language or Language.ENGLISH
        book.selected_language = lang

        provider_id = (payload.get("provider_id") or "").strip()
        voice_id = (payload.get("voice_id") or "").strip()

        provider = _resolve_provider_for_voice(state, provider_id, voice_id, lang)
        if not provider:
            return jsonify({"ok": False, "error": "No TTS provider is configured."}), 500
        ok, reason = provider.is_available()
        if not ok:
            return jsonify({"ok": False, "error": reason}), 400

        if not voice_id:
            dv = provider.default_voice(lang)
            voice_id = dv.id if dv else ""
        if not voice_id:
            # helpful message for piper
            if provider.id == "piper":
                return jsonify({"ok": False, "error": "No offline voice selected. Please download and select a Piper voice model first."}), 400
            return jsonify({"ok": False, "error": "No voice selected and no default voice available for this language."}), 400

        # Ensure voice belongs to resolved provider; if not, try to locate correct provider
        if not _voice_exists(provider, voice_id):
            p2, v2 = _find_voice_any_provider(state, voice_id, lang)
            if p2 and v2:
                provider = p2
            else:
                if provider.id == "piper":
                    return jsonify({"ok": False, "error": "Selected offline voice is not available. Please download it first."}), 400
                return jsonify({"ok": False, "error": "Selected voice is not available. Please choose a different voice."}), 400

        speed = _to_float(payload.get("speed"), 1.0)
        pitch = _to_float(payload.get("pitch"), 0.0)
        style = payload.get("style") or "Natural Audiobook Narration"
        output_format = normalize_output_format(payload.get("output_format") or payload.get("format") or "mp3")
        bitrate = int(_to_float(payload.get("bitrate_kbps"), 128))
        bitrate = 64 if bitrate < 64 else min(bitrate, 320)
        combine = bool(payload.get("combine", False))
        pause_ms = int(_to_float(payload.get("chapter_pause_ms"), 1200))

        out_dir_raw = payload.get("output_dir")
        if isinstance(out_dir_raw, str) and out_dir_raw.strip():
            out_dir = Path(out_dir_raw).expanduser()
        else:
            last = state.settings_store.get("last_output_dir")
            if isinstance(last, str) and last.strip():
                out_dir = Path(last).expanduser()
            else:
                out_dir = Path.home() / "BookCoderAudiobooks" / _safe_name(book.title or book.source_path.stem)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Cannot create output directory '{out_dir}': {e}"}), 400

        paragraph_pause_ms = int(_to_float(payload.get("paragraph_pause_ms"), 450))
        sentence_pause_hint = payload.get("sentence_pause_hint", True)
        if isinstance(sentence_pause_hint, str):
            sentence_pause_hint = sentence_pause_hint.strip().lower() not in ("0", "false", "no", "off")
        else:
            sentence_pause_hint = bool(sentence_pause_hint)
        tone_profile = (payload.get("tone_profile") or "natural")
        if isinstance(tone_profile, str):
            tone_profile = tone_profile.strip().lower() or "natural"
        else:
            tone_profile = "natural"
        dialogue_voice_id = (payload.get("dialogue_voice_id") or "").strip()
        dialogue_voice_alt_id = (payload.get("dialogue_voice_alt_id") or "").strip()
        pronunciation_map = payload.get("pronunciation_map") if isinstance(payload.get("pronunciation_map"), dict) else {}
        cleaned_pm = {}
        if isinstance(pronunciation_map, dict):
            for k, v in pronunciation_map.items():
                try:
                    ks = str(k).strip()
                    vs = str(v).strip()
                except Exception:
                    continue
                if ks and vs:
                    cleaned_pm[ks] = vs
        voice_cast_map = payload.get("voice_cast_map") if isinstance(payload.get("voice_cast_map"), dict) else {}
        cleaned_vcm = {}
        if isinstance(voice_cast_map, dict):
            for k, v in voice_cast_map.items():
                try:
                    ks = str(k).strip().lower()
                    vs = str(v).strip()
                except Exception:
                    continue
                if ks and vs:
                    cleaned_vcm[ks] = vs

        ns = NarrationSettings(
            provider_id=provider.id,
            voice_id=voice_id,
            language=lang,
            speed=max(0.5, min(speed, 2.0)),
            pitch=max(-10.0, min(pitch, 10.0)),
            style=style,
            output_format=output_format,
            output_bitrate_kbps=bitrate,
            combine_into_single_file=combine,
            chapter_pause_ms=max(0, min(pause_ms, 10000)),
            paragraph_pause_ms=max(0, min(paragraph_pause_ms, 5000)),
            sentence_pause_hint=sentence_pause_hint,
            tone_profile=tone_profile if tone_profile in ("natural", "expressive", "clear", "neutral") else "natural",
            dialogue_voice_id=dialogue_voice_id,
            dialogue_voice_alt_id=dialogue_voice_alt_id,
            voice_cast_map=cleaned_vcm,
            pronunciation_map=cleaned_pm,
        )
        state.settings_store.save_narration_settings(ns, lang)
        state.settings_store.set("last_output_dir", str(out_dir))

        job_id = str(uuid.uuid4())
        job = Job(id=job_id, book_id=book_id)
        state.jobs[job_id] = job

        config = GenerationConfig(
            output_dir=out_dir,
            settings=ns,
            provider=provider,
            voice_id=voice_id,
            combine=combine,
            bitrate_kbps=bitrate,
            chapter_pause_ms=ns.chapter_pause_ms,
            output_format=output_format,
        )

        t = threading.Thread(target=_run_generation_job, args=(state, job, book, config), daemon=True)
        job.thread = t
        t.start()

        return jsonify({"ok": True, "job_id": job_id, "output_dir": str(out_dir)})

    @app.get("/api/jobs/<job_id>/events")
    def job_events(job_id: str):
        job = state.jobs.get(job_id)
        if not job:
            return jsonify({"ok": False, "error": "Job not found."}), 404

        def stream():
            init = {"type": "snapshot", "status": job.status, "messages": list(job.messages)[-20:], "result": job.result}
            yield f"data: {json.dumps(init, ensure_ascii=False)}\n\n"
            while True:
                try:
                    item = job.queue.get(timeout=15)
                except queue.Empty:
                    if job.status in ("done", "error", "cancelled"):
                        break
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item.get("type") in ("done", "error", "cancelled"):
                    break

        return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/jobs/<job_id>/cancel")
    def cancel_job(job_id: str):
        job = state.jobs.get(job_id)
        if not job:
            return jsonify({"ok": False, "error": "Job not found."}), 404
        job.pipeline.cancel()
        job.status = "cancelling"
        return jsonify({"ok": True})

    @app.get("/api/jobs/<job_id>")
    def job_status(job_id: str):
        job = state.jobs.get(job_id)
        if not job:
            return jsonify({"ok": False, "error": "Job not found."}), 404
        return jsonify({"ok": True, "status": job.status, "result": job.result, "error": job.error, "messages": list(job.messages)[-50:]})

    return app


class Job:
    def __init__(self, id: str, book_id: str):
        self.id = id
        self.book_id = book_id
        self.queue: "queue.Queue[dict]" = queue.Queue()
        self.status = "running"
        self.pipeline = AudiobookPipeline()
        self.thread: Optional[threading.Thread] = None
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self.messages: list[str] = []


class AppState:
    def __init__(self) -> None:
        self.uploads: dict[str, dict] = {}
        self.books: dict[str, dict] = {}
        self.jobs: dict[str, Job] = {}
        self.last_book_id: Optional[str] = None
        self.tts_registry = TTSRegistry()
        self.settings_store = SettingsStore()
        self.download_progress: dict[str, dict] = {}
        self._upload_dir: Optional[Path] = None

    def ensure_upload_dir(self) -> Path:
        if self._upload_dir and self._upload_dir.exists():
            return self._upload_dir
        base = Path(tempfile.gettempdir()) / "bookcoder_uploads"
        base.mkdir(parents=True, exist_ok=True)
        self._upload_dir = base
        return base


def _run_generation_job(state: AppState, job: Job, book: Book, config: GenerationConfig) -> None:
    def cb(u: ProgressUpdate):
        msg = u.message
        job.messages.append(msg)
        job.queue.put({
            "type": "progress",
            "stage": u.stage,
            "message": u.message,
            "current": u.current,
            "total": u.total,
            "chapter_title": u.chapter_title,
            "fraction": u.fraction,
        })

    try:
        result = job.pipeline.generate(book, config, progress=cb)
        job.status = "done"
        job.result = {
            "output_dir": str(result.output_dir) if result.output_dir else "",
            "chapter_files": [str(p) for p in result.chapter_files],
            "combined_file": str(result.combined_file) if result.combined_file else None,
        }
        job.queue.put({"type": "done", "message": "Generation complete.", "result": job.result})
    except CancelledError:
        job.status = "cancelled"
        job.queue.put({"type": "cancelled", "message": "Generation cancelled."})
    except (PipelineError, Exception) as e:
        traceback.print_exc()
        job.status = "error"
        job.error = str(e)
        job.queue.put({"type": "error", "message": str(e)})


# ------------------ helpers ------------------

def _resolve_provider(state: AppState, provider_id: str, lang):
    pid = (provider_id or "").strip()
    if pid:
        p = state.tts_registry.get(pid)
        if p:
            ok, _ = p.is_available()
            if ok:
                return p
    # try saved global setting
    if not pid:
        try:
            saved = state.settings_store._data.get("narration", {})
            if isinstance(saved, dict):
                spid = (saved.get("provider_id") or "").strip()
                if spid:
                    p = state.tts_registry.get(spid)
                    if p:
                        ok, _ = p.is_available()
                        if ok:
                            # for piper, prefer only if has voices? but allow showing it
                            return p
        except Exception:
            pass
    return state.tts_registry.resolve_provider("", lang)


def _resolve_provider_for_voice(state: AppState, provider_id: str, voice_id: str, lang):
    vid = (voice_id or "").strip()
    pid = (provider_id or "").strip()
    # infer from voice id
    if not pid and vid.startswith("piper:"):
        pid = "piper"
    if not pid and vid and not vid.startswith("piper:"):
        # could be edge voice id
        edge = state.tts_registry.get("edge-tts")
        if edge:
            pid = "edge-tts"
    provider = _resolve_provider(state, pid, lang)
    if provider:
        return provider
    # try to find any provider that has this voice
    p, _ = _find_voice_any_provider(state, vid, lang)
    if p:
        return p
    return state.tts_registry.resolve_provider("", lang)


def _find_voice(provider, voice_id: str, lang):
    try:
        for v in provider.list_voices(lang):
            if v.id == voice_id:
                return v
        for v in provider.list_voices(None):
            if v.id == voice_id:
                return v
    except Exception:
        return None
    return None


def _voice_exists(provider, voice_id: str) -> bool:
    return _find_voice(provider, voice_id, None) is not None


def _find_voice_any_provider(state: AppState, voice_id: str, lang):
    if not voice_id:
        return None, None
    # prefer inferred provider
    if voice_id.startswith("piper:"):
        p = state.tts_registry.get("piper")
        if p:
            v = _find_voice(p, voice_id, lang)
            if v:
                return p, v
    for p in state.tts_registry.providers():
        ok, _ = p.is_available()
        if not ok:
            continue
        v = _find_voice(p, voice_id, lang)
        if v:
            return p, v
    return None, None


def _provider_info(provider) -> dict:
    ok, reason = provider.is_available()
    return {
        "id": provider.id,
        "name": provider.name,
        "description": provider.description,
        "available": ok,
        "reason": reason,
        "supports_pitch": provider.supports_pitch,
        "supports_styles": provider.supports_styles,
    }


def _book_to_json(book: Book, book_id: str) -> dict:
    return {
        "id": book_id,
        "title": book.title,
        "author": book.author,
        "filename": book.filename,
        "format": book.format.value,
        "file_size": book.file_size,
        "detected_language": book.detected_language.value if book.detected_language else None,
        "selected_language": book.effective_language.value if book.effective_language else None,
        "chapters": [
            {
                "id": c.id,
                "title": c.title,
                "index": c.index,
                "included": c.included,
                "word_count": c.word_count,
                "char_count": c.char_count,
                "preview": (c.text[:220] + ("…" if len(c.text) > 220 else "")),
            }
            for c in book.chapters
        ],
    }


def _voice_to_json(v) -> dict:
    return {
        "id": v.id,
        "name": v.name,
        "language": v.language.value,
        "gender": v.gender,
        "locale": v.locale,
        "style": v.style,
        "description": v.description,
        "provider": v.provider,
    }


def _settings_to_json(ns: NarrationSettings) -> dict:
    return {
        "provider_id": ns.provider_id,
        "voice_id": ns.voice_id,
        "language": ns.language.value if ns.language else None,
        "speed": ns.speed,
        "pitch": ns.pitch,
        "style": ns.style,
        "output_format": getattr(ns, "output_format", "mp3") or "mp3",
        "output_bitrate_kbps": ns.output_bitrate_kbps,
        "combine_into_single_file": ns.combine_into_single_file,
        "chapter_pause_ms": ns.chapter_pause_ms,
        "paragraph_pause_ms": ns.paragraph_pause_ms,
        "sentence_pause_hint": bool(getattr(ns, "sentence_pause_hint", True)),
        "tone_profile": getattr(ns, "tone_profile", "natural") or "natural",
        "dialogue_voice_id": getattr(ns, "dialogue_voice_id", "") or "",
        "dialogue_voice_alt_id": getattr(ns, "dialogue_voice_alt_id", "") or "",
        "voice_cast_map": getattr(ns, "voice_cast_map", {}) or {},
        "pronunciation_map": getattr(ns, "pronunciation_map", {}) or {},
    }


def _settings_from_json(d: dict) -> NarrationSettings:
    ns = NarrationSettings()
    if isinstance(d.get("provider_id"), str):
        ns.provider_id = d["provider_id"]
    if isinstance(d.get("voice_id"), str):
        ns.voice_id = d["voice_id"]
    ns.language = _parse_language(d.get("language"))
    ns.speed = max(0.5, min(_to_float(d.get("speed"), 1.0), 2.0))
    ns.pitch = max(-10.0, min(_to_float(d.get("pitch"), 0.0), 10.0))
    if isinstance(d.get("style"), str) and d["style"].strip():
        ns.style = d["style"].strip()
    if isinstance(d.get("output_format"), str):
        ns.output_format = normalize_output_format(d.get("output_format"))
    ns.output_bitrate_kbps = int(_to_float(d.get("output_bitrate_kbps"), 128))
    ns.combine_into_single_file = bool(d.get("combine_into_single_file", False))
    ns.chapter_pause_ms = int(_to_float(d.get("chapter_pause_ms"), 1200))
    ns.paragraph_pause_ms = int(_to_float(d.get("paragraph_pause_ms"), 450))
    if "sentence_pause_hint" in d:
        ns.sentence_pause_hint = bool(d.get("sentence_pause_hint"))
    if isinstance(d.get("tone_profile"), str) and d.get("tone_profile").strip():
        tp = d.get("tone_profile").strip().lower()
        ns.tone_profile = tp if tp in ("natural", "expressive", "clear", "neutral") else tp
    if isinstance(d.get("dialogue_voice_id"), str):
        ns.dialogue_voice_id = d.get("dialogue_voice_id").strip()
    if isinstance(d.get("dialogue_voice_alt_id"), str):
        ns.dialogue_voice_alt_id = d.get("dialogue_voice_alt_id").strip()
    vcm = d.get("voice_cast_map")
    if isinstance(vcm, dict):
        cleaned_cast = {}
        for k, v in vcm.items():
            try:
                ks = str(k).strip().lower()
                vs = str(v).strip()
            except Exception:
                continue
            if ks and vs:
                cleaned_cast[ks] = vs
        ns.voice_cast_map = cleaned_cast
    pm = d.get("pronunciation_map")
    if isinstance(pm, dict):
        cleaned = {}
        for k, v in pm.items():
            try:
                ks = str(k).strip()
                vs = str(v).strip()
            except Exception:
                continue
            if ks and vs:
                cleaned[ks] = vs
        ns.pronunciation_map = cleaned
    return ns


def _parse_language(v: Any) -> Optional[Language]:
    if isinstance(v, Language):
        return v
    if not isinstance(v, str):
        return None
    s = v.strip().lower()
    if s in ("en", "eng", "english"):
        return Language.ENGLISH
    if s in ("hu", "hun", "hungarian", "magyar"):
        return Language.HUNGARIAN
    return None


def _to_float(v: Any, default: float) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _safe_name(name: str) -> str:
    import re
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name or "book").strip().strip(". ")
    return name[:80] or "book"


def run(host: str = "127.0.0.1", port: int = 8765, debug: bool = False, open_browser: bool = True) -> None:
    app = create_app()
    url = f"http://{host}:{port}"
    if open_browser:
        import webbrowser
        import threading as _th

        def _open():
            try:
                webbrowser.open(url)
            except Exception:
                pass
        _th.Timer(0.8, _open).start()
    print(f"BookCoder running at {url}")
    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)
