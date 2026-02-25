"""
Message Queue Manager - Handles pending messages with text/audio-media matching
Text/Audio waits for media (image/video/audio), media waits for text/audio.
Both sides queue and pair up within timeout.
"""
import time
from collections import defaultdict
from typing import Optional, Dict
import threading


class MessageQueue:
    """Queue system to match text/audio with media for each user"""
    
    def __init__(self, text_wait_timeout=30):
        """
        Args:
            text_wait_timeout: Seconds each side waits for the other (default: 30)
        """
        self.pending_media = defaultdict(list)
        self.pending_text = defaultdict(list)
        self.pending_audio = defaultdict(list)  # NEW: for user-provided audio
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

    def add_message(self, sender: str, message_type: str, data: dict, message_id: str = None) -> Optional[Dict]:
        with self.lock:
            current_time = time.time()
            if not isinstance(data, dict):
                data = {}
            data['timestamp'] = current_time
            data['sender'] = sender

            if message_id:
                dedup_key = f"{sender}:id:{message_id}"
            else:
                dedup_key = f"{sender}:{self._get_message_hash(message_type, data)}"

            if dedup_key in self.processed_messages:
                if current_time - self.processed_messages[dedup_key] < 3600:
                    print(f"⭕ Duplicate skipped for {sender} [{message_type}]")
                    return {'duplicate': True, 'sender': sender}

            self.processed_messages[dedup_key] = current_time

            # Media arriving (image/video)
            if message_type in ['image', 'video']:
                # Check for waiting user-audio first
                if self.pending_audio[sender]:
                    audio_data = self.pending_audio[sender].pop(0)
                    text_data = None
                    if self.pending_text[sender]:
                        text_data = self.pending_text[sender].pop(0)
                    
                    print(f"✅ Media arrived, paired with waiting user-audio for {sender}")
                    return {
                        'text': text_data.get('text') if text_data else None,
                        'media': data,
                        'user_audio': audio_data,
                        'sender': sender
                    }
                # Check for waiting text
                elif self.pending_text[sender]:
                    text_data = self.pending_text[sender].pop(0)
                    print(f"✅ Media arrived, paired with waiting text for {sender}")
                    return {
                        'text': text_data.get('text'),
                        'media': data,
                        'user_audio': None,
                        'sender': sender
                    }
                else:
                    self.pending_media[sender].append(data)
                    print(f"⏳ Media queued, waiting for text/audio from {sender}")
                    return None

            # User-provided audio arriving
            elif message_type == 'user_audio':
                if self.pending_media[sender]:
                    media_data = self.pending_media[sender].pop(0)
                    text_data = None
                    if self.pending_text[sender]:
                        text_data = self.pending_text[sender].pop(0)
                    
                    print(f"✅ User-audio arrived, paired with waiting media for {sender}")
                    return {
                        'text': text_data.get('text') if text_data else None,
                        'media': media_data,
                        'user_audio': data,
                        'sender': sender
                    }
                else:
                    self.pending_audio[sender].append(data)
                    print(f"⏳ User-audio queued, waiting for media from {sender}")
                    return None

            # Text arriving
            elif message_type == 'text':
                if self.pending_media[sender]:
                    media_data = self.pending_media[sender].pop(0)
                    audio_data = None
                    if self.pending_audio[sender]:
                        audio_data = self.pending_audio[sender].pop(0)
                    
                    print(f"✅ Text arrived, paired with waiting media for {sender}")
                    return {
                        'text': data.get('text'),
                        'media': media_data,
                        'user_audio': audio_data,
                        'sender': sender
                    }
                else:
                    self.pending_text[sender].append(data)
                    print(f"⏳ Text queued, waiting for media from {sender}")
                    return None

            return None

    def get_expired_media(self) -> list:
        """
        Returns media that waited longer than timeout.
        Video without text/audio allowed (extract audio from video).
        Image without text/audio is discarded.
        """
        with self.lock:
            expired = []
            current_time = time.time()

            for sender, messages in list(self.pending_media.items()):
                for msg in messages[:]:
                    if current_time - msg['timestamp'] > self.text_wait_timeout:
                        media_type = msg.get('type', 'image')
                        has_content = msg.get('text') or self.pending_audio[sender]
                        
                        # Allow video even without text/audio (will extract from video)
                        # Skip image-only
                        if media_type == 'video' or has_content:
                            audio_data = self.pending_audio[sender].pop(0) if self.pending_audio[sender] else None
                            expired.append({
                                'sender': sender,
                                'media': msg,
                                'user_audio': audio_data
                            })
                        else:
                            print(f"⏭️ Skipping image-only (no text/audio) for {sender}")
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
                        print(f"⏰ Text timeout for {sender}, processing as text-only")
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

    def get_queue_status(self) -> dict:
        with self.lock:
            return {
                'pending_media_count': sum(len(msgs) for msgs in self.pending_media.values()),
                'pending_text_count': sum(len(msgs) for msgs in self.pending_text.values()),
                'pending_audio_count': sum(len(msgs) for msgs in self.pending_audio.values()),
                'users_with_pending': len(self.pending_media) + len(self.pending_text) + len(self.pending_audio)
            }