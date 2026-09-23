import React, { useState, useEffect } from 'react';
import {
  Calendar, CheckSquare, Clock, Award, Building2,
  FileText, Sparkles, Copy, Check, RefreshCw
} from 'lucide-react';
import { TodayMetrics } from '../types';
import { apiClient } from '../api/client';

interface TodayProps {
  language: 'ar' | 'en';
}

export const TodayDashboard: React.FC<TodayProps> = ({ language }) => {
  const [metrics, setMetrics] = useState<TodayMetrics | null>(null);
  const [recentTasks, setRecentTasks] = useState<any[]>([]);
  const [recentWaiting, setRecentWaiting] = useState<any[]>([]);
  const [briefing, setBriefing] = useState<string>('');
  const [briefingType, setBriefingType] = useState<'daily' | 'weekly'>('daily');
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(true);

  const isAr = language === 'ar';

  useEffect(() => {
    loadData();
  }, [briefingType]);

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await apiClient.getTodayDashboard();
      setMetrics(data.metrics);
      setRecentTasks(data.recent_tasks);
      setRecentWaiting(data.recent_waiting);

      const bData = await apiClient.getBriefing(briefingType);
      setBriefing(bData.content_markdown);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const copyBriefing = () => {
    navigator.clipboard.writeText(briefing);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (loading && !metrics) {
    return (
      <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
        {isAr ? 'جارٍ تحميل لوحة اليوم والموجز...' : 'Loading today dashboard...'}
      </div>
    );
  }

  return (
    <div style={{ padding: '24px', overflowY: 'auto', height: '100%' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Calendar size={20} color="var(--accent-color)" />
            {isAr ? 'لوحة اليوم والموجز التنفيذي' : 'Today & Executive Briefing'}
          </h2>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            {isAr ? 'نظرة شاملة فورية على جميع المحادثات والمهام المستخرجة' : 'Real-time overview of conversations, tasks, and waiting items'}
          </p>
        </div>

        <button onClick={loadData} className="btn btn-secondary" style={{ fontSize: '12px' }}>
          <RefreshCw size={13} /> {isAr ? 'تحديث' : 'Refresh'}
        </button>
      </div>

      {/* Metrics Cards Grid */}
      {metrics && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '12px', marginBottom: '24px' }}>
          <div className="card" style={{ padding: '12px' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'المحادثات' : 'Chats'}</span>
            <p style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)' }}>{metrics.conversations}</p>
          </div>
          <div className="card" style={{ padding: '12px' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'الرسائل' : 'Messages'}</span>
            <p style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)' }}>{metrics.messages}</p>
          </div>
          <div className="card" style={{ padding: '12px' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'الصوتيات' : 'Voice Notes'}</span>
            <p style={{ fontSize: '20px', fontWeight: 700, color: 'var(--wa-green)' }}>{metrics.voice_notes}</p>
          </div>
          <div className="card" style={{ padding: '12px' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'وارد المهام' : 'Inbox Tasks'}</span>
            <p style={{ fontSize: '20px', fontWeight: 700, color: '#60a5fa' }}>{metrics.inbox_tasks}</p>
          </div>
          <div className="card" style={{ padding: '12px' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'قيد الانتظار' : 'Waiting For'}</span>
            <p style={{ fontSize: '20px', fontWeight: 700, color: '#fbbf24' }}>{metrics.waiting_items}</p>
          </div>
          <div className="card" style={{ padding: '12px' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'القرارات' : 'Decisions'}</span>
            <p style={{ fontSize: '20px', fontWeight: 700, color: '#34d399' }}>{metrics.decisions}</p>
          </div>
          <div className="card" style={{ padding: '12px' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'العقارات' : 'Properties'}</span>
            <p style={{ fontSize: '20px', fontWeight: 700, color: '#a78bfa' }}>{metrics.properties}</p>
          </div>
        </div>
      )}

      {/* Briefing Generator Section */}
      <div className="card" style={{ padding: '20px', marginBottom: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Sparkles size={16} color="var(--accent-color)" />
            <h3 style={{ fontSize: '15px', fontWeight: 700 }}>
              {isAr ? 'الموجز التنفيذي الذكي' : 'Automated Executive Briefing'}
            </h3>
          </div>

          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={() => setBriefingType('daily')}
              className={`btn ${briefingType === 'daily' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ fontSize: '11px', padding: '4px 10px' }}
            >
              {isAr ? 'موجز يومي' : 'Daily'}
            </button>
            <button
              onClick={() => setBriefingType('weekly')}
              className={`btn ${briefingType === 'weekly' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ fontSize: '11px', padding: '4px 10px' }}
            >
              {isAr ? 'موجز أسبوعي' : 'Weekly'}
            </button>
            <button
              onClick={copyBriefing}
              className="btn btn-secondary"
              style={{ fontSize: '11px', padding: '4px 10px' }}
            >
              {copied ? <Check size={12} color="var(--success-color)" /> : <Copy size={12} />}
              {copied ? (isAr ? 'تم النسخ' : 'Copied') : (isAr ? 'نسخ للنوت بوك' : 'Copy Briefing')}
            </button>
          </div>
        </div>

        <div style={{
          backgroundColor: 'rgba(15, 23, 42, 0.7)',
          border: '1px solid var(--border-color)',
          borderRadius: '10px',
          padding: '16px',
          fontSize: '13px',
          lineHeight: 1.6,
          whiteSpace: 'pre-wrap',
          color: 'var(--text-secondary)',
        }}>
          {briefing}
        </div>
      </div>
    </div>
  );
};
