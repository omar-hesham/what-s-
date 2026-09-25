"""
Relational models for OWI knowledge graph and storage.
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, Index, JSON
)
from sqlalchemy.orm import relationship
from owi.db.database import Base

class Job(Base):
    """Background asynchronous processing job."""
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_type = Column(String(50), nullable=False, index=True)  # transcription, ocr, import, nlp, video
    status = Column(String(20), default="queued", index=True)  # queued, processing, completed, failed
    progress = Column(Integer, default=0)  # 0 to 100
    error_message = Column(Text, nullable=True)
    payload = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    attempts = Column(Integer, default=0)
    lease_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Conversation(Base):
    """WhatsApp conversation container."""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    source_type = Column(String(50), default="export_txt")  # export_txt, export_zip, drag_drop, folder_watch, companion
    source_hash = Column(String(64), nullable=True, index=True)  # SHA256 of source file for deduplication
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    message_count = Column(Integer, default=0)
    summary = Column(Text, nullable=True)
    detailed_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.timestamp")
    media_assets = relationship("MediaAsset", back_populates="conversation", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="conversation", cascade="all, delete-orphan")
    waiting_items = relationship("WaitingFor", back_populates="conversation", cascade="all, delete-orphan")
    decisions = relationship("Decision", back_populates="conversation", cascade="all, delete-orphan")
    ideas = relationship("Idea", back_populates="conversation", cascade="all, delete-orphan")
    commitments = relationship("Commitment", back_populates="conversation", cascade="all, delete-orphan")
    properties = relationship("Property", back_populates="conversation", cascade="all, delete-orphan")
    research_items = relationship("ResearchItem", back_populates="conversation", cascade="all, delete-orphan")
    attachment_records = relationship("AttachmentRecord", back_populates="conversation", cascade="all, delete-orphan")

class Participant(Base):
    """Chat participant / contact."""
    __tablename__ = "participants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    phone_number = Column(String(50), nullable=True, index=True)
    normalized_name = Column(String(255), nullable=False, index=True)
    role = Column(String(100), nullable=True)
    organization_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Message(Base):
    """Individual WhatsApp message with rich media references."""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_name = Column(String(255), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    content = Column(Text, nullable=False)
    message_type = Column(String(50), default="text", index=True)  # text, voice, image, video, document, system
    raw_text = Column(Text, nullable=True)
    has_attachment = Column(Boolean, default=False)
    attachment_name = Column(String(255), nullable=True)
    attachment_status = Column(String(50), default="none", nullable=True)  # saved-original, preview-only, unavailable, expired, too-large, failed, unsupported, none
    source_index = Column(Integer, default=0)
    timestamp_provenance = Column(String(50), default="verified", nullable=True)  # verified, unverified_fallback
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    media_assets = relationship("MediaAsset", back_populates="message", cascade="all, delete-orphan")
    attachment_records = relationship("AttachmentRecord", back_populates="message", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="message")
    decisions = relationship("Decision", back_populates="message")
    commitments = relationship("Commitment", back_populates="message")
    waiting_items = relationship("WaitingFor", back_populates="message")

class MediaAsset(Base):
    """Media attachment (audio, video, image, document)."""
    __tablename__ = "media_assets"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False, index=True)  # audio, image, video, document
    mime_type = Column(String(100), nullable=True)
    file_size = Column(Integer, default=0)
    file_path = Column(String(500), nullable=False)
    sha256_hash = Column(String(64), nullable=False, index=True)
    duration_seconds = Column(Float, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    processing_status = Column(String(50), default="unprocessed", index=True)  # unprocessed, queued, processing, completed, failed, unsupported, setup_needed
    processing_error = Column(String(255), nullable=True)
    processing_attempts = Column(Integer, default=0)
    processing_method = Column(String(100), nullable=True)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    conversation = relationship("Conversation", back_populates="media_assets")
    message = relationship("Message", back_populates="media_assets")
    attachment_records = relationship("AttachmentRecord", back_populates="media_asset")
    transcript = relationship("Transcript", uselist=False, back_populates="media_asset", cascade="all, delete-orphan")
    document_record = relationship("DocumentRecord", uselist=False, back_populates="media_asset", cascade="all, delete-orphan")

class AttachmentRecord(Base):
    """
    Durable per-attachment capture record linked to Message and capture session.
    Tracks every detected attachment with per-file status:
    saved-original, preview-only, unavailable, expired, too-large, failed, unsupported.
    """
    __tablename__ = "attachment_records"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=True, index=True)
    media_asset_id = Column(Integer, ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(String(100), nullable=True, index=True)
    message_key = Column(String(150), nullable=True, index=True)
    attachment_position = Column(Integer, nullable=True)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # audio, image, video, document, other
    mime_type = Column(String(100), nullable=True)
    file_size = Column(Integer, default=0)
    sha256_hash = Column(String(64), nullable=True, index=True)
    status = Column(String(50), nullable=False, default="unavailable")  # saved-original, preview-only, unavailable, expired, too-large, failed, unsupported
    reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    conversation = relationship("Conversation", back_populates="attachment_records")
    message = relationship("Message", back_populates="attachment_records")
    media_asset = relationship("MediaAsset", back_populates="attachment_records")

class Transcript(Base):
    """Audio/video speech transcript produced by local Whisper engine."""
    __tablename__ = "transcripts"

    id = Column(Integer, primary_key=True, index=True)
    media_asset_id = Column(Integer, ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    language_detected = Column(String(10), nullable=True)
    confidence = Column(Float, default=1.0)
    full_text = Column(Text, nullable=False)
    duration_seconds = Column(Float, nullable=True)
    model_used = Column(String(50), default="base")
    created_at = Column(DateTime, default=datetime.utcnow)

    media_asset = relationship("MediaAsset", back_populates="transcript")
    segments = relationship("TranscriptSegment", back_populates="transcript", cascade="all, delete-orphan", order_by="TranscriptSegment.start_time")

class TranscriptSegment(Base):
    """Timed speech segment for audio scrubbing and playback."""
    __tablename__ = "transcript_segments"

    id = Column(Integer, primary_key=True, index=True)
    transcript_id = Column(Integer, ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False, index=True)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    speaker = Column(String(100), nullable=True)

    transcript = relationship("Transcript", back_populates="segments")

class DocumentRecord(Base):
    """Parsed document information (PDF, DOCX, XLSX, TXT, CSV)."""
    __tablename__ = "document_records"

    id = Column(Integer, primary_key=True, index=True)
    media_asset_id = Column(Integer, ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String(255), nullable=True)
    doc_type = Column(String(20), nullable=False)  # pdf, docx, xlsx, txt, csv
    page_count = Column(Integer, default=1)
    extracted_text = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    media_asset = relationship("MediaAsset", back_populates="document_record")

class Task(Base):
    """Extracted action item or task."""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), default="inbox", index=True)  # inbox, open, waiting, completed, dismissed
    priority = Column(String(20), default="medium")  # low, medium, high
    confidence = Column(Float, default=0.8)
    created_date = Column(DateTime, default=datetime.utcnow)
    due_date = Column(DateTime, nullable=True)
    assigned_contact_name = Column(String(255), nullable=True)
    related_project_name = Column(String(255), nullable=True)
    source_excerpt = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="tasks")
    message = relationship("Message", back_populates="tasks")

class WaitingFor(Base):
    """Tracking pending deliverables or replies."""
    __tablename__ = "waiting_for"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True)
    person_name = Column(String(255), nullable=False, index=True)
    deliverable = Column(Text, nullable=False)
    status = Column(String(20), default="open", index=True)  # open, resolved, overdue, dismissed
    due_date = Column(DateTime, nullable=True)
    source_excerpt = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="waiting_items")
    message = relationship("Message", back_populates="waiting_items")

class Decision(Base):
    """Recorded agreement or decision."""
    __tablename__ = "decisions"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True)
    decision_text = Column(Text, nullable=False)
    confidence = Column(Float, default=0.85)
    participants = Column(String(255), nullable=True)
    timestamp = Column(DateTime, nullable=True)
    source_excerpt = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="decisions")
    message = relationship("Message", back_populates="decisions")

class Idea(Base):
    """Extracted concept or idea."""
    __tablename__ = "ideas"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    source_excerpt = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="ideas")

class Commitment(Base):
    """Pledge made by a participant."""
    __tablename__ = "commitments"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True)
    person_name = Column(String(255), nullable=False)
    commitment_text = Column(Text, nullable=False)
    expected_date = Column(DateTime, nullable=True)
    source_excerpt = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="commitments")
    message = relationship("Message", back_populates="commitments")

class Property(Base):
    """Stone Mode: Real estate domain record."""
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    property_type = Column(String(50), nullable=True)  # office, apartment, villa, commercial
    area_sqm = Column(Float, nullable=True)
    location = Column(String(255), nullable=True)
    district = Column(String(255), nullable=True)
    price = Column(Float, nullable=True)
    currency = Column(String(10), default="EGP")
    deal_type = Column(String(20), default="sale")  # sale, rent
    finishing = Column(String(50), nullable=True)  # core & shell, semi-finished, ultra-lux
    is_furnished = Column(Boolean, default=False)
    has_admin_license = Column(Boolean, default=False)
    rooms = Column(Integer, nullable=True)
    bathrooms = Column(Integer, nullable=True)
    parking = Column(String(100), nullable=True)
    features_json = Column(JSON, nullable=True)
    listing_draft = Column(Text, nullable=True)
    source_evidence = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="properties")

class ResearchItem(Base):
    """Research Mode: Academic / investigation item."""
    __tablename__ = "research_items"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    topic = Column(String(255), nullable=False)
    question = Column(Text, nullable=True)
    author = Column(String(255), nullable=True)
    citation = Column(Text, nullable=True)
    method = Column(Text, nullable=True)
    finding = Column(Text, nullable=True)
    idea = Column(Text, nullable=True)
    follow_up = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="research_items")

class Relationship(Base):
    """Knowledge graph edge connecting entities."""
    __tablename__ = "relationships"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(50), nullable=False, index=True)  # participant, message, property, task, etc.
    source_id = Column(Integer, nullable=False, index=True)
    relation_type = Column(String(50), nullable=False, index=True)  # sent, refers_to, creates, assigned_to, price_of
    target_type = Column(String(50), nullable=False, index=True)
    target_id = Column(Integer, nullable=False, index=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Tag(Base):
    """Tag entity for categorizing messages or conversations."""
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    color = Column(String(20), default="#4F46E5")
