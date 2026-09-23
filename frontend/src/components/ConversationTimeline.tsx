import React, { useState, useEffect, useRef } from 'react';
import {
  MessageSquare, Sparkles, Filter, Search, Mic,
  Image as ImageIcon, FileText, Video, Trash2, ArrowUpDown
} from 'lucide-react';
import { Conversation, Message } from '../types';
import { apiClient } from '../api/client';
import { VoiceMessageCard } from './VoiceMessageCard';
import { ImageCard } from './ImageCard';
import { DocumentCard } from './DocumentCard';

interface TimelineProps {
  conversation: Conversation | null;
  onRefreshConversation: () => void;
  language: 'ar' | 'en';
}

export const ConversationTimeline: React.FC<TimelineProps> = ({
  conversation,
  onRefreshConversation,
  language,
}) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterType, setFilterType] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const isAr = language === 'ar';

  useEffect(() => {
    if (conversation) {
      loadMessages();
    } else {
      setMessages([]);
    }
  }, [conversation?.id, filterType]);

  const loadMessages = async () => {
    if (!conversation) return;
    setLoading(true);
    try {
      const filter = filterType !== 'all' ? { messageType: filterType } : undefined;
      const data = await apiClient.getMessages(conversation.id, filter);
      setMessages(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleAnalyze = async () => {
    if (!conversation) return;
    setAnalyzing(true);
    try {
      await apiClient.analyzeConversation(conversation.id);
      onRefreshConversation();
      await loadMessages();
    } catch (e) {
      console.error(e);
    } finally {
      setAnalyzing(false);
    }
  };

  const filteredMessages = messages.filter((m) => {
    if (!searchQuery) return true;
    return (
      m.content.toLowerCase().includes(searchQuery.toLowerCase()) ||
      m.sender_name.toLowerCase().includes(searchQuery.toLowerCase())
    );
  });

  if (!conversation) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', gap: '12px' }}>
        <MessageSquare size={48} strokeWidth={1.5} />
        <p style={{ fontSize: '15px' }}>
          {isAr ? 'اختر محادثة من القائمة الجانبية أو استورد محادثة جديدة' : 'Select a conversation from the sidebar or import an export'}
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Header Bar */}
      <div style={{
        padding: '12px 20px',
        backgroundColor: 'var(--bg-secondary)',
        borderBottom: '1px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '10px',
      }}>
        <div>
          <h2 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {conversation.title}
          </h2>
          <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            {conversation.message_count} {isAr ? 'رسالة' : 'messages'}
            {conversation.start_date && ` • ${new Date(conversation.start_date).toLocaleDateString()}`}
          </p>
        </div>

        {/* Header Actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            onClick={handleAnalyze}
            disabled={analyzing}
            className="btn btn-primary"
            style={{ fontSize: '12px', padding: '6px 12px' }}
          >
            <Sparkles size={14} />
            {analyzing ? (isAr ? 'جارٍ التحليل...' : 'Analyzing...') : (isAr ? 'تحليل بالذكاء الاصطناعي' : 'Run AI Analysis')}
          </button>
        </div>
      </div>

      {/* Filter / Search Bar */}
      <div style={{
        padding: '8px 20px',
        backgroundColor: 'rgba(15, 23, 42, 0.6)',
        borderBottom: '1px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px',
      }}>
        {/* Media type tabs */}
        <div style={{ display: 'flex', gap: '4px' }}>
          {[
            { id: 'all', label: isAr ? 'الكل' : 'All' },
            { id: 'voice', label: isAr ? 'صوت' : 'Voice', icon: Mic },
            { id: 'image', label: isAr ? 'صور' : 'Images', icon: ImageIcon },
            { id: 'document', label: isAr ? 'مستندات' : 'Docs', icon: FileText },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setFilterType(tab.id)}
              style={{
                padding: '4px 10px',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: filterType === tab.id ? 600 : 400,
                backgroundColor: filterType === tab.id ? 'var(--accent-color)' : 'transparent',
                color: filterType === tab.id ? 'white' : 'var(--text-secondary)',
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Search inside chat */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: 'var(--bg-tertiary)', borderRadius: '6px', padding: '4px 8px' }}>
          <Search size={13} color="var(--text-muted)" />
          <input
            type="text"
            placeholder={isAr ? 'بحث في الرسائل...' : 'Filter messages...'}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: 'var(--text-primary)',
              fontSize: '12px',
              width: '140px',
            }}
          />
        </div>
      </div>

      {/* Messages Timeline Feed */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '10px',
      }}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)', fontSize: '13px' }}>
            {isAr ? 'جارٍ تحميل الرسائل...' : 'Loading messages...'}
          </div>
        ) : filteredMessages.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)', fontSize: '13px' }}>
            {isAr ? 'لا توجد رسائل مطابقة' : 'No matching messages'}
          </div>
        ) : (
          filteredMessages.map((msg) => {
            const isSystem = msg.message_type === 'system';
            const isOmar = msg.sender_name.toLowerCase().includes('omar');

            if (isSystem) {
              return (
                <div key={msg.id} className="msg-bubble msg-system">
                  {msg.content}
                </div>
              );
            }

            return (
              <div
                key={msg.id}
                className={`msg-bubble ${isOmar ? 'msg-outgoing' : 'msg-incoming'}`}
              >
                {/* Sender & Timestamp */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', marginBottom: '3px' }}>
                  <span style={{ fontWeight: 700, fontSize: '11.5px', color: isOmar ? '#6ee7b7' : '#93c5fd' }}>
                    {msg.sender_name}
                  </span>
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                    {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>

                {/* Message Body */}
                <p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.4 }}>
                  {msg.content}
                </p>

                {/* Render Media Attachments */}
                {msg.media_assets && msg.media_assets.length > 0 && (
                  <div style={{ marginTop: '6px' }}>
                    {msg.media_assets.map((asset) => {
                      if (asset.file_type === 'audio') {
                        return <VoiceMessageCard key={asset.id} asset={asset} senderName={msg.sender_name} />;
                      }
                      if (asset.file_type === 'image') {
                        return <ImageCard key={asset.id} asset={asset} />;
                      }
                      if (asset.file_type === 'document') {
                        return <DocumentCard key={asset.id} asset={asset} />;
                      }
                      return null;
                    })}
                  </div>
                )}
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
};
