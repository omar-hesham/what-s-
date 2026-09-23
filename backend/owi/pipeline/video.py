"""
Local video processing pipeline using FFmpeg.
Extracts metadata, extracts audio for speech transcription,
intelligently samples representative keyframes (capping at max 10 frames),
and summarizes content.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from owi.config import settings
from owi.core.logging import logger
from owi.db.models import MediaAsset
from owi.pipeline.audio import AudioTranscriber

def find_ffmpeg_binary() -> Optional[str]:
    """Find FFmpeg binary on Windows."""
    in_path = shutil.which("ffmpeg")
    if in_path:
        return in_path
    custom = Path(r"C:\AI-Tools\bin\ffmpeg.exe")
    if custom.exists():
        return str(custom)
    return None

class VideoProcessor:
    """Processes video files using local FFmpeg."""

    @classmethod
    def process_video(
        cls, 
        media_asset_id: int, 
        db: Session, 
        max_keyframes: int = 6
    ) -> Dict[str, Any]:
        asset = db.query(MediaAsset).filter(MediaAsset.id == media_asset_id).first()
        if not asset:
            raise ValueError(f"MediaAsset #{media_asset_id} not found.")

        video_path = Path(asset.file_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        ffmpeg_bin = find_ffmpeg_binary()
        if not ffmpeg_bin:
            logger.warning("FFmpeg binary not found. Skipping deep video frame extraction.")
            return {
                "media_asset_id": asset.id,
                "status": "ffmpeg_unavailable",
                "keyframes": [],
                "transcript": None
            }

        # 1. Determine duration
        duration = AudioTranscriber.get_audio_duration(video_path)
        asset.duration_seconds = duration

        # 2. Extract audio track for transcription
        audio_out_path = settings.DATA_DIR / "media" / "audio" / f"extracted_audio_{asset.id}.mp3"
        try:
            cmd_audio = [
                ffmpeg_bin, "-y", "-i", str(video_path),
                "-vn", "-acodec", "libmp3lame", "-q:a", "4",
                str(audio_out_path)
            ]
            subprocess.run(cmd_audio, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        except Exception as e:
            logger.error(f"Failed to extract audio from video: {e}")

        # 3. Intelligent keyframe sampling
        keyframe_paths: List[str] = []
        if duration > 0:
            interval = max(int(duration / (max_keyframes + 1)), 2)
            frames_dir = settings.DATA_DIR / "derived" / "frames" / f"video_{asset.id}"
            frames_dir.mkdir(parents=True, exist_ok=True)

            try:
                # Extract 1 frame every `interval` seconds, max `max_keyframes`
                frame_pattern = str(frames_dir / "frame_%03d.jpg")
                cmd_frames = [
                    ffmpeg_bin, "-y", "-i", str(video_path),
                    "-vf", f"fps=1/{interval}", "-vframes", str(max_keyframes),
                    frame_pattern
                ]
                subprocess.run(cmd_frames, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
                
                for f in sorted(frames_dir.glob("*.jpg")):
                    keyframe_paths.append(str(f.as_posix()))
            except Exception as e:
                logger.error(f"Error extracting video keyframes: {e}")

        db.commit()

        # 4. Transcribe extracted audio if available
        transcript_res = None
        if audio_out_path.exists() and audio_out_path.stat().st_size > 1000:
            # Create a temporary or linked MediaAsset for the audio
            try:
                from owi.core.hashing import compute_sha256
                audio_asset = MediaAsset(
                    conversation_id=asset.conversation_id,
                    message_id=asset.message_id,
                    file_name=audio_out_path.name,
                    file_type="audio",
                    file_path=str(audio_out_path.as_posix()),
                    sha256_hash=compute_sha256(audio_out_path),
                    duration_seconds=duration
                )
                db.add(audio_asset)
                db.commit()
                db.refresh(audio_asset)
                transcript_res = AudioTranscriber.transcribe(audio_asset.id, db)
            except Exception as e:
                logger.error(f"Error transcribing extracted video audio: {e}")

        return {
            "media_asset_id": asset.id,
            "duration": duration,
            "keyframes": keyframe_paths,
            "transcript": transcript_res
        }
