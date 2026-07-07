import os
import re
import shutil
import tempfile
import uuid
import requests
import uvicorn
from dotenv import load_dotenv
from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Header
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from markitdown import MarkItDown

# Load environment variables from .env
load_dotenv()

app = FastAPI(title="MarkitDown Web Converter")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# List of allowed file extensions
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".html",
    ".htm",
    ".csv",
    ".tsv",
    ".json",
    ".xml",
    ".txt",
    ".text",
    ".md",
    ".rst",
    ".png",
    ".jpg",
    ".jpeg"
}

class MultiProviderMockClient:
    def __init__(self, provider: str, api_key: str):
        self.provider = provider.lower().strip() if provider else "gemini"
        self.api_key = api_key
        self.chat = self.Chat(self.provider, api_key)

    class Chat:
        def __init__(self, provider: str, api_key: str):
            self.completions = self.Completions(provider, api_key)

        class Completions:
            def __init__(self, provider: str, api_key: str):
                self.provider = provider
                self.api_key = api_key

            def create(self, model: str, messages: list, **kwargs):
                import requests
                timeout = 60
                
                if self.provider == "gemini":
                    gemini_model = "gemini-1.5-flash"
                    if "pro" in model.lower():
                        gemini_model = "gemini-1.5-pro"
                    elif "2.0" in model.lower():
                        gemini_model = "gemini-2.0-flash-exp"

                    gemini_parts = []
                    for msg in messages:
                        content = msg.get("content")
                        if isinstance(content, str):
                            gemini_parts.append({"text": content})
                        elif isinstance(content, list):
                            for part in content:
                                if part.get("type") == "text":
                                    gemini_parts.append({"text": part.get("text", "")})
                                elif part.get("type") == "image_url":
                                    image_url_val = part.get("image_url", {}).get("url", "")
                                    if image_url_val.startswith("data:"):
                                        try:
                                            header, base64_data = image_url_val.split(",", 1)
                                            mime_type = header.split(";")[0].split(":")[1]
                                            gemini_parts.append({
                                                "inlineData": {
                                                    "mimeType": mime_type,
                                                    "data": base64_data
                                                }
                                            })
                                        except Exception:
                                            pass

                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={self.api_key}"
                    headers = {"Content-Type": "application/json"}
                    body = {"contents": [{"parts": gemini_parts}]}

                    res = requests.post(url, headers=headers, json=body, timeout=timeout)
                    if res.status_code != 200:
                        raise Exception(f"Gemini API error ({res.status_code}): {res.text}")

                    res_json = res.json()
                    try:
                        text_response = res_json["candidates"][0]["content"]["parts"][0]["text"]
                    except (KeyError, IndexError):
                        raise Exception(f"Unexpected Gemini response format: {res_json}")

                elif self.provider == "claude":
                    claude_model = "claude-3-5-sonnet-20241022"
                    if "haiku" in model.lower():
                        claude_model = "claude-3-5-haiku-20241022"

                    claude_parts = []
                    for msg in messages:
                        content = msg.get("content")
                        if isinstance(content, str):
                            claude_parts.append({"type": "text", "text": content})
                        elif isinstance(content, list):
                            for part in content:
                                if part.get("type") == "text":
                                    claude_parts.append({"type": "text", "text": part.get("text", "")})
                                elif part.get("type") == "image_url":
                                    image_url_val = part.get("image_url", {}).get("url", "")
                                    if image_url_val.startswith("data:"):
                                        try:
                                            header, base64_data = image_url_val.split(",", 1)
                                            mime_type = header.split(";")[0].split(":")[1]
                                            claude_parts.append({
                                                "type": "image",
                                                "source": {
                                                    "type": "base64",
                                                    "media_type": mime_type,
                                                    "data": base64_data
                                                }
                                            })
                                        except Exception:
                                            pass

                    url = "https://api.anthropic.com/v1/messages"
                    headers = {
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    }
                    body = {
                        "model": claude_model,
                        "max_tokens": 2048,
                        "messages": [{"role": "user", "content": claude_parts}]
                    }

                    res = requests.post(url, headers=headers, json=body, timeout=timeout)
                    if res.status_code != 200:
                        raise Exception(f"Claude API error ({res.status_code}): {res.text}")

                    res_json = res.json()
                    try:
                        text_response = res_json["content"][0]["text"]
                    except (KeyError, IndexError):
                        raise Exception(f"Unexpected Claude response format: {res_json}")

                else:
                    openai_model = "gpt-4o-mini"
                    if "gpt-4o" in model.lower() and "mini" not in model.lower():
                        openai_model = "gpt-4o"

                    url = "https://api.openai.com/v1/chat/completions"
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}"
                    }
                    body = {
                        "model": openai_model,
                        "messages": messages
                    }

                    res = requests.post(url, headers=headers, json=body, timeout=timeout)
                    if res.status_code != 200:
                        raise Exception(f"OpenAI API error ({res.status_code}): {res.text}")

                    res_json = res.json()
                    try:
                        text_response = res_json["choices"][0]["message"]["content"]
                    except (KeyError, IndexError):
                        raise Exception(f"Unexpected OpenAI response format: {res_json}")

                class MockMessage:
                    def __init__(self, content):
                        self.content = content
                class MockChoice:
                    def __init__(self, content):
                        self.message = MockMessage(content)
                class MockResponse:
                    def __init__(self, content):
                        self.choices = [MockChoice(content)]
                return MockResponse(text_response)

def sanitize_markdown(md_text: str) -> str:
    if not md_text:
        return md_text
        
    # 1. Strip out inline base64/data URI images and replace with a clean text tag.
    # This prevents massive token waste on binary image characters!
    md_text = re.sub(
        r'!\[(.*?)\]\(data:image/[^)]+\)',
        r'[Embedded Image: \1]',
        md_text
    )
    
    # Strip raw HTML img tags with data URIs
    md_text = re.sub(
        r'<img[^>]*src=["\']data:image/[^"\']+["\'][^>]*>',
        r'[Embedded Image]',
        md_text
    )
    
    # 2. Fix mixed list bullet/numbering hierarchy (e.g. "* 1. **TEXT**" -> "1. **TEXT**")
    md_text = re.sub(
        r'^(\s*)[*\-]\s+(\d+\.)',
        r'\1\2',
        md_text,
        flags=re.MULTILINE
    )
    
    # 3. Convert standalone bold chapters to proper H1 headings
    md_text = re.sub(
        r'^(\s*)\*\*(CHAPTER \d+)\*\*$',
        r'\1# \2',
        md_text,
        flags=re.MULTILINE | re.IGNORECASE
    )
    
    # 4. Convert standalone bold lines (without punctuation, between 3 to 60 chars) to H2 headings
    md_text = re.sub(
        r'^(\s*)\*\*([a-zA-Z0-9\s:._\-]{3,60})\*\*$',
        r'\1## \2',
        md_text,
        flags=re.MULTILINE
    )
    
    # 5. Compress multiple consecutive blank lines to at most 1 blank line (replaces 3+ newlines with 2 newlines)
    # This keeps the markdown extremely compact for LLMs
    md_text = re.sub(r'\n{3,}', '\n\n', md_text)
    
    return md_text

def format_to_internship_template(text: str) -> str:
    if not text:
        return text

    # Regex to detect entry start (date optionally preceded by Date: label or separator lines)
    # The date string itself is in capture group 1.
    entry_start_regex = re.compile(
        r'(?:^|\n)(?:[\s#\-*=_]*\n)?'      # optional separator lines and spaces
        r'(?:[\s#\-*]*\bDate\b[\s:*-]*)?' # optional "Date:" prefix
        r'\b('
        r'\d{1,2}/\d{1,2}/\d{2,4}|'
        r'\d{1,2}-\d{1,2}-\d{2,4}|'
        r'\d{4}-\d{1,2}-\d{1,2}|'
        r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}'
        r')\b',
        re.IGNORECASE
    )
    
    matches = list(entry_start_regex.finditer(text))
    
    chunks = []
    if not matches:
        chunks.append({
            "date": "02/02/2026",  # Default fallback date
            "content": text
        })
    else:
        # Split the text by entry start positions
        for i in range(len(matches)):
            date_str = matches[i].group(1)
            chunk_start = matches[i].end()
            chunk_end = matches[i+1].start() if i + 1 < len(matches) else len(text)
            chunk_content = text[chunk_start:chunk_end]
            chunks.append({
                "date": date_str,
                "content": chunk_content
            })
            
    formatted_entries = []
    
    for chunk in chunks:
        date_val = chunk["date"]
        content = chunk["content"]
        
        # Normalize date to DD/MM/YYYY if possible
        normalized_date = date_val
        try:
            if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', date_val):
                parts = date_val.split('-')
                normalized_date = f"{int(parts[2]):02d}/{int(parts[1]):02d}/{parts[0]}"
            elif re.match(r'^\d{1,2}-\d{1,2}-\d{4}$', date_val):
                parts = date_val.split('-')
                normalized_date = f"{int(parts[0]):02d}/{int(parts[1]):02d}/{parts[2]}"
            elif re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}$', date_val):
                parts = date_val.split('/')
                year = parts[2]
                if len(year) == 2:
                    year = "20" + year
                normalized_date = f"{int(parts[0]):02d}/{int(parts[1]):02d}/{year}"
            else:
                # e.g., Feb 4, 2026
                date_parts = re.split(r'[\s,]+', date_val)
                if len(date_parts) >= 3:
                    month_name = date_parts[0][:3].lower()
                    months_map = {
                        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
                        "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"
                    }
                    mm = months_map.get(month_name, "02")
                    dd = f"{int(date_parts[1]):02d}"
                    yyyy = date_parts[2]
                    normalized_date = f"{dd}/{mm}/{yyyy}"
        except Exception:
            pass
            
        # Extract Hours
        hours_val = "6"
        hours_patterns = [
            r'(?:No\.\s+of\s+)?Hours?:\s*(\d+(?:\.\d+)?)',
            r'Duration:\s*(\d+(?:\.\d+)?)',
            r'\b(\d+(?:\.\d+)?)\s*hours?\b'
        ]
        for hp in hours_patterns:
            hours_match = re.search(hp, content, re.IGNORECASE)
            if hours_match:
                hours_val = hours_match.group(1)
                if hours_val.endswith('.0'):
                    hours_val = hours_val[:-2]
                break
                
        # Clean content (remove hours markers; date is already removed by starting at matches[i].end())
        cleaned_content = content
        for hp in hours_patterns:
            cleaned_content = re.sub(hp, '', cleaned_content, flags=re.IGNORECASE)
            
        work_desc = ""
        learn_outcomes = ""
        
        # Keywords for sections
        desc_keywords = [
            r'Work\s+Description:', r'WorkDescription:', r'Description:', 
            r'Work\s+Done:', r'Activities:', r'Tasks?:', r'Work:'
        ]
        learn_keywords = [
            r'Learning\s+Outcomes?:', r'LearningOutcomes?:', r'Learning:', 
            r'Outcomes?:', r'What\s+I\s+learned:', r'Learnt:', r'Key\s+Takeaways?:'
        ]
        
        desc_pos = -1
        desc_len = 0
        for kw in desc_keywords:
            m = re.search(kw, cleaned_content, re.IGNORECASE)
            if m:
                desc_pos = m.start()
                desc_len = m.end() - m.start()
                break
                
        learn_pos = -1
        learn_len = 0
        for kw in learn_keywords:
            m = re.search(kw, cleaned_content, re.IGNORECASE)
            if m:
                learn_pos = m.start()
                learn_len = m.end() - m.start()
                break
                
        if desc_pos != -1 and learn_pos != -1:
            if desc_pos < learn_pos:
                work_desc = cleaned_content[desc_pos + desc_len : learn_pos]
                learn_outcomes = cleaned_content[learn_pos + learn_len :]
            else:
                learn_outcomes = cleaned_content[learn_pos + learn_len : desc_pos]
                work_desc = cleaned_content[desc_pos + desc_len :]
        elif desc_pos != -1:
            work_desc = cleaned_content[desc_pos + desc_len :]
        elif learn_pos != -1:
            learn_outcomes = cleaned_content[learn_pos + learn_len :]
            work_desc = cleaned_content[:learn_pos]
        else:
            # Fallback line-splitting heuristics
            lines = [line.strip() for line in cleaned_content.split('\n') if line.strip()]
            lines = [l for l in lines if not re.match(r'^[\s#\-*=_]*$', l)]
            
            if len(lines) >= 2:
                split_idx = len(lines) // 2
                for idx, line in enumerate(lines):
                    if any(w in line.lower() for w in ["learn", "gain", "insight", "understand", "outcome"]):
                        split_idx = idx
                        break
                work_desc = "\n".join(lines[:split_idx])
                learn_outcomes = "\n".join(lines[split_idx:])
            elif len(lines) == 1:
                work_desc = lines[0]
            else:
                work_desc = "Initiated the internship by exploring..."
                learn_outcomes = "Gained insights into brain structures..."
                
        # Helper to strip extra characters
        def clean_field(val: str, default: str) -> str:
            val = val.strip()
            val = re.sub(r'^[:\s\-*•+=#]+', '', val)
            val = val.strip()
            val = re.sub(r'[:\s\-*•+=#]+$', '', val)
            val = val.strip()
            return val if val else default
            
        work_desc = clean_field(work_desc, "Initiated the internship by exploring...")
        learn_outcomes = clean_field(learn_outcomes, "Gained insights into brain structures...")
        
        # Build entry
        entry = (
            f"---\n\n"
            f"### 📅 Date: {normalized_date}\n\n"
            f"**No. of Hours:** {hours_val}\n\n"
            f"**Work Description:**\n"
            f"{work_desc}\n\n"
            f"**Learning Outcomes:**\n"
            f"{learn_outcomes}"
        )
        formatted_entries.append(entry)
        
    return "\n\n".join(formatted_entries)

def to_title_case(s: str) -> str:
    small_words = {"to", "a", "the", "and", "in", "for", "with", "on", "at", "an", "by", "of", "from"}
    words = s.split()
    if not words:
        return s
    title_words = []
    for idx, w in enumerate(words):
        w_clean = re.sub(r'[^a-zA-Z0-9]', '', w)
        if w_clean.lower() in small_words and idx > 0:
            title_words.append(w.lower())
        else:
            title_words.append(w.capitalize())
    return " ".join(title_words)

def format_aicte_report(text: str) -> str:
    if not text:
        return text
        
    # 1. Merge Chapter title and name: e.g. "CHAPTER 1**\n# **INTRODUCTION**" -> "# **CHAPTER 1: INTRODUCTION**"
    text = re.sub(
        r'(?:\*\*|#\s*)?CHAPTER\s+(\d+)\s*(?:\*\*)?\s*\n+\s*(?:#\s*)?\*\*([a-zA-Z\s]+)\*\*',
        r'# **CHAPTER \1: \2**',
        text,
        flags=re.IGNORECASE
    )
    
    # 2. Split text by lines and format subheadings cleanly
    lines = text.split('\n')
    new_lines = []
    chapter_num = None
    subheading_index = 1
    
    for line in lines:
        line_stripped = line.strip()
        # Check if this line is a Chapter header
        chap_match = re.match(r'^#\s*(?:\*\*)?CHAPTER\s+(\d+)(?:[\s:]*([^*]+)?)(?:\*\*)?$', line_stripped, re.IGNORECASE)
        if chap_match:
            chapter_num = chap_match.group(1)
            subheading_index = 1
            new_lines.append(line)
            continue
            
        # Check if we are inside a chapter
        if chapter_num:
            # Let's see if the line looks like a subheading:
            # Pattern 1: e.g. "1. **HELPING LOCAL SCHOOLS**" or "2.1 HELPING LOCAL SCHOOLS" (bold or not)
            sub_num_match = re.match(
                r'^(?:##\s*)?(?:\*\*?)?(\d+(?:\.\d+)*)\.?\s+(?:\*\*?)?([a-zA-Z0-9\s:.,()&-]{5,150})(?:\*\*?)?$',
                line_stripped
            )
            
            # Pattern 2: e.g. "**HELPING LOCAL SCHOOLS TO ACHIEVE...**" (all caps bold line)
            sub_bold_match = re.match(
                r'^(?:##\s*)?(?:\*\*?)?([A-Z0-9\s:.,()&-]{5,150})(?:\*\*?)?$',
                line_stripped
            )
            
            if sub_num_match:
                title = sub_num_match.group(2).strip()
                title_clean = to_title_case(title)
                formatted_line = f"## **{chapter_num}.{subheading_index} {title_clean}**"
                subheading_index += 1
                new_lines.append(formatted_line)
                continue
            elif sub_bold_match:
                title = sub_bold_match.group(1).strip()
                title_clean = to_title_case(title)
                formatted_line = f"## **{chapter_num}.{subheading_index} {title_clean}**"
                subheading_index += 1
                new_lines.append(formatted_line)
                continue
                
        new_lines.append(line)
        
    text = "\n".join(new_lines)

    # 3. Remove tables that only contain pipes, spaces, and hyphens (phantom empty tables)
    text = re.sub(
        r'\n(?:[|\s\-:]+\n){2,}',
        '\n\n',
        text
    )
    
    # 4. Fix cut-off testimonial sentence
    text = re.sub(
        r'(\b(?:encouraged\s+students\s+to\s+consider\s+)?higher,\s*technical,?\s+and\s+vocational)\s*\n*(Testimonial\s+\d+.*?)\s+education\s+seriously\b',
        r'\1 education seriously.\n\n\2',
        text,
        flags=re.IGNORECASE | re.DOTALL
    )
    
    # 5. Format Chapter 4 images (with generated figure references)
    text = format_chapter_4_images(text)
            
    return text

def format_chapter_4_images(text: str) -> str:
    if "CHAPTER 4" in text.upper():
        fig_map = {
            1: ("/static/fig_4_1_1.png", "Fig 4.1.1: Photo of mentoring school students"),
            2: ("/static/fig_4_2_1.png", "Fig 4.2.1: Photo at the Sangolli Rayanna Samadhi / Halsi Temple"),
            3: ("/static/fig_4_3_1.png", "Fig 4.3.1: Photo of interacting with a local vendor showing a UPI QR code"),
            4: ("/static/fig_4_4_1.png", "Fig 4.4.1: Photo of participating in the cleanliness/sweeping drive"),
            5: ("/static/fig_4_5_1.png", "Fig 4.5.1: Photo of conducting the health outreach/handwashing demonstration")
        }
        
        # We can find sections 4.1, 4.2, 4.3, 4.4, 4.5
        parts = re.split(r'(##\s*\*\*4\.[1-5]\s+[^*]+\*\*)', text)
        
        if len(parts) > 1:
            new_parts = [parts[0]]
            for i in range(1, len(parts), 2):
                header = parts[i]
                body = parts[i+1] if i+1 < len(parts) else ""
                
                sec_num_match = re.search(r'4\.([1-5])', header)
                if sec_num_match:
                    sec_num = int(sec_num_match.group(1))
                    img_url, caption = fig_map[sec_num]
                    
                    img_tag_regex = re.compile(r'\[Embedded Image[^\]]*\]', re.IGNORECASE)
                    if img_tag_regex.search(body):
                        body = img_tag_regex.sub(f"![{caption}]({img_url})\n\n*{caption}*", body, count=1)
                        
                new_parts.append(header)
                new_parts.append(body)
                
            text = "".join(new_parts)
            
    return text

def refine_with_llm(markdown_text: str, api_key: Optional[str] = None, provider: str = "gemini") -> str:
    actual_api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not actual_api_key or actual_api_key == "your_gemini_api_key_here":
        print("No valid API key provided. Falling back to local offline formatting...")
        return format_aicte_report(markdown_text)
        
    try:
        client = MultiProviderMockClient(provider=provider, api_key=actual_api_key)
        prompt = (
            "You are an expert technical editor. You are refining an AICTE Activity Points document converted to markdown.\n"
            "Please refine the markdown document by applying these rules:\n"
            "1. Standardize the headers: Merge split chapter headers like 'CHAPTER 1**\\n# **INTRODUCTION**' into '# **CHAPTER 1: INTRODUCTION**'.\n"
            "2. Subheadings must be cleanly numbered and formatted in Title Case: e.g. '## **1.1 Helping Local Schools**', '## **2.1 Helping Local Schools to Achieve Good Result...**'. Ensure the numbering is consistent within each chapter (1.1, 1.2..., 2.1, 2.2...).\n"
            "3. Strip out any phantom empty tables (stray table structures containing only blank cells/pipes).\n"
            "4. Resolve cut-off paragraphs: e.g. fix the split testimonial at the end of Section 4.1 so it reads smoothly as '...encouraged students to consider higher, technical, and vocational education seriously.' and starts Testimonial 2 as a new paragraph.\n"
            "5. Retain all '[Embedded Image: ...]' tags exactly where they are.\n"
            "6. Keep the actual content, details, local references (Belagavi, Sangolli Rayanna Samadhi, Halsi Temple, small vendors) 100% accurate and unchanged. Do not rewrite or summarize the core text.\n\n"
            "Output ONLY the clean, refined Markdown content. Do not add any conversational text or markdown code fences (like ```markdown) at the beginning or end of your output.\n\n"
            "Document to refine:\n\n" + markdown_text
        )
        
        model_name = "gemini-1.5-flash"
        if provider == "openai":
            model_name = "gpt-4o-mini"
        elif provider == "claude":
            model_name = "claude-3-5-sonnet"
            
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}]
        )
        refined_text = response.choices[0].message.content.strip()
        
        # Clean markdown code fences if outputted by the model
        if refined_text.startswith("```markdown"):
            refined_text = refined_text[11:]
        elif refined_text.startswith("```"):
            refined_text = refined_text[3:]
        if refined_text.endswith("```"):
            refined_text = refined_text[:-3]
        refined_text = refined_text.strip()
        
        # Format images to local URLs
        refined_text = format_chapter_4_images(refined_text)
        return refined_text
    except Exception as e:
        print(f"Failed to query LLM for refinement: {e}. Falling back to local formatting.")
        return format_aicte_report(markdown_text)

@app.post("/convert")
async def convert_file(
    file: UploadFile = File(...),
    x_api_key: Optional[str] = Header(None),
    x_api_provider: Optional[str] = Header(None),
    x_template: Optional[str] = Header(None)
):
    # 1. Validate file extension
    filename = file.filename
    _, ext = os.path.splitext(filename.lower())
    
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: '{ext}'. Audio, video, and non-document types are blocked."
        )
        
    # 2. Save the uploaded file to a temporary file
    temp_dir = tempfile.gettempdir()
    temp_file_name = f"{uuid.uuid4()}{ext}"
    temp_file_path = os.path.join(temp_dir, temp_file_name)
    
    try:
        # Write to disk in chunks to avoid memory spikes (good for files >= 100MB)
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        original_size = os.path.getsize(temp_file_path)
        
        # 3. Perform conversion using MarkItDown
        is_image = ext in {".png", ".jpg", ".jpeg"}
        user_api_key = x_api_key
        user_provider = x_api_provider or "gemini"
        template = x_template or "auto"
        
        server_api_key = os.environ.get("GEMINI_API_KEY")
        active_key = user_api_key or (server_api_key if user_provider == "gemini" else None)
        
        if active_key and active_key != "your_gemini_api_key_here":
            mock_client = MultiProviderMockClient(provider=user_provider, api_key=active_key)
            model_name = "gemini-1.5-flash"
            if user_provider == "openai":
                model_name = "gpt-4o-mini"
            elif user_provider == "claude":
                model_name = "claude-3-5-sonnet"
                
            local_markitdown = MarkItDown(llm_client=mock_client, llm_model=model_name)
        else:
            local_markitdown = MarkItDown()
            
        result = local_markitdown.convert(temp_file_path)
        
        if not result or result.text_content is None:
            raise ValueError("Conversion succeeded but returned no content.")
            
        markdown_content = result.text_content
        
        # Apply token and layout sanitization post-processing
        markdown_content = sanitize_markdown(markdown_content)
        
        # Dynamically or explicitly detect document type and apply formatting
        if template == "raw":
            pass
        elif template == "aicte":
            markdown_content = refine_with_llm(markdown_content, api_key=user_api_key, provider=user_provider)
        elif template == "internship":
            markdown_content = format_to_internship_template(markdown_content)
        else:
            # "auto"
            content_lower = markdown_content.lower()
            if "chapter 1" in content_lower or "chapter 2" in content_lower or "aicte" in content_lower or "conclusion" in content_lower:
                markdown_content = refine_with_llm(markdown_content, api_key=user_api_key, provider=user_provider)
            else:
                markdown_content = format_to_internship_template(markdown_content)
        
        markdown_size = len(markdown_content.encode("utf-8"))
        
        # Detect if we should pop up warning about missing API key for images
        has_api_key = bool(active_key and active_key != "your_gemini_api_key_here")
        image_no_key = False
        if not has_api_key:
            if is_image:
                image_no_key = True
            elif "[Embedded Image" in markdown_content or "![Embedded Image" in markdown_content or "![fig" in markdown_content or "![Fig" in markdown_content:
                image_no_key = True
                
        return {
            "success": True,
            "filename": filename,
            "original_size": original_size,
            "markdown_size": markdown_size,
            "markdown": markdown_content,
            "image_no_key": image_no_key
        }
        
    except Exception as e:
        error_msg = str(e)
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": f"Conversion error: {error_msg}"}
        )
        
    finally:
        # 4. Clean up temporary files
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass

@app.post("/validate-key")
async def validate_key(
    x_api_key: str = Header(...),
    x_api_provider: str = Header(...)
):
    provider = x_api_provider.lower().strip()
    try:
        if provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={x_api_key}"
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                return {"valid": True}
            else:
                return {"valid": False, "detail": f"Gemini status {res.status_code}"}
        elif provider == "openai":
            url = "https://api.openai.com/v1/models"
            headers = {"Authorization": f"Bearer {x_api_key}"}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                return {"valid": True}
            else:
                return {"valid": False, "detail": f"OpenAI status {res.status_code}"}
        elif provider == "claude":
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": x_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            body = {
                "model": "claude-3-5-haiku-20241022",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}]
            }
            res = requests.post(url, headers=headers, json=body, timeout=10)
            if res.status_code in (200, 201):
                return {"valid": True}
            else:
                return {"valid": False, "detail": f"Claude status {res.status_code}"}
        else:
            return {"valid": False, "detail": "Invalid provider"}
    except Exception as e:
        return {"valid": False, "detail": str(e)}

# Serve static files from the 'static' directory
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def get_index():
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Welcome to MarkitDown Web Converter. Static frontend is not created yet."}

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

