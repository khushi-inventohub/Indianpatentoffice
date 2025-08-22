import os, time, platform, shutil, json, re
from io import BytesIO
from PIL import Image
import fitz  # PyMuPDF
import boto3
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import chromedriver_autoinstaller
from datetime import datetime


# === AWS credentials ===
ACCESS_KEY = "AKIA472NH4QZCZARTEOG"
SECRET_KEY = "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"
BUCKET_NAME = "indianpatentofficedata-inventohub"
S3_PREFIX = "pdfs"


# === Setup S3 ===
s3 = boto3.client("s3", aws_access_key_id=ACCESS_KEY, aws_secret_access_key=SECRET_KEY)


def upload_to_s3(local_path, year, month, app_number, filename):
    key = f"{S3_PREFIX}/{year}/{year}_{month:02}/{app_number}/{filename}"
    try:
        s3.upload_file(local_path, BUCKET_NAME, key)
        print(f" Uploaded to S3: {key}")
    except Exception as e:
        print(f" Failed to upload {filename} to S3: {e}")


def application_exists_in_s3(year, month, app_number):
    """
    Check if the application folder already has any files in S3.
    Returns True if any object exists under that prefix.
    """
    prefix = f"{S3_PREFIX}/{year}/{year}_{month:02}/{app_number}/"
    try:
        resp = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix, MaxKeys=1)
        return 'Contents' in resp and len(resp['Contents']) > 0
    except Exception as e:
        print(f" Error checking S3 for {app_number}: {e}")
        return False


# === Setup local temp paths ===
BASE_DIR = os.path.abspath("ipindia_documents")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


KEYWORDS = ["IntimationOfGrant", "PatentCertificate", "Complete Specification", "Form 5", "FER"]


# === Setup Chrome ===
chromedriver_autoinstaller.install()
options = webdriver.ChromeOptions()
options.add_experimental_option("prefs", {
    "download.default_directory": DOWNLOAD_DIR,
    "plugins.always_open_pdf_externally": True
})
options.add_argument("--start-maximized")
driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, 40)


def get_captcha_text(driver):
    captcha_el = driver.find_element(By.CSS_SELECTOR, "img#Captcha")
    img = Image.open(BytesIO(captcha_el.screenshot_as_png))
    img.save("captcha.png")
    os.startfile("captcha.png") if platform.system() == "Windows" else os.system("open captcha.png")
    return input(" Enter CAPTCHA text: ")


try:
    driver.get("https://iprsearch.ipindia.gov.in/publicsearch")
    print(" Page loaded")

## ADJUST THE DATES HERE

    wait.until(EC.presence_of_element_located((By.ID, "Granted"))).click()
    driver.find_element(By.ID, "FromDate").send_keys("01/01/2022")
    driver.find_element(By.ID, "ToDate").send_keys("10/31/2022")

    captcha = get_captcha_text(driver)
    driver.find_element(By.ID, "CaptchaText").send_keys(captcha + Keys.RETURN)
    wait.until(EC.presence_of_element_located((By.XPATH, "//table[@id='tableData']//tr")))

    row_index = 0
    while True:
        rows = driver.find_elements(By.XPATH, "//table[@id='tableData']//tr")
        rows = [r for r in rows if len(r.find_elements(By.TAG_NAME, "td")) >= 4]
        if row_index >= len(rows):
            # === Try to go to next page ===
            try:
                next_button = driver.find_element(By.XPATH, "//button[@class='next' and not(@disabled)]")
                driver.execute_script("arguments[0].scrollIntoView(true);", next_button)
                next_button.click()
                time.sleep(3)
                row_index = 0  # Reset index for next page
                continue
            except:
                print("\n No more pages or unable to locate 'Next' button.")
                break

        row = rows[row_index]
        row_index += 1
        cells = row.find_elements(By.TAG_NAME, "td")
        app_number = cells[0].text.strip().replace("/", "_")
        title = cells[1].text.strip()
        print(f"\n🔗 {row_index}. Application: {app_number} | Title: {title}")

        # === STEP 1: IPC + Inventors ===
        try:
            btn = row.find_element(By.XPATH, ".//button[@name='ApplicationNumber']")
            driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            btn.click()
            driver.switch_to.window(driver.window_handles[-1])
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            time.sleep(2)

            try:
                ipc = driver.find_element(By.XPATH, '//td[contains(text(), "Classification (IPC)")]/following-sibling::td').text.strip()
            except:
                ipc = "NA"

            inventors = []
            try:
                inventor_header = driver.find_element(By.XPATH, '//td[contains(text(), "Inventor")]/parent::tr')
                inventor_table = inventor_header.find_element(By.XPATH, 'following-sibling::tr[1]//table')
                inventor_rows = inventor_table.find_elements(By.TAG_NAME, "tr")
                for r in inventor_rows[1:]:
                    tds = r.find_elements(By.TAG_NAME, "td")
                    if tds and tds[0].text.strip():
                        inventors.append(tds[0].text.strip())
            except:
                inventors = ["NA"]

            ipc_data = {
                "application_number": app_number,
                "ipc": ipc,
                "inventors": ", ".join(inventors)
            }

            ipc_path = os.path.join(DOWNLOAD_DIR, f"{app_number}_ipc_inventors.json")
            with open(ipc_path, "w", encoding="utf-8") as f:
                json.dump(ipc_data, f, indent=4, ensure_ascii=False)
            print(" Saved ipc_inventors JSON")

            driver.close()
            driver.switch_to.window(driver.window_handles[0])

        except Exception as e:
            print(f" IPC + Inventors failed for {app_number}: {e}")
            continue

        # Refresh row due to DOM reset
        rows = driver.find_elements(By.XPATH, "//table[@id='tableData']//tr")
        rows = [r for r in rows if len(r.find_elements(By.TAG_NAME, "td")) >= 4]
        row = next(r for r in rows if app_number in r.text)

        # === STEP 2: Application Status ===
        try:
            # Open Application Status page/tab
            row.find_element(By.XPATH, ".//button[contains(text(), 'Application Status')]").click()
            driver.switch_to.window(driver.window_handles[-1])
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            time.sleep(2)

            details_table = wait.until(EC.presence_of_element_located((By.XPATH, "//div[@id='Content']//table[1]")))
            rows_detail = details_table.find_elements(By.TAG_NAME, "tr")
            status_data = {}
            for tr in rows_detail:
                tds = tr.find_elements(By.TAG_NAME, "td")
                if len(tds) >= 2:
                    status_data[tds[0].text.strip().replace(":", "")] = tds[1].text.strip()

            # Use application filing date (DATE OF FILING) for bifurcation
            app_date = status_data.get("DATE OF FILING", "01/01/2024")
            try:
                app_dt = datetime.strptime(app_date, "%d/%m/%Y")
                year, month = app_dt.year, app_dt.month
            except:
                year, month = 2024, 1

            # === Skip if application files already exist in S3 ===
            if application_exists_in_s3(year, month, app_number):
                print(f"  Skipping {app_number} (already exists in S3)")
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                continue

            status_path = os.path.join(DOWNLOAD_DIR, f"{app_number}_status.json")
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(status_data, f, indent=4, ensure_ascii=False)
            print(" Saved application_status JSON")

            driver.close()
            driver.switch_to.window(driver.window_handles[0])

        except Exception as e:
            print(f" Application status failed for {app_number}: {e}")
            continue

        # Refresh row again
        rows = driver.find_elements(By.XPATH, "//table[@id='tableData']//tr")
        rows = [r for r in rows if len(r.find_elements(By.TAG_NAME, "td")) >= 4]
        row = next(r for r in rows if app_number in r.text)

        # === STEP 3: Download Matching Documents ===
        try:
            # Open Application Status and click "View Documents"
            row.find_element(By.XPATH, ".//button[contains(text(), 'Application Status')]").click()
            driver.switch_to.window(driver.window_handles[-1])
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            time.sleep(3)  # Let everything render

            view_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//input[@type='submit' and @value='View Documents']")
            ))
            driver.execute_script("arguments[0].scrollIntoView(true);", view_btn)
            view_btn.click()

            # Wait for document buttons to appear, if any
            try:
                wait.until(EC.presence_of_element_located((By.XPATH, "//button[@class='btn btn-link']")))
                buttons = driver.find_elements(By.XPATH, "//button[@class='btn btn-link']")
            except:
                buttons = []

            if not buttons:
                print(f" No downloadable documents found for {app_number}, skipping download step.")
            else:
                for j, btn in enumerate(buttons, 1):
                    name = btn.get_attribute("value").strip().replace("/", "_")
                    if not any(k.lower() in name.lower() for k in KEYWORDS):
                        continue

                    print(f" Downloading: {name}")
                    before = set(os.listdir(DOWNLOAD_DIR))
                    btn.click()
                    time.sleep(2)

                    for _ in range(60):
                        time.sleep(1)
                        after = set(os.listdir(DOWNLOAD_DIR))
                        new_files = after - before
                        pdfs = [f for f in new_files if f.endswith(".pdf")]
                        if pdfs:
                            pdf_file = pdfs[0]
                            local_path = os.path.join(DOWNLOAD_DIR, pdf_file)
                            upload_to_s3(local_path, year, month, app_number, f"{j}_{name}.pdf")
                            os.remove(local_path)
                            break
                    else:
                        print(" Download timeout for:", name)

            # Upload JSON files
            upload_to_s3(ipc_path, year, month, app_number, "ipc_inventors_output.json")
            upload_to_s3(status_path, year, month, app_number, "application_status.json")
            os.remove(ipc_path)
            os.remove(status_path)

            driver.close()
            driver.switch_to.window(driver.window_handles[0])

        except Exception as e:
            print(f" Failed to download/upload documents for {app_number}: {e}")

except Exception as e:
    print(f" General Error: {e}")
finally:
    driver.quit()
    print("\n Done.")

# based on what year you want you can adjust the dates