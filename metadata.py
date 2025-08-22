import os
import re
import io
import json
import boto3
import fitz  # PyMuPDF
import pandas as pd
from PIL import Image
import pytesseract

# === AWS S3 Setup ===
ACCESS_KEY = "AKIA472NH4QZCZARTEOG"
SECRET_KEY = "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"
BUCKET_NAME = "indianpatentofficedata-inventohub"

s3 = boto3.client(
    "s3",
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY
)

# === OCR Setup ===
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

FIELDNAMES = [
    "application_number",
    "doc_number", "doc_id", "country", "country_code", "lang",
    "date_publ", "year_publ", "date_publication", "year_publication",
    "date_filing", "year_filing", "priority_date", "priority_date: iog",
    "title_en", "abstract", "description", "claims",
    "international_application_number", "applicants", "proprietors", "inventors",
    "ipc_classification",
    "publication_number",
    "field_of_invention",
    "representatives", "references_cited"
]

SECTION_ALIASES = {
    "field": ["field of the invention", "technical field", "field"],
    "background": ["background of the invention", "background"],
    "summary": ["summary of the invention", "summary"],
    "detailed": ["detailed description", "description of the invention", "details"],
    "problem": ["problem", "need", "challenge"],
    "solution": ["solution", "approach", "proposed method"],
    "objects": ["objects of the invention", "objectives", "aims"]
}

def clean_text(text):
    replacements = {
        "â€œ": '"', "â€": '"',
        "â€˜": "'", "â€™": "'",
        "â€“": "-", "â€”": "-",
        "â€¦": "...", "â€": '"',
        "\u2013": "-", "\u2014": "-",
        "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"',
        "\xa0": " ", "\n": " ", "\r": " "
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return re.sub(r"\s+", " ", text).strip()

def download_s3_object(key):
    obj = s3.get_object(Bucket=BUCKET_NAME, Key=key)
    return obj['Body'].read()

def open_pdf_from_s3(key):
    pdf_bytes = download_s3_object(key)
    return fitz.open(stream=pdf_bytes, filetype="pdf")

def load_json_from_s3(key):
    json_bytes = download_s3_object(key)
    return json.load(io.BytesIO(json_bytes))

def extract_sections(doc):
    text = "\n".join(page.get_text() for page in doc)
    lines = text.split('\n')
    headings = []
    for i, line in enumerate(lines):
        for key, aliases in SECTION_ALIASES.items():
            if any(a in line.lower() for a in aliases):
                headings.append((i, key, line.strip()))
    headings = sorted(headings, key=lambda x: x[0])
    sections = {}
    for idx, (line_idx, key, heading_text) in enumerate(headings):
        start = line_idx + 1
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        section_text = "\n".join(lines[start:end]).strip()
        sections[key] = {"heading": heading_text, "content": section_text}
    return sections

def extract_full_abstract(doc):
    full_text = "\n".join(page.get_text() for page in doc)
    match = re.search(r"\bABSTRACT\b\s*[:\-]?\s*(.*)", full_text, re.IGNORECASE | re.DOTALL)
    if match:
        abstract = re.split(r"\b(FIELD\s+OF\s+INVENTION|CLAIMS|BACKGROUND\s+OF\s+THE\s+INVENTION|SUMMARY)\b", match.group(1), flags=re.IGNORECASE)[0]
        abstract = re.sub(r"\n\d+\s*", " ", abstract)
        abstract = re.sub(r"\s+", " ", abstract).strip()
        return abstract
    return "NA"

def extract_claims_from_spec(doc):
    full_text = "\n".join(page.get_text() for page in doc)
    text_lower = full_text.lower()
    start_index = text_lower.find("we claim")
    if start_index == -1:
        return "NA"
    end_index = len(full_text)
    for marker in [
        r"dated this", r"\(.*?authorized agent.*?\)", r"indian patent agent regn no\.",
        r"university", r"figure\s+\d+", r"sheet\s*:\s*\d+/\d+"
    ]:
        m = re.search(marker, text_lower[start_index:], re.IGNORECASE)
        if m:
            end_index = start_index + m.start()
            break
    return clean_text(full_text[start_index:end_index])

def extract_pct_number(doc):
    text = "\n".join(page.get_text() for page in doc).replace('\xa0', ' ')
    pct_match = re.search(r"(PCT International Application No\.? & Date|पीसीटी[^:\n]*)[^\d]*(\w+/\w+)?\s*(\d{2}-\d{2}-\d{4}|--)?", text)
    if pct_match:
        return f"{pct_match.group(2) or ''} {pct_match.group(3) or ''}".strip() or "NA"
    return "NA"

def extract_agent_info(doc):
    text = "\n".join(page.get_text() for page in doc).replace('\xa0', ' ').strip()
    reg_matches = list(re.finditer(r"IN/PA[-/]?\d{3,6}", text))
    if not reg_matches:
        return "NA"
    last_match = reg_matches[-1]
    reg_index = last_match.start()
    before_chunk = text[max(0, reg_index - 300):reg_index]
    lines = [line.strip() for line in before_chunk.splitlines() if line.strip()]
    for line in reversed(lines):
        if (2 <= len(line.split()) <= 4 and all(w[0].isupper() for w in line.split())):
            return f"{line}, {last_match.group()}"
    return last_match.group()

def extract_d_references(doc):
    text = "\n".join(page.get_text() for page in doc).replace('\xa0', ' ')
    start_match = re.search(r"D1\s*[:\-]", text)
    if not start_match:
        return "NA"
    lines = text[start_match.start():].splitlines()
    collected = []
    collecting = False
    for line in lines:
        if re.match(r"(D\d+\s*[:\-])", line.strip()):
            collecting = True
        if collecting:
            if any(x in line for x in ["THE PATENT OFFICE", "No Document Cited", "Page "]):
                break
            collected.append(line.strip())
    return clean_text("\n".join(collected))

def extract_priority_date_with_ocr(doc):
    try:
        text = ""
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            text += pytesseract.image_to_string(img) + "\n"
        date_match = re.search(r"(?:Priority\s*(?:Date|Details|Data)?\s*[:\-]?\s*)(\d{2}[-/]\d{2}[-/]\d{4})", text, re.IGNORECASE)
        if date_match:
            return date_match.group(1)
        alt_match = re.search(r"Priority.*?(?:Dated|Date)?[:\-]?\s*(\d{2}[-/]\d{2}[-/]\d{4})", text, re.IGNORECASE)
        if alt_match:
            return alt_match.group(1)
        return "NA"
    except Exception as e:
        print(f"❌ OCR Error: {e}")
        return "NA"

def extract_description_from_json(complete_spec_text):
    if not complete_spec_text or complete_spec_text.strip().lower() == "na":
        return None
    idx = complete_spec_text.lower().find("we claim")
    if idx != -1:
        return complete_spec_text[:idx].strip()
    return complete_spec_text.strip()

def is_placeholder_attachment(text):
    if not text or text.strip().lower() == "na":
        return False
    patterns = [
        "please see the attached specification",
        "please see the attachment",
        "description:please see the attachment",
        "description:please see the attached specification",
        "claims:please see the attachment",
        "claims:please see the attached specification"
    ]
    t = text.strip().lower().replace(" ", "")
    for p in patterns:
        if p.replace(" ", "") in t:
            return True
    return False

def is_na_or_placeholder(val):
    return (not val) or val.strip().lower() == "na" or is_placeholder_attachment(val)

def extract_fields_from_s3(folder_prefix):
    data = {k: "NA" for k in FIELDNAMES}
    data.update({"doc_number": "", "doc_id": "", "lang": "en", "country": "India", "country_code": "IN"})

    # 1. Load application_status.json
    try:
        status_key = f"{folder_prefix}application_status.json"
        status_data = load_json_from_s3(status_key)
        app_number = (status_data.get("APPLICATION NUMBER") or
                      status_data.get("Application Number") or
                      status_data.get("Application number") or
                      folder_prefix.strip('/').split('/')[-1].replace("_", "/"))
        data["application_number"] = app_number
        data["date_filing"] = status_data.get("DATE OF FILING", "NA")
        data["date_publication"] = status_data.get("PUBLICATION DATE (U/S 11A)", "NA")
        data["title_en"] = status_data.get("TITLE OF INVENTION", "NA")
        applicants = status_data.get("APPLICANT NAME", "").split("\n")
        data["applicants"] = ", ".join([a.strip() for a in applicants if a.strip()]) or "NA"
        data["proprietors"] = data["applicants"]
    except Exception:
        data["application_number"] = folder_prefix.strip('/').split('/')[-1].replace("_", "/")

    if data["date_filing"].count("/") == 2:
        data["year_filing"] = data["date_filing"].split("/")[-1]
    if data["date_publication"].count("/") == 2:
        data["year_publication"] = data["date_publication"].split("/")[-1]
    data["date_publ"] = data["date_publication"]
    data["year_publ"] = data["year_publication"]

    # 2. Load ipc_inventors_output.json and extract all relevant fields if present
    try:
        ipc_key = f"{folder_prefix}ipc_inventors_output.json"
        ipc_data = load_json_from_s3(ipc_key)
        data["ipc_classification"] = ipc_data.get("ipc", "NA")
        data["inventors"] = ipc_data.get("inventors", "NA")
        data["publication_number"] = ipc_data.get("publication_number", "NA")
        data["field_of_invention"] = ipc_data.get("field_of_invention", "NA")

        # abstract
        ipc_abstract = ipc_data.get("abstract", "").strip()
        if not is_na_or_placeholder(ipc_abstract):
            data["abstract"] = clean_text(ipc_abstract)

        # description
        ipc_desc = ipc_data.get("complete_specification", "").strip()
        if not is_na_or_placeholder(ipc_desc):
            desc_txt = extract_description_from_json(ipc_desc)
            if desc_txt:
                data["description"] = clean_text(desc_txt[:3000])
        # claims
        ipc_claims = ipc_data.get("claims", "").strip() if "claims" in ipc_data else ""
        if not is_na_or_placeholder(ipc_claims):
            data["claims"] = clean_text(ipc_claims)

        # representatives
        ipc_repr = ipc_data.get("representatives", "").strip() if "representatives" in ipc_data else ""
        if not is_na_or_placeholder(ipc_repr):
            data["representatives"] = clean_text(ipc_repr)

    except Exception:
        data["ipc_classification"] = "NA"
        data["inventors"] = "NA"
        data["publication_number"] = "NA"
        data["field_of_invention"] = "NA"

    # 3. List PDFs for this patent folder
    resp = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=folder_prefix)
    pdf_keys = [obj["Key"] for obj in resp.get("Contents", []) if obj["Key"].lower().endswith(".pdf")]

    # === PDF Fallbacks for abstract, description, claims, representatives ===
    pdf_doc = None
    pdf_doc_used = None
    for pdf_key in pdf_keys:
        fname = os.path.basename(pdf_key).lower()
        if re.search(r"complete[_\s\-]?specification", fname):
            doc = open_pdf_from_s3(pdf_key)

            # Fallback for abstract
            if data.get("abstract", "NA") in ["NA", "", None] or is_placeholder_attachment(data.get("abstract", "")):
                data["abstract"] = extract_full_abstract(doc)

            # Fallback for description (from sections)
            if data.get("description", "NA") in ["NA", "", None] or is_placeholder_attachment(data.get("description", "")):
                sections = extract_sections(doc)
                desc_parts = []
                for key in ["field", "background", "summary", "detailed", "problem", "solution", "objects"]:
                    if key in sections:
                        desc_parts.append(f"{sections[key]['heading']}: {sections[key]['content']}")
                full_desc = "\n\n".join(desc_parts)
                if full_desc:
                    data["description"] = clean_text(full_desc[:3000])

            # Fallback for claims
            if data.get("claims", "NA") in ["NA", "", None] or is_placeholder_attachment(data.get("claims", "")):
                data["claims"] = extract_claims_from_spec(doc)

            # Fallback for representatives
            if data.get("representatives", "NA") in ["NA", "", None] or is_placeholder_attachment(data.get("representatives", "")):
                data["representatives"] = extract_agent_info(doc)

            pdf_doc = doc  # for later if no other path contains inventors/doc_number
            pdf_doc_used = pdf_key

        elif "certificate" in fname:
            # Extract doc_number, inventors from certificate
            doc_cert = open_pdf_from_s3(pdf_key)
            text = "\n".join(page.get_text() for page in doc_cert)
            match = re.search(r"Patent\s*(No\.?|Number)?\s*[:\-]?\s*([A-Z]?\d{6,})", text, re.IGNORECASE)
            if match:
                data["doc_number"] = match.group(2)
            inventors = re.findall(r"\d+\.\s*([A-Z][A-Za-z\s.,-]+)", text)
            if inventors:
                data["inventors"] = ", ".join(set(i.strip() for i in inventors))

        elif "fer" in fname:
            doc = open_pdf_from_s3(pdf_key)
            if data.get("international_application_number", "NA") in ["NA", "", None]:
                data["international_application_number"] = extract_pct_number(doc)
            if data.get("references_cited", "NA") in ["NA", "", None]:
                data["references_cited"] = extract_d_references(doc)

        elif "intimationofgrant" in fname and fname.endswith(".pdf"):
            doc = open_pdf_from_s3(pdf_key)
            data["priority_date: iog"] = extract_priority_date_with_ocr(doc)

    # So 'inventors' field matches applicants if everything else fails (as in local)
    if data["inventors"] == "NA":
        data["inventors"] = data["applicants"]

    return data

def save_metadata_to_s3(df, year, month):
    prefix = f"metadata/{year}/{year}_{month:02}/"
    parquet_key = prefix + "patent_metadata.parquet"
    json_key = prefix + "patent_metadata.json"

    buffer_parquet = io.BytesIO()
    df.to_parquet(buffer_parquet, index=False, engine="pyarrow", compression="snappy")
    buffer_parquet.seek(0)
    s3.put_object(Bucket=BUCKET_NAME, Key=parquet_key, Body=buffer_parquet.getvalue())
    print(f"✅ Parquet file saved to s3://{BUCKET_NAME}/{parquet_key}")

    json_data = df.to_json(orient="records", force_ascii=False)
    s3.put_object(Bucket=BUCKET_NAME, Key=json_key, Body=json_data.encode("utf-8"))
    print(f"✅ JSON file saved to s3://{BUCKET_NAME}/{json_key}")

def build_monthly_metadata(year, month):
    prefix = f"pdfs/{year}/{year}_{month:02}/"
    resp = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix, Delimiter='/')

    if "Contents" not in resp and "CommonPrefixes" not in resp:
        print(f"❌ No data found for {year}_{month:02}")
        return

    # Collect application folder prefixes
    application_folders = set()

    # 'CommonPrefixes' contains folder prefixes if Delimiter is set
    if "CommonPrefixes" in resp:
        for cp in resp["CommonPrefixes"]:
            application_folders.add(cp["Prefix"])

    # Otherwise parse from keys by dirname
    if not application_folders:
        if "Contents" in resp:
            for obj in resp["Contents"]:
                if obj["Key"].endswith(".json"):
                    parts = obj["Key"].split("/")
                    if len(parts) >= 4:
                        folder = "/".join(parts[:4]) + "/"
                        application_folders.add(folder)

    if not application_folders:
        print(f"❌ No patent folders found for {year}-{month:02}")
        return

    records = []
    for folder_prefix in sorted(application_folders):
        print(f"📂 Processing {folder_prefix}")
        try:
            data = extract_fields_from_s3(folder_prefix)
            # Clean large text fields
            for key in ["abstract", "description", "claims", "references_cited"]:
                if data.get(key, "NA") != "NA":
                    data[key] = clean_text(data[key])
            records.append(data)
            print(f"✅ {data.get('application_number', 'UNKNOWN')}")
        except Exception as e:
            print(f"❌ Failed to process {folder_prefix}: {e}")

    if not records:
        print(f"⚠️ No records extracted for {year}_{month:02}")
        return

    df = pd.DataFrame(records)

    # Save metadata back to S3
    save_metadata_to_s3(df, year, month)

if __name__ == "__main__":
    for i in range(1,13):
        build_monthly_metadata(2023,i)


#based on what month you want you can edit the dates in the script