import React, { useState } from 'react';
import { Search, X, MessageSquare, Mic, Image as ImageIcon, FileText } from 'lucide-react';
import { apiClient } from '../api/client';

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectResult: (conversationId: number) => void;
  language: 'ar' | 'en';
}

export const SearchModal: React.FC<SearchModalProps> = ({
  isOpen,
  onClose,
  onSelectResult,
  language,
}) => {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<'hybrid' | 'fts' | 'semantic'>('hybrid');
  const [results, setResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);

  const isAr = language === 'ar';

  if (!isOpen) return null;

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setSearching(true);
    try {
      const res = await apiClient.search(query, mode);
      setResults(res.results || []);
    } catch (e) {
      console.error(e);
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '650px' }}>
        {/* Search Input Bar */}
        <form onSubmit={handleSearch} style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Search size={18} color="var(--text-muted)" />
          <input
            type="text"
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={isAr ? 'بحث شامل في كل الرسائل والمستندات والتفريغات الصوتية...' : 'Search all messages, documents, and transcripts...'}
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: 'white',
              fontSize: '14px',
            }}
          />
          <button type="submit" disabled={searching} className="btn btn-primary" style={{ padding: '6px 12px', fontSize: '12px' }}>
            {searching ? (isAr ? 'جارٍ البحث...' : 'Searching...') : (isAr ? 'بحث' : 'Search')}
          </button>
          <button type="button" onClick={onClose} style={{ background: 'transparent', color: 'var(--text-muted)' }}>
            <X size={18} />
          </button>
        </form>

        {/* Mode Selector */}
        <div style={{ padding: '8px 16px', backgroundColor: 'rgba(0,0,0,0.2)', display: 'flex', gap: '8px', fontSize: '11px' }}>
          <span style={{ color: 'var(--text-muted)', alignSelf: 'center' }}>{isAr ? 'طريقة البحث:' : 'Search Mode:'}</span>
          {[
            { id: 'hybrid', label: isAr ? 'هجين (نصي + دلالي)' : 'Hybrid (FTS + Semantic)' },
            { id: 'fts', label: isAr ? 'نصي فقط (FTS5)' : 'Full-Text Only' },
            { id: 'semantic', label: isAr ? 'دلالي ذكي (Semantic)' : 'Semantic Vectors' },
          ].map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => setMode(m.id as any)}
              style={{
                background: mode === m.id ? 'var(--accent-color)' : 'transparent',
                color: mode === m.id ? 'white' : 'var(--text-secondary)',
                padding: '2px 8px',
                borderRadius: '4px',
              }}
            >
              {m.label}
            </button>
          ))}
        </div>

        {/* Results Feed */}
        <div style={{ padding: '16px', maxHeight: '400px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {results.length === 0 ? (
            <p style={{ textAlign: 'center', padding: '30px', color: 'var(--text-muted)', fontSize: '12px' }}>
              {isAr ? 'اكتب كلمة للبحث واضغط Enter' : 'Enter search terms and press Enter'}
            </p>
          ) : (
            results.map((r, idx) => (
              <div
                key={idx}
                onClick={() => {
                  onSelectResult(r.conversation_id);
                  onClose();
                }}
                className="card"
                style={{ padding: '10px 14px', cursor: 'pointer' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  <span style={{ fontWeight: 600, color: '#93c5fd' }}>{r.sender_name}</span>
                  <span>{new Date(r.timestamp).toLocaleDateString()}</span>
                </div>
                <p style={{ fontSize: '12.5px', color: 'var(--text-primary)', lineHeight: 1.4 }}>
                  {r.content}
                </p>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
