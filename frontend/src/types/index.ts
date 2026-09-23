/**
 * TypeScript types for Omar WhatsApp Intelligence (OWI)
 */

export interface Conversation {
  id: number;
  title: string;
  source_type: string;
  message_count: number;
  start_date?: string;
  end_date?: string;
  summary?: string;
  detailed_summary?: string;
  created_at: string;
  participants?: string[];
  tasks_count?: number;
  properties_count?: number;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
  speaker?: string;
}

export interface Transcript {
  id: number;
  language?: string;
  full_text: string;
  duration?: number;
  segments: TranscriptSegment[];
}

export interface DocumentRecord {
  id: number;
  title: string;
  doc_type: string;
  page_count: number;
  extracted_text: string;
}

export interface MediaAsset {
  id: number;
  file_name: string;
  file_type: 'audio' | 'image' | 'video' | 'document';
  file_size: number;
  duration_seconds?: number;
  width?: number;
  height?: number;
  transcript?: Transcript;
  document?: DocumentRecord;
}

export interface Message {
  id: number;
  conversation_id: number;
  sender_name: string;
  timestamp: string;
  content: string;
  message_type: 'text' | 'voice' | 'image' | 'video' | 'document' | 'system';
  has_attachment: boolean;
  attachment_name?: string;
  source_index: number;
  media_assets: MediaAsset[];
}

export interface TaskItem {
  id: number;
  conversation_id: number;
  message_id?: number;
  title: string;
  description?: string;
  status: 'inbox' | 'open' | 'waiting' | 'completed' | 'dismissed';
  priority: 'low' | 'medium' | 'high';
  confidence: number;
  created_date?: string;
  due_date?: string;
  assigned_contact_name?: string;
  source_excerpt?: string;
}

export interface WaitingItem {
  id: number;
  conversation_id: number;
  message_id?: number;
  person_name: string;
  deliverable: string;
  status: 'open' | 'resolved' | 'overdue' | 'dismissed';
  due_date?: string;
  source_excerpt?: string;
}

export interface DecisionItem {
  id: number;
  conversation_id: number;
  decision_text: string;
  confidence: number;
  participants?: string;
  timestamp?: string;
  source_excerpt?: string;
}

export interface IdeaItem {
  id: number;
  conversation_id: number;
  title: string;
  description?: string;
  source_excerpt?: string;
}

export interface PropertyItem {
  id: number;
  conversation_id: number;
  title: string;
  property_type?: string;
  area_sqm?: number;
  location?: string;
  district?: string;
  price?: number;
  currency: string;
  deal_type: 'sale' | 'rent';
  finishing?: string;
  has_admin_license: boolean;
  rooms?: number;
  bathrooms?: number;
  listing_draft?: string;
  source_evidence?: string;
}

export interface ResearchItem {
  id: number;
  conversation_id: number;
  topic: string;
  question?: string;
  author?: string;
  finding?: string;
  citation?: string;
}

export interface Citation {
  source_type: string;
  message_id?: number;
  conversation_id?: number;
  sender?: string;
  timestamp?: string;
  content?: string;
  deliverable?: string;
  status?: string;
  title?: string;
  price?: number;
  evidence?: string;
}

export interface AskResponse {
  answer: string;
  citations: Citation[];
}

export interface TodayMetrics {
  conversations: number;
  messages: number;
  voice_notes: number;
  images: number;
  documents: number;
  inbox_tasks: number;
  open_tasks: number;
  waiting_items: number;
  decisions: number;
  ideas: number;
  properties: number;
}

export interface CostAudit {
  core_mode: string;
  mandatory_subscription: string;
  mandatory_api: string;
  recurring_software_fee: string;
  cloud_ai_enabled: boolean;
  cloud_storage_enabled: boolean;
  status_notice: string;
}

export interface HardwareResources {
  cpu_cores: number;
  total_ram_gb: number;
  available_ram_gb: number;
  ram_usage_percent: number;
  suggested_profile: 'LIGHT' | 'BALANCED' | 'QUALITY';
  current_profile: 'LIGHT' | 'BALANCED' | 'QUALITY';
}

export interface StorageDashboardData {
  total_mb: number;
  database_mb: number;
  audio_mb: number;
  images_mb: number;
  video_mb: number;
  documents_mb: number;
  models_mb: number;
  derived_files_mb: number;
  logs_mb: number;
  storage_path: string;
}
