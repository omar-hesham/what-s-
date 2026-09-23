import React, { useState, useEffect } from 'react';
import { HardDrive, Trash2, Check, RefreshCw, Folder } from 'lucide-react';
import { StorageDashboardData } from '../types';
import { apiClient } from '../api/client';

interface StorageProps {
  language: 'ar' | 'en';
}

export const StorageDashboard: React.FC<StorageProps> = ({ language }) => {
  const [data, setData] = useState<StorageDashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [cleaning, setCleaning] = useState(false);
  const [cleanMsg, setCleanMsg] = useState('');

  const isAr = language === 'ar';

  useEffect(() => {
    loadStorage();
  }, []);

  const loadStorage = async () => {
    setLoading(true);
    try {
      const res = await apiClient.getStorage();
      setData(res);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleCleanup = async () => {
    if (!window.confirm(isAr ? 'هل أنت متأكد من تنظيف الملفات المؤقتة والكاش؟ (لن يتم حذف أي ملفات أصلية)' : 'Clear temporary derived caches? (Original media is never touched)')) {
      return;
    }
    setCleaning(true);
    try {
      const res = await apiClient.cleanupStorage();
      setCleanMsg(res.message);
      await loadStorage();
      setTimeout(() => setCleanMsg(''), 4000);
    } catch (e) {
      console.error(e);
    } finally {
      setCleaning(false);
    }
  };

  return (
    <div style={{ padding: '24px', overflowY: 'auto', height: '100%', maxWidth: '850px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <HardDrive size={22} color="var(--accent-color)" />
            {isAr ? 'لوحة إدارة التخزين المحلي' : 'Local Storage Dashboard'}
          </h2>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            {isAr ? 'مراقبة استهلاك القرص للوسائط، الصوتيات، قواعد البيانات، والتنظيف الآمن للكاش' : 'Monitor local disk consumption and safely clear caches without deleting originals'}
          </p>
        </div>
        <button onClick={loadStorage} className="btn btn-secondary" style={{ fontSize: '12px' }}>
          <RefreshCw size={13} />
        </button>
      </div>

      {cleanMsg && (
        <div style={{ backgroundColor: 'rgba(16, 185, 129, 0.1)', border: '1px solid var(--success-color)', padding: '12px', borderRadius: '8px', marginBottom: '16px', fontSize: '12.5px', color: 'var(--success-color)' }}>
          ✓ {cleanMsg}
        </div>
      )}

      {data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Total Storage Summary */}
          <div className="card" style={{ padding: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{isAr ? 'إجمالي المساحة المستخدمة' : 'Total Storage Consumed'}</span>
              <p style={{ fontSize: '28px', fontWeight: 800, color: 'var(--text-primary)' }}>
                {data.total_mb} <span style={{ fontSize: '16px', fontWeight: 500 }}>MB</span>
              </p>
              <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Folder size={12} /> {data.storage_path}
              </p>
            </div>

            <button
              onClick={handleCleanup}
              disabled={cleaning}
              className="btn btn-danger"
              style={{ fontSize: '12px' }}
            >
              <Trash2 size={14} />
              {cleaning ? (isAr ? 'جارٍ التنظيف...' : 'Cleaning...') : (isAr ? 'تنظيف الكاش المؤقت' : 'Clear Temporary Cache')}
            </button>
          </div>

          {/* Category Breakdown */}
          <div className="card" style={{ padding: '16px' }}>
            <h3 style={{ fontSize: '13px', fontWeight: 700, marginBottom: '14px' }}>
              {isAr ? 'توزيع التخزين حسب التصنيف' : 'Storage Breakdown by Category'}
            </h3>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '12px' }}>
              <div style={{ background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: '8px' }}>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'قاعدة البيانات (SQLite):' : 'Database (SQLite):'}</span>
                <p style={{ fontSize: '16px', fontWeight: 700, marginTop: '4px' }}>{data.database_mb} MB</p>
              </div>
              <div style={{ background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: '8px' }}>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'الملفات الصوتية:' : 'Audio Assets:'}</span>
                <p style={{ fontSize: '16px', fontWeight: 700, marginTop: '4px', color: 'var(--wa-green)' }}>{data.audio_mb} MB</p>
              </div>
              <div style={{ background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: '8px' }}>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'الصور واللقطات:' : 'Images:'}</span>
                <p style={{ fontSize: '16px', fontWeight: 700, marginTop: '4px', color: '#60a5fa' }}>{data.images_mb} MB</p>
              </div>
              <div style={{ background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: '8px' }}>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'المستندات (PDF/Word):' : 'Documents:'}</span>
                <p style={{ fontSize: '16px', fontWeight: 700, marginTop: '4px', color: '#fbbf24' }}>{data.documents_mb} MB</p>
              </div>
              <div style={{ background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: '8px' }}>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'مقاطع الفيديو:' : 'Videos:'}</span>
                <p style={{ fontSize: '16px', fontWeight: 700, marginTop: '4px' }}>{data.video_mb} MB</p>
              </div>
              <div style={{ background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: '8px' }}>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{isAr ? 'الملفات المشتقة والكاش:' : 'Derived Files:'}</span>
                <p style={{ fontSize: '16px', fontWeight: 700, marginTop: '4px', color: '#f87171' }}>{data.derived_files_mb} MB</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
