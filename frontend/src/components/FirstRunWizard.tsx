import React, { useState, useEffect } from 'react';
import {
  Globe, Cpu, HardDrive, Sparkles, Check, ArrowRight, ArrowLeft, Upload
} from 'lucide-react';
import { HardwareResources } from '../types';
import { apiClient } from '../api/client';

interface WizardProps {
  isOpen: boolean;
  onComplete: () => void;
  language: 'ar' | 'en';
  onLanguageChange: (lang: 'ar' | 'en') => void;
  onImportClick: () => void;
}

export const FirstRunWizard: React.FC<WizardProps> = ({
  isOpen,
  onComplete,
  language,
  onLanguageChange,
  onImportClick,
}) => {
  const [step, setStep] = useState(1);
  const [profile, setProfile] = useState<'LIGHT' | 'BALANCED' | 'QUALITY'>('BALANCED');
  const [resources, setResources] = useState<HardwareResources | null>(null);

  const isAr = language === 'ar';

  useEffect(() => {
    if (isOpen) {
      apiClient.getHardwareResources().then(setResources).catch(console.error);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleFinish = async () => {
    try {
      await apiClient.setProfile(profile);
    } catch (e) {
      console.error(e);
    }
    onComplete();
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: '580px', padding: '24px' }}>
        {/* Wizard Header */}
        <div style={{ textAlign: 'center', marginBottom: '20px' }}>
          <h2 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {isAr ? 'مرحباً بك في عمر واتساب إنتلجنس (OWI)' : 'Welcome to Omar WhatsApp Intelligence'}
          </h2>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
            {isAr ? `خطوة ${step} من 4: الإعداد الأولي للتشغيل المحلي` : `Step ${step} of 4: Initial Local Setup`}
          </p>
        </div>

        {/* STEP 1: Language */}
        {step === 1 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: 600 }}>
              {isAr ? 'اختر لغة الواجهة الأساسية:' : 'Choose your preferred language:'}
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <button
                onClick={() => onLanguageChange('ar')}
                className="card"
                style={{
                  padding: '20px',
                  borderColor: language === 'ar' ? 'var(--accent-color)' : 'var(--border-color)',
                  backgroundColor: language === 'ar' ? 'rgba(59, 130, 246, 0.1)' : 'var(--bg-secondary)',
                  textAlign: 'center',
                }}
              >
                <p style={{ fontSize: '16px', fontWeight: 700 }}>العربية (RTL)</p>
                <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>دعم كامل للهجات العربية</p>
              </button>
              <button
                onClick={() => onLanguageChange('en')}
                className="card"
                style={{
                  padding: '20px',
                  borderColor: language === 'en' ? 'var(--accent-color)' : 'var(--border-color)',
                  backgroundColor: language === 'en' ? 'rgba(59, 130, 246, 0.1)' : 'var(--bg-secondary)',
                  textAlign: 'center',
                }}
              >
                <p style={{ fontSize: '16px', fontWeight: 700 }}>English (LTR)</p>
                <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>International format</p>
              </button>
            </div>
          </div>
        )}

        {/* STEP 2: Resources & Performance Profile */}
        {step === 2 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: 600 }}>
              {isAr ? 'اختر ملف أداء النظام بناءً على عتاد جهازك:' : 'Select performance profile for your PC:'}
            </h3>

            {resources && (
              <div style={{ backgroundColor: 'rgba(0,0,0,0.2)', padding: '10px 14px', borderRadius: '8px', fontSize: '12px', display: 'flex', justifyContent: 'space-between' }}>
                <span>{isAr ? 'المعالج:' : 'CPU:'} {resources.cpu_cores} Cores</span>
                <span>{isAr ? 'الذاكرة الكلية:' : 'RAM:'} {resources.total_ram_gb} GB</span>
                <span style={{ color: 'var(--accent-color)', fontWeight: 600 }}>{isAr ? 'المقترح:' : 'Suggested:'} {resources.suggested_profile}</span>
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {[
                { id: 'LIGHT', name: isAr ? 'خفيف (Light)' : 'Light', desc: isAr ? 'استهلاك منخفض جداً للذاكرة والمعالج.' : 'Low memory footprint. Fast execution.' },
                { id: 'BALANCED', name: isAr ? 'متوازن (Balanced)' : 'Balanced', desc: isAr ? 'الخيار الأفضل لمعظم أجهزة ويندوز 10/11.' : 'Recommended balance of speed and dialect accuracy.' },
                { id: 'QUALITY', name: isAr ? 'أعلى دقة (Quality)' : 'Quality', desc: isAr ? 'نماذج أكبر لدقة متناهية في التفريغ والتحليل.' : 'Highest accuracy model for heavy transcripts.' },
              ].map((p) => (
                <div
                  key={p.id}
                  onClick={() => setProfile(p.id as any)}
                  className="card"
                  style={{
                    padding: '12px',
                    cursor: 'pointer',
                    borderColor: profile === p.id ? 'var(--accent-color)' : 'var(--border-color)',
                    backgroundColor: profile === p.id ? 'rgba(59, 130, 246, 0.1)' : 'var(--bg-secondary)',
                  }}
                >
                  <p style={{ fontSize: '13px', fontWeight: 700, color: profile === p.id ? 'var(--accent-color)' : 'var(--text-primary)' }}>{p.name}</p>
                  <p style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '2px' }}>{p.desc}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* STEP 3: Zero-Cost Confirmation */}
        {step === 3 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--wa-green)' }}>
              ✓ {isAr ? 'ضمان الخصوصية والتكلفة الصفرية (0$)' : 'Zero-Cost & Local Privacy Guarantee'}
            </h3>
            <div className="card" style={{ padding: '16px', fontSize: '12.5px', lineHeight: 1.6, color: 'var(--text-secondary)' }}>
              <p>• <strong>{isAr ? 'لا توجد أي رسوم أو اشتراكات شهرية.' : 'No subscriptions or recurring fees.'}</strong></p>
              <p>• <strong>{isAr ? 'لا يتطلب أي مفتاح API خارجي أو سحابي مدفوع.' : 'No mandatory paid external APIs.'}</strong></p>
              <p>• <strong>{isAr ? 'جميع المحادثات والملفات تخزن محلياً فقط على جهازك.' : 'All data stays 100% on your local disk.'}</strong></p>
            </div>
          </div>
        )}

        {/* STEP 4: Ready to Import */}
        {step === 4 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', textAlign: 'center', padding: '20px 0' }}>
            <Sparkles size={40} color="var(--accent-color)" style={{ margin: '0 auto' }} />
            <h3 style={{ fontSize: '16px', fontWeight: 700 }}>
              {isAr ? 'أنت جاهز تماماً للبدء!' : 'You are all set!'}
            </h3>
            <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)' }}>
              {isAr ? 'يمكنك الآن استيراد أول محادثة واتساب (ملف .txt أو أرشيف .zip مع الوسائط) والبدء في استخراج المعرفة.' : 'Import your first WhatsApp chat export (.txt or .zip) to start extracting knowledge.'}
            </p>
          </div>
        )}

        {/* Wizard Footer Navigation */}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '24px', borderTop: '1px solid var(--border-color)', paddingTop: '16px' }}>
          {step > 1 ? (
            <button onClick={() => setStep(step - 1)} className="btn btn-secondary">
              {isAr ? <ArrowRight size={14} /> : <ArrowLeft size={14} />}
              {isAr ? 'السابق' : 'Back'}
            </button>
          ) : <div />}

          {step < 4 ? (
            <button onClick={() => setStep(step + 1)} className="btn btn-primary">
              {isAr ? 'التالي' : 'Next'}
              {isAr ? <ArrowLeft size={14} /> : <ArrowRight size={14} />}
            </button>
          ) : (
            <button
              onClick={() => {
                handleFinish();
                onImportClick();
              }}
              className="btn btn-success"
              style={{ padding: '8px 16px' }}
            >
              <Upload size={14} />
              {isAr ? 'بدء استيراد المحادثة الأولى' : 'Import First Chat'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
