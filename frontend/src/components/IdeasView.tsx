import React, { useState, useEffect } from 'react';
import { Lightbulb, Quote, Sparkles } from 'lucide-react';
import { IdeaItem } from '../types';
import { apiClient } from '../api/client';

interface IdeasProps {
  language: 'ar' | 'en';
}

export const IdeasView: React.FC<IdeasProps> = ({ language }) => {
  const [ideas, setIdeas] = useState<IdeaItem[]>([]);
  const [loading, setLoading] = useState(true);

  const isAr = language === 'ar';

  useEffect(() => {
    loadIdeas();
  }, []);

  const loadIdeas = async () => {
    setLoading(true);
    try {
      const data = await apiClient.getIdeas();
      setIdeas(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '24px', overflowY: 'auto', height: '100%' }}>
      {/* Header */}
      <div style={{ marginBottom: '20px' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Lightbulb size={22} color="#eab308" />
          {isAr ? 'بنك الأفكار والمقترحات' : 'Ideas & Brainstorming Vault'}
        </h2>
        <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          {isAr
            ? 'الأفكار والمقترحات الإبداعية المستخلصة تلقائياً من نقاشات ومحادثات واتساب'
            : 'Creative ideas, suggestions, and proposals automatically captured from conversations'}
        </p>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
          {isAr ? 'جارٍ تحميل الأفكار...' : 'Loading ideas...'}
        </div>
      ) : ideas.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '40px' }}>
          <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
            {isAr ? 'لا توجد أفكار مسجلة حتى الآن' : 'No ideas captured yet'}
          </p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: '16px' }}>
          {ideas.map((idea) => (
            <div key={idea.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '12px', padding: '18px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="badge badge-open" style={{ backgroundColor: 'rgba(234, 179, 8, 0.2)', color: '#fde047', border: '1px solid rgba(234, 179, 8, 0.3)' }}>
                  <Sparkles size={12} style={{ display: 'inline', marginInlineEnd: '4px' }} />
                  {isAr ? 'فكرة مقترحة' : 'Proposal'}
                </span>
              </div>

              <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.5 }}>
                {idea.title}
              </h3>

              {idea.description && (
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                  {idea.description}
                </p>
              )}

              {idea.source_excerpt && (
                <div style={{
                  backgroundColor: 'rgba(15, 23, 42, 0.6)',
                  padding: '10px',
                  borderRadius: '6px',
                  borderInlineStart: '3px solid #eab308',
                  fontSize: '12px',
                  color: 'var(--text-muted)',
                  display: 'flex',
                  gap: '8px'
                }}>
                  <Quote size={14} style={{ flexShrink: 0, marginTop: '2px', opacity: 0.7 }} />
                  <span style={{ fontStyle: 'italic' }}>"{idea.source_excerpt}"</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
