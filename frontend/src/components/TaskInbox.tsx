import React, { useState, useEffect } from 'react';
import {
  Inbox, Check, X, CheckSquare, Clock, AlertCircle,
  Filter, Calendar, User, Search
} from 'lucide-react';
import { TaskItem } from '../types';
import { apiClient } from '../api/client';

interface TaskInboxProps {
  language: 'ar' | 'en';
  onTaskChange?: () => void;
}

export const TaskInbox: React.FC<TaskInboxProps> = ({ language, onTaskChange }) => {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>('inbox');
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  const isAr = language === 'ar';

  useEffect(() => {
    loadTasks();
  }, [statusFilter]);

  const loadTasks = async () => {
    setLoading(true);
    try {
      const data = await apiClient.getTasks(statusFilter !== 'all' ? statusFilter : undefined);
      setTasks(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleStatusChange = async (taskId: number, newStatus: string) => {
    try {
      await apiClient.updateTask(taskId, { status: newStatus as any });
      await loadTasks();
      if (onTaskChange) onTaskChange();
    } catch (e) {
      console.error(e);
    }
  };

  const filteredTasks = tasks.filter((t) => {
    if (!search) return true;
    return (
      t.title.toLowerCase().includes(search.toLowerCase()) ||
      (t.assigned_contact_name && t.assigned_contact_name.toLowerCase().includes(search.toLowerCase()))
    );
  });

  return (
    <div style={{ padding: '24px', overflowY: 'auto', height: '100%' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Inbox size={20} color="var(--accent-color)" />
            {isAr ? 'الوارد الذكي للمهام المكتشفة' : 'AI Task Inbox & Review'}
          </h2>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            {isAr ? 'مراجعة وتأكيد المهام المكتشفة من المحادثات والصوتيات مع درجات الثقة' : 'Review and accept AI-extracted tasks before committing to your board'}
          </p>
        </div>

        {/* Search */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: 'var(--bg-secondary)', borderRadius: '8px', padding: '6px 12px', border: '1px solid var(--border-color)' }}>
          <Search size={14} color="var(--text-muted)" />
          <input
            type="text"
            placeholder={isAr ? 'بحث في المهام...' : 'Search tasks...'}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ background: 'transparent', border: 'none', outline: 'none', color: 'white', fontSize: '12px', width: '160px' }}
          />
        </div>
      </div>

      {/* Status Filter Tabs */}
      <div style={{ display: 'flex', gap: '6px', marginBottom: '20px', overflowX: 'auto' }}>
        {[
          { id: 'inbox', label: isAr ? 'الوارد (بحاجة لمراجعة)' : 'Inbox (Pending Review)' },
          { id: 'open', label: isAr ? 'مفتوحة ومؤكدة' : 'Open / Accepted' },
          { id: 'completed', label: isAr ? 'مكتملة' : 'Completed' },
          { id: 'dismissed', label: isAr ? 'مستبعدة' : 'Dismissed' },
          { id: 'all', label: isAr ? 'الكل' : 'All' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setStatusFilter(tab.id)}
            style={{
              padding: '6px 14px',
              borderRadius: '8px',
              fontSize: '12px',
              fontWeight: statusFilter === tab.id ? 600 : 400,
              backgroundColor: statusFilter === tab.id ? 'var(--accent-color)' : 'var(--bg-secondary)',
              color: statusFilter === tab.id ? 'white' : 'var(--text-secondary)',
              border: '1px solid var(--border-color)',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Task Cards List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
            {isAr ? 'جارٍ تحميل المهام...' : 'Loading tasks...'}
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="card" style={{ textAlign: 'center', padding: '40px' }}>
            <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
              {isAr ? 'لا توجد مهام في هذا التصنيف' : 'No tasks in this category'}
            </p>
          </div>
        ) : (
          filteredTasks.map((task) => (
            <div key={task.id} className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', padding: '16px' }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                  <span className={`badge ${task.status === 'inbox' ? 'badge-inbox' : (task.status === 'completed' ? 'badge-open' : 'badge-waiting')}`}>
                    {task.status}
                  </span>
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    {isAr ? 'نسبة الثقة:' : 'Confidence:'} {Math.round(task.confidence * 100)}%
                  </span>
                </div>

                <h3 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
                  {task.title}
                </h3>

                {task.source_excerpt && (
                  <p style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic', marginBottom: '8px' }}>
                    "{task.source_excerpt}"
                  </p>
                )}

                <div style={{ display: 'flex', gap: '14px', fontSize: '11.5px', color: 'var(--text-secondary)' }}>
                  {task.due_date && (
                    <span style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#fbbf24' }}>
                      <Calendar size={13} /> {new Date(task.due_date).toLocaleDateString()}
                    </span>
                  )}
                  {task.assigned_contact_name && (
                    <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <User size={13} /> {task.assigned_contact_name}
                    </span>
                  )}
                </div>
              </div>

              {/* Actions */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {task.status === 'inbox' && (
                  <button
                    onClick={() => handleStatusChange(task.id, 'open')}
                    className="btn btn-success"
                    style={{ fontSize: '11px', padding: '6px 12px' }}
                  >
                    <Check size={13} /> {isAr ? 'قبول وتأكيد' : 'Accept'}
                  </button>
                )}

                {task.status !== 'completed' && task.status !== 'dismissed' && (
                  <button
                    onClick={() => handleStatusChange(task.id, 'completed')}
                    className="btn btn-secondary"
                    style={{ fontSize: '11px', padding: '6px 12px' }}
                  >
                    <CheckSquare size={13} /> {isAr ? 'إنجاز' : 'Mark Done'}
                  </button>
                )}

                {task.status !== 'dismissed' && (
                  <button
                    onClick={() => handleStatusChange(task.id, 'dismissed')}
                    className="btn btn-secondary"
                    style={{ fontSize: '11px', padding: '6px 12px', color: '#f87171' }}
                  >
                    <X size={13} /> {isAr ? 'استبعاد' : 'Dismiss'}
                  </button>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
