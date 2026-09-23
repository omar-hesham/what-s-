import React, { useState, useEffect } from 'react';
import { Cpu, HardDrive, Zap, CheckCircle2, RefreshCw } from 'lucide-react';
import { HardwareResources } from '../types';
import { apiClient } from '../api/client';

interface ModelProps {
  language: 'ar' | 'en';
}

export const ModelManager: React.FC<ModelProps> = ({ language }) => {
  const [resources, setResources] = useState<HardwareResources | null>(null);
  const [modelStatus, setModelStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const isAr = language === 'ar';

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [resData, mData] = await Promise.all([
        apiClient.getHardwareResources(),
        apiClient.getModelStatus(),
      ]);
      setResources(resData);
      setModelStatus(mData);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const selectProfile = async (profile: 'LIGHT' | 'BALANCED' | 'QUALITY') => {
    setSaving(true);
    try {
      await apiClient.setProfile(profile);
      await loadData();
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ padding: '24px', overflowY: 'auto', height: '100%', maxWidth: '850px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Cpu size={22} color="var(--accent-color)" />
            {isAr ? 'إدارة النماذج المحلية ومستويات الأداء' : 'Model Manager & Performance Profiles'}
          </h2>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            {isAr ? 'ضبط استهلاك المعالج والذاكرة واختيار أحجام نماذج التفريغ الصوتي والذكاء الاصطناعي المحلي' : 'Configure local CPU/RAM utilization and speech transcription models'}
          </p>
        </div>
        <button onClick={loadData} className="btn btn-secondary" style={{ fontSize: '12px' }}>
          <RefreshCw size={13} />
        </button>
      </div>

      {/* Hardware Resources Card */}
      {resources && (
        <div className="card" style={{ padding: '16px', marginBottom: '20px' }}>
          <h3 style={{ fontSize: '13px', fontWeight: 700, marginBottom: '10px' }}>
            {isAr ? 'فحص عتاد الجهاز الحالي' : 'Hardware Resources Detected'}
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '10px', fontSize: '12px' }}>
            <div style={{ background: 'rgba(0,0,0,0.2)', padding: '10px', borderRadius: '8px' }}>
              <span style={{ color: 'var(--text-muted)' }}>{isAr ? 'أنوية المعالج:' : 'CPU Cores:'}</span>
              <p style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>{resources.cpu_cores}</p>
            </div>
            <div style={{ background: 'rgba(0,0,0,0.2)', padding: '10px', borderRadius: '8px' }}>
              <span style={{ color: 'var(--text-muted)' }}>{isAr ? 'الذاكرة الكلية:' : 'Total RAM:'}</span>
              <p style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>{resources.total_ram_gb} GB</p>
            </div>
            <div style={{ background: 'rgba(0,0,0,0.2)', padding: '10px', borderRadius: '8px' }}>
              <span style={{ color: 'var(--text-muted)' }}>{isAr ? 'الذاكرة المتاحة:' : 'Available RAM:'}</span>
              <p style={{ fontSize: '16px', fontWeight: 700, color: '#34d399' }}>{resources.available_ram_gb} GB</p>
            </div>
            <div style={{ background: 'rgba(0,0,0,0.2)', padding: '10px', borderRadius: '8px' }}>
              <span style={{ color: 'var(--text-muted)' }}>{isAr ? 'الملف المقترح:' : 'Suggested Profile:'}</span>
              <p style={{ fontSize: '16px', fontWeight: 700, color: '#60a5fa' }}>{resources.suggested_profile}</p>
            </div>
          </div>
        </div>
      )}

      {/* Performance Profiles Options */}
      <h3 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '12px' }}>
        {isAr ? 'اختر ملف الأداء (Performance Profile)' : 'Select Performance Profile'}
      </h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px', marginBottom: '24px' }}>
        {[
          {
            id: 'LIGHT',
            title: isAr ? 'الخفيف (LIGHT)' : 'LIGHT Mode',
            desc: isAr ? 'للأجهزة الاقتصادية. استهلاك ضئيل للرام والمعالج.' : 'Low RAM & CPU usage. Ultra-fast processing.',
            whisper: 'Whisper Tiny (75MB)',
            ram: '~1 GB RAM',
          },
          {
            id: 'BALANCED',
            title: isAr ? 'المتوازن (BALANCED)' : 'BALANCED Mode',
            desc: isAr ? 'التوازن المثالي بين الدقة والسرعة لمعظم أجهزة ويندوز.' : 'Optimal balance of accuracy and speed for most PCs.',
            whisper: 'Whisper Base (145MB)',
            ram: '~2 GB RAM',
          },
          {
            id: 'QUALITY',
            title: isAr ? 'الجودة العالية (QUALITY)' : 'QUALITY Mode',
            desc: isAr ? 'أعلى دقة في تفريغ اللهجات العربية والمصطلحات التقنية.' : 'Maximum accuracy for Arabic dialects and technical jargon.',
            whisper: 'Whisper Small (460MB)',
            ram: '~4 GB RAM',
          },
        ].map((prof) => {
          const isSelected = modelStatus?.performance_profile === prof.id;
          return (
            <div
              key={prof.id}
              onClick={() => selectProfile(prof.id as any)}
              className="card"
              style={{
                cursor: 'pointer',
                borderColor: isSelected ? 'var(--accent-color)' : 'var(--border-color)',
                backgroundColor: isSelected ? 'rgba(59, 130, 246, 0.08)' : 'var(--bg-secondary)',
                padding: '16px',
                position: 'relative',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <h4 style={{ fontSize: '14px', fontWeight: 700, color: isSelected ? 'var(--accent-color)' : 'var(--text-primary)' }}>
                  {prof.title}
                </h4>
                {isSelected && <CheckCircle2 size={16} color="var(--accent-color)" />}
              </div>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '10px', lineHeight: 1.4 }}>
                {prof.desc}
              </p>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                <div>• {prof.whisper}</div>
                <div>• {prof.ram}</div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Recommended Models Table */}
      {modelStatus?.recommended_models && (
        <div className="card" style={{ padding: '16px' }}>
          <h3 style={{ fontSize: '13px', fontWeight: 700, marginBottom: '12px' }}>
            {isAr ? 'النماذج المحلية المتوافقة ومساحة التخزين' : 'Available Local Models & Footprint'}
          </h3>
          <table style={{ width: '100%', fontSize: '12px', borderCollapse: 'collapse', textAlign: isAr ? 'right' : 'left' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
                <th style={{ padding: '8px' }}>{isAr ? 'النموذج' : 'Model'}</th>
                <th style={{ padding: '8px' }}>{isAr ? 'النوع' : 'Type'}</th>
                <th style={{ padding: '8px' }}>{isAr ? 'الحجم' : 'Size'}</th>
                <th style={{ padding: '8px' }}>{isAr ? 'الرام المطلوب' : 'RAM'}</th>
                <th style={{ padding: '8px' }}>{isAr ? 'الحالة' : 'Status'}</th>
              </tr>
            </thead>
            <tbody>
              {modelStatus.recommended_models.map((m: any, idx: number) => (
                <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <td style={{ padding: '10px 8px', fontWeight: 600 }}>{m.name}</td>
                  <td style={{ padding: '10px 8px', color: 'var(--text-secondary)' }}>{m.type}</td>
                  <td style={{ padding: '10px 8px' }}>{m.size_mb > 0 ? `${m.size_mb} MB` : '0 MB (Built-in)'}</td>
                  <td style={{ padding: '10px 8px' }}>{m.ram_needed_gb} GB</td>
                  <td style={{ padding: '10px 8px' }}>
                    <span className="badge badge-open">{m.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
