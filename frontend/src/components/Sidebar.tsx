import React, { useRef } from 'react';
import {
  Inbox, Calendar, MessageSquare, CheckSquare, Clock,
  Award, Lightbulb, Building2, BookOpen, Search,
  HardDrive, DollarSign, Cpu, Settings, Upload, Globe
} from 'lucide-react';
import { Conversation } from '../types';

interface SidebarProps {
  currentView: string;
  onViewChange: (view: string) => void;
  conversations: Conversation[];
  selectedConversationId: number | null;
  onSelectConversation: (id: number) => void;
  onImportClick: () => void;
  language: 'ar' | 'en';
  onToggleLanguage: () => void;
  inboxCount: number;
  waitingCount: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentView,
  onViewChange,
  conversations,
  selectedConversationId,
  onSelectConversation,
  onImportClick,
  language,
  onToggleLanguage,
  inboxCount,
  waitingCount,
}) => {
  const isAr = language === 'ar';

  const navItems = [
    { id: 'inbox', label: isAr ? 'الوارد الذكي' : 'AI Inbox', icon: Inbox, badge: inboxCount },
    { id: 'today', label: isAr ? 'اليوم والموجز' : 'Today & Briefing', icon: Calendar },
    { id: 'timeline', label: isAr ? 'المحادثات' : 'Chats Timeline', icon: MessageSquare },
    { id: 'tasks', label: isAr ? 'المهام' : 'Tasks', icon: CheckSquare },
    { id: 'waiting', label: isAr ? 'قيد الانتظار' : 'Waiting For', icon: Clock, badge: waitingCount },
    { id: 'decisions', label: isAr ? 'القرارات' : 'Decisions', icon: Award },
    { id: 'ideas', label: isAr ? 'الأفكار' : 'Ideas', icon: Lightbulb },
    { id: 'properties', label: isAr ? 'العقارات (Stone Mode)' : 'Properties (Stone)', icon: Building2 },
    { id: 'research', label: isAr ? 'وضع الأبحاث' : 'Research Mode', icon: BookOpen },
    { id: 'storage', label: isAr ? 'لوحة التخزين' : 'Storage', icon: HardDrive },
    { id: 'cost', label: isAr ? 'التكلفة والخدمات ($0)' : 'Cost & Services ($0)', icon: DollarSign },
    { id: 'models', label: isAr ? 'إدارة النماذج والأداء' : 'Model Manager', icon: Cpu },
  ];

  return (
    <aside className="sidebar">
      {/* Brand Header */}
      <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h1 style={{ fontSize: '16px', fontWeight: '700', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ color: 'var(--wa-green)' }}>●</span> OWI Intelligence
            </h1>
            <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              {isAr ? 'ذكاء واتساب المحلي' : 'Local WhatsApp Knowledge'}
            </p>
          </div>
          <button
            onClick={onToggleLanguage}
            title={isAr ? 'Switch to English' : 'التحويل للعربية'}
            className="btn btn-secondary"
            style={{ padding: '4px 8px', fontSize: '11px' }}
          >
            <Globe size={13} />
            {isAr ? 'EN' : 'عربي'}
          </button>
        </div>

        {/* Import Action */}
        <button
          onClick={onImportClick}
          className="btn btn-primary"
          style={{ width: '100%', marginTop: '12px', fontSize: '12px' }}
        >
          <Upload size={14} />
          {isAr ? 'استيراد محادثة واتساب' : 'Import WhatsApp Export'}
        </button>
      </div>

      {/* Main Navigation */}
      <nav style={{ flex: 1, overflowY: 'auto', padding: '10px 8px' }}>
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = currentView === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onViewChange(item.id)}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '9px 12px',
                borderRadius: '8px',
                marginBottom: '2px',
                fontSize: '12.5px',
                fontWeight: isActive ? 600 : 400,
                color: isActive ? 'white' : 'var(--text-secondary)',
                backgroundColor: isActive ? 'var(--accent-color)' : 'transparent',
                textAlign: isAr ? 'right' : 'left',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Icon size={16} />
                <span>{item.label}</span>
              </div>
              {item.badge !== undefined && item.badge > 0 && (
                <span className={`badge ${item.id === 'inbox' ? 'badge-inbox' : 'badge-waiting'}`}>
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}

        {/* Conversations Mini List */}
        {conversations.length > 0 && (
          <div style={{ marginTop: '18px', borderTop: '1px solid var(--border-color)', paddingTop: '12px' }}>
            <p style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '8px', paddingInline: '8px' }}>
              {isAr ? 'المحادثات المحفوظة' : 'SAVED CHATS'} ({conversations.length})
            </p>
            {conversations.map((c) => {
              const isSelected = selectedConversationId === c.id;
              return (
                <button
                  key={c.id}
                  onClick={() => {
                    onSelectConversation(c.id);
                    onViewChange('timeline');
                  }}
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    borderRadius: '6px',
                    marginBottom: '2px',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                    backgroundColor: isSelected ? 'var(--bg-tertiary)' : 'transparent',
                    borderInlineStart: isSelected ? '3px solid var(--accent-color)' : '3px solid transparent',
                    color: isSelected ? 'var(--text-primary)' : 'var(--text-secondary)',
                    fontSize: '12px',
                    textAlign: isAr ? 'right' : 'left',
                  }}
                >
                  <span style={{ fontWeight: isSelected ? 600 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', width: '100%' }}>
                    {c.title}
                  </span>
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                    {c.message_count} {isAr ? 'رسالة' : 'messages'}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </nav>

      {/* Footer Local Status */}
      <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border-color)', fontSize: '11px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'var(--success-color)' }} />
          <span>{isAr ? 'محلي 100% | رسوم: 0$' : '100% Local | $0 Fees'}</span>
        </div>
      </div>
    </aside>
  );
};
