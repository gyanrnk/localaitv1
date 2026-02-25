"""
Gupshup Handler - Manages Gupshup WhatsApp API integration
Receives and processes WhatsApp messages from Gupshup
"""
import requests
import json
from typing import Optional, Dict, Any
import os

from config import GUPSHUP_API_KEY, GUPSHUP_APP_NAME


class GupshupHandler:
    """Handle Gupshup WhatsApp API"""
    
    def __init__(self):
        self.api_key = GUPSHUP_API_KEY
        self.app_name = GUPSHUP_APP_NAME
        self.base_url = "https://api.gupshup.io/sm/api/v1"

    def parse_webhook_message(self, webhook_data: dict) -> Dict[str, Any]:
        """
        Parse incoming Gupshup webhook message
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
            outer_payload = webhook_data.get('payload', {})
            
            sender_info = outer_payload.get('sender', {})
            result['sender'] = (
                sender_info.get('phone')
                or outer_payload.get('source')
                or webhook_data.get('sender', {}).get('phone')
                or outer_payload.get('mobile')
                or ''
            )
            result['message_id'] = outer_payload.get('id', '')
            result['timestamp'] = webhook_data.get('timestamp', '')
            
            inner_payload = outer_payload.get('payload', {})
            message_type = outer_payload.get('type', '')
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
                result['media_url'] = inner_payload.get('url', '')
                result['text'] = inner_payload.get('caption', '')
            
            elif message_type == 'video':
                result['media_type'] = 'video'
                result['media_url'] = inner_payload.get('url', '')
                result['text'] = inner_payload.get('caption', '')
            
            elif message_type == 'audio':
                result['media_type'] = 'audio'
                result['media_url'] = inner_payload.get('url', '')
        
        except Exception as e:
            print(f"Error parsing webhook: {e}")
        
        return result
    
    def download_media(self, media_url: str, save_path: str) -> bool:
        """
        Download media file from Gupshup
        
        Args:
            media_url: URL of the media file
            save_path: Where to save the file
            
        Returns:
            True if successful
        """
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
        """
        Send text message via Gupshup
        
        Args:
            phone_number: Recipient phone number
            message: Message text
            
        Returns:
            True if successful
        """
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
