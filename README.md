# Indianpatentoffice
Scraping data from indian patent office website and extracting data and storing it in s3 buckets


Indian Patent Data Scraper and Metadata Extractor
This repository contains two Python scripts written to automate the extraction, processing, and storage of Indian patent data published by the Intellectual Property India office. The data is scraped from the IP India website and stored in AWS S3, with metadata extraction performed from the stored patent documents.

Overview
1. scraper.py
Purpose:
Automatically scrapes patent application data from the IP India public search portal.

Main functionalities:
Automates browser interaction using Selenium WebDriver (Google Chrome).
Navigates date ranges and handles multi-page patents list.

For each patent application:
Extracts classification (IPC) and inventor information.
Fetches application status details.
Downloads key patent documents (like Certificate of Grant, Complete Specification PDFs) filtered by keywords.
Saves extracted information temporarily on local disk.
Uploads downloaded PDF files and JSON metadata to an AWS S3 bucket.
Supports CAPTCHA handling by saving the CAPTCHA image and prompting the user to enter the text manually.
Implements error handling to skip problematic applications and continue scraping.

Important configurations:
AWS credentials & S3 bucket details (replace placeholders with your keys).
Date range for scraping is configurable in the script.
Keywords to filter documents for download.
Runs the Chrome WebDriver in headless mode by default to allow execution on headless servers/clouds.

2. metadata.py
Purpose:
Processes the XML/JSON/PDF patent documents saved in AWS S3 to extract structured metadata for analysis and indexing.

Main functionalities:
Connects to AWS S3 bucket to list and read stored patent-related JSON and PDF files.
Uses OCR (via Tesseract + pytesseract) to extract text from PDFs where necessary.
Extracts key patent fields such as:
Application number, IPC classification, inventors, applicants, dates of filing and publication, abstracts, claims, description, representatives, and references cited
Supports fuzzy matching and cleaning of text fields to standardize the output.
Handles PDF parsing using PyMuPDF (fitz) for advanced text extraction.
Generates structured pandas DataFrame with all patent metadata.
Saves metadata back to S3 in JSON and Parquet formats for further analysis.

Important configurations:
AWS credentials for accessing the S3 bucket.
Path to tesseract.exe (Windows) or system setup for Tesseract OCR.
Configuration for expected metadata fields and logical grouping of patent document sections.

Prerequisites
Python 3.8+
Google Chrome or Chromium browser installed.
Chromedriver matching your Chrome version (automatic installation via chromedriver_autoinstaller).
AWS account with access credentials and an S3 bucket.
Tesseract OCR installed on your system (required by metadata.py).

Python packages (install via pip):
bash
pip install selenium boto3 pillow pymupdf pytesseract pandas pyarrow

For headless server/cloud runs:
Use Chrome in headless mode (--headless flag in scraper.py).


Usage
Running the Scraper
Set your AWS credentials and S3 bucket details in scraper.py.
Adjust the date range in scraper.py (lines configuring FromDate and ToDate).
Run the scraper:
bash
python scraper.py
When prompted, view the saved CAPTCHA image (captcha.png), solve the CAPTCHA manually, and enter the text.
The scraper will process patent applications, download documents, and upload them to S3.
Running the Metadata Extractor
Set AWS credentials and Tesseract path in metadata.py.
Adjust the year and months to process in metadata.py.
Run the metadata extraction:
bash
python metadata.py
The script will read patent files from S3, extract metadata, and save consolidated datasets back to S3.

How It Works
scraper.py:
Uses Selenium to simulate browser activity on the Indian patent website. Navigates through pages, extracts relevant info, and downloads documents. AWS SDK uploads files and metadata for centralized storage.

metadata.py:
Uses AWS SDK to retrieve stored files. Parses PDFs using PyMuPDF, applies OCR via Tesseract to extract text. Uses regex and heuristics to identify patent claims, abstracts, dates, and other fields. Saves cleaned metadata for downstream use.

Troubleshooting
CAPTCHA Handling:
CAPTCHA must be solved manually during scraping. Image is saved as captcha.png—use an image viewer to read.

Browser Compatibility:
Ensure Chrome and Chromedriver versions match. Chromedriver is auto-installed by chromedriver_autoinstaller.

AWS Credentials:
Verify your AWS keys and bucket names are correctly set and have proper permissions.

Headless Execution:
Consider using a virtual display like Xvfb on headless Linux servers to avoid rendering problems. (Haven't implemented this yet)

Verify download folder permissions and that files are fully downloaded before upload.
