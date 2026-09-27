import React, { useState } from 'react';
import { Eye, FileText, ChevronDown, ChevronUp, Copy, Check } from 'lucide-react';
import { MediaAsset } from '../types';
import { apiClient } from '../api/client';

interface ImageCardProps {
  asset: MediaAsset;
}

export const ImageCard: React.FC<ImageCardProps> = ({ asset }) => {
  const [showOcr, setShowOcr] = useState(false);
  const [copied, setCopied] = useState(false);
  const mediaUrl = apiClient.getMediaUrl(asset.id);
  const ocrText = asset.document?.extracted_text;

  const handleCopy = () => {
    if (ocrText) {
      navigator.clipboard.writeText(ocrText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div style={{
      backgroundColor: 'rgba(30, 41, 59, 0.8)',
      border: '1px solid var(--border-color)',
      borderRadius: '10px',
      overflow: 'hidden',
      marginTop: '6px',
      maxWidth: '380px',
    }}>
      <div style={{ position: 'relative' }}>
        <img
          src={mediaUrl}
          alt={asset.file_name}
          style={{ width: '100%', height: 'auto', maxHeight: '240px', objectFit: 'contain', backgroundColor: 'rgba(0,0,0,0.3)', display: 'block' }}
          onError={(e) => {
            (e.target as HTMLImageElement).src = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="150" viewBox="0 0 300 150"><rect fill="%231e293b" width="300" height="150"/><text fill="%2394a3b8" font-family="sans-serif" font-size="14" dy="10.5" font-weight="bold" x="50%" y="50%" text-anchor="middle">Image Attachment</text></svg>';
          }}
        />
        <div style={{
          position: 'absolute',
          bottom: '6px',
          right: '6px',
          backgroundColor: 'rgba(0,0,0,0.7)',
          borderRadius: '4px',
          padding: '2px 6px',
          fontSize: '10px',
          color: 'white',
        }}>
          {asset.file_name}
        </div>
      </div>

      <div style={{ padding: '8px 10px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-muted)' }}>
        <span>{asset.width ? `${asset.width}×${asset.height} px` : `${Math.round(asset.file_size / 1024)} KB`}</span>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {ocrText && (
            <button
              onClick={() => setShowOcr(!showOcr)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '3px',
                background: 'none',
                border: 'none',
                color: showOcr ? '#34d399' : '#60a5fa',
                cursor: 'pointer',
                fontSize: '11px',
                padding: '2px 6px',
                borderRadius: '4px',
                backgroundColor: showOcr ? 'rgba(52, 211, 153, 0.15)' : 'rgba(96, 165, 250, 0.15)'
              }}
              title="عرض النص المستخرج عبر OCR"
            >
              <FileText size={11} />
              <span>{showOcr ? 'إخفاء النص' : 'نص الصورة (OCR)'}</span>
              {showOcr ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            </button>
          )}

          <a
            href={mediaUrl}
            target="_blank"
            rel="noreferrer"
            style={{ color: 'var(--accent-color)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '3px' }}
          >
            <Eye size={12} /> فتح بالحجم الكامل
          </a>
        </div>
      </div>

      {showOcr && ocrText && (
        <div style={{
          padding: '10px',
          backgroundColor: 'rgba(15, 23, 42, 0.95)',
          borderTop: '1px solid var(--border-color)',
          fontSize: '11.5px',
          lineHeight: '1.6',
          color: 'var(--text-secondary)',
          direction: 'rtl',
          textAlign: 'right',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <span style={{ fontSize: '10.5px', fontWeight: 600, color: 'var(--text-muted)' }}>النص المستخرج عبر OCR:</span>
            <button
              onClick={handleCopy}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                background: 'none',
                border: 'none',
                color: copied ? '#34d399' : 'var(--text-muted)',
                cursor: 'pointer',
                fontSize: '10.5px',
              }}
            >
              {copied ? <Check size={11} /> : <Copy size={11} />}
              <span>{copied ? 'تم النسخ' : 'نسخ'}</span>
            </button>
          </div>
          <div style={{ maxHeight: '180px', overflowY: 'auto', whiteSpace: 'pre-wrap', padding: '4px' }}>
            {ocrText}
          </div>
        </div>
      )}
    </div>
  );
};
