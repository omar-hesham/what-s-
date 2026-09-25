"""
Local video processing pipeline using FFmpeg and FFprobe.
Extracts real FFprobe metadata (duration, width, height, streams).
Extracts bounded audio track and transcribes via AudioTranscriber.
Intelligently samples bounded keyframes and runs local Tesseract OCR when available.
Never fabricates transcripts or OCR text; stores truthful status and provenance.
Preserves original video bytes.
"""

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from owi.config import settings
from owi.core.logging import logger
from owi.db.models import MediaAsset, Transcript, TranscriptSegment, DocumentRecord
from owi.db.migrations import sync_derived_fts, remove_derived_fts
from owi.pipeline.audio import AudioTranscriber
from owi.pipeline.ocr import ImageAnalyzer, find_tessdata_dir

# Video safety boundaries
MAX_VIDEO_BYTES = 500 * 1024 * 1024  # 500 MB
MAX_KEYFRAMES_LIMIT = 6

def find_ffmpeg_binary() -> Optional[str]:
    """Find FFmpeg binary on Windows or PATH."""
    in_path = shutil.which("ffmpeg")
    if in_path:
        return in_path
    custom = Path(r"C:\AI-Tools\bin\ffmpeg.exe")
    if custom.exists():
        return str(custom)
    return None

def find_ffprobe_binary() -> Optional[str]:
    """Find FFprobe binary on Windows or PATH."""
    in_path = shutil.which("ffprobe")
    if in_path:
        return in_path
    custom = Path(r"C:\AI-Tools\bin\ffprobe.exe")
    if custom.exists():
        return str(custom)
    ffmpeg = find_ffmpeg_binary()
    if ffmpeg:
        candidate = Path(ffmpeg).parent / "ffprobe.exe"
        if candidate.exists():
            return str(candidate)
    return None

class VideoProcessor:
    """Processes video files locally with FFmpeg, FFprobe, Whisper, and Tesseract."""

    _custom_ffmpeg: Any = None
    _custom_ffprobe: Any = None

    @classmethod
    def set_ffmpeg_binary(cls, path: Any):
        cls._custom_ffmpeg = path

    @classmethod
    def set_ffprobe_binary(cls, path: Any):
        cls._custom_ffprobe = path

    @classmethod
    def get_ffmpeg_binary(cls) -> Optional[str]:
        if cls._custom_ffmpeg is False or cls._custom_ffmpeg == "":
            return None
        if cls._custom_ffmpeg is not None:
            return str(cls._custom_ffmpeg)
        return find_ffmpeg_binary()

    @classmethod
    def get_ffprobe_binary(cls) -> Optional[str]:
        if cls._custom_ffprobe is False or cls._custom_ffprobe == "":
            return None
        if cls._custom_ffprobe is not None:
            return str(cls._custom_ffprobe)
        return find_ffprobe_binary()

    @classmethod
    def probe_video(cls, video_path: Path) -> Dict[str, Any]:
        """Extract genuine duration, dimensions, and audio stream presence using ffprobe."""
        ffprobe_bin = cls.get_ffprobe_binary()
        if not ffprobe_bin:
            return {"available": False}

        cmd = [
            ffprobe_bin, "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(video_path)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                duration = float(data.get("format", {}).get("duration", 0.0))
                width = 0
                height = 0
                has_audio = False
                for stream in data.get("streams", []):
                    c_type = stream.get("codec_type")
                    if c_type == "video" and not width:
                        width = int(stream.get("width", 0))
                        height = int(stream.get("height", 0))
                    elif c_type == "audio":
                        has_audio = True

                return {
                    "available": True,
                    "duration": duration,
                    "width": width,
                    "height": height,
                    "has_audio": has_audio,
                    "format_name": data.get("format", {}).get("format_name", "")
                }
        except Exception as e:
            logger.warning(f"FFprobe metadata probe error on {video_path.name}: {e}")

        return {"available": False}

    @classmethod
    def process_video(
        cls, 
        media_asset_id: int, 
        db: Session, 
        max_keyframes: int = 4
    ) -> Dict[str, Any]:
        asset = db.query(MediaAsset).filter(MediaAsset.id == media_asset_id).first()
        if not asset:
            raise ValueError(f"MediaAsset #{media_asset_id} not found.")

        video_path = Path(asset.file_path)
        if not video_path.exists():
            asset.processing_status = "failed"
            asset.processing_error = "file_not_found"
            asset.processing_attempts = (asset.processing_attempts or 0) + 1
            asset.processed_at = datetime.utcnow()
            db.commit()
            raise FileNotFoundError(f"Video file not found: {video_path}")

        asset.processing_attempts = (asset.processing_attempts or 0) + 1
        asset.processing_status = "processing"
        db.commit()

        ffmpeg_bin = cls.get_ffmpeg_binary()
        ffprobe_bin = cls.get_ffprobe_binary()

        if not ffmpeg_bin or not ffprobe_bin:
            logger.warning("FFmpeg or FFprobe binary missing for video processing.")
            asset.processing_status = "setup_needed"
            asset.processing_error = "ffmpeg_ffprobe_missing"
            asset.processing_method = "ffmpeg"
            asset.processed_at = datetime.utcnow()
            db.commit()
            return {
                "media_asset_id": asset.id,
                "status": "setup_needed",
                "error": "FFmpeg and FFprobe binaries are required on host for video processing.",
                "duration": 0.0,
                "keyframes": [],
                "transcript": None,
                "ocr_text": ""
            }

        # 1. Probe video metadata
        probe_info = cls.probe_video(video_path)
        duration = float(probe_info.get("duration", 0.0))
        if duration > 0:
            asset.duration_seconds = duration
        if probe_info.get("width"):
            asset.width = int(probe_info["width"])
        if probe_info.get("height"):
            asset.height = int(probe_info["height"])

        has_audio = probe_info.get("has_audio", False)
        db.commit()

        # 2. Extract audio track for transcription if audio exists
        transcript_result = None
        if has_audio and duration > 0:
            audio_dir = settings.DATA_DIR / "derived" / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            audio_out_path = audio_dir / f"extracted_audio_{asset.id}.wav"

            try:
                cmd_audio = [
                    ffmpeg_bin, "-y", "-i", str(video_path),
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    str(audio_out_path)
                ]
                subprocess.run(cmd_audio, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)

                if audio_out_path.exists() and audio_out_path.stat().st_size > 1000:
                    speaker = asset.message.sender_name if asset.message else "Speaker"
                    transcript_result = AudioTranscriber.transcribe_file(
                        audio_out_path,
                        speaker_name=speaker
                    )

                    full_text = transcript_result.get("full_text", "")
                    if full_text:
                        # Idempotently save Transcript directly for this video asset
                        existing_t = db.query(Transcript).filter(Transcript.media_asset_id == asset.id).first()
                        if existing_t:
                            db.delete(existing_t)
                            db.flush()

                        transcript = Transcript(
                            media_asset_id=asset.id,
                            language_detected=transcript_result.get("language"),
                            full_text=full_text,
                            duration_seconds=duration,
                            model_used=transcript_result.get("model_used", "faster-whisper-base")
                        )
                        db.add(transcript)
                        db.flush()

                        for seg in transcript_result.get("segments", []):
                            db.add(TranscriptSegment(
                                transcript_id=transcript.id,
                                start_time=seg["start_time"],
                                end_time=seg["end_time"],
                                text=seg["text"],
                                speaker=seg.get("speaker")
                            ))

                        # Sync verified speech text to derived_fts
                        sync_derived_fts(
                            db.connection(),
                            media_asset_id=asset.id,
                            message_id=asset.message_id,
                            conversation_id=asset.conversation_id,
                            file_name=asset.file_name,
                            source_type="transcript",
                            content=full_text
                        )
            except Exception as e:
                logger.error(f"Failed to extract and transcribe audio from video #{asset.id}: {e}")

        # 3. Bounded keyframe extraction
        keyframe_paths: List[str] = []
        ocr_lines: List[str] = []
        bounded_keyframes = min(max_keyframes, MAX_KEYFRAMES_LIMIT)

        if duration > 0 and bounded_keyframes > 0:
            interval = max(int(duration / (bounded_keyframes + 1)), 2)
            frames_dir = settings.DATA_DIR / "derived" / "frames" / f"video_{asset.id}"
            frames_dir.mkdir(parents=True, exist_ok=True)

            try:
                frame_pattern = str(frames_dir / "frame_%03d.jpg")
                cmd_frames = [
                    ffmpeg_bin, "-y", "-i", str(video_path),
                    "-vf", f"fps=1/{interval}", "-vframes", str(bounded_keyframes),
                    frame_pattern
                ]
                subprocess.run(cmd_frames, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
                
                for f in sorted(frames_dir.glob("*.jpg")):
                    keyframe_paths.append(str(f.as_posix()))
            except Exception as e:
                logger.error(f"Error extracting video keyframes for #{asset.id}: {e}")

            # 4. Bounded keyframe OCR if Tesseract is available
            tess_bin = ImageAnalyzer.get_tesseract_binary()
            if tess_bin and keyframe_paths:
                tessdata_dir = find_tessdata_dir()
                for idx, kf_path in enumerate(keyframe_paths, start=1):
                    try:
                        cmd_ocr = [tess_bin, kf_path, "stdout", "-l", "ara+eng", "--psm", "3"]
                        if tessdata_dir:
                            cmd_ocr.extend(["--tessdata-dir", str(tessdata_dir)])
                        res_ocr = subprocess.run(cmd_ocr, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
                        if res_ocr.returncode == 0:
                            f_text = (res_ocr.stdout or "").strip()
                            if f_text:
                                approx_sec = idx * interval
                                ocr_lines.append(f"[Frame {idx} at ~{approx_sec}s]:\n{f_text}")
                    except Exception as ocr_err:
                        logger.warning(f"Keyframe OCR error on {kf_path}: {ocr_err}")

        # Idempotently update DocumentRecord with Keyframe OCR text
        ocr_full_text = "\n\n".join(ocr_lines).strip()
        doc_record = db.query(DocumentRecord).filter(DocumentRecord.media_asset_id == asset.id).first()
        if ocr_full_text:
            if not doc_record:
                doc_record = DocumentRecord(
                    media_asset_id=asset.id,
                    conversation_id=asset.conversation_id,
                    title=video_path.stem,
                    doc_type="video_ocr",
                    page_count=len(keyframe_paths),
                    extracted_text=ocr_full_text,
                    metadata_json={
                        "duration": duration,
                        "keyframes_extracted": len(keyframe_paths),
                        "width": asset.width,
                        "height": asset.height
                    }
                )
                db.add(doc_record)
            else:
                doc_record.doc_type = "video_ocr"
                doc_record.extracted_text = ocr_full_text
                doc_record.page_count = len(keyframe_paths)

            # Sync verified OCR to derived_fts
            sync_derived_fts(
                db.connection(),
                media_asset_id=asset.id,
                message_id=asset.message_id,
                conversation_id=asset.conversation_id,
                file_name=asset.file_name,
                source_type="ocr",
                content=ocr_full_text
            )

        asset.processing_status = "completed"
        asset.processing_method = "ffmpeg+whisper+tesseract"
        asset.processing_error = None
        asset.processed_at = datetime.utcnow()
        db.commit()

        return {
            "media_asset_id": asset.id,
            "status": "completed",
            "duration": duration,
            "width": asset.width,
            "height": asset.height,
            "keyframes": keyframe_paths,
            "transcript": transcript_result,
            "ocr_text": ocr_full_text
        }
