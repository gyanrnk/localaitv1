"""
Media Handler - Manages image and video files
Validates and processes media files for the bulletin
"""
import os
from pathlib import Path
from typing import Tuple, Optional
from PIL import Image
import base64
from io import BytesIO

from config import SUPPORTED_IMAGE_FORMATS, SUPPORTED_VIDEO_FORMATS


class MediaHandler:
    """Handle media files (images and videos)"""
    
    def __init__(self):
        self.media_path = None
        self.media_type = None  # 'image' or 'video'
    
    def validate_media(self, file_path: str) -> bool:
        """
        Validate if the file is a supported media format
        
        Args:
            file_path: Path to the media file
            
        Returns:
            bool: True if valid media file
        """
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            return False
        
        file_ext = Path(file_path).suffix.lower()
        
        if file_ext in SUPPORTED_IMAGE_FORMATS:
            self.media_type = 'image'
            self.media_path = file_path
            return True
        elif file_ext in SUPPORTED_VIDEO_FORMATS:
            self.media_type = 'video'
            self.media_path = file_path
            return True
        else:
            print(f"Unsupported file format: {file_ext}")
            return False
    
    def get_media_info(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Get media file information
        
        Returns:
            Tuple of (media_path, media_type)
        """
        return self.media_path, self.media_type
    
    def encode_image_to_base64(self, image_path: str) -> Optional[str]:
        """
        Encode image to base64 for OpenAI API
        
        Args:
            image_path: Path to image file
            
        Returns:
            Base64 encoded string or None
        """
        try:
            with Image.open(image_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                max_size = 2048
                if img.width > max_size or img.height > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                
                buffered = BytesIO()
                img.save(buffered, format="JPEG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                
                return img_str
        except Exception as e:
            print(f"Error encoding image: {e}")
            return None
    
    def prepare_image_for_analysis(self) -> Optional[dict]:
        """
        Prepare image for OpenAI Vision API
        
        Returns:
            Dictionary with image data or None
        """
        if self.media_type != 'image':
            return None
        
        base64_image = self.encode_image_to_base64(self.media_path)
        if not base64_image:
            return None
        
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{base64_image}"
            }
        }
