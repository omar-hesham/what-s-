"""
Local audio and voice note transcription pipeline.
Uses faster-whisper on CPU with local_files_only=True.
Extracts full transcript, language detected, timestamped segments, and duration.
Never fabricates transcripts or uses cloud/Gemini services.
Preserves original audio bytes and message text integrity.
"""

import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from owi.config import settings
from owi.core.logging import logger
from owi.db.models import MediaAsset, Transcript, TranscriptSegment
from owi.db.migrations import sync_derived_fts, remove_derived_fts

class AudioTranscriber:
    """Manages local Whisper transcription with strict local-first model loading."""

    _model_instance = None
    _loaded_model_name = None

    @classmethod
    def set_model_instance(cls, model_instance: Any, model_name: Optional[str] = None):
        """Inject a pre-loaded or mock model instance (useful for tests)."""
        cls._model_instance = model_instance
        cls._loaded_model_name = model_name or settings.WHISPER_MODEL

    @classmethod
    def reset_model(cls):
        """Reset cached model instance."""
        cls._model_instance = None
        cls._loaded_model_name = None

    @classmethod
    def get_model(cls, model_size: str = "base"):
        """
        Load local faster-whisper model on CPU strictly from local cache.
        Does not attempt automatic internet downloads (local_files_only=True).
        """
        if cls._model_instance is not None and cls._loaded_model_name == model_size:
            return cls._model_instance

        whisper_dir = settings.DATA_DIR / "models" / "whisper"
        try:
            from faster_whisper import WhisperModel
            logger.info(f"Loading local faster-whisper model '{model_size}' from {whisper_dir} (local_files_only=True)...")
            cls._model_instance = WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8",
                download_root=str(whisper_dir),
                local_files_only=True
            )
            cls._loaded_model_name = model_size
            return cls._model_instance
        except Exception as e:
            logger.warning(f"Could not load faster-whisper model '{model_size}' from local cache {whisper_dir}: {e}")
            cls._model_instance = None
            cls._loaded_model_name = None
            return None

    @classmethod
    def get_audio_duration(cls, audio_path: Path) -> float:
        """Extract audio duration in seconds using ffprobe or ffmpeg."""
        ffprobe_bin = shutil.which("ffprobe")
        if not ffprobe_bin:
            candidate = Path(r"C:\AI-Tools\bin\ffprobe.exe")
            if candidate.exists():
                ffprobe_bin = str(candidate)

        if not ffprobe_bin:
            ffmpeg_bin = shutil.which("ffmpeg")
            if not ffmpeg_bin:
                candidate_ff = Path(r"C:\AI-Tools\bin\ffmpeg.exe")
                if candidate_ff.exists():
                    ffmpeg_bin = str(candidate_ff)
            if ffmpeg_bin:
                cand_next = Path(ffmpeg_bin).parent / "ffprobe.exe"
                if cand_next.exists():
                    ffprobe_bin = str(cand_next)

        if ffprobe_bin:
            try:
                cmd = [
                    ffprobe_bin, "-v", "error", "-show_entries",
                    "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                    str(audio_path)
                ]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
                if res.returncode == 0 and res.stdout.strip():
                    return float(res.stdout.strip())
            except Exception:
                pass
        return 0.0

    @classmethod
    def transcribe_file(
        cls,
        audio_path: Path,
        model_size: Optional[str] = None,
        speaker_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Transcribe a physical audio file path directly without requiring a database record.
        Returns explicit status: completed, no_speech, setup_needed, or failed.
        """
        if not audio_path.exists():
            return {
                "status": "failed",
                "error": f"Audio file not found: {audio_path}",
                "full_text": "",
                "segments": [],
                "duration": 0.0,
                "language": None
            }

        chosen_model = model_size or settings.WHISPER_MODEL
        duration = cls.get_audio_duration(audio_path)
        model = cls.get_model(chosen_model)

        if model is None:
            return {
                "status": "setup_needed",
                "error": f"Local faster-whisper model '{chosen_model}' cache missing. Place model files in data/models/whisper.",
                "duration": duration,
                "full_text": "",
                "segments": [],
                "language": None,
                "model_used": f"faster-whisper-{chosen_model}"
            }

        segments_data: List[Dict[str, Any]] = []
        full_text = ""
        lang_detected = None

        try:
            segs_gen, info = model.transcribe(str(audio_path), beam_size=5)
            if info:
                lang_detected = getattr(info, "language", None)

            for s in segs_gen:
                text_clean = getattr(s, "text", "").strip()
                if text_clean:
                    segments_data.append({
                        "start_time": float(getattr(s, "start", 0.0)),
                        "end_time": float(getattr(s, "end", 0.0)),
                        "text": text_clean,
                        "speaker": speaker_name or "Speaker"
                    })
            full_text = " ".join(s["text"] for s in segments_data).strip()
        except Exception as e:
            logger.error(f"Error during local model transcription of {audio_path.name}: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "duration": duration,
                "full_text": "",
                "segments": [],
                "language": lang_detected,
                "model_used": f"faster-whisper-{chosen_model}"
            }

        return {
            "status": "completed" if full_text else "no_speech",
            "duration": duration,
            "language": lang_detected,
            "full_text": full_text,
            "segments": segments_data,
            "model_used": f"faster-whisper-{chosen_model}"
        }

    @classmethod
    def transcribe(
        cls, 
        media_asset_id: int, 
        db: Session, 
        model_size: Optional[str] = None
    ) -> Dict[str, Any]:
        asset = db.query(MediaAsset).filter(MediaAsset.id == media_asset_id).first()
        if not asset:
            raise ValueError(f"Media asset #{media_asset_id} not found.")

        audio_path = Path(asset.file_path)
        if not audio_path.exists():
            asset.processing_status = "failed"
            asset.processing_error = "file_not_found"
            asset.processing_attempts = (asset.processing_attempts or 0) + 1
            asset.processed_at = datetime.utcnow()
            db.commit()
            raise FileNotFoundError(f"Audio file does not exist: {audio_path}")

        chosen_model = model_size or settings.WHISPER_MODEL
        asset.processing_attempts = (asset.processing_attempts or 0) + 1
        asset.processing_status = "processing"
        db.commit()

        speaker = asset.message.sender_name if asset.message else "Speaker"
        t_res = cls.transcribe_file(audio_path, model_size=chosen_model, speaker_name=speaker)

        duration = t_res.get("duration", 0.0)
        if duration > 0:
            asset.duration_seconds = duration

        if t_res["status"] == "setup_needed":
            asset.processing_status = "setup_needed"
            asset.processing_error = "whisper_model_missing"
            asset.processing_method = t_res.get("model_used", f"faster-whisper-{chosen_model}")
            asset.processed_at = datetime.utcnow()
            db.commit()
            return {
                "media_asset_id": asset.id,
                **t_res
            }

        if t_res["status"] == "failed":
            asset.processing_status = "failed"
            asset.processing_error = f"transcription_error: {str(t_res.get('error'))[:150]}"
            asset.processing_method = t_res.get("model_used", f"faster-whisper-{chosen_model}")
            asset.processed_at = datetime.utcnow()
            db.commit()
            return {
                "media_asset_id": asset.id,
                **t_res
            }

        full_text = t_res.get("full_text", "")
        lang_detected = t_res.get("language")
        segments_data = t_res.get("segments", [])

        # Idempotently update Transcript in DB
        existing_t = db.query(Transcript).filter(Transcript.media_asset_id == asset.id).first()
        if existing_t:
            db.delete(existing_t)
            db.flush()

        transcript = Transcript(
            media_asset_id=asset.id,
            language_detected=lang_detected,
            full_text=full_text,
            duration_seconds=duration,
            model_used=t_res.get("model_used", f"faster-whisper-{chosen_model}")
        )
        db.add(transcript)
        db.flush()

        for seg in segments_data:
            s_rec = TranscriptSegment(
                transcript_id=transcript.id,
                start_time=seg["start_time"],
                end_time=seg["end_time"],
                text=seg["text"],
                speaker=seg.get("speaker")
            )
            db.add(s_rec)

        # Update MediaAsset durable processing state
        asset.processing_method = t_res.get("model_used", f"faster-whisper-{chosen_model}")
        asset.processing_error = None
        asset.processed_at = datetime.utcnow()

        if not full_text:
            # Explicit empty / no speech detected state
            asset.processing_status = "completed"
            remove_derived_fts(db.connection(), asset.id)
            db.commit()
            return {
                "media_asset_id": asset.id,
                "transcript_id": transcript.id,
                "status": "no_speech",
                "duration": duration,
                "language": lang_detected,
                "full_text": "",
                "segment_count": 0
            }

        # Verified speech found
        asset.processing_status = "completed"
        # Index ONLY verified derived text into derived_fts with exact provenance
        sync_derived_fts(
            db.connection(),
            media_asset_id=asset.id,
            message_id=asset.message_id,
            conversation_id=asset.conversation_id,
            file_name=asset.file_name,
            source_type="transcript",
            content=full_text
        )

        db.commit()

        return {
            "media_asset_id": asset.id,
            "transcript_id": transcript.id,
            "status": "completed",
            "duration": duration,
            "language": lang_detected,
            "full_text": full_text,
            "segment_count": len(segments_data)
        }
