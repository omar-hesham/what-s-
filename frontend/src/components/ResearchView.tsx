import React, { useState, useEffect } from 'react';
import { BookOpen, User, HelpCircle, FileText, CheckCircle2, Bookmark } from 'lucide-react';
import { ResearchItem } from '../types';
import { apiClient } from '../api/client';

interface ResearchProps {
  language: 'ar' | 'en';
}

export const ResearchView: React.FC<ResearchProps> = ({ language }) => {
  const [researchItems, setResearchItems] = useState<ResearchItem[]>([]);
  const [loading, setLoading] = useState(true);

  const isAr = language === 'ar';

  useEffect(() => {
    loadResearch();
  }, []);

  const loadResearch = async () => {
    setLoading(true);
    try {
      const data = await apiClient.getResearch();
      setResearchItems(data);
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
          <BookOpen size={22} color="#3b82f6" />
          {isAr ? 'وضع الأبحاث الأكاديمية والاستقصائية' : 'Research & Investigation Mode'}
        </h2>
        <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          {isAr
            ? 'استخراج أسئلة البحث، الفرضيات، الأوراق العلمية، التوثيقات والنتائج المستخلصة'
            : 'Structured extraction of research questions, hypotheses, paper citations, and investigative findings'}
        </p>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
          {isAr ? 'جارٍ تحميل الأبحاث...' : 'Loading research items...'}
        </div>
      ) : researchItems.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '40px' }}>
          <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
            {isAr ? 'لا توجد أبحاث أو أوراق مسجلة حتى الآن' : 'No research items identified yet'}
          </p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))', gap: '16px' }}>
          {researchItems.map((r) => (
            <div key={r.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '12px', padding: '18px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="badge badge-open" style={{ backgroundColor: 'rgba(59, 130, 246, 0.2)', color: '#93c5fd', border: '1px solid rgba(59, 130, 246, 0.3)' }}>
                  <Bookmark size={12} style={{ display: 'inline', marginInlineEnd: '4px' }} />
                  {r.topic || (isAr ? 'بحث علمي' : 'Research Item')}
                </span>
                {r.author && (
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <User size={12} /> {r.author}
                  </span>
                )}
              </div>

              {r.question && (
                <div>
                  <h4 style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '4px' }}>
                    <HelpCircle size={13} color="#60a5fa" /> {isAr ? 'سؤال البحث / الفرضية:' : 'Research Question / Hypothesis:'}
                  </h4>
                  <p style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>
                    {r.question}
                  </p>
                </div>
              )}

              {r.finding && (
                <div>
                  <h4 style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '4px' }}>
                    <CheckCircle2 size={13} color="var(--wa-green)" /> {isAr ? 'النتيجة / المستخلص:' : 'Finding / Discovery:'}
                  </h4>
                  <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                    {r.finding}
                  </p>
                </div>
              )}

              {r.citation && (
                <div style={{
                  backgroundColor: 'rgba(15, 23, 42, 0.6)',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  fontSize: '11px',
                  color: 'var(--text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px'
                }}>
                  <FileText size={13} color="#93c5fd" />
                  <span>{isAr ? 'التوثيق / الورقة:' : 'Citation / Paper:'} {r.citation}</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
