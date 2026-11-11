import re
import io
import os
import shutil
import subprocess
import tempfile
from PIL import Image
from langdetect import detect, DetectorFactory

# Set seed for deterministic language detection
DetectorFactory.seed = 42

INDIAN_LANG_MAP = {
    'hi': 'Hindi (हिंदी)',
    'bn': 'Bengali (বাংলা)',
    'ta': 'Tamil (தமிழ்)',
    'te': 'Telugu (తెలుగు)',
    'mr': 'Marathi (मराठी)',
    'gu': 'Gujarati (ગુજરાતી)',
    'kn': 'Kannada (কন্নড)',
    'ml': 'Malayalam (മലയാളം)',
    'pa': 'Punjabi (ਪੰਜਾਬੀ)',
    'en': 'English'
}

def detect_language(text: str) -> dict:
    """Detects the primary language of the text."""
    if not text or len(text.strip()) < 5:
        return {'code': 'en', 'name': 'English', 'is_indian_lang': False}
    
    try:
        code = detect(text)
        name = INDIAN_LANG_MAP.get(code, code.upper())
        is_indian = code in ['hi', 'bn', 'ta', 'te', 'mr', 'gu', 'kn', 'ml', 'pa']
        return {
            'code': code,
            'name': name,
            'is_indian_lang': is_indian
        }
    except Exception:
        return {'code': 'en', 'name': 'English', 'is_indian_lang': False}

def extract_urls(text: str) -> list[str]:
    """Extracts all URLs present in the input string."""
    url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
    return re.findall(url_pattern, text)

def clean_text(text: str) -> str:
    """Cleans text for claim processing while retaining essential semantic structure."""
    if not text:
        return ""
    # Normalize multiple whitespace
    cleaned = re.sub(r'\s+', ' ', text).strip()
    return cleaned

def extract_text_from_image(image_bytes: bytes) -> dict:
    """
    Extracts text from an image payload (poster/screenshot forward).
    Integrates Pillow for inspection and OCR engine.
    """
    try:
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size
        
        try:
            import pytesseract
            tesseract_cmd = os.getenv("TESSERACT_CMD")
            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            elif not shutil.which("tesseract"):
                default_tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
                if os.path.isfile(default_tesseract_path):
                    pytesseract.pytesseract.tesseract_cmd = default_tesseract_path
            ocr_text = pytesseract.image_to_string(image)
        except ImportError:
            return {
                "success": False,
                "extracted_text": "",
                "image_dimensions": f"{width}x{height}",
                "format": image.format or "JPEG",
                "error": "Image OCR is unavailable. Install Tesseract OCR and the pytesseract package."
            }
        except pytesseract.pytesseract.TesseractNotFoundError:
            return {
                "success": False,
                "extracted_text": "",
                "image_dimensions": f"{width}x{height}",
                "format": image.format or "JPEG",
                "error": (
                    "Tesseract OCR was not found. Install Tesseract, then add it to PATH "
                    "or set TESSERACT_CMD to the full path of tesseract.exe "
                    "(commonly C:\\Program Files\\Tesseract-OCR\\tesseract.exe), and restart the app."
                )
            }
        except Exception as exc:
            return {
                "success": False,
                "extracted_text": "",
                "image_dimensions": f"{width}x{height}",
                "format": image.format or "JPEG",
                "error": f"Image OCR failed: {exc}"
            }

        if not ocr_text.strip():
            return {
                "success": False,
                "extracted_text": "",
                "image_dimensions": f"{width}x{height}",
                "format": image.format or "JPEG",
                "error": "No readable text was found in the image."
            }
        
        return {
            "success": True,
            "extracted_text": ocr_text.strip(),
            "image_dimensions": f"{width}x{height}",
            "format": image.format or "JPEG"
        }
    except Exception as e:
        return {
            "success": False,
            "extracted_text": "",
            "error": str(e)
        }


def extract_text_from_video(video_bytes: bytes, max_frames: int = 8) -> dict:
    """Extracts visible text from sampled video frames using FFmpeg and image OCR."""
    ffmpeg = shutil.which(os.getenv("FFMPEG_PATH") or "ffmpeg")
    if not ffmpeg:
        return {
            "success": False,
            "extracted_text": "",
            "error": "Video frame extraction is unavailable. Install FFmpeg and add it to PATH."
        }

    try:
        with tempfile.TemporaryDirectory(prefix="factshield-video-") as temp_dir:
            video_path = os.path.join(temp_dir, "upload.mp4")
            output_pattern = os.path.join(temp_dir, "frame-%02d.jpg")
            with open(video_path, "wb") as video_file:
                video_file.write(video_bytes)

            completed = subprocess.run(
                [
                    ffmpeg, "-nostdin", "-v", "error", "-t", "120",
                    "-i", video_path,
                    "-vf", "fps=1/10,scale=1280:-1:force_original_aspect_ratio=decrease",
                    "-frames:v", str(max_frames), "-q:v", "4", "-y", output_pattern
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False
            )
            if completed.returncode != 0:
                return {
                    "success": False,
                    "extracted_text": "",
                    "error": f"Could not read the video: {completed.stderr.strip() or 'FFmpeg failed.'}"
                }

            frame_paths = sorted(
                os.path.join(temp_dir, name)
                for name in os.listdir(temp_dir)
                if name.startswith("frame-") and name.endswith(".jpg")
            )
            extracted_frames = []
            for frame_path in frame_paths:
                with open(frame_path, "rb") as frame_file:
                    extracted_frames.append(extract_text_from_image(frame_file.read()))
            text = "\n".join(
                frame["extracted_text"]
                for frame in extracted_frames
                if frame.get("success") and frame.get("extracted_text")
            )
            if not text:
                return {
                    "success": False,
                    "extracted_text": "",
                    "frames_analyzed": len(frame_paths),
                    "error": "No readable on-screen text was found. Speech in the video is not transcribed."
                }

            return {
                "success": True,
                "extracted_text": text,
                "frames_analyzed": len(frame_paths),
                "error": None
            }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "extracted_text": "",
            "error": "Video frame extraction timed out."
        }
    except OSError as exc:
        return {
            "success": False,
            "extracted_text": "",
            "error": f"Video frame extraction failed: {exc}"
        }
