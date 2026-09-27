import React, { useState } from 'react';
import { FileText, Download, ExternalLink, ChevronDown, ChevronUp, Copy, Check } from 'lucide-react';
import { MediaAsset } from '../types';
import { apiClient } from '../api/client';

interface DocumentCardProps {
  asset: MediaAsset;
}

export const DocumentCard: React.FC<DocumentCardProps> = ({ asset }) => {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const mediaUrl = apiClient.getMediaUrl(asset.id);
  const doc = asset.document;

  const getDocBadgeColor = (name: string) => {
    const ext = name.split('.').pop()?.toLowerCase();
    if (ext === 'pdf') return '#ef4444';
    if (ext === 'xlsx' || ext === 'xls') return '#10b981';
    if (ext === 'docx' || ext === 'doc') return '#3b82f6';
    return '#8b5cf6';
  };

  const badgeColor = getDocBadgeColor(asset.file_name);

  const handleCopy = () => {
    if (doc?.extracted_text) {
      navigator.clipboard.writeText(doc.extracted_text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div style={{
      backgroundColor: 'rgba(30, 41, 59, 0.85)',
      border: '1px solid var(--border-color)',
      borderRadius: '10px',
      padding: '12px',
      marginTop: '6px',
      maxWidth: '520px',
      display: 'flex',
      flexDirection: 'column',
      gap: '8px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', overflow: 'hidden' }}>
          <div style={{
            width: '38px',
            height: '38px',
            borderRadius: '8px',
            backgroundColor: `${badgeColor}20`,
            border: `1px solid ${badgeColor}50`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: badgeColor,
            flexShrink: 0,
          }}>
            <FileText size={20} />
          </div>

          <div style={{ overflow: 'hidden' }}>
            <p style={{
              fontSize: '13px',
              fontWeight: 600,
              color: 'var(--text-primary)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>
              {asset.file_name}
            </p>
            <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              {doc ? `${doc.doc_type.toUpperCase()} • ${doc.page_count} صفحة` : `${Math.round(asset.file_size / 1024)} KB`}
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          {doc && doc.extracted_text && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="btn btn-secondary"
              style={{ padding: '6px 8px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}
              title={expanded ? 'طي النص المستخرج' : 'عرض النص المستخرج'}
            >
              <span>{expanded ? 'إخفاء' : 'قراءة النص'}</span>
              {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
          )}

          <a
            href={mediaUrl}
            target="_blank"
            rel="noreferrer"
            className="btn btn-secondary"
            style={{ padding: '6px 8px', fontSize: '11px', flexShrink: 0 }}
            title="تنزيل المستند الأصلي"
          >
            <Download size={13} />
          </a>
        </div>
      </div>

      {/* Expandable Extracted Content */}
      {expanded && doc && doc.extracted_text && (
        <div style={{
          marginTop: '6px',
          padding: '10px',
          backgroundColor: 'rgba(15, 23, 42, 0.7)',
          borderRadius: '8px',
          border: '1px solid rgba(255, 255, 255, 0.08)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <span style={{ fontSize: '11px', color: '#60a5fa', fontWeight: 600 }}>
              📄 النص المستخرج من المستند ({doc.title})
            </span>
            <button
              onClick={handleCopy}
              style={{
                background: 'transparent',
                border: 'none',
                color: copied ? '#34d399' : 'var(--text-muted)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                fontSize: '11px',
              }}
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              <span>{copied ? 'تم النسخ' : 'نسخ'}</span>
            </button>
          </div>
          <div style={{
            fontSize: '12px',
            color: 'var(--text-primary)',
            lineHeight: 1.6,
            maxHeight: '260px',
            overflowY: 'auto',
            whiteSpace: 'pre-wrap',
            paddingRight: '6px',
          }}>
            {doc.extracted_text}
          </div>
        </div>
      )}
    </div>
  );
};
