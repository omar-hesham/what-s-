import React, { useState, useEffect } from 'react';
import {
  Sparkles, CheckSquare, Award, Building2, Send,
  HelpCircle, ChevronRight, FileText, Check, X, ExternalLink
} from 'lucide-react';
import { Conversation, TaskItem, DecisionItem, PropertyItem, AskResponse, Citation } from '../types';
import { apiClient } from '../api/client';

interface IntelProps {
  conversation: Conversation | null;
  language: 'ar' | 'en';
  onTaskUpdated?: () => void;
}

export const IntelligencePanel: React.FC<IntelProps> = ({
  conversation,
  language,
  onTaskUpdated,
}) => {
  const [activeTab, setActiveTab] = useState<'summary' | 'tasks' | 'decisions' | 'property' | 'ask'>('summary');
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [decisions, setDecisions] = useState<DecisionItem[]>([]);
  const [property, setProperty] = useState<PropertyItem | null>(null);

  // Ask Your WhatsApp state
  const [query, setQuery] = useState('');
  const [asking, setAsking] = useState(false);
  const [chatHistory, setChatHistory] = useState<Array<{ q: string; res: AskResponse }>>([]);

  const isAr = language === 'ar';

  useEffect(() => {
    if (conversation) {
      loadEntities();
    }
  }, [conversation?.id]);

  const loadEntities = async () => {
    if (!conversation) return;
    try {
      const [tList, dList, pList] = await Promise.all([
        apiClient.getTasks(undefined, conversation.id),
        apiClient.getDecisions(conversation.id),
        apiClient.getProperties(conversation.id),
      ]);
      setTasks(tList);
      setDecisions(dList);
      setProperty(pList.length > 0 ? pList[0] : null);
    } catch (e) {
      console.error(e);
    }
  };

  const handleTaskStatus = async (taskId: number, newStatus: string) => {
    try {
      await apiClient.updateTask(taskId, { status: newStatus as any });
      await loadEntities();
      if (onTaskUpdated) onTaskUpdated();
    } catch (e) {
      console.error(e);
    }
  };

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || asking) return;

    const userQ = query.trim();
    setQuery('');
    setAsking(true);

    try {
      const res = await apiClient.ask(userQ, conversation?.id);
      setChatHistory((prev) => [...prev, { q: userQ, res }]);
    } catch (err) {
      console.error(err);
    } finally {
      setAsking(false);
    }
  };

  if (!conversation) {
    return (
      <aside className="right-panel" style={{ padding: '24px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
        <p style={{ fontSize: '13px', textAlign: 'center' }}>
          {isAr ? 'اختر محادثة لعرض الذكاء الاصطناعي المستخرج' : 'Select a conversation to inspect intelligence'}
        </p>
      </aside>
    );
  }

  return (
    <aside className="right-panel">
      {/* Panel Tabs Header */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid var(--border-color)',
        backgroundColor: 'var(--bg-secondary)',
        padding: '6px 8px',
        gap: '4px',
        overflowX: 'auto',
      }}>
        {[
          { id: 'summary', label: isAr ? 'الملخص' : 'Summary' },
          { id: 'tasks', label: `${isAr ? 'المهام' : 'Tasks'} (${tasks.length})` },
          { id: 'decisions', label: `${isAr ? 'القرارات' : 'Decisions'} (${decisions.length})` },
          { id: 'property', label: isAr ? 'العقار' : 'Property' },
          { id: 'ask', label: isAr ? 'اسأل واتساب' : 'Ask AI' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as any)}
            style={{
              padding: '6px 10px',
              borderRadius: '6px',
              fontSize: '11.5px',
              fontWeight: activeTab === tab.id ? 600 : 400,
              backgroundColor: activeTab === tab.id ? 'var(--accent-color)' : 'transparent',
              color: activeTab === tab.id ? 'white' : 'var(--text-secondary)',
              whiteSpace: 'nowrap',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div style={{ flex: 1, padding: '16px', overflowY: 'auto' }}>
        {/* SUMMARY TAB */}
        {activeTab === 'summary' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div className="card">
              <h3 style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Sparkles size={14} color="var(--accent-color)" />
                {isAr ? 'الموجز التنفيذي السريع' : 'Quick Summary'}
              </h3>
              <p style={{ fontSize: '12.5px', lineHeight: 1.6, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>
                {conversation.summary || (isAr ? 'انقر على "تحليل بالذكاء الاصطناعي" لتوليد الموجز.' : 'Click "Run AI Analysis" to generate summary.')}
              </p>
            </div>

            {/* Quick Metrics */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
              <div className="card" style={{ padding: '10px' }}>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'إجمالي المهام' : 'Total Tasks'}</span>
                <p style={{ fontSize: '18px', fontWeight: 700, color: '#60a5fa' }}>{tasks.length}</p>
              </div>
              <div className="card" style={{ padding: '10px' }}>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'القرارات المتخذة' : 'Decisions'}</span>
                <p style={{ fontSize: '18px', fontWeight: 700, color: '#34d399' }}>{decisions.length}</p>
              </div>
            </div>
          </div>
        )}

        {/* TASKS TAB */}
        {activeTab === 'tasks' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontSize: '13px', fontWeight: 700 }}>
                {isAr ? 'المهام المستخرجة' : 'Extracted Tasks'}
              </h3>
              <span className="badge badge-inbox">{tasks.length}</span>
            </div>

            {tasks.length === 0 ? (
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', textAlign: 'center', marginTop: '20px' }}>
                {isAr ? 'لا توجد مهام مستخرجة حالياً' : 'No extracted tasks'}
              </p>
            ) : (
              tasks.map((task) => (
                <div key={task.id} className="card" style={{ padding: '12px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                    <p style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--text-primary)' }}>
                      {task.title}
                    </p>
                    <span className={`badge ${task.status === 'inbox' ? 'badge-inbox' : 'badge-open'}`}>
                      {task.status}
                    </span>
                  </div>

                  {task.due_date && (
                    <p style={{ fontSize: '11px', color: '#fbbf24', marginTop: '4px' }}>
                      📅 {isAr ? 'الموعد المحدد:' : 'Due:'} {new Date(task.due_date).toLocaleDateString()}
                    </p>
                  )}

                  {task.source_excerpt && (
                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px', fontStyle: 'italic' }}>
                      "{task.source_excerpt}"
                    </p>
                  )}

                  {/* Actions: Accept / Dismiss */}
                  <div style={{ display: 'flex', gap: '6px', marginTop: '8px' }}>
                    {task.status === 'inbox' && (
                      <button
                        onClick={() => handleTaskStatus(task.id, 'open')}
                        className="btn btn-success"
                        style={{ padding: '4px 8px', fontSize: '11px' }}
                      >
                        <Check size={12} /> {isAr ? 'قبول' : 'Accept'}
                      </button>
                    )}
                    {task.status !== 'completed' && (
                      <button
                        onClick={() => handleTaskStatus(task.id, 'completed')}
                        className="btn btn-secondary"
                        style={{ padding: '4px 8px', fontSize: '11px' }}
                      >
                        {isAr ? 'إنجاز' : 'Done'}
                      </button>
                    )}
                    {task.status !== 'dismissed' && (
                      <button
                        onClick={() => handleTaskStatus(task.id, 'dismissed')}
                        className="btn btn-secondary"
                        style={{ padding: '4px 8px', fontSize: '11px', color: '#f87171' }}
                      >
                        <X size={12} /> {isAr ? 'تجاهل' : 'Dismiss'}
                      </button>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* DECISIONS TAB */}
        {activeTab === 'decisions' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <h3 style={{ fontSize: '13px', fontWeight: 700 }}>
              {isAr ? 'القرارات والاتفاقات' : 'Recorded Decisions'}
            </h3>
            {decisions.length === 0 ? (
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', textAlign: 'center', marginTop: '20px' }}>
                {isAr ? 'لا توجد قرارات مسجلة' : 'No decisions recorded'}
              </p>
            ) : (
              decisions.map((d) => (
                <div key={d.id} className="card" style={{ padding: '12px' }}>
                  <p style={{ fontSize: '12.5px', fontWeight: 600, color: '#34d399' }}>
                    🤝 {d.decision_text}
                  </p>
                  {d.participants && (
                    <p style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                      {isAr ? 'المشاركون:' : 'Participants:'} {d.participants}
                    </p>
                  )}
                  {d.source_excerpt && (
                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px', fontStyle: 'italic' }}>
                      "{d.source_excerpt}"
                    </p>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {/* PROPERTY STONE MODE TAB */}
        {activeTab === 'property' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <h3 style={{ fontSize: '13px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Building2 size={15} color="var(--wa-green)" />
              {isAr ? 'بيانات العقار (Stone Mode)' : 'Property Intelligence'}
            </h3>

            {!property ? (
              <div className="card" style={{ textAlign: 'center', padding: '24px' }}>
                <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                  {isAr ? 'لم يتم رصد تفاصيل عقار في هذه المحادثة.' : 'No property details identified in this chat.'}
                </p>
              </div>
            ) : (
              <div className="card" style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <h4 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>
                  {property.title}
                </h4>

                <div style={{ fontSize: '12px', lineHeight: 1.6, color: 'var(--text-secondary)' }}>
                  <p>• <strong>{isAr ? 'المساحة:' : 'Area:'}</strong> {property.area_sqm || '-'} م²</p>
                  <p>• <strong>{isAr ? 'السعر:' : 'Price:'}</strong> {property.price ? `${property.price.toLocaleString()} ${property.currency}` : 'غير محدد'}</p>
                  <p>• <strong>{isAr ? 'الموقع:' : 'Location:'}</strong> {property.location || '-'}</p>
                  <p>• <strong>{isAr ? 'الترخيص الإداري:' : 'Admin License:'}</strong> {property.has_admin_license ? (isAr ? 'مرخص إداري' : 'Yes') : (isAr ? 'غير محدد' : 'No')}</p>
                  <p>• <strong>{isAr ? 'التشطيب:' : 'Finishing:'}</strong> {property.finishing || '-'}</p>
                </div>

                {property.listing_draft && (
                  <div style={{ marginTop: '8px', borderTop: '1px solid var(--border-color)', paddingTop: '8px' }}>
                    <p style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                      {isAr ? 'مسودة الإعلان المقترحة:' : 'Generated Listing Draft:'}
                    </p>
                    <div style={{
                      backgroundColor: 'rgba(15, 23, 42, 0.8)',
                      padding: '10px',
                      borderRadius: '8px',
                      fontSize: '11.5px',
                      whiteSpace: 'pre-wrap',
                      fontFamily: 'monospace',
                    }}>
                      {property.listing_draft}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ASK YOUR WHATSAPP TAB */}
        {activeTab === 'ask' && (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <h3 style={{ fontSize: '13px', fontWeight: 700, marginBottom: '8px' }}>
              {isAr ? 'اسأل محادثاتك (استرجاع محلي دقيق)' : 'Ask Your WhatsApp (Grounded RAG)'}
            </h3>

            {/* Q&A Stream */}
            <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '12px' }}>
              {chatHistory.length === 0 && (
                <div style={{ textAlign: 'center', padding: '30px 10px', color: 'var(--text-muted)', fontSize: '12px' }}>
                  <HelpCircle size={28} style={{ margin: '0 auto 8px auto', opacity: 0.5 }} />
                  <p>{isAr ? 'اسأل أي سؤال وسيتم الإجابة بالاستشهاد بالمصدر المحلي فقط بدون هلوسة.' : 'Ask any question. Answers cite exact local sources only.'}</p>
                  <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <button
                      onClick={() => setQuery(isAr ? 'ما هو سعر إيجار المقر؟' : 'What was the office rent price?')}
                      style={{ background: 'var(--bg-tertiary)', padding: '4px 8px', borderRadius: '4px', fontSize: '11px', color: 'var(--text-secondary)' }}
                    >
                      💡 {isAr ? 'ما هو سعر إيجار المقر؟' : 'What was the office rent price?'}
                    </button>
                    <button
                      onClick={() => setQuery(isAr ? 'ما الذي ننتظره من جهات الاتصال؟' : 'What are we waiting for?')}
                      style={{ background: 'var(--bg-tertiary)', padding: '4px 8px', borderRadius: '4px', fontSize: '11px', color: 'var(--text-secondary)' }}
                    >
                      💡 {isAr ? 'ما الذي ننتظره من جهات الاتصال؟' : 'What are we waiting for?'}
                    </button>
                  </div>
                </div>
              )}

              {chatHistory.map((item, idx) => (
                <div key={idx} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <div style={{ alignSelf: 'flex-end', backgroundColor: 'var(--accent-color)', color: 'white', padding: '6px 12px', borderRadius: '10px', fontSize: '12px', maxWidth: '85%' }}>
                    {item.q}
                  </div>
                  <div className="card" style={{ padding: '10px', fontSize: '12px', lineHeight: 1.5 }}>
                    <p style={{ whiteSpace: 'pre-wrap' }}>{item.res.answer}</p>
                    
                    {/* Citations List */}
                    {item.res.citations && item.res.citations.length > 0 && (
                      <div style={{ marginTop: '8px', borderTop: '1px solid var(--border-color)', paddingTop: '6px' }}>
                        <span style={{ fontSize: '10px', color: 'var(--accent-color)', fontWeight: 700 }}>
                          {isAr ? '📌 المصادر المحلية المستشهد بها:' : '📌 Cited Local Sources:'}
                        </span>
                        {item.res.citations.map((c, cIdx) => (
                          <div key={cIdx} style={{ fontSize: '10.5px', color: 'var(--text-muted)', marginTop: '3px', background: 'rgba(0,0,0,0.2)', padding: '4px 6px', borderRadius: '4px' }}>
                            {c.sender && <strong>{c.sender}: </strong>}
                            {c.content || c.deliverable || c.title || c.evidence}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Input Form */}
            <form onSubmit={handleAsk} style={{ display: 'flex', gap: '6px' }}>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={isAr ? 'اسأل عن الأسعار، المهام، التواريخ...' : 'Ask about prices, tasks, dates...'}
                style={{
                  flex: 1,
                  padding: '8px 12px',
                  borderRadius: '8px',
                  backgroundColor: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-color)',
                  color: 'white',
                  fontSize: '12px',
                  outline: 'none',
                }}
              />
              <button
                type="submit"
                disabled={asking || !query.trim()}
                className="btn btn-primary"
                style={{ padding: '8px 12px' }}
              >
                <Send size={14} />
              </button>
            </form>
          </div>
        )}
      </div>
    </aside>
  );
};
