import csv
import time
import logging
from langdetect import detect
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from config import driver, LOG_LEVEL, file_path, WAIT_TIME, TIMEOUT

# Configure logging
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')

def load_job_listings(file_path):
    """
    Load job listings from a CSV file.

    :param file_path: Path to the CSV file containing job listings.
    :return: Tuple of headers and data rows from the file.
    """
    with open(file_path, 'r', newline='', encoding='utf-8') as file:
        rows = list(csv.reader(file))
        return rows[0], rows[1:]

def save_job_listings(file_path, headers, data):
    """
    Save job listings to a CSV file.

    :param file_path: Path to the CSV file where job listings will be saved.
    :param headers: Headers for the CSV file.
    :param data: Data rows to be written to the file.
    """
    with open(file_path, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(data)

def process_job_listings(headers, data):
    """
    Process each job listing.

    :param headers: Headers of the job listings.
    :param data: Data rows of the job listings.
    """
    for i, row in enumerate(data):
        if len(row) < len(headers):
            row += [''] * (len(headers) - len(row))

        job_url, language, application_sent, join_com_url, employer_urls = row[:5]
        if language == 'en' and application_sent not in ['done', 'not suitable'] and employer_urls.startswith("https://adesso-se.contactrh.com/"):
            logging.info("Processing a job listing on adesso-group.com")
            driver.get(employer_urls)
            time.sleep(WAIT_TIME)

            try:
                description_element = WebDriverWait(driver, TIMEOUT).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "span.jobdescription"))
                )
                description_text = description_element.text

                if detect(description_text) != 'en':
                    logging.info("Job description in non-English language. Marking as not suitable.")
                    row[headers.index('Application Sent')] = 'not suitable'
                    continue

                cookie_accept_button = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.ID, "cookie-accept"))
                )
                driver.execute_script("arguments[0].click();", cookie_accept_button)

                apply_button = WebDriverWait(driver, TIMEOUT).until(
                    EC.visibility_of_element_located((By.TAG_NAME, "adesso-apply-button"))
                )
                driver.execute_script("arguments[0].click();", apply_button)
                logging.info("Application process triggered")
                row[headers.index('Application Sent')] = 'future'

            except TimeoutException as te:
                logging.error(f"Timeout error: {str(te)}")
            except WebDriverException as we:
                logging.error(f"WebDriver error: {str(we)}")
            finally:
                data[i] = row

def run_job_processing():
    """
    Run the job processing workflow.
    """
    headers, data = load_job_listings(file_path)
    process_job_listings(headers, data)
    save_job_listings(file_path, headers, data)



