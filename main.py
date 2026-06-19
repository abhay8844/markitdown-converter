import os
import re
import shutil
import tempfile
import uuid
import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException
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

# Initialize MarkItDown (without external LLM dependencies, just local document parser)
markitdown = MarkItDown()

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
    ".rst"
}

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

def refine_with_llm(markdown_text: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or api_key == "your_gemini_api_key_here":
        # Fall back to local formatting if no valid API key is set
        print("GEMINI_API_KEY is not set. Falling back to local offline formatting...")
        return format_aicte_report(markdown_text)
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
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
    
    body = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }
    
    try:
        res = requests.post(url, headers=headers, json=body, timeout=30)
        if res.status_code == 200:
            res_json = res.json()
            refined_text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            
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
        else:
            print(f"Gemini API returned status code {res.status_code}: {res.text}. Falling back to local formatting.")
            return format_aicte_report(markdown_text)
    except Exception as e:
        print(f"Failed to query Gemini API: {e}. Falling back to local formatting.")
        return format_aicte_report(markdown_text)

@app.post("/convert")
async def convert_file(file: UploadFile = File(...)):
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
        # This executes synchronously in a standard worker thread (FastAPI handles def endpoints on a thread pool)
        result = markitdown.convert(temp_file_path)
        
        if not result or result.text_content is None:
            raise ValueError("Conversion succeeded but returned no content.")
            
        markdown_content = result.text_content
        
        # Apply token and layout sanitization post-processing
        markdown_content = sanitize_markdown(markdown_content)
        
        # Dynamically detect document type and apply formatting
        content_lower = markdown_content.lower()
        if "chapter 1" in content_lower or "chapter 2" in content_lower or "aicte" in content_lower or "conclusion" in content_lower:
            markdown_content = refine_with_llm(markdown_content)
        else:
            markdown_content = format_to_internship_template(markdown_content)
        
        markdown_size = len(markdown_content.encode("utf-8"))
        
        return {
            "success": True,
            "filename": filename,
            "original_size": original_size,
            "markdown_size": markdown_size,
            "markdown": markdown_content
        }
        
    except Exception as e:
        # Catch and return generic errors cleanly
        error_msg = str(e)
        # Simplify common backend failures if needed, but return full details for debugging
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

