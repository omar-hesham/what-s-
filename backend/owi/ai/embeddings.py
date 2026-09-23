"""
Local vector embedding and semantic search engine.
Provides 100% offline embedding and cosine similarity ranking.
Works without requiring external cloud vector databases or mandatory GPU.
"""

import math
import re
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from owi.core.logging import logger
from owi.db.models import Message

class LocalEmbeddingEngine:
    """
    Local embedding engine supporting both dense transformer embeddings
    and offline semantic n-gram vectorizer with cosine similarity.
    """

    _transformer_model = None

    @classmethod
    def get_transformer(cls):
        """Lazy-load sentence-transformers if installed."""
        if cls._transformer_model is not None:
            return cls._transformer_model
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading local sentence-transformers model...")
            cls._transformer_model = SentenceTransformer("all-MiniLM-L6-v2")
            return cls._transformer_model
        except Exception:
            return None

    @classmethod
    def compute_embedding(cls, text_input: str) -> List[float]:
        """Compute normalized vector representation for text."""
        model = cls.get_transformer()
        if model is not None:
            try:
                emb = model.encode(text_input, normalize_embeddings=True)
                return emb.tolist()
            except Exception as e:
                logger.warning(f"Transformer encode failed: {e}")

        # Fallback: High-precision semantic hashing vectorizer (384-dim)
        # Supports Arabic and English tokenization, n-grams, and subwords
        dim = 384
        vec = [0.0] * dim
        tokens = re.findall(r'[\w\u0600-\u06FF]+', text_input.lower())
        if not tokens:
            return vec

        for t in tokens:
            # Word hash
            h = hash(t) % dim
            vec[h] += 1.0
            # Character trigrams for morphological robustness
            if len(t) >= 3:
                for i in range(len(t) - 2):
                    sub_h = hash(t[i:i+3]) % dim
                    vec[sub_h] += 0.5

        # L2 Normalize
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    @staticmethod
    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        """Compute cosine similarity between two normalized vectors."""
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        return sum(a * b for a, b in zip(v1, v2))

    @classmethod
    def search_semantic(
        cls, 
        query: str, 
        db: Session, 
        limit: int = 10,
        conversation_id: Optional[int] = None,
        max_scan: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Rank messages by semantic vector similarity to query.
        """
        query_vec = cls.compute_embedding(query)
        
        q = db.query(Message)
        if conversation_id:
            q = q.filter(Message.conversation_id == conversation_id)
        q = q.order_by(Message.timestamp.desc())
        if max_scan:
            q = q.limit(max_scan)
        messages = q.all()

        results = []
        for msg in messages:
            msg_vec = cls.compute_embedding(msg.content)
            score = cls.cosine_similarity(query_vec, msg_vec)
            if score > 0.05:
                results.append({
                    "message_id": msg.id,
                    "conversation_id": msg.conversation_id,
                    "sender_name": msg.sender_name,
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else "",
                    "content": msg.content,
                    "message_type": msg.message_type,
                    "similarity": round(score, 3)
                })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]
