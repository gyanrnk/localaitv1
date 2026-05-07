"""
File Manager - Handles all file storage with proper naming conventions
Manages inputs and outputs folder structure
"""
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
import threading 
from config import (
    BASE_INPUT_DIR, BASE_OUTPUT_DIR,
    INPUT_IMAGE_DIR, INPUT_VIDEO_DIR, INPUT_AUDIO_DIR,
    OUTPUT_SCRIPT_DIR, OUTPUT_HEADLINE_DIR, OUTPUT_AUDIO_DIR,
    PREFIX_IMAGE, PREFIX_VIDEO, PREFIX_AUDIO,
    PREFIX_SCRIPT, PREFIX_HEADLINE, PREFIX_OUTPUT_AUDIO,
    SUPPORTED_IMAGE_FORMATS, SUPPORTED_VIDEO_FORMATS, SUPPORTED_AUDIO_FORMATS
)

def _get_audio_duration(path: str) -> float:
    """Return audio duration in seconds using ffprobe. Returns 0.0 on failure."""
    try:
        import subprocess, json
        result = subprocess.run(
            [
                'ffprobe', '-v', 'quiet',
                '-print_format', 'json',
                '-show_streams', path
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10
        )
        info = json.loads(result.stdout)
        for stream in info.get('streams', []):
            if stream.get('codec_type') == 'audio':
                return float(stream.get('duration', 0.0))
    except Exception:
        pass
    return 0.0

class FileManager:
    """Manage file storage with proper naming conventions"""
    
    def __init__(self):
        self._lock = threading.Lock()  # ← add as first line
        self._ensure_directories()
        self.counters = self._load_counters()
    
    def _ensure_directories(self):
        """Create all required directories if they don't exist"""
        directories = [
            BASE_INPUT_DIR, BASE_OUTPUT_DIR,
            INPUT_IMAGE_DIR, INPUT_VIDEO_DIR, INPUT_AUDIO_DIR,
            OUTPUT_SCRIPT_DIR, OUTPUT_HEADLINE_DIR, OUTPUT_AUDIO_DIR
        ]
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
    
    def _wrap_headline(text: str, max_chars: int = 20) -> str:
        words = text.split()
        lines, current = [], ""
        for word in words:
            if len(current) + len(word) + 1 <= max_chars:
                current = (current + " " + word).strip()
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)

        # ← Agar 3 se zyada lines hain to last line mein merge karo, words drop mat karo
        if len(lines) > 3:
            lines = lines[:2] + [" ".join(lines[2:])]

        return "\n".join(lines)
    
    def _load_counters(self) -> dict:
        """Load existing file counters by finding the highest-numbered file in each dir"""
        counters = {'image': 0, 'video': 0, 'audio': 0}

        def _max_counter(directory: str, prefix: str) -> int:
            max_n = 0
            for fname in os.listdir(directory):
                if fname.startswith(prefix):
                    stem = Path(fname).stem
                    num_str = stem[len(prefix):]
                    try:
                        n = int(num_str)
                        if n > max_n:
                            max_n = n
                    except ValueError:
                        pass
            return max_n

        counters['image'] = _max_counter(INPUT_IMAGE_DIR, PREFIX_IMAGE)
        counters['video'] = _max_counter(INPUT_VIDEO_DIR, PREFIX_VIDEO)
        counters['audio'] = _max_counter(INPUT_AUDIO_DIR, PREFIX_AUDIO)
        return counters
    
    def _get_file_type(self, file_path: str) -> Optional[str]:
        """Determine file type from extension"""
        ext = Path(file_path).suffix.lower()
        if ext in SUPPORTED_IMAGE_FORMATS:
            return 'image'
        elif ext in SUPPORTED_VIDEO_FORMATS:
            return 'video'
        elif ext in SUPPORTED_AUDIO_FORMATS:
            return 'audio'
        return None
    
    def save_input_media(self, file_path: str) -> Optional[dict]:
        """Save single input media file"""
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            return None
        
        file_type = self._get_file_type(file_path)
        if not file_type:
            print(f"Unsupported file type: {file_path}")
            return None

        with self._lock:
            self.counters[file_type] += 1
            counter = self.counters[file_type]

        ext = Path(file_path).suffix.lower()
        prefix_map = {
            'image': (PREFIX_IMAGE, INPUT_IMAGE_DIR),
            'video': (PREFIX_VIDEO, INPUT_VIDEO_DIR),
            'audio': (PREFIX_AUDIO, INPUT_AUDIO_DIR)
        }
        prefix, target_dir = prefix_map[file_type]
        new_filename = f"{prefix}{counter}{ext}"
        new_path = os.path.join(target_dir, new_filename)

        try:
            shutil.copy2(file_path, new_path)
            print(f"✅ Saved {file_type}: {new_filename}")
            return {
                'type': file_type,
                'input_path': new_path,
                'filename': new_filename,
                'counter': counter,
                'media_files': [new_filename]   # ← list format for consistency
            }
        except Exception as e:
            print(f"Error saving file: {e}")
            return None


    def save_input_media_list(self, file_paths: list) -> Optional[dict]:
        """
        Save multiple media files (max 3) for a single news item.
        All files must be same type (all images OR all videos).
        Files saved as: vi4_1.mp4, vi4_2.mp4, vi4_3.mp4

        Returns dict with:
            type, counter, media_files (list of filenames), input_paths (list)
        """
        if not file_paths:
            return None

        file_paths = file_paths[:3]  # max 3

        # Validate all same type
        types = [self._get_file_type(p) for p in file_paths if os.path.exists(p)]
        if not types:
            print("No valid files found")
            return None
        if len(set(types)) > 1:
            print(f"Mixed media types not allowed: {set(types)}")
            return None

        file_type = types[0]
        prefix_map = {
            'image': (PREFIX_IMAGE, INPUT_IMAGE_DIR),
            'video': (PREFIX_VIDEO, INPUT_VIDEO_DIR),
            'audio': (PREFIX_AUDIO, INPUT_AUDIO_DIR)
        }
        prefix, target_dir = prefix_map[file_type]

        with self._lock:
            self.counters[file_type] += 1
            counter = self.counters[file_type]

        saved_filenames = []
        saved_paths = []

        for idx, file_path in enumerate(file_paths, start=1):
            if not os.path.exists(file_path):
                print(f"⚠️ Skipping missing file: {file_path}")
                continue
            ext = Path(file_path).suffix.lower()
            # single file → vi4.mp4, multiple → vi4_1.mp4, vi4_2.mp4
            if len(file_paths) == 1:
                new_filename = f"{prefix}{counter}{ext}"
            else:
                new_filename = f"{prefix}{counter}_{idx}{ext}"
            new_path = os.path.join(target_dir, new_filename)
            try:
                shutil.copy2(file_path, new_path)
                saved_filenames.append(new_filename)
                saved_paths.append(new_path)
                print(f"✅ Saved {file_type} [{idx}/{len(file_paths)}]: {new_filename}")
            except Exception as e:
                print(f"Error saving {file_path}: {e}")

        if not saved_filenames:
            return None

        return {
            'type': file_type,
            'counter': counter,
            'input_path': saved_paths[0],       # backward compat
            'filename': saved_filenames[0],      # backward compat
            'media_files': saved_filenames,      # ← new: full list
            'input_paths': saved_paths,          # ← new: full list
        }
    
    def save_outputs(self, script: str, headline: str, media_counter: int,
                     media_type: str, audio_data_or_path: Optional[str] = None,
                     headline_audio_data_or_path: Optional[str] = None) -> dict:
        """
        Save script, headline text, headline audio, and script audio.

        Storage layout:
            outputs/scripts/    si1.txt
            outputs/headlines/  hi1.txt  +  hi1.mp3  (headline audio lives here)
            outputs/audios/     oai1.mp3              (script audio)

        Args:
            script: Generated news script
            headline: Generated headline text
            media_counter: Counter number from input media
            media_type: Type of input media (image/video/audio)
            audio_data_or_path: Path or binary data for script audio
            headline_audio_data_or_path: Path or binary data for headline audio
        """
        type_prefix_map = {'image': 'i', 'video': 'v', 'audio': 'a'}
        type_prefix = type_prefix_map.get(media_type, 'x')

        script_filename         = f"{PREFIX_SCRIPT}{type_prefix}{media_counter}.txt"
        headline_filename       = f"{PREFIX_HEADLINE}{type_prefix}{media_counter}.txt"
        headline_audio_filename = f"{PREFIX_HEADLINE}{type_prefix}{media_counter}.mp3"  # e.g. hi1.mp3
        audio_filename          = f"{PREFIX_OUTPUT_AUDIO}{type_prefix}{media_counter}.mp3"  # e.g. oai1.mp3

        script_path         = os.path.join(OUTPUT_SCRIPT_DIR,   script_filename)
        headline_path       = os.path.join(OUTPUT_HEADLINE_DIR, headline_filename)
        headline_audio_path = os.path.join(OUTPUT_HEADLINE_DIR, headline_audio_filename)
        audio_path          = os.path.join(OUTPUT_AUDIO_DIR,    audio_filename)

        results = {
            'script_path':             None,
            'headline_path':           None,
            'headline_audio_path':     None,
            'audio_path':              None,
            'script_filename':         script_filename,
            'headline_filename':       headline_filename,
            'headline_audio_filename': headline_audio_filename,
            'audio_filename':          audio_filename,
            'script_duration':         0.0,
            'headline_duration':       0.0,
            'total_duration':          0.0,   # headline + script + transition_buffer
        }

        try:
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(script)
            results['script_path'] = script_path
            print(f"✅ Saved script: {script_filename}")
        except Exception as e:
            print(f"Error saving script: {e}")

        try:
            with open(headline_path, 'w', encoding='utf-8') as f:
                f.write(headline)
            results['headline_path'] = headline_path
            print(f"✅ Saved headline: {headline_filename}")
        except Exception as e:
            print(f"Error saving headline: {e}")

        if headline_audio_data_or_path:
            try:
                if isinstance(headline_audio_data_or_path, str) and os.path.exists(headline_audio_data_or_path):
                    shutil.copy2(headline_audio_data_or_path, headline_audio_path)
                else:
                    with open(headline_audio_path, 'wb') as f:
                        f.write(headline_audio_data_or_path)
                results['headline_audio_path'] = headline_audio_path
                results['headline_duration'] = _get_audio_duration(headline_audio_path)  # ← add this
                print(f"✅ Saved headline audio: {headline_audio_filename}")
            except Exception as e:
                print(f"Error saving headline audio: {e}")

        if audio_data_or_path:
            try:
                if isinstance(audio_data_or_path, str) and os.path.exists(audio_data_or_path):
                    shutil.copy2(audio_data_or_path, audio_path)
                else:
                    with open(audio_path, 'wb') as f:
                        f.write(audio_data_or_path)
                results['audio_path'] = audio_path
                results['script_duration'] = _get_audio_duration(audio_path)  # ← add this
                print(f"✅ Saved script audio: {audio_filename}")
            except Exception as e:
                print(f"Error saving script audio: {e}")

        # Pre-compute total_duration = headline + script + 0.5s transition buffer
        TRANSITION_BUFFER = 0.5
        results['total_duration'] = (
            results['headline_duration'] +
            results['script_duration'] +
            TRANSITION_BUFFER
        )

        return results

    def get_input_file_path(self, filename: str) -> Optional[str]:
        """Get full path for an input file"""
        for directory in [INPUT_IMAGE_DIR, INPUT_VIDEO_DIR, INPUT_AUDIO_DIR]:
            path = os.path.join(directory, filename)
            if os.path.exists(path):
                return path
        return None