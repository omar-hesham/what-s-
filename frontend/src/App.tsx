import React, { useState, useEffect, useRef } from 'react';
import { Conversation } from './types';
import { apiClient } from './api/client';
import { Sidebar } from './components/Sidebar';
import { ConversationTimeline } from './components/ConversationTimeline';
import { IntelligencePanel } from './components/IntelligencePanel';
import { TodayDashboard } from './components/TodayDashboard';
import { TaskInbox } from './components/TaskInbox';
import { WaitingForView } from './components/WaitingForView';
import { PropertyStoneView } from './components/PropertyStoneView';
import { CostScreen } from './components/CostScreen';
import { ModelManager } from './components/ModelManager';
import { StorageDashboard } from './components/StorageDashboard';
import { DecisionsView } from './components/DecisionsView';
import { IdeasView } from './components/IdeasView';
import { ResearchView } from './components/ResearchView';
import { RequirementsView } from './components/RequirementsView';
import { SearchModal } from './components/SearchModal';
import { FirstRunWizard } from './components/FirstRunWizard';

export const App: React.FC = () => {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<number | null>(null);
  const [currentView, setCurrentView] = useState<string>('timeline');
  const [language, setLanguage] = useState<'ar' | 'en'>('ar');
  const [searchOpen, setSearchOpen] = useState(false);
  const [firstRunOpen, setFirstRunOpen] = useState(false);

  // Badge counts
  const [inboxCount, setInboxCount] = useState(0);
  const [waitingCount, setWaitingCount] = useState(0);

  // Upload status
  const [uploading, setUploading] = useState(false);
  const [uploadNotice, setUploadNotice] = useState('');

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    // Apply RTL or LTR to document
    document.documentElement.dir = language === 'ar' ? 'rtl' : 'ltr';
    document.documentElement.lang = language;
  }, [language]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setSearchOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  useEffect(() => {
    loadInitialData();
  }, []);

  const loadInitialData = async () => {
    try {
      await apiClient.ensureSession();
      const convList = await apiClient.getConversations();
      setConversations(convList);
      if (convList.length > 0 && selectedConversationId === null) {
        // Default to Conversation 13 if present, otherwise first
        const hConv = convList.find(c => c.id === 13);
        setSelectedConversationId(hConv ? hConv.id : convList[0].id);
      } else if (convList.length === 0) {
        // Show onboarding wizard if no conversations exist yet
        setFirstRunOpen(true);
      }

      // Fetch badge counts
      const [inboxTasks, waitingItems] = await Promise.all([
        apiClient.getTasks('inbox'),
        apiClient.getWaiting('open'),
      ]);
      setInboxCount(inboxTasks.length);
      setWaitingCount(waitingItems.length);
    } catch (e) {
      console.error('Failed to load initial data:', e);
    }
  };

  const handleRefreshConversation = async () => {
    await loadInitialData();
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadNotice(language === 'ar' ? `جارٍ استيراد ومعالجة: ${file.name}...` : `Importing: ${file.name}...`);

    try {
      let res;
      if (file.name.endsWith('.zip')) {
        res = await apiClient.importZip(file);
      } else {
        res = await apiClient.importText(file);
      }

      if (res.conversation_id) {
        setSelectedConversationId(res.conversation_id);
        setCurrentView('timeline');
        await loadInitialData();
        setUploadNotice(
          language === 'ar'
            ? `✓ تم الاستيراد بنجاح! (${res.messages_imported || res.message_count} رسالة)`
            : `✓ Successfully imported! (${res.messages_imported || res.message_count} messages)`
        );
      }
    } catch (err) {
      console.error(err);
      setUploadNotice(language === 'ar' ? 'حدث خطأ أثناء الاستيراد.' : 'Import failed.');
    } finally {
      setUploading(false);
      setTimeout(() => setUploadNotice(''), 4000);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const selectedConversation = conversations.find((c) => c.id === selectedConversationId) || null;

  return (
    <div className="app-container">
      {/* Hidden File Input for WhatsApp Exports */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileUpload}
        accept=".txt,.zip"
        style={{ display: 'none' }}
      />

      {/* Global Notifications */}
      {uploadNotice && (
        <div style={{
          position: 'fixed',
          top: '16px',
          left: '50%',
          transform: 'translateX(-50%)',
          backgroundColor: 'var(--bg-secondary)',
          border: '1px solid var(--accent-color)',
          borderRadius: '8px',
          padding: '10px 20px',
          fontSize: '13px',
          fontWeight: 600,
          color: 'var(--text-primary)',
          zIndex: 100,
          boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
        }}>
          {uploadNotice}
        </div>
      )}

      {/* Left Sidebar */}
      <Sidebar
        currentView={currentView}
        onViewChange={(view) => {
          if (view === 'search') {
            setSearchOpen(true);
          } else {
            setCurrentView(view);
          }
        }}
        conversations={conversations}
        selectedConversationId={selectedConversationId}
        onSelectConversation={(id) => setSelectedConversationId(id)}
        onImportClick={() => fileInputRef.current?.click()}
        language={language}
        onToggleLanguage={() => setLanguage(language === 'ar' ? 'en' : 'ar')}
        inboxCount={inboxCount}
        waitingCount={waitingCount}
      />

      {/* Center Main Stage */}
      <main className="center-timeline">
        {currentView === 'timeline' && (
          <ConversationTimeline
            conversation={selectedConversation}
            onRefreshConversation={handleRefreshConversation}
            language={language}
          />
        )}
        {currentView === 'requirements' && (
          <RequirementsView
            conversation={selectedConversation}
            conversations={conversations}
            onSelectConversation={(id) => setSelectedConversationId(id)}
            language={language}
            onOpenTimeline={() => setCurrentView('timeline')}
          />
        )}
        {currentView === 'today' && <TodayDashboard language={language} />}
        {currentView === 'inbox' && <TaskInbox language={language} onTaskChange={loadInitialData} />}
        {currentView === 'tasks' && <TaskInbox language={language} onTaskChange={loadInitialData} />}
        {currentView === 'waiting' && <WaitingForView language={language} onUpdate={loadInitialData} />}
        {currentView === 'properties' && <PropertyStoneView language={language} />}
        {currentView === 'decisions' && <DecisionsView language={language} />}
        {currentView === 'ideas' && <IdeasView language={language} />}
        {currentView === 'research' && <ResearchView language={language} />}
        {currentView === 'cost' && <CostScreen language={language} />}
        {currentView === 'models' && <ModelManager language={language} />}
        {currentView === 'storage' && <StorageDashboard language={language} />}
      </main>

      {/* Right Intelligence Panel (Shown in Timeline view) */}
      {currentView === 'timeline' && (
        <IntelligencePanel
          conversation={selectedConversation}
          language={language}
          onTaskUpdated={loadInitialData}
        />
      )}

      {/* Search Modal */}
      <SearchModal
        isOpen={searchOpen}
        onClose={() => setSearchOpen(false)}
        onSelectResult={(cid) => {
          setSelectedConversationId(cid);
          setCurrentView('timeline');
        }}
        language={language}
      />

      {/* First Run Onboarding Wizard */}
      <FirstRunWizard
        isOpen={firstRunOpen}
        onComplete={() => setFirstRunOpen(false)}
        language={language}
        onLanguageChange={setLanguage}
        onImportClick={() => fileInputRef.current?.click()}
      />
    </div>
  );
};

export default App;
