import React, { useState, useRef } from 'react';
import { Play, Pause, Volume2, ChevronDown, ChevronUp } from 'lucide-react';
import { MediaAsset } from '../types';
import { apiClient } from '../api/client';

interface VoiceCardProps {
  asset: MediaAsset;
  senderName: string;
}

export const VoiceMessageCard: React.FC<VoiceCardProps> = ({ asset, senderName }) => {
  const [isPlaying, setIsPlaying] = useState(false);
  const [showFullTranscript, setShowFullTranscript] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const mediaUrl = apiClient.getMediaUrl(asset.id);
  const transcript = asset.transcript;

  const togglePlay = () => {
    if (!audioRef.current) return;
    if (isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
    } else {
      audioRef.current.play();
      setIsPlaying(true);
    }
  };

  const seekTo = (seconds: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = seconds;
      audioRef.current.play();
      setIsPlaying(true);
    }
  };

  const formatTime = (sec: number) => {
    const mins = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${mins}:${s < 10 ? '0' : ''}${s}`;
  };

  return (
    <div style={{
      backgroundColor: 'rgba(30, 41, 59, 0.8)',
      border: '1px solid var(--border-color)',
      borderRadius: '10px',
      padding: '12px',
      marginTop: '6px',
      maxWidth: '100%',
    }}>
      <audio
        ref={audioRef}
        src={mediaUrl}
        onTimeUpdate={() => audioRef.current && setCurrentTime(audioRef.current.currentTime)}
        onEnded={() => setIsPlaying(false)}
      />

      {/* Audio Bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <button
          onClick={togglePlay}
          style={{
            width: '36px',
            height: '36px',
            borderRadius: '50%',
            backgroundColor: 'var(--wa-green)',
            color: 'white',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {isPlaying ? <Pause size={16} /> : <Play size={16} style={{ marginInlineStart: '2px' }} />}
        </button>

        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
            <span>{formatTime(currentTime)}</span>
            <span>{formatTime(asset.duration_seconds || 0)}</span>
          </div>
          {/* Progress bar */}
          <div
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const pct = (e.clientX - rect.left) / rect.width;
              seekTo(pct * (asset.duration_seconds || 1));
            }}
            style={{
              height: '5px',
              backgroundColor: 'var(--bg-tertiary)',
              borderRadius: '4px',
              cursor: 'pointer',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${asset.duration_seconds ? (currentTime / asset.duration_seconds) * 100 : 0}%`,
                height: '100%',
                backgroundColor: 'var(--wa-green)',
                borderRadius: '4px',
              }}
            />
          </div>
        </div>

        <Volume2 size={16} color="var(--text-muted)" />
      </div>

      {/* Transcript Excerpt */}
      {transcript && (
        <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--text-primary)', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '11px', color: 'var(--wa-green)', fontWeight: 600 }}>
              🎤 تفريغ صوتي ({transcript.language || 'عربي'})
            </span>
            <button
              onClick={() => setShowFullTranscript(!showFullTranscript)}
              style={{ background: 'transparent', color: 'var(--text-muted)', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '3px' }}
            >
              {showFullTranscript ? 'طي' : 'عرض المقاطع'}
              {showFullTranscript ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
          </div>

          <p style={{ marginTop: '4px', fontStyle: 'italic', lineHeight: 1.4 }}>
            "{transcript.full_text}"
          </p>

          {/* Timed scrubbable segments */}
          {showFullTranscript && transcript.segments && transcript.segments.length > 0 && (
            <div style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {transcript.segments.map((seg, idx) => (
                <div
                  key={idx}
                  onClick={() => seekTo(seg.start)}
                  style={{
                    padding: '4px 6px',
                    borderRadius: '4px',
                    backgroundColor: 'rgba(51, 65, 85, 0.4)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: '11.5px',
                  }}
                  title="انقر للاستماع من هذه النقطة"
                >
                  <span style={{ color: 'var(--accent-color)', fontWeight: 600, fontFamily: 'monospace' }}>
                    [{formatTime(seg.start)}]
                  </span>
                  <span>{seg.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
