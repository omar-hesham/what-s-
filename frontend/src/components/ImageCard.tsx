import React, { useState } from 'react';
import { Eye, FileText } from 'lucide-react';
import { MediaAsset } from '../types';
import { apiClient } from '../api/client';

interface ImageCardProps {
  asset: MediaAsset;
}

export const ImageCard: React.FC<ImageCardProps> = ({ asset }) => {
  const [showOcr, setShowOcr] = useState(false);
  const mediaUrl = apiClient.getMediaUrl(asset.id);

  return (
    <div style={{
      backgroundColor: 'rgba(30, 41, 59, 0.8)',
      border: '1px solid var(--border-color)',
      borderRadius: '10px',
      overflow: 'hidden',
      marginTop: '6px',
      maxWidth: '320px',
    }}>
      <div style={{ position: 'relative' }}>
        <img
          src={mediaUrl}
          alt={asset.file_name}
          style={{ width: '100%', height: 'auto', maxHeight: '220px', objectFit: 'cover', display: 'block' }}
          onError={(e) => {
            // Placeholder if image failed loading
            (e.target as HTMLImageElement).src = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="150" viewBox="0 0 300 150"><rect fill="%231e293b" width="300" height="150"/><text fill="%2394a3b8" font-family="sans-serif" font-size="14" dy="10.5" font-weight="bold" x="50%" y="50%" text-anchor="middle">Image Attachment</text></svg>';
          }}
        />
        <div style={{
          position: 'absolute',
          bottom: '6px',
          right: '6px',
          backgroundColor: 'rgba(0,0,0,0.6)',
          borderRadius: '4px',
          padding: '2px 6px',
          fontSize: '10px',
          color: 'white',
        }}>
          {asset.file_name}
        </div>
      </div>

      <div style={{ padding: '8px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-muted)' }}>
        <span>{asset.width ? `${asset.width}x${asset.height} px` : `${Math.round(asset.file_size / 1024)} KB`}</span>
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
  );
};
