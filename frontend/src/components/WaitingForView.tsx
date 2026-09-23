import React, { useState, useEffect } from 'react';
import { Clock, Check, X, User, Calendar, AlertCircle } from 'lucide-react';
import { WaitingItem } from '../types';
import { apiClient } from '../api/client';

interface WaitingProps {
  language: 'ar' | 'en';
  onUpdate?: () => void;
}

export const WaitingForView: React.FC<WaitingProps> = ({ language, onUpdate }) => {
  const [items, setItems] = useState<WaitingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'open' | 'resolved' | 'all'>('open');

  const isAr = language === 'ar';

  useEffect(() => {
    loadItems();
  }, [filter]);

  const loadItems = async () => {
    setLoading(true);
    try {
      const data = await apiClient.getWaiting(filter !== 'all' ? filter : undefined);
      setItems(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleStatus = async (id: number, status: string) => {
    try {
      await apiClient.updateWaiting(id, { status: status as any });
      await loadItems();
      if (onUpdate) onUpdate();
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div style={{ padding: '24px', overflowY: 'auto', height: '100%' }}>
      {/* Header */}
      <div style={{ marginBottom: '20px' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Clock size={20} color="#fbbf24" />
          {isAr ? 'قيد الانتظار (Waiting For)' : 'Waiting For Tracker'}
        </h2>
        <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          {isAr ? 'تتبع كل ما تنتظره من الزملاء أو العملاء أو الموردين (ملفات، عروض أسعار، ردود)' : 'Track pending deliverables, documents, prices, and replies from contacts'}
        </p>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '6px', marginBottom: '20px' }}>
        {[
          { id: 'open', label: isAr ? 'معلقة ومطلوبة' : 'Pending Open' },
          { id: 'resolved', label: isAr ? 'تم استلامها' : 'Resolved' },
          { id: 'all', label: isAr ? 'الكل' : 'All' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setFilter(tab.id as any)}
            style={{
              padding: '6px 14px',
              borderRadius: '8px',
              fontSize: '12px',
              fontWeight: filter === tab.id ? 600 : 400,
              backgroundColor: filter === tab.id ? 'var(--accent-color)' : 'var(--bg-secondary)',
              color: filter === tab.id ? 'white' : 'var(--text-secondary)',
              border: '1px solid var(--border-color)',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Items List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
            {isAr ? 'جارٍ تحميل العناصر...' : 'Loading items...'}
          </div>
        ) : items.length === 0 ? (
          <div className="card" style={{ textAlign: 'center', padding: '40px' }}>
            <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
              {isAr ? 'لا توجد عناصر قيد الانتظار حالياً' : 'No waiting items'}
            </p>
          </div>
        ) : (
          items.map((item) => (
            <div key={item.id} className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '16px', padding: '16px' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                  <span className="badge badge-waiting">
                    <User size={12} style={{ marginInlineEnd: '4px' }} />
                    {item.person_name}
                  </span>
                  <span style={{ fontSize: '11px', color: item.status === 'open' ? '#fbbf24' : '#34d399' }}>
                    {item.status.toUpperCase()}
                  </span>
                </div>

                <h3 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
                  {item.deliverable}
                </h3>

                {item.source_excerpt && (
                  <p style={{ fontSize: '11.5px', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                    "{item.source_excerpt}"
                  </p>
                )}
              </div>

              {/* Actions */}
              <div style={{ display: 'flex', gap: '8px' }}>
                {item.status === 'open' ? (
                  <button
                    onClick={() => handleStatus(item.id, 'resolved')}
                    className="btn btn-success"
                    style={{ fontSize: '11px', padding: '6px 12px' }}
                  >
                    <Check size={13} /> {isAr ? 'تم الاستلام' : 'Mark Received'}
                  </button>
                ) : (
                  <button
                    onClick={() => handleStatus(item.id, 'open')}
                    className="btn btn-secondary"
                    style={{ fontSize: '11px', padding: '6px 12px' }}
                  >
                    {isAr ? 'إعادة فتح' : 'Reopen'}
                  </button>
                )}
                {item.status !== 'dismissed' && (
                  <button
                    onClick={() => handleStatus(item.id, 'dismissed')}
                    className="btn btn-secondary"
                    style={{ fontSize: '11px', padding: '6px 12px', color: '#f87171' }}
                  >
                    <X size={13} />
                  </button>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
