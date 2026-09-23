import React, { useState, useEffect } from 'react';
import { Building2, Copy, Check, ExternalLink, ShieldCheck, MapPin, DollarSign } from 'lucide-react';
import { PropertyItem } from '../types';
import { apiClient } from '../api/client';

interface PropertyProps {
  language: 'ar' | 'en';
}

export const PropertyStoneView: React.FC<PropertyProps> = ({ language }) => {
  const [properties, setProperties] = useState<PropertyItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const isAr = language === 'ar';

  useEffect(() => {
    loadProperties();
  }, []);

  const loadProperties = async () => {
    setLoading(true);
    try {
      const data = await apiClient.getProperties();
      setProperties(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const copyDraft = (id: number, text?: string) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div style={{ padding: '24px', overflowY: 'auto', height: '100%' }}>
      {/* Header */}
      <div style={{ marginBottom: '20px' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Building2 size={20} color="var(--wa-green)" />
          {isAr ? 'عقارات ستون مود (Property Stone Mode)' : 'Real Estate Stone Mode Records'}
        </h2>
        <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          {isAr ? 'استخراج ذكي لبيانات العقارات، التراخيص الإدارية، الأسعار ومسودات الإعلانات استناداً إلى أدلة المحادثة الموثقة' : 'Structured real estate intelligence, administrative licenses, and verified listing drafts'}
        </p>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
          {isAr ? 'جارٍ تحميل العقارات...' : 'Loading properties...'}
        </div>
      ) : properties.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '40px' }}>
          <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
            {isAr ? 'لم يتم رصد وحدات عقارية حتى الآن' : 'No property records detected yet'}
          </p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: '16px' }}>
          {properties.map((p) => (
            <div key={p.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '12px', padding: '18px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                <div>
                  <span className="badge badge-open" style={{ marginBottom: '6px' }}>
                    {p.property_type || (isAr ? 'عقار' : 'Property')} • {p.deal_type === 'sale' ? (isAr ? 'للبيع' : 'For Sale') : (isAr ? 'للإيجار' : 'For Rent')}
                  </span>
                  <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                    {p.title}
                  </h3>
                </div>

                {p.price && (
                  <div style={{ textAlign: isAr ? 'left' : 'right' }}>
                    <span style={{ fontSize: '16px', fontWeight: 800, color: '#34d399' }}>
                      {p.price.toLocaleString()} {p.currency}
                    </span>
                  </div>
                )}
              </div>

              {/* Specs Grid */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '8px',
                backgroundColor: 'rgba(15, 23, 42, 0.5)',
                padding: '10px',
                borderRadius: '8px',
                fontSize: '12px',
                color: 'var(--text-secondary)',
              }}>
                <div>• <strong>{isAr ? 'المساحة:' : 'Area:'}</strong> {p.area_sqm ? `${p.area_sqm} م²` : '-'}</div>
                <div>• <strong>{isAr ? 'الموقع:' : 'Location:'}</strong> {p.district || p.location || '-'}</div>
                <div>• <strong>{isAr ? 'التشطيب:' : 'Finishing:'}</strong> {p.finishing || '-'}</div>
                <div>• <strong>{isAr ? 'رخصة إداري:' : 'License:'}</strong> {p.has_admin_license ? (isAr ? 'مرخص إداري' : 'Yes') : (isAr ? 'غير محدد' : 'Standard')}</div>
              </div>

              {/* Listing Draft Preview */}
              {p.listing_draft && (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                    <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)' }}>
                      {isAr ? 'مسودة الإعلان الجاهزة:' : 'Ready-to-use Listing Draft:'}
                    </span>
                    <button
                      onClick={() => copyDraft(p.id, p.listing_draft)}
                      className="btn btn-secondary"
                      style={{ fontSize: '10px', padding: '3px 8px' }}
                    >
                      {copiedId === p.id ? <Check size={11} color="var(--success-color)" /> : <Copy size={11} />}
                      {copiedId === p.id ? (isAr ? 'تم النسخ' : 'Copied') : (isAr ? 'نسخ الإعلان' : 'Copy Draft')}
                    </button>
                  </div>
                  <pre style={{
                    backgroundColor: 'rgba(0, 0, 0, 0.4)',
                    padding: '10px',
                    borderRadius: '6px',
                    fontSize: '11px',
                    whiteSpace: 'pre-wrap',
                    fontFamily: 'monospace',
                    color: 'var(--text-primary)',
                    maxHeight: '130px',
                    overflowY: 'auto',
                  }}>
                    {p.listing_draft}
                  </pre>
                </div>
              )}

              {/* Source Evidence */}
              {p.source_evidence && (
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', borderTop: '1px solid var(--border-color)', paddingTop: '8px' }}>
                  <strong>{isAr ? 'الدليل من المحادثة:' : 'Evidence:'} </strong>
                  <span>{p.source_evidence}</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
