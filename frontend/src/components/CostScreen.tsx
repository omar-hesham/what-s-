import React, { useState, useEffect } from 'react';
import { DollarSign, ShieldCheck, CheckCircle2, AlertTriangle, Lock } from 'lucide-react';
import { CostAudit } from '../types';
import { apiClient } from '../api/client';

interface CostProps {
  language: 'ar' | 'en';
}

export const CostScreen: React.FC<CostProps> = ({ language }) => {
  const [costData, setCostData] = useState<CostAudit | null>(null);
  const [loading, setLoading] = useState(true);

  const isAr = language === 'ar';

  useEffect(() => {
    loadCost();
  }, []);

  const loadCost = async () => {
    setLoading(true);
    try {
      const data = await apiClient.getCostAudit();
      setCostData(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '24px', overflowY: 'auto', height: '100%', maxWidth: '800px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <DollarSign size={22} color="var(--wa-green)" />
          {isAr ? 'شاشة التكلفة والخدمات الخارجية (ضمان 0$ مصروفات)' : 'Zero-Surprise Cost & External Services'}
        </h2>
        <p style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>
          {isAr ? 'تأكيد أمني ومالي بأن النظام يعمل محلياً بالكامل وبدون أي اشتراكات أو رسوم شهرية أو مفاتيح API مدفوعة.' : 'Financial and privacy audit verifying that OWI operates 100% locally with zero recurring fees.'}
        </p>
      </div>

      {costData && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Main Status Banner */}
          <div className="card" style={{
            backgroundColor: 'rgba(16, 185, 129, 0.08)',
            border: '1px solid rgba(16, 185, 129, 0.3)',
            padding: '20px',
            display: 'flex',
            alignItems: 'center',
            gap: '16px',
          }}>
            <ShieldCheck size={36} color="var(--wa-green)" />
            <div>
              <h3 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--wa-green)' }}>
                {isAr ? 'وضع التشغيل: محلي بالكامل (Zero-Cost Mode)' : 'Core Mode: 100% Local (Zero-Cost)'}
              </h3>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                {costData.status_notice}
              </p>
            </div>
          </div>

          {/* Audit Table */}
          <div className="card" style={{ padding: '20px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '14px', borderBottom: '1px solid var(--border-color)', paddingBottom: '10px' }}>
              {isAr ? 'جدول تدقيق التكاليف والاشتراكات' : 'Cost & Services Audit Breakdown'}
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '13px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '8px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <span style={{ color: 'var(--text-secondary)' }}>{isAr ? 'وضع النظام الأساسي:' : 'Core Mode:'}</span>
                <strong style={{ color: 'var(--wa-green)' }}>{costData.core_mode}</strong>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '8px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <span style={{ color: 'var(--text-secondary)' }}>{isAr ? 'الاشتراكات الإلزامية:' : 'Mandatory subscription:'}</span>
                <span style={{ color: 'var(--text-primary)' }}>{costData.mandatory_subscription}</span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '8px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <span style={{ color: 'var(--text-secondary)' }}>{isAr ? 'مفاتيح API الإلزامية:' : 'Mandatory API:'}</span>
                <span style={{ color: 'var(--text-primary)' }}>{costData.mandatory_api}</span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '8px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <span style={{ color: 'var(--text-secondary)' }}>{isAr ? 'رسوم البرمجيات المتكررة:' : 'Recurring software fee:'}</span>
                <strong style={{ color: '#34d399' }}>{costData.recurring_software_fee}</strong>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '8px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <span style={{ color: 'var(--text-secondary)' }}>{isAr ? 'الذكاء الاصطناعي السحابي الخارجي:' : 'External AI:'}</span>
                <span className="badge badge-waiting">{costData.cloud_ai_enabled ? 'Enabled' : 'Disabled (معطل افتراضياً)'}</span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>{isAr ? 'التخزين السحابي المدفوع:' : 'Cloud storage:'}</span>
                <span className="badge badge-waiting">{costData.cloud_storage_enabled ? 'Enabled' : 'Disabled (معطل افتراضياً)'}</span>
              </div>
            </div>
          </div>

          {/* Privacy & Guarantees Note */}
          <div className="card" style={{ padding: '16px', backgroundColor: 'rgba(51, 65, 85, 0.3)' }}>
            <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
              <Lock size={18} color="var(--accent-color)" style={{ marginTop: '2px', flexShrink: 0 }} />
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                <strong style={{ color: 'var(--text-primary)' }}>
                  {isAr ? 'ضمان الخصوصية والبيانات المحلية:' : 'Local Privacy Guarantee:'}
                </strong>
                <p style={{ marginTop: '4px' }}>
                  {isAr
                    ? 'جميع ملفاتك، تسجيلاتك الصوتية، صورك، وقواعد بياناتك مخزنة فقط على هذا الجهاز. لا يتم إرسال أي بايت إلى خوادم خارجية أو شركات إعلانية.'
                    : 'All your chats, voice notes, photos, and databases stay strictly on this device. No data is ever transmitted to cloud servers.'}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
