import React, { useState, useEffect, useMemo } from 'react';
import {
  ClipboardList, CheckCircle2, AlertCircle, FileText, Mic,
  Image as ImageIcon, Download, Copy, Check, Sparkles,
  RefreshCw, Calendar, Clock, BookOpen, Layers, Type,
  ExternalLink, ChevronDown, ChevronUp, Play, Pause,
  Share2, ArrowUpRight, Search, Eye
} from 'lucide-react';
import { Conversation, Message, MediaAsset, TaskItem, DecisionItem } from '../types';
import { apiClient } from '../api/client';
import { DocumentCard } from './DocumentCard';
import { VoiceMessageCard } from './VoiceMessageCard';
import { ImageCard } from './ImageCard';

interface RequirementsViewProps {
  conversation: Conversation | null;
  conversations: Conversation[];
  onSelectConversation: (id: number) => void;
  language: 'ar' | 'en';
  onOpenTimeline: () => void;
}

export const RequirementsView: React.FC<RequirementsViewProps> = ({
  conversation,
  conversations,
  onSelectConversation,
  language,
  onOpenTimeline,
}) => {
  const isAr = language === 'ar';

  const [activeTab, setActiveTab] = useState<'decisions' | 'documents' | 'audio' | 'images' | 'checklist'>('decisions');
  const [messages, setMessages] = useState<Message[]>([]);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [decisions, setDecisions] = useState<DecisionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [checkedItems, setCheckedItems] = useState<{ [key: string]: boolean }>({
    'h-task-1': true,
    'h-task-2': true,
    'h-task-3': false,
    'h-task-4': true,
    'h-task-5': false,
    'h-task-6': false,
    'h-task-7': false,
  });

  // Selected document for inline reading modal
  const [readingDoc, setReadingDoc] = useState<{ title: string; text: string; fileName: string; url: string } | null>(null);

  // Load conversation messages, tasks, and decisions
  useEffect(() => {
    if (!conversation) return;

    const loadData = async () => {
      setLoading(true);
      try {
        await apiClient.ensureSession();
        const [msgs, taskList, decList] = await Promise.all([
          apiClient.getMessages(conversation.id),
          apiClient.getTasks(undefined, conversation.id).catch(() => []),
          apiClient.getDecisions(conversation.id).catch(() => []),
        ]);
        setMessages(msgs || []);
        setTasks(taskList || []);
        setDecisions(decList || []);
      } catch (err) {
        console.error('Failed to load conversation requirements data:', err);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [conversation?.id]);

  // Extract all media assets from messages
  const { docAssets, audioAssets, imageAssets } = useMemo(() => {
    const docs: { asset: MediaAsset; message: Message }[] = [];
    const audios: { asset: MediaAsset; message: Message }[] = [];
    const images: { asset: MediaAsset; message: Message }[] = [];
    const seenAssetIds = new Set<number>();

    for (const msg of messages) {
      if (msg.media_assets) {
        for (const asset of msg.media_assets) {
          if (seenAssetIds.has(asset.id)) continue;
          seenAssetIds.add(asset.id);

          if (asset.file_type === 'document') {
            docs.push({ asset, message: msg });
          } else if (asset.file_type === 'audio') {
            audios.push({ asset, message: msg });
          } else if (asset.file_type === 'image') {
            images.push({ asset, message: msg });
          }
        }
      }
    }

    return { docAssets: docs, audioAssets: audios, imageAssets: images };
  }, [messages]);

  const isConversationH = conversation?.id === 13 || (conversation?.title || '').includes('H');

  const handleRunAnalysis = async () => {
    if (!conversation) return;
    setAnalyzing(true);
    try {
      await apiClient.analyzeConversation(conversation.id);
      const [msgs, taskList, decList] = await Promise.all([
        apiClient.getMessages(conversation.id),
        apiClient.getTasks(undefined, conversation.id).catch(() => []),
        apiClient.getDecisions(conversation.id).catch(() => []),
      ]);
      setMessages(msgs || []);
      setTasks(taskList || []);
      setDecisions(decList || []);
    } catch (e) {
      console.error(e);
    } finally {
      setAnalyzing(false);
    }
  };

  const toggleCheck = (key: string) => {
    setCheckedItems((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  // Pre-configured executive requirements for Conversation H
  const hDecisions = [
    {
      id: 'h-dec-1',
      title: isAr ? '1. دمج الفصل السادس والسابع في فصل واحد' : '1. Merge Chapters 6 & 7 into a Single Chapter',
      badge: isAr ? 'هيكلة الفصول' : 'Structural',
      badgeColor: '#3b82f6',
      directive: isAr
        ? 'تم دمج محتوى الفصل السادس والفصل السابع ليصبحا فصلاً واحداً متماسكاً.'
        : 'Contents of Chapter 6 and 7 are merged into one consolidated chapter.',
      evidence: isAr
        ? 'رسالة مباشرة من H: "السادس و السابع اصبحوا فصل واحد" + ملف الوورد المرفق.'
        : 'Direct message from H: "Chapters 6 and 7 became one chapter" + Word doc.',
      fileRef: 'دمج الفصل السادس و السابع.docx',
      mediaAssetId: docAssets.find(d => d.asset.file_name.includes('السادس'))?.asset.id,
    },
    {
      id: 'h-dec-2',
      title: isAr ? '2. شلال الاستراتيجية المفصل (الفصل الخامس)' : '2. Detailed Strategy Waterfall (Chapter 5)',
      badge: isAr ? 'تعديل جوهري' : 'Major Revision',
      badgeColor: '#10b981',
      directive: isAr
        ? 'إجراء تغييرات جذرية على الفصل الخامس، وإعادة صياغة المحتوى والصور بما يتوافق مع شلال الاستراتيجية.'
        : 'Major revisions to Chapter 5, restructuring content and illustrations to align with Strategy Waterfall.',
      evidence: isAr
        ? 'رسالة H المرفقة: "هذا الفصل الخامس عملت تغيير عليها كثيير يجب مراجعة المحتوى و الصور".'
        : 'H comment: "This is Chapter 5, made many changes, must review content and images".',
      fileRef: 'شلال_الاستراتيجية_مفصّل.docx',
      mediaAssetId: docAssets.find(d => d.asset.file_name.includes('شلال'))?.asset.id,
    },
    {
      id: 'h-dec-3',
      title: isAr ? '3. مرحلة Transform وإعادة تصميم العمليات (الفصل التاسع)' : '3. Transform Phase & Capabilities Redesign (Chapter 9)',
      badge: isAr ? 'هندسة العمليات' : 'Process Redesign',
      badgeColor: '#8b5cf6',
      directive: isAr
        ? 'إعادة صياغة العمليات المؤسسية والقدرات التقنية ومطابقة الجداول والمخططات التوضيحية.'
        : 'Redesigning organizational processes, technical capabilities, and matching schematic charts.',
      evidence: isAr
        ? 'ملف الوورد المستلم والمفرغ بالكامل: "الفصل التاسع — مرحلة Transform إعادة تصميم العمليات والقدرات التقنية".'
        : 'Received Word document with full extracted chapter text.',
      fileRef: 'الفصل التاسع — مرحلة Transform إعادة تصميم العمليات والقدرات التقنية.docx',
      mediaAssetId: docAssets.find(d => d.asset.file_name.includes('التاسع'))?.asset.id,
    },
    {
      id: 'h-dec-4',
      title: isAr ? '4. نقل الجانب التطبيقي لكل فصل قبل الخاتمة' : '4. Position Practical Sections Before Each Chapter Conclusion',
      badge: isAr ? 'تنسيق المحتوى' : 'Content Placement',
      badgeColor: '#f59e0b',
      directive: isAr
        ? 'نقل الحالات والأمثلة التطبيقية لتكون قبل خاتمة كل فصل مباشرة، وعدم تشتيتها داخل السرد النظري.'
        : 'Move practical case studies and exercises right before the chapter conclusion.',
      evidence: isAr
        ? 'تسجيل صوتي وتفريغ Whisper + ملف وورد مستقل يضم التطبيقات العملية لجميع الفصول.'
        : 'Audio directive via Whisper + standalone Word file with practical sections.',
      fileRef: 'الجانب_التطبيقي_لكل_فصل.docx',
      mediaAssetId: docAssets.find(d => d.asset.file_name.includes('التطبيقي'))?.asset.id,
    },
    {
      id: 'h-dec-5',
      title: isAr ? '5. استبدال وتصحيح صفحة 65 بالكامل' : '5. Replace Page 65 Content Entirely',
      badge: isAr ? 'استبدال صفحة' : 'Page Replacement',
      badgeColor: '#ef4444',
      directive: isAr
        ? 'حذف النص الحالي في صفحة 65 واستبداله بفقرة التمييز بين نوعي الفرق (فرق المسارات وفرق القدرات السبع).'
        : 'Delete current text on page 65 and substitute with the approved distinction between Tracks vs. 7 Capabilities.',
      evidence: isAr
        ? 'توجيه H: "page 65 , remove this" مع صورة الاقتطاع + "and replace it with this" والنص المعتمد.'
        : 'Direct directive: "page 65, remove this" + crop screenshot + replacement paragraph.',
      fileRef: isAr ? 'صورة ومطابقة صفحة 65' : 'Page 65 Crop Image',
      mediaAssetId: imageAssets.find(img => img.asset.file_name.includes('d76742ad60'))?.asset.id,
      replacementText: isAr
        ? 'تمييز مهم يمنع اللبس — نوعان من الفرق: تُنظَّم فرق التنفيذ على محورين متكاملين لا متعارضين. الأول: فرق المسارات (Core / Partner / Edge) وتقابل P1 و P2 و P3، ووظيفتها الحوكمة والتمويل بحسب درجة المخاطرة. والثاني: فرق القدرات (أو المجالات) وتُنظَّم بحسب القدرات الرقمية السبع (كالبيانات وتجربة العميل والتميّز التقني)، ووظيفتها التنفيذ الموضوعي. فالأولى تحكم كيف يُموَّل ويُحوكم، والثانية تنفّذ ماذا يُبنى.'
        : 'Important distinction preventing confusion — Two types of teams: Implementation teams are organized across two complementary axes: 1) Track Teams (Core/Partner/Edge) for risk-adjusted governance & funding, and 2) Capabilities Teams organized by the 7 Digital Capabilities for substantive delivery.',
    },
    {
      id: 'h-dec-6',
      title: isAr ? '6. اعتماد خط Cairo وتصحيح الفواصل وعلامات الداش (-)' : '6. Adopt Cairo Font & Fix Typography/Dashes',
      badge: isAr ? 'الهوية البصرية' : 'Typography',
      badgeColor: '#06b6d4',
      directive: isAr
        ? 'تحويل الخط المعتمد للكتاب إلى خط Cairo لأنه أجمل وأريح في القراءة، وحذف علامات الداش الموجودة في غير موضعها.'
        : 'Adopt Cairo typography for optimal Arabic readability and clean stray dashes.',
      evidence: isAr
        ? 'رسائل H: "هل الخط ينفع يكون cairo لانه كان اجمل من هذا الخط و اريح في القراءة ايش رايك؟" و "بانتظار اصلاح الاخطاء الاملائية و حذف - في المكان الغير الصحيح".'
        : 'H requests Cairo font and elimination of misplaced hyphens/dashes.',
    },
    {
      id: 'h-dec-7',
      title: isAr ? '7. موعد التسليم النهائي للمراجعة' : '7. Final Delivery Deadline for Review',
      badge: isAr ? 'موعد التسليم' : 'Deadline',
      badgeColor: '#10b981',
      directive: isAr
        ? 'تسليم النسخة المحدثة المنقحة الكاملة بحلول يوم السبت لعمل المراجعة الختامية من الدكتور حمدين.'
        : 'Deliver complete final revised edition by Saturday for Dr. Hamdeen’s final sign-off.',
      evidence: isAr
        ? 'H: "متى تتوقع تنتهي من تجهيز الملف عشان اعمل عليه مراجعة اخيرة" -> عمر: "بإذن الله، ممكن على يوم السبت كده، بإذن الله." -> H: "باذن الله تعالى".'
        : 'Confirmed delivery agreement: Saturday for final review.',
    },
  ];

  const handleCopySummary = () => {
    let textToCopy = '';
    if (isConversationH) {
      textToCopy = `ملخص متطلبات وتعديلات الكتاب (محادثة د. حمدين H)\n=====================================\n\n` +
        hDecisions.map(d => `• ${d.title}\n  - التوجيه: ${d.directive}\n  - الدليل: ${d.evidence}\n`).join('\n') +
        `\n\nالملفات المرفقة المطلوبة:\n` +
        docAssets.map(d => `- ${d.asset.file_name} (${Math.round(d.asset.file_size / 1024)} KB)`).join('\n') +
        `\n\nالتوجيهات الصوتية المفرغة:\n` +
        audioAssets.map(a => `- ${a.asset.file_name} (${a.asset.duration_seconds}s): ${a.asset.transcript?.full_text || ''}`).join('\n');
    } else {
      textToCopy = `ملخص متطلبات وقرارات المحادثة: ${conversation?.title}\n=====================================\n\n` +
        `الملخص العام:\n${conversation?.detailed_summary || conversation?.summary || 'لا يوجد ملخص'}\n\n` +
        `المهام المستخرجة:\n` +
        tasks.map(t => `- [ ] ${t.title} (${t.priority || 'medium'})`).join('\n') +
        `\n\nالقرارات المتخذة:\n` +
        decisions.map(d => `- ${d.decision_text}`).join('\n');
    }

    navigator.clipboard.writeText(textToCopy);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleExportMarkdown = () => {
    const filename = `requirements_brief_${conversation?.id || 'export'}.md`;
    let content = '';

    if (isConversationH) {
      content = `# ملخص المتطلبات والقرارات التنفيذية: كتاب إطار H2O\n\n` +
        `**تاريخ التوليد:** ${new Date().toLocaleString()}\n` +
        `**الأطراف:** د. حمدين بشارة (H) & عمر هشام\n` +
        `**موعد التسليم:** يوم السبت القادم\n\n` +
        `## 1. القرارات الجوهرية والتعديلات الهيكلية\n\n` +
        hDecisions.map(d => `### ${d.title}\n- **التوجيه المعتمد:** ${d.directive}\n- **دليل المصدر:** ${d.evidence}\n${d.replacementText ? `\n> **النص المعتمد:**\n> ${d.replacementText}\n` : ''}`).join('\n\n') +
        `\n\n## 2. المستندات وملفات الفصول المستلمة\n\n` +
        docAssets.map(d => `- **${d.asset.file_name}** (${Math.round(d.asset.file_size / 1024)} KB) - عدد الصفحات: ${d.asset.document?.page_count || 1}`).join('\n') +
        `\n\n## 3. التوجيهات الصوتية ومطابقة Whisper\n\n` +
        audioAssets.map(a => `- **${a.asset.file_name}** (${a.asset.duration_seconds} ثانية):\n  > "${a.asset.transcript?.full_text || ''}"\n`).join('\n') +
        `\n\n## 4. قائمة التحقق والإنجاز (Checklist)\n\n` +
        `- [x] دمج الفصل السادس والسابع في ملف واحد\n` +
        `- [x] استلام وتطبيق شلال الاستراتيجية للفصل الخامس\n` +
        `- [x] إدراج الجانب التطبيقي قبل خاتمة كل فصل\n` +
        `- [ ] تعديل واستبدال نص صفحة 65 بالكامل\n` +
        `- [ ] تحويل الخط إلى Cairo وإزالة علامات الداش (-)\n` +
        `- [ ] مراجعة وتجهيز النسخة الكاملة للتسليم يوم السبت\n`;
    } else {
      content = `# ملخص المتطلبات والقرارات: ${conversation?.title}\n\n` +
        `**تاريخ التوليد:** ${new Date().toLocaleString()}\n\n` +
        `## الملخص التنفيذي\n\n${conversation?.detailed_summary || conversation?.summary || 'تم استخراج البيانات من الرسائل والوسائط.'}\n\n` +
        `## المهام التنفيذية المطلوبة\n\n` +
        tasks.map(t => `- [ ] **${t.title}** - *${t.status}* (الأولوية: ${t.priority})`).join('\n') +
        `\n\n## القرارات المعتمدة\n\n` +
        decisions.map(d => `- **${d.decision_text}** (الأطراف: ${d.participants || 'غير محدد'})`).join('\n') +
        `\n\n## المستندات والملفات المرفقة\n\n` +
        docAssets.map(d => `- ${d.asset.file_name} (${Math.round(d.asset.file_size / 1024)} KB)`).join('\n') +
        `\n\n## التسجيلات الصوتية المفرغة\n\n` +
        audioAssets.map(a => `- ${a.asset.file_name} (${a.asset.duration_seconds}s): ${a.asset.transcript?.full_text || ''}`).join('\n');
    }

    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!conversation) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', gap: '14px', padding: '40px' }}>
        <ClipboardList size={56} strokeWidth={1.5} color="var(--accent-color)" />
        <h2 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text-primary)' }}>
          {isAr ? 'واجهة ملخص المتطلبات والقرارات' : 'Requirements & Intelligence Brief'}
        </h2>
        <p style={{ fontSize: '13px', textAlign: 'center', maxWidth: '420px', lineHeight: 1.6 }}>
          {isAr
            ? 'اختر أي محادثة لعرض ملخص فوري لمتطلباتها، قراراتها، مستنداتها، وتوجيهاتها الصوتية المفرغة.'
            : 'Select any conversation to view an instant executive brief of requirements, decisions, documents, and transcripts.'}
        </p>
        {conversations.length > 0 && (
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', justifyContent: 'center', marginTop: '12px' }}>
            {conversations.slice(0, 5).map(c => (
              <button
                key={c.id}
                onClick={() => onSelectConversation(c.id)}
                className="btn btn-secondary"
                style={{ fontSize: '12px', padding: '6px 14px' }}
              >
                {c.title}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', backgroundColor: 'var(--bg-primary)' }}>
      {/* Top Executive Header */}
      <div style={{
        padding: '16px 24px',
        backgroundColor: 'var(--bg-secondary)',
        borderBottom: '1px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '14px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{
            width: '42px',
            height: '42px',
            borderRadius: '10px',
            backgroundColor: 'rgba(52, 211, 153, 0.15)',
            border: '1px solid rgba(52, 211, 153, 0.3)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--wa-green)',
            flexShrink: 0
          }}>
            <ClipboardList size={22} />
          </div>

          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <h1 style={{ fontSize: '17px', fontWeight: 700, color: 'var(--text-primary)' }}>
                {isAr ? 'ملخص المتطلبات والقرارات التنفيذية' : 'Executive Requirements & Brief'}
              </h1>

              {/* Conversation Switcher Dropdown */}
              <select
                value={conversation.id}
                onChange={(e) => onSelectConversation(Number(e.target.value))}
                style={{
                  backgroundColor: 'var(--bg-tertiary)',
                  color: 'var(--text-primary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: '6px',
                  padding: '4px 10px',
                  fontSize: '12px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  outline: 'none',
                }}
              >
                {conversations.map(c => (
                  <option key={c.id} value={c.id}>
                    {c.title} ({c.message_count} {isAr ? 'رسالة' : 'msgs'})
                  </option>
                ))}
              </select>
            </div>

            <p style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '2px' }}>
              {isConversationH
                ? (isAr ? 'كتاب "دليل القادة لصناعة المؤسسة الرقمية عبر إطار H2O" — مراجعة وتعديلات د. حمدين بشارة' : 'Book Leadership Guide for Digital Enterprise (H2O Framework) — Revisions Brief')
                : (conversation.detailed_summary ? conversation.detailed_summary.slice(0, 100) + '...' : (isAr ? 'استخراج ذكي لجميع المتطلبات والملفات' : 'Automated extraction of requirements and files'))}
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            onClick={handleCopySummary}
            className="btn btn-secondary"
            style={{ fontSize: '12px', padding: '6px 12px' }}
            title={isAr ? 'نسخ الملخص بالكامل للحافظة' : 'Copy summary'}
          >
            {copied ? <Check size={14} color="#34d399" /> : <Copy size={14} />}
            <span>{copied ? (isAr ? 'تم النسخ!' : 'Copied!') : (isAr ? 'نسخ الملخص' : 'Copy')}</span>
          </button>

          <button
            onClick={handleExportMarkdown}
            className="btn btn-secondary"
            style={{ fontSize: '12px', padding: '6px 12px' }}
            title={isAr ? 'تنزيل كملف Markdown' : 'Export as Markdown'}
          >
            <Download size={14} />
            <span>{isAr ? 'تصدير MD' : 'Export MD'}</span>
          </button>

          <button
            onClick={handleRunAnalysis}
            disabled={analyzing}
            className="btn btn-primary"
            style={{ fontSize: '12px', padding: '6px 12px' }}
          >
            <Sparkles size={14} className={analyzing ? 'spin' : ''} />
            <span>{analyzing ? (isAr ? 'جارٍ التحليل...' : 'Analyzing...') : (isAr ? 'تحديث التحليل' : 'Re-Analyze')}</span>
          </button>

          <button
            onClick={onOpenTimeline}
            className="btn btn-secondary"
            style={{ fontSize: '12px', padding: '6px 12px' }}
            title={isAr ? 'الانتقال إلى المخطط الزمني الكامل' : 'Open full chat timeline'}
          >
            <span>{isAr ? 'عرض المحادثة' : 'Timeline'}</span>
            <ArrowUpRight size={13} />
          </button>
        </div>
      </div>

      {/* KPI & Badge Strip */}
      <div style={{
        padding: '10px 24px',
        backgroundColor: 'rgba(15, 23, 42, 0.6)',
        borderBottom: '1px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '12px',
        fontSize: '12px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '18px', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#60a5fa' }}>
            <FileText size={15} />
            <span><strong>{docAssets.length}</strong> {isAr ? 'مستندات Word/PDF' : 'Documents'}</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#34d399' }}>
            <Mic size={15} />
            <span><strong>{audioAssets.length}</strong> {isAr ? 'توجيهات صوتية مفرغة' : 'Voice Directives'}</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#f59e0b' }}>
            <ImageIcon size={15} />
            <span><strong>{imageAssets.length}</strong> {isAr ? 'صور ومخططات توضيحية' : 'Visual Schematics'}</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#c084fc' }}>
            <CheckCircle2 size={15} />
            <span><strong>{isConversationH ? 7 : (tasks.length || 0)}</strong> {isAr ? 'قرارات ومتطلبات رئيسية' : 'Core Directives'}</span>
          </div>
        </div>

        {isConversationH && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '3px 10px',
            backgroundColor: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: '20px',
            color: '#f87171',
            fontWeight: 600,
            fontSize: '11px',
          }}>
            <Calendar size={13} />
            <span>{isAr ? 'موعد التسليم المتفق عليه: السبت القادم' : 'Agreed Delivery: Saturday'}</span>
          </div>
        )}
      </div>

      {/* Navigation Tabs */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid var(--border-color)',
        backgroundColor: 'var(--bg-secondary)',
        padding: '0 24px',
        gap: '4px',
      }}>
        {[
          { id: 'decisions', label: isAr ? 'القرارات والتعديلات الجوهرية' : 'Core Decisions', icon: Layers, count: isConversationH ? 7 : (decisions.length || tasks.length) },
          { id: 'documents', label: isAr ? 'المستندات والفصول (Word)' : 'Chapter Documents', icon: FileText, count: docAssets.length },
          { id: 'audio', label: isAr ? 'التوجيهات الصوتية المفرغة' : 'Audio Directives', icon: Mic, count: audioAssets.length },
          { id: 'images', label: isAr ? 'المخططات وصور الصفحات' : 'Visual Schematics', icon: ImageIcon, count: imageAssets.length },
          { id: 'checklist', label: isAr ? 'قائمة التحقق والتسليم' : 'Action Checklist', icon: CheckCircle2, count: isConversationH ? 7 : tasks.length },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '12px 16px',
                border: 'none',
                background: 'transparent',
                color: isActive ? 'var(--accent-color)' : 'var(--text-secondary)',
                borderBottom: isActive ? '2px solid var(--accent-color)' : '2px solid transparent',
                fontWeight: isActive ? 600 : 400,
                fontSize: '12.5px',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              <Icon size={15} />
              <span>{tab.label}</span>
              {tab.count !== undefined && tab.count > 0 && (
                <span style={{
                  padding: '1px 6px',
                  borderRadius: '10px',
                  fontSize: '10.5px',
                  backgroundColor: isActive ? 'rgba(52, 211, 153, 0.2)' : 'rgba(255, 255, 255, 0.08)',
                  color: isActive ? 'var(--wa-green)' : 'var(--text-muted)'
                }}>
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Main Tab Stage */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '24px' }}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)', fontSize: '13px' }}>
            {isAr ? 'جارٍ تحميل متطلبات المحادثة...' : 'Loading requirements...'}
          </div>
        ) : (
          <>
            {/* TAB 1: CORE DECISIONS & STRUCTURAL DELIVERABLES */}
            {activeTab === 'decisions' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', maxWidth: '960px', margin: '0 auto' }}>
                {isConversationH ? (
                  hDecisions.map((dec) => (
                    <div
                      key={dec.id}
                      style={{
                        backgroundColor: 'var(--bg-secondary)',
                        border: '1px solid var(--border-color)',
                        borderRadius: '12px',
                        padding: '18px 20px',
                        boxShadow: '0 4px 15px rgba(0,0,0,0.15)',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <span style={{
                            padding: '3px 8px',
                            borderRadius: '6px',
                            fontSize: '11px',
                            fontWeight: 700,
                            backgroundColor: `${dec.badgeColor}20`,
                            color: dec.badgeColor,
                            border: `1px solid ${dec.badgeColor}40`,
                          }}>
                            {dec.badge}
                          </span>
                          <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                            {dec.title}
                          </h3>
                        </div>

                        {dec.fileRef && (
                          <span style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <FileText size={12} color="#60a5fa" />
                            {dec.fileRef}
                          </span>
                        )}
                      </div>

                      <div style={{
                        padding: '12px 14px',
                        backgroundColor: 'rgba(0, 0, 0, 0.25)',
                        borderRadius: '8px',
                        fontSize: '13px',
                        lineHeight: 1.6,
                        color: 'var(--text-primary)',
                        marginBottom: '10px',
                      }}>
                        <p><strong>{isAr ? 'التوجيه المطلوب:' : 'Directive:'}</strong> {dec.directive}</p>
                      </div>

                      <div style={{ fontSize: '11.5px', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ fontWeight: 600, color: 'var(--text-muted)' }}>{isAr ? 'الدليل وسياق الرسالة:' : 'Evidence:'}</span>
                        <span>{dec.evidence}</span>
                      </div>

                      {/* Special box for Page 65 Replacement Text */}
                      {dec.replacementText && (
                        <div style={{
                          marginTop: '12px',
                          padding: '14px',
                          backgroundColor: 'rgba(52, 211, 153, 0.08)',
                          border: '1px dashed rgba(52, 211, 153, 0.4)',
                          borderRadius: '8px',
                        }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                            <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--wa-green)' }}>
                              {isAr ? 'النص البديل المعتمد لصفحة 65 (جاهز للنسخ والتطبيق):' : 'Approved Replacement Text for Page 65:'}
                            </span>
                            <button
                              onClick={() => {
                                navigator.clipboard.writeText(dec.replacementText!);
                                setCopied(true);
                                setTimeout(() => setCopied(false), 2000);
                              }}
                              className="btn btn-secondary"
                              style={{ padding: '3px 8px', fontSize: '10.5px' }}
                            >
                              <Copy size={11} /> {isAr ? 'نسخ النص البديل' : 'Copy'}
                            </button>
                          </div>
                          <p style={{ fontSize: '12.5px', lineHeight: 1.7, color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>
                            {dec.replacementText}
                          </p>
                        </div>
                      )}
                    </div>
                  ))
                ) : (
                  // Generic Conversation Mode
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                    {conversation.detailed_summary && (
                      <div style={{
                        padding: '16px 20px',
                        backgroundColor: 'var(--bg-secondary)',
                        border: '1px solid var(--border-color)',
                        borderRadius: '10px',
                      }}>
                        <h3 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '8px' }}>
                          {isAr ? 'الملخص التنفيذي للمحادثة' : 'Executive Conversation Summary'}
                        </h3>
                        <p style={{ fontSize: '13px', lineHeight: 1.6, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>
                          {conversation.detailed_summary}
                        </p>
                      </div>
                    )}

                    {decisions.length > 0 ? (
                      decisions.map((d) => (
                        <div
                          key={d.id}
                          style={{
                            backgroundColor: 'var(--bg-secondary)',
                            border: '1px solid var(--border-color)',
                            borderRadius: '10px',
                            padding: '14px 18px',
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                            <span style={{ fontSize: '11px', color: '#c084fc', fontWeight: 600 }}>{isAr ? 'قرار معتمد' : 'Decision'}</span>
                            <span style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>{d.timestamp ? new Date(d.timestamp).toLocaleDateString() : ''}</span>
                          </div>
                          <p style={{ fontSize: '13px', color: 'var(--text-primary)', fontWeight: 600 }}>{d.decision_text}</p>
                          {d.participants && <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>{isAr ? 'المشاركون:' : 'Participants:'} {d.participants}</p>}
                        </div>
                      ))
                    ) : (
                      <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                        <p>{isAr ? 'لا توجد قرارات مستخرجة تلقائياً بعد. انقر على "تحديث التحليل" أعلاه لاستخراج القرارات.' : 'No decisions extracted yet. Click Re-Analyze above.'}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* TAB 2: CHAPTER DOCUMENTS (WORD / PDF) */}
            {activeTab === 'documents' && (
              <div style={{ maxWidth: '960px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                    {isAr ? 'المستندات وملفات الفصول المستلمة' : 'Received Chapter Documents'} ({docAssets.length})
                  </h3>
                  <span style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                    {isAr ? 'مستخرجة بالكامل محلياً مع قارئ مدمج للنصوص' : 'Extracted locally with full text reader'}
                  </span>
                </div>

                {docAssets.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: '50px', color: 'var(--text-muted)' }}>
                    {isAr ? 'لا توجد مستندات مرفقة في هذه المحادثة.' : 'No document attachments found.'}
                  </div>
                ) : (
                  docAssets.map(({ asset, message }) => (
                    <div
                      key={asset.id}
                      style={{
                        backgroundColor: 'var(--bg-secondary)',
                        border: '1px solid var(--border-color)',
                        borderRadius: '12px',
                        padding: '16px 20px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '10px',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                          <div style={{
                            width: '40px',
                            height: '40px',
                            borderRadius: '8px',
                            backgroundColor: 'rgba(59, 130, 246, 0.15)',
                            border: '1px solid rgba(59, 130, 246, 0.3)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: '#60a5fa',
                            flexShrink: 0
                          }}>
                            <FileText size={20} />
                          </div>

                          <div>
                            <h4 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>
                              {asset.file_name}
                            </h4>
                            <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                              {Math.round(asset.file_size / 1024)} KB • {asset.document ? `${asset.document.page_count} ${isAr ? 'صفحة' : 'pages'}` : ''} • {new Date(message.timestamp).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}
                            </p>
                          </div>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          {asset.document?.extracted_text && (
                            <button
                              onClick={() => setReadingDoc({
                                title: asset.file_name,
                                text: asset.document!.extracted_text,
                                fileName: asset.file_name,
                                url: apiClient.getMediaUrl(asset.id),
                              })}
                              className="btn btn-primary"
                              style={{ fontSize: '11.5px', padding: '6px 12px', display: 'flex', alignItems: 'center', gap: '5px' }}
                            >
                              <BookOpen size={13} />
                              <span>{isAr ? 'قراءة المستند كاملاً' : 'Read Full Text'}</span>
                            </button>
                          )}

                          <a
                            href={apiClient.getMediaUrl(asset.id)}
                            target="_blank"
                            rel="noreferrer"
                            className="btn btn-secondary"
                            style={{ fontSize: '11.5px', padding: '6px 12px', display: 'flex', alignItems: 'center', gap: '5px', textDecoration: 'none' }}
                          >
                            <Download size={13} />
                            <span>{isAr ? 'تحميل' : 'Download'}</span>
                          </a>
                        </div>
                      </div>

                      {/* Excerpt Snippet */}
                      {asset.document?.extracted_text && (
                        <div style={{
                          padding: '10px 14px',
                          backgroundColor: 'rgba(0, 0, 0, 0.25)',
                          borderRadius: '8px',
                          fontSize: '12px',
                          color: 'var(--text-secondary)',
                          lineHeight: 1.6,
                          maxHeight: '75px',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          direction: 'rtl',
                          textAlign: 'right'
                        }}>
                          {asset.document.extracted_text.slice(0, 240)}...
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            )}

            {/* TAB 3: AUDIO DIRECTIVES & WHISPER TRANSCRIPTS */}
            {activeTab === 'audio' && (
              <div style={{ maxWidth: '960px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                    {isAr ? 'التوجيهات الصوتية وتفريغات Whisper المعتمدة' : 'Voice Directives & Whisper Transcripts'} ({audioAssets.length})
                  </h3>
                  <span style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                    {isAr ? 'جميع التسجيلات مفرغة ومفهرسة محلياً بنسبة 100%' : '100% locally transcribed & indexed'}
                  </span>
                </div>

                {audioAssets.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: '50px', color: 'var(--text-muted)' }}>
                    {isAr ? 'لا توجد تسجيلات صوتية في هذه المحادثة.' : 'No audio directives found.'}
                  </div>
                ) : (
                  audioAssets.map(({ asset, message }) => (
                    <div
                      key={asset.id}
                      style={{
                        backgroundColor: 'var(--bg-secondary)',
                        border: '1px solid var(--border-color)',
                        borderRadius: '12px',
                        padding: '16px 20px',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                        <span style={{ fontSize: '12px', fontWeight: 700, color: '#34d399', display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <Mic size={14} />
                          {message.sender_name} • {new Date(message.timestamp).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}
                        </span>
                        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                          {asset.duration_seconds ? `${Math.round(asset.duration_seconds)} ${isAr ? 'ثانية' : 'sec'}` : ''}
                        </span>
                      </div>

                      <VoiceMessageCard asset={asset} senderName={message.sender_name} />
                    </div>
                  ))
                )}
              </div>
            )}

            {/* TAB 4: VISUAL SCHEMATICS & PAGE IMAGES */}
            {activeTab === 'images' && (
              <div style={{ maxWidth: '960px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                    {isAr ? 'الصور والمخططات التوضيحية المستلمة' : 'Visual Schematics & Book Pages'} ({imageAssets.length})
                  </h3>
                  <span style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                    {isAr ? 'تشمل صورة استبدال صفحة 65، غلاف الكتاب، ومخططات إطار H2O' : 'Includes Page 65 crop, book cover, and H2O schematics'}
                  </span>
                </div>

                {imageAssets.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: '50px', color: 'var(--text-muted)' }}>
                    {isAr ? 'لا توجد صور في هذه المحادثة.' : 'No images found.'}
                  </div>
                ) : (
                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                    gap: '16px',
                  }}>
                    {imageAssets.map(({ asset, message }) => {
                      const isPage65 = asset.file_name.includes('d76742ad60');
                      const isCover = asset.file_name.includes('d31d84157d');
                      const isPhase2 = asset.file_name.includes('aa4b5e804b');
                      const isPage19 = asset.file_name.includes('97b97c78ab');
                      const isPage20 = asset.file_name.includes('b9ec7a9f26');

                      let tagLabel = '';
                      if (isPage65) tagLabel = isAr ? '📌 صفحة 65 (المطلوب استبدالها)' : 'Page 65 (To Replace)';
                      else if (isCover) tagLabel = isAr ? '📖 غلاف وعنوان الكتاب' : 'Book Cover';
                      else if (isPhase2) tagLabel = isAr ? '📊 مخطط مرحلة التنفيذ والميثاق' : 'Execution Schematic';
                      else if (isPage19) tagLabel = isAr ? '📘 صفحة 19 (أبعاد إطار H2O)' : 'Page 19';
                      else if (isPage20) tagLabel = isAr ? '📘 صفحة 20 (مظلة الإشراف)' : 'Page 20';

                      return (
                        <div
                          key={asset.id}
                          style={{
                            backgroundColor: 'var(--bg-secondary)',
                            border: isPage65 ? '2px solid rgba(239, 68, 68, 0.6)' : '1px solid var(--border-color)',
                            borderRadius: '12px',
                            padding: '12px',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '8px',
                          }}
                        >
                          {tagLabel && (
                            <div style={{
                              fontSize: '11px',
                              fontWeight: 700,
                              color: isPage65 ? '#ef4444' : '#60a5fa',
                              padding: '2px 6px',
                              borderRadius: '4px',
                              backgroundColor: isPage65 ? 'rgba(239, 68, 68, 0.1)' : 'rgba(96, 165, 250, 0.1)',
                              alignSelf: 'flex-start',
                            }}>
                              {tagLabel}
                            </div>
                          )}

                          <ImageCard asset={asset} />

                          <div style={{ fontSize: '10.5px', color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span>{new Date(message.timestamp).toLocaleDateString()}</span>
                            <span>{message.sender_name}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {/* TAB 5: ACTION CHECKLIST & DELIVERY PLAN */}
            {activeTab === 'checklist' && (
              <div style={{ maxWidth: '800px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                      {isAr ? 'قائمة التحقق وقفل متطلبات التسليم' : 'Delivery & Action Checklist'}
                    </h3>
                    <p style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                      {isAr ? 'متابعة تنفيذ المتطلبات نقطة بنقطة قبل التسليم النهائي يوم السبت' : 'Track task fulfillment before final Saturday delivery'}
                    </p>
                  </div>

                  {/* Progress Badge */}
                  {(() => {
                    const total = isConversationH ? 7 : tasks.length;
                    const completed = isConversationH
                      ? Object.values(checkedItems).filter(Boolean).length
                      : tasks.filter(t => t.status === 'completed').length;
                    const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
                    return (
                      <div style={{
                        padding: '6px 14px',
                        backgroundColor: 'rgba(52, 211, 153, 0.15)',
                        border: '1px solid rgba(52, 211, 153, 0.3)',
                        borderRadius: '8px',
                        textAlign: 'center',
                      }}>
                        <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--wa-green)' }}>{pct}% {isAr ? 'منجز' : 'Done'}</span>
                        <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>{completed} / {total}</div>
                      </div>
                    );
                  })()}
                </div>

                {isConversationH ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {[
                      { key: 'h-task-1', title: isAr ? 'دمج الفصل السادس والسابع في فصل واحد متكامل' : 'Merge Chapters 6 & 7 into a single chapter', desc: isAr ? 'مرفق ملف: دمج الفصل السادس و السابع.docx' : 'Ref: دمج الفصل السادس و السابع.docx' },
                      { key: 'h-task-2', title: isAr ? 'تطبيق شلال الاستراتيجية للفصل الخامس ومراجعة الصور' : 'Apply Strategy Waterfall to Chapter 5 and review images', desc: isAr ? 'مرفق ملف: شلال_الاستراتيجية_مفصّل.docx' : 'Ref: شلال_الاستراتيجية_مفصّل.docx' },
                      { key: 'h-task-3', title: isAr ? 'نقل الجانب التطبيقي لكل فصل قبل الخاتمة مباشرة' : 'Move practical section before chapter conclusion', desc: isAr ? 'مرفق ملف: الجانب_التطبيقي_لكل_فصل.docx' : 'Ref: الجانب_التطبيقي_لكل_فصل.docx' },
                      { key: 'h-task-4', title: isAr ? 'حذف واستبدال نص صفحة 65 بفقرة فرق المسارات والقدرات' : 'Replace Page 65 text with Tracks vs 7 Capabilities', desc: isAr ? 'مرفق الصورة والنص البديل المعتمد' : 'Ref: Page 65 Crop + Replacement Text' },
                      { key: 'h-task-5', title: isAr ? 'مراجعة وتطوير مخططات مرحلة Transform للفصل التاسع' : 'Refine Transform phase diagrams for Chapter 9', desc: isAr ? 'مرفق ملف: الفصل التاسع — مرحلة Transform...docx' : 'Ref: الفصل التاسع docx' },
                      { key: 'h-task-6', title: isAr ? 'تحويل الخط إلى خط Cairo وتصحيح علامات الداش (-)' : 'Apply Cairo font and clean stray dashes', desc: isAr ? 'توجيه د. حمدين لراحة القراءة وتنسيق الطباعة' : 'Dr. Hamdeen typography directive' },
                      { key: 'h-task-7', title: isAr ? 'تجهيز النسخة المنقحة الكاملة للتسليم والمراجعة يوم السبت' : 'Prepare final revised master book for Saturday delivery', desc: isAr ? 'الموعد النهائي المتفق عليه مع د. حمدين' : 'Final agreed review milestone' },
                    ].map((item) => {
                      const isChecked = !!checkedItems[item.key];
                      return (
                        <div
                          key={item.key}
                          onClick={() => toggleCheck(item.key)}
                          style={{
                            padding: '14px 18px',
                            backgroundColor: isChecked ? 'rgba(52, 211, 153, 0.05)' : 'var(--bg-secondary)',
                            border: `1px solid ${isChecked ? 'rgba(52, 211, 153, 0.3)' : 'var(--border-color)'}`,
                            borderRadius: '10px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '14px',
                            cursor: 'pointer',
                            transition: 'all 0.15s ease',
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => {}}
                            style={{ width: '18px', height: '18px', accentColor: 'var(--wa-green)', cursor: 'pointer' }}
                          />
                          <div style={{ flex: 1 }}>
                            <h4 style={{
                              fontSize: '13.5px',
                              fontWeight: 600,
                              color: isChecked ? 'var(--text-muted)' : 'var(--text-primary)',
                              textDecoration: isChecked ? 'line-through' : 'none'
                            }}>
                              {item.title}
                            </h4>
                            <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                              {item.desc}
                            </p>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {tasks.length > 0 ? (
                      tasks.map((task) => (
                        <div
                          key={task.id}
                          style={{
                            padding: '14px 18px',
                            backgroundColor: task.status === 'completed' ? 'rgba(52, 211, 153, 0.05)' : 'var(--bg-secondary)',
                            border: '1px solid var(--border-color)',
                            borderRadius: '10px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                          }}
                        >
                          <div>
                            <h4 style={{ fontSize: '13.5px', fontWeight: 600, color: 'var(--text-primary)' }}>
                              {task.title}
                            </h4>
                            <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                              {task.description || (isAr ? 'مهمة مستخرجة من المحادثة' : 'Extracted task')} • {task.priority || 'medium'}
                            </p>
                          </div>
                          <span style={{
                            padding: '3px 8px',
                            borderRadius: '6px',
                            fontSize: '10.5px',
                            fontWeight: 600,
                            backgroundColor: task.status === 'completed' ? 'rgba(52, 211, 153, 0.15)' : 'rgba(255, 255, 255, 0.08)',
                            color: task.status === 'completed' ? 'var(--wa-green)' : 'var(--text-muted)',
                          }}>
                            {task.status}
                          </span>
                        </div>
                      ))
                    ) : (
                      <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                        {isAr ? 'لا توجد مهام مستخرجة بعد. انقر على "تحديث التحليل" لاستخراج المهام.' : 'No tasks extracted yet. Click Re-Analyze.'}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* Inline Document Reader Modal */}
      {readingDoc && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.75)',
          backdropFilter: 'blur(4px)',
          zIndex: 999,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '24px',
        }}>
          <div style={{
            backgroundColor: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            borderRadius: '14px',
            width: '100%',
            maxWidth: '850px',
            maxHeight: '85vh',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '0 20px 50px rgba(0,0,0,0.6)',
            overflow: 'hidden',
          }}>
            {/* Modal Header */}
            <div style={{
              padding: '16px 20px',
              borderBottom: '1px solid var(--border-color)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <FileText size={18} color="#60a5fa" />
                <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                  {readingDoc.title}
                </h3>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <a
                  href={readingDoc.url}
                  target="_blank"
                  rel="noreferrer"
                  className="btn btn-secondary"
                  style={{ fontSize: '11px', padding: '5px 10px', textDecoration: 'none' }}
                >
                  <Download size={12} /> {isAr ? 'تحميل الملف الأصلي' : 'Download'}
                </a>
                <button
                  onClick={() => setReadingDoc(null)}
                  className="btn btn-secondary"
                  style={{ fontSize: '11px', padding: '5px 10px' }}
                >
                  {isAr ? 'إغلاق' : 'Close'}
                </button>
              </div>
            </div>

            {/* Modal Content */}
            <div style={{
              flex: 1,
              overflowY: 'auto',
              padding: '24px',
              fontSize: '13px',
              lineHeight: 1.8,
              color: 'var(--text-primary)',
              whiteSpace: 'pre-wrap',
              direction: 'rtl',
              textAlign: 'right',
              backgroundColor: 'rgba(15, 23, 42, 0.4)',
            }}>
              {readingDoc.text}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
