import React, { useState, useEffect } from 'react';
import { Award, Calendar, Users, Quote, CheckCircle2 } from 'lucide-react';
import { DecisionItem } from '../types';
import { apiClient } from '../api/client';

interface DecisionsProps {
  language: 'ar' | 'en';
}

export const DecisionsView: React.FC<DecisionsProps> = ({ language }) => {
  const [decisions, setDecisions] = useState<DecisionItem[]>([]);
  const [loading, setLoading] = useState(true);

  const isAr = language === 'ar';

  useEffect(() => {
    loadDecisions();
  }, []);

  const loadDecisions = async () => {
    setLoading(true);
    try {
      const data = await apiClient.getDecisions();
      setDecisions(data);
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
          <Award size={22} color="#a855f7" />
          {isAr ? 'سجل القرارات والاتفاقات' : 'Decisions Register'}
        </h2>
        <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          {isAr
            ? 'سجل توثيقي للقرارات والتوافقات المتخذة في المحادثات مع هوية المشاركين والأدلة النصية'
            : 'Audit-ready register of agreed decisions, participants, timestamps, and verbatim citations'}
        </p>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
          {isAr ? 'جارٍ تحميل القرارات...' : 'Loading decisions...'}
        </div>
      ) : decisions.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '40px' }}>
          <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
            {isAr ? 'لا توجد قرارات مسجلة حتى الآن' : 'No decisions recorded yet'}
          </p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))', gap: '16px' }}>
          {decisions.map((d) => (
            <div key={d.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '12px', padding: '18px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                <span className="badge badge-open" style={{ backgroundColor: 'rgba(168, 85, 247, 0.2)', color: '#c084fc', border: '1px solid rgba(168, 85, 247, 0.3)' }}>
                  <CheckCircle2 size={12} style={{ display: 'inline', marginInlineEnd: '4px' }} />
                  {isAr ? 'قرار معتمد' : 'Agreed Decision'}
                </span>
                {d.confidence && (
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    {isAr ? 'ثقة:' : 'Confidence:'} {Math.round(d.confidence * 100)}%
                  </span>
                )}
              </div>

              <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.5 }}>
                {d.decision_text}
              </h3>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', fontSize: '12px', color: 'var(--text-secondary)' }}>
                {d.participants && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Users size={13} color="var(--wa-green)" />
                    <span>{d.participants}</span>
                  </div>
                )}
                {d.timestamp && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Calendar size={13} color="var(--text-muted)" />
                    <span>{new Date(d.timestamp).toLocaleDateString(isAr ? 'ar-EG' : 'en-US')}</span>
                  </div>
                )}
              </div>

              {d.source_excerpt && (
                <div style={{
                  backgroundColor: 'rgba(15, 23, 42, 0.6)',
                  padding: '10px',
                  borderRadius: '6px',
                  borderInlineStart: '3px solid #a855f7',
                  fontSize: '12px',
                  color: 'var(--text-muted)',
                  display: 'flex',
                  gap: '8px'
                }}>
                  <Quote size={14} style={{ flexShrink: 0, marginTop: '2px', opacity: 0.7 }} />
                  <span style={{ fontStyle: 'italic' }}>"{d.source_excerpt}"</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
