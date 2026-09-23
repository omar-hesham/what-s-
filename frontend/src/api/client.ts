/**
 * API Client for communicating with the local OWI FastAPI backend.
 */

import {
  Conversation, Message, TaskItem, WaitingItem, DecisionItem,
  IdeaItem, PropertyItem, ResearchItem, AskResponse,
  TodayMetrics, CostAudit, HardwareResources, StorageDashboardData
} from '../types';

const API_BASE = 'http://127.0.0.1:8765';

export const apiClient = {
  // Media URL helper
  getMediaUrl(mediaAssetId: number): string {
    return `${API_BASE}/api/media/${mediaAssetId}/file`;
  },

  // Conversations
  async getConversations(): Promise<Conversation[]> {
    const res = await fetch(`${API_BASE}/api/conversations`);
    return res.json();
  },

  async getConversation(id: number): Promise<Conversation> {
    const res = await fetch(`${API_BASE}/api/conversations/${id}`);
    return res.json();
  },

  async importText(file: File, title?: string): Promise<any> {
    const formData = new FormData();
    formData.append('file', file);
    if (title) formData.append('title', title);
    const res = await fetch(`${API_BASE}/api/conversations/import/text`, {
      method: 'POST',
      body: formData,
    });
    return res.json();
  },

  async importZip(file: File, title?: string): Promise<any> {
    const formData = new FormData();
    formData.append('file', file);
    if (title) formData.append('title', title);
    const res = await fetch(`${API_BASE}/api/conversations/import/zip`, {
      method: 'POST',
      body: formData,
    });
    return res.json();
  },

  async deleteConversation(id: number): Promise<any> {
    const res = await fetch(`${API_BASE}/api/conversations/${id}`, { method: 'DELETE' });
    return res.json();
  },

  async analyzeConversation(id: number): Promise<any> {
    const res = await fetch(`${API_BASE}/api/conversations/${id}/analyze`, { method: 'POST' });
    return res.json();
  },

  // Messages
  async getMessages(
    conversationId: number, 
    filter?: { messageType?: string; sender?: string }
  ): Promise<Message[]> {
    let url = `${API_BASE}/api/conversations/${conversationId}/messages?limit=300`;
    if (filter?.messageType) url += `&message_type=${filter.messageType}`;
    if (filter?.sender) url += `&sender=${encodeURIComponent(filter.sender)}`;
    const res = await fetch(url);
    return res.json();
  },

  // Tasks & Knowledge Entities
  async getTasks(status?: string, conversationId?: number): Promise<TaskItem[]> {
    let url = `${API_BASE}/api/tasks?`;
    if (status) url += `status=${status}&`;
    if (conversationId) url += `conversation_id=${conversationId}`;
    const res = await fetch(url);
    return res.json();
  },

  async updateTask(id: number, update: Partial<TaskItem>): Promise<any> {
    const res = await fetch(`${API_BASE}/api/tasks/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(update),
    });
    return res.json();
  },

  async getWaiting(status?: string, conversationId?: number): Promise<WaitingItem[]> {
    let url = `${API_BASE}/api/waiting?`;
    if (status) url += `status=${status}&`;
    if (conversationId) url += `conversation_id=${conversationId}`;
    const res = await fetch(url);
    return res.json();
  },

  async updateWaiting(id: number, update: Partial<WaitingItem>): Promise<any> {
    const res = await fetch(`${API_BASE}/api/waiting/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(update),
    });
    return res.json();
  },

  async getDecisions(conversationId?: number): Promise<DecisionItem[]> {
    let url = `${API_BASE}/api/decisions`;
    if (conversationId) url += `?conversation_id=${conversationId}`;
    const res = await fetch(url);
    return res.json();
  },

  async getIdeas(conversationId?: number): Promise<IdeaItem[]> {
    let url = `${API_BASE}/api/ideas`;
    if (conversationId) url += `?conversation_id=${conversationId}`;
    const res = await fetch(url);
    return res.json();
  },

  async getProperties(conversationId?: number): Promise<PropertyItem[]> {
    let url = `${API_BASE}/api/properties`;
    if (conversationId) url += `?conversation_id=${conversationId}`;
    const res = await fetch(url);
    return res.json();
  },

  async getResearch(conversationId?: number): Promise<ResearchItem[]> {
    let url = `${API_BASE}/api/research`;
    if (conversationId) url += `?conversation_id=${conversationId}`;
    const res = await fetch(url);
    return res.json();
  },

  // Conversational Search / RAG
  async ask(query: string, conversationId?: number): Promise<AskResponse> {
    const res = await fetch(`${API_BASE}/api/intelligence/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, conversation_id: conversationId }),
    });
    return res.json();
  },

  async search(query: string, mode: 'fts' | 'semantic' | 'hybrid' = 'hybrid', conversationId?: number): Promise<any> {
    let url = `${API_BASE}/api/intelligence/search?q=${encodeURIComponent(query)}&mode=${mode}`;
    if (conversationId) url += `&conversation_id=${conversationId}`;
    const res = await fetch(url);
    return res.json();
  },

  // Today & Briefing
  async getTodayDashboard(): Promise<{ metrics: TodayMetrics; recent_tasks: any[]; recent_waiting: any[] }> {
    const res = await fetch(`${API_BASE}/api/intelligence/today`);
    return res.json();
  },

  async getBriefing(type: 'daily' | 'weekly' | 'project' = 'daily'): Promise<{ title: string; content_markdown: string }> {
    const res = await fetch(`${API_BASE}/api/intelligence/briefing?briefing_type=${type}`);
    return res.json();
  },

  // System & Cost & Models
  async getCostAudit(): Promise<CostAudit> {
    const res = await fetch(`${API_BASE}/api/system/cost`);
    return res.json();
  },

  async getHardwareResources(): Promise<HardwareResources> {
    const res = await fetch(`${API_BASE}/api/system/resources`);
    return res.json();
  },

  async getStorage(): Promise<StorageDashboardData> {
    const res = await fetch(`${API_BASE}/api/system/storage`);
    return res.json();
  },

  async cleanupStorage(): Promise<any> {
    const res = await fetch(`${API_BASE}/api/system/cleanup`, { method: 'POST' });
    return res.json();
  },

  async getModelStatus(): Promise<any> {
    const res = await fetch(`${API_BASE}/api/models/status`);
    return res.json();
  },

  async setProfile(profile: 'LIGHT' | 'BALANCED' | 'QUALITY'): Promise<any> {
    const res = await fetch(`${API_BASE}/api/models/profile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile }),
    });
    return res.json();
  }
};
