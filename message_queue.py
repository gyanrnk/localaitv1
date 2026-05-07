import time
from collections import defaultdict
from typing import Optional, Dict
import threading
import logging

logger = logging.getLogger(__name__)


class MessageQueue:
    """Queue system to match text/audio with media for each user"""
    
    def __init__(self, text_wait_timeout=10):
        """
        Args:
            text_wait_timeout: Seconds each side waits for the other (default: 30)
        """
        self.pending_media = defaultdict(list)
        self.pending_text = defaultdict(list)
        self.pending_audio = defaultdict(list)
        self.text_wait_timeout = text_wait_timeout
        self.lock = threading.Lock()
        self.processed_messages = {}

    def _get_message_hash(self, message_type: str, data: dict) -> str:
        if message_type == 'text':
            return f"text:{data.get('text', '')}"
        elif message_type == 'user_audio':
            return f"user_audio:{data.get('url', '')}"
        url = data.get('url', '')
        caption = data.get('text', '')
        return f"{message_type}:{url}:{caption}"

    def add_message(self, sender: str, message_type: str, data: dict, message_id: str = None, sender_name: str = '') -> Optional[Dict]:
        with self.lock:
            current_time = time.time()
            if not isinstance(data, dict):
                data = {}
            data['timestamp'] = current_time
            data['sender'] = sender
            data['sender_name'] = sender_name  # [FIX] sender display name store karo

            if message_id:
                dedup_key = f"{sender}:id:{message_id}"
            else:
                dedup_key = f"{sender}:{self._get_message_hash(message_type, data)}"

            if dedup_key in self.processed_messages:
                if current_time - self.processed_messages[dedup_key] < 3600:
                    logger.warning(f"⭕ Duplicate skipped for {sender} [{message_type}]")
                    return {'duplicate': True, 'sender': sender}

            self.processed_messages[dedup_key] = current_time

            # Media arriving (image/video)
            if message_type in ['image', 'video']:
                logger.info(f"📸 Media arrived [{message_type}] for {sender}")
                logger.info(f"   pending_text={len(self.pending_text[sender])}, pending_audio={len(self.pending_audio[sender])}")
                
                # Check for waiting user-audio first
                if self.pending_audio[sender]:
                    audio_data = self.pending_audio[sender].pop(0)
                    text_data = None
                    if self.pending_text[sender]:
                        text_data = self.pending_text[sender].pop(0)
                    
                    logger.info(f"✅ MATCHED: Media + Audio for {sender}")
                    return {
                        'text': text_data.get('text') if text_data else None,
                        'media': data,
                        'user_audio': audio_data,
                        'sender': sender,
                        'sender_name': sender_name
                    }
                # Check for waiting text
                elif self.pending_text[sender]:
                    text_data = self.pending_text[sender].pop(0)
                    logger.info(f"✅ MATCHED: Media + Text for {sender}")
                    return {
                        'text': text_data.get('text'),
                        'media': data,
                        'user_audio': None,
                        'sender': sender,
                        'sender_name': sender_name
                    }
                else:
                    self.pending_media[sender].append(data)
                    logger.info(f"⏳ Media queued, waiting for text/audio from {sender}")
                    return None

            # User-provided audio arriving
            elif message_type == 'user_audio':
                logger.info(f"🎙️ Audio arrived for {sender}")
                logger.info(f"   pending_media={len(self.pending_media[sender])}, pending_text={len(self.pending_text[sender])}")
                
                if self.pending_media[sender]:
                    media_data = self.pending_media[sender].pop(0)
                    text_data = None
                    if self.pending_text[sender]:
                        text_data = self.pending_text[sender].pop(0)
                    
                    logger.info(f"✅ MATCHED: Audio + Media for {sender}")
                    return {
                        'text': text_data.get('text') if text_data else None,
                        'media': media_data,
                        'user_audio': data,
                        'sender': sender,
                        'sender_name': sender_name
                    }
                else:
                    self.pending_audio[sender].append(data)
                    logger.info(f"⏳ Audio queued, waiting for media from {sender}")
                    return None

            # Text arriving
            elif message_type == 'text':
                logger.info(f"📝 Text arrived for {sender}")
                logger.info(f"   pending_media={len(self.pending_media[sender])}, pending_audio={len(self.pending_audio[sender])}")
                
                if self.pending_media[sender]:
                    media_data = self.pending_media[sender].pop(0)
                    audio_data = None
                    if self.pending_audio[sender]:
                        audio_data = self.pending_audio[sender].pop(0)
                    
                    logger.info(f"✅ MATCHED: Text + Media for {sender}")
                    return {
                        'text': data.get('text'),
                        'media': media_data,
                        'user_audio': audio_data,
                        'sender': sender,
                        'sender_name': sender_name
                    }
                else:
                    self.pending_text[sender].append(data)
                    logger.info(f"⏳ Text queued, waiting for media from {sender}")
                    return None

            return None

    def get_expired_media(self) -> list:
        """
        Returns media that waited longer than timeout.
        
        NEW RULES:
        - Video WITH text/audio → ✅ Process
        - Video WITHOUT text/audio → ✅ Pass to background worker (will check voice there)
        - Image WITH text/audio → ✅ Process
        - Image WITHOUT text/audio → ❌ Skip
        """
        with self.lock:
            expired = []
            current_time = time.time()

            for sender, messages in list(self.pending_media.items()):
                for msg in messages[:]:
                    if current_time - msg['timestamp'] > self.text_wait_timeout:
                        media_type = msg.get('type', 'image')
                        has_content = msg.get('text') or self.pending_audio[sender]
                        
                        # Process if has content OR is video (voice check happens later)
                        if has_content or media_type == 'video':
                            audio_data = self.pending_audio[sender].pop(0) if self.pending_audio[sender] else None
                            
                            if has_content:
                                logger.info(f"⏰ Expired {media_type} with content → processing")
                            else:
                                logger.info(f"⏰ Expired video-only → will check for human voice")
                            
                            expired.append({
                                'sender': sender,
                                'media': msg,
                                'user_audio': audio_data
                            })
                        else:
                            # Image-only → skip
                            logger.info(f"⏭️ Skipping image-only (no text/audio) for {sender}")
                        
                        messages.remove(msg)

            return expired

    def get_expired_text(self) -> list:
        """
        Returns text messages that waited longer than timeout with no media arriving.
        These will be processed as text-only.
        """
        with self.lock:
            expired = []
            current_time = time.time()

            for sender, messages in list(self.pending_text.items()):
                for msg in messages[:]:
                    if current_time - msg['timestamp'] > self.text_wait_timeout:
                        logger.info(f"⏰ Expired text for {sender} → processing as text-only")
                        expired.append({'sender': sender, 'text_data': msg})
                        messages.remove(msg)

            return expired

    def clear_user_queue(self, sender: str):
        with self.lock:
            if sender in self.pending_media:
                del self.pending_media[sender]
            if sender in self.pending_text:
                del self.pending_text[sender]
            if sender in self.pending_audio:
                del self.pending_audio[sender]
            logger.info(f"🧹 Queue cleared for {sender}")

    def get_queue_status(self) -> dict:
        with self.lock:
            return {
                'pending_media_count': sum(len(msgs) for msgs in self.pending_media.values()),
                'pending_text_count': sum(len(msgs) for msgs in self.pending_text.values()),
                'pending_audio_count': sum(len(msgs) for msgs in self.pending_audio.values()),
                'users_with_pending': len(self.pending_media) + len(self.pending_text) + len(self.pending_audio)
            }