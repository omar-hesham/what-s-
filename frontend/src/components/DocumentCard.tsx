import React from 'react';
import { FileText, Download, ExternalLink } from 'lucide-react';
import { MediaAsset } from '../types';
import { apiClient } from '../api/client';

interface DocumentCardProps {
  asset: MediaAsset;
}

export const DocumentCard: React.FC<DocumentCardProps> = ({ asset }) => {
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

  return (
    <div style={{
      backgroundColor: 'rgba(30, 41, 59, 0.8)',
      border: '1px solid var(--border-color)',
      borderRadius: '10px',
      padding: '12px',
      marginTop: '6px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: '12px',
      maxWidth: '360px',
    }}>
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

      <a
        href={mediaUrl}
        target="_blank"
        rel="noreferrer"
        className="btn btn-secondary"
        style={{ padding: '6px 10px', fontSize: '11px', flexShrink: 0 }}
        title="فتح المستند"
      >
        <ExternalLink size={13} />
      </a>
    </div>
  );
};
