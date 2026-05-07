"""
Gupshup Handler - Manages Gupshup WhatsApp API
Supports both Gupshup and Meta webhook formats
"""
import requests
import json
from typing import Optional, Dict, Any
import os

from config import GUPSHUP_API_KEY, GUPSHUP_APP_NAME


class GupshupHandler:
    """Handle Gupshup WhatsApp API - supports both Gupshup and Meta payloads"""
    
    def __init__(self):
        self.api_key = GUPSHUP_API_KEY
        self.app_name = GUPSHUP_APP_NAME
        self.base_url = "https://api.gupshup.io/sm/api/v1"

    def parse_webhook_message(self, webhook_data: dict) -> Dict[str, Any]:
        """
        Parse incoming webhook — supports two formats:
          1. Meta WhatsApp Business API  (entry → changes → value → messages)
          2. Gupshup format              (payload → payload)
        """
        result = {
            'text': None,
            'media_url': None,
            'media_type': None,
            'sender': None,
            'message_id': None,
            'timestamp': None
        }

        try:
            # ── Meta WhatsApp Business API format ───────────────────────────
            if 'entry' in webhook_data:
                entry   = webhook_data['entry'][0]
                changes = entry.get('changes', [{}])[0]
                value   = changes.get('value', {})
                msgs    = value.get('messages', [])

                if not msgs:
                    return result

                msg    = msgs[0]
                result['sender']     = msg.get('from', '')
                result['message_id'] = msg.get('id', '')
                result['timestamp']  = msg.get('timestamp', '')
                msg_type             = msg.get('type', 'text')

                if msg_type == 'text':
                    result['text'] = msg.get('text', {}).get('body', '')
                    print(f"   TEXT: {result['text'][:100]}")

                elif msg_type == 'image':
                    result['media_type'] = 'image'
                    img = msg.get('image', {})
                    result['media_url'] = img.get('url') or img.get('id', '')
                    result['text']      = img.get('caption', '')
                    print(f"   IMAGE: url={result['media_url'][:80]}")

                elif msg_type == 'video':
                    result['media_type'] = 'video'
                    vid = msg.get('video', {})
                    result['media_url'] = vid.get('url') or vid.get('id', '')
                    result['text']      = vid.get('caption', '')
                    print(f"   VIDEO: url={result['media_url'][:80]}")

                elif msg_type == 'audio':
                    result['media_type'] = 'audio'
                    aud = msg.get('audio', {})
                    result['media_url'] = aud.get('url') or aud.get('id', '')

                elif msg_type == 'document':
                    result['media_type'] = 'document'
                    doc = msg.get('document', {})
                    result['media_url'] = doc.get('url') or doc.get('id', '')
                    result['text']      = doc.get('caption', '')

                return result

            # ── Gupshup format ───────────────────────────────────────────────
            outer_payload = webhook_data.get('payload', {})

            sender_info = outer_payload.get('sender', {})
            result['sender'] = (
                sender_info.get('phone')
                or outer_payload.get('source')
                or webhook_data.get('sender', {}).get('phone')
                or outer_payload.get('mobile')
                or ''
            )
            # Sender ka display name extract karo (Gupshup payload mein 'name' field hota hai)
            result['sender_name'] = (
                sender_info.get('name', '')
                or webhook_data.get('sender', {}).get('name', '')
                or ''
            )
            print(f"  [GUPSHUP] sender={result['sender']} | sender_name='{result['sender_name']}'" )
            result['message_id'] = outer_payload.get('id', '')
            result['timestamp']  = webhook_data.get('timestamp', '')

            inner_payload = outer_payload.get('payload', {})
            message_type  = outer_payload.get('type', '')
            if not message_type:
                content_type = inner_payload.get('contentType', '')
                if 'image' in content_type:
                    message_type = 'image'
                elif 'video' in content_type:
                    message_type = 'video'
                elif 'audio' in content_type:
                    message_type = 'audio'
                else:
                    message_type = 'text'

            if message_type == 'text':
                result['text'] = inner_payload.get('text', '')
            elif message_type == 'image':
                result['media_type'] = 'image'
                result['media_url']  = inner_payload.get('url', '')
                result['text']       = inner_payload.get('caption', '')
            elif message_type == 'video':
                result['media_type'] = 'video'
                result['media_url']  = inner_payload.get('url', '')
                result['text']       = inner_payload.get('caption', '')
            elif message_type == 'audio':
                result['media_type'] = 'audio'
                result['media_url']  = inner_payload.get('url', '')

        except Exception as e:
            print(f"Error parsing webhook: {e}")

        return result
    
    def download_media(self, media_url: str, save_path: str) -> bool:
        """Download media file from Gupshup or Meta"""
        try:
            response = requests.get(media_url, stream=True)
            response.raise_for_status()
            
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return True
        except Exception as e:
            print(f"Error downloading media: {e}")
            return False
    
    def send_message(self, phone_number: str, message: str) -> bool:
        """Send text message via Gupshup"""
        if not self.api_key or not self.app_name:
            print("Gupshup credentials not configured")
            return False
        
        url = f"{self.base_url}/msg"
        
        headers = {
            'apikey': self.api_key,
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'channel': 'whatsapp',
            'source': self.app_name,
            'destination': phone_number,
            'message': json.dumps({
                'type': 'text',
                'text': message
            })
        }
        
        try:
            response = requests.post(url, headers=headers, data=data)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"Error sending message: {e}")
            return False