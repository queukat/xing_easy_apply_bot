import csv
import os
import pickle
import random
import time
import logging
from langdetect import detect
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait, Select

from config import *

# Set up basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def is_logged_in():
    try:
        driver.find_element(By.CSS_SELECTOR, "img[data-testid='top-bar-profile-logo']")
        return True
    except NoSuchElementException:
        return False

def login():
    logging.info("Starting login process...")

    load_cookies(driver, xing_cookies_file_path, "https://www.xing.com/")
    time.sleep(2)

    if is_logged_in():
        logging.info("Logged in successfully using cookies.")
        return

    driver.get("https://login.xing.com/")
    time.sleep(2)

    try:
        consent_button = driver.find_element(By.ID, "consent-accept-button")
        consent_button.click()
        time.sleep(2)
    except Exception as e:
        logging.warning(f"Consent popup not found: {e}")

    driver.find_element(By.ID, "username").send_keys(EMAIL_XING)
    driver.find_element(By.ID, "password").send_keys(PASSWORD_XING)

    login_button = driver.find_element(By.XPATH, "//button[contains(., 'Log in')]")
    login_button.click()
    time.sleep(2)

    pickle.dump(driver.get_cookies(), open(xing_cookies_file_path, "wb"))
    logging.info("Login completed.")

def load_cookies(driver, cookies_file_path, url):
    if os.path.exists(cookies_file_path):
        driver.get(url)
        cookies = pickle.load(open(cookies_file_path, "rb"))
        for cookie in cookies:
            driver.add_cookie(cookie)
        driver.get(url)
        logging.info("Cookies successfully loaded and added.")
    else:
        logging.warning("Cookies file not found. Login required.")

def start_scraping_process():
    for url in initial_urls:
        logging.info(f"Starting data collection from {url}...")
        ensure_login_and_navigate_to_jobs(url)  # Navigate to the initial URL
        scrape_jobs()  # Collect jobs from the current URL


# This function checks for cookies and tries to load them. If not, starts the login process.
def ensure_login_and_navigate_to_jobs(url):
    if os.path.exists(xing_cookies_file_path):
        logging.info("Loading saved cookies...")
        load_cookies(driver, xing_cookies_file_path, "https://www.xing.com/")
        driver.get(url)
        remove_location_filter(driver)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
    else:
        logging.info("Cookies not found, login process needed...")
        login()
        driver.get(url)
        remove_location_filter(driver)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
    logging.info("On the job listings page.")


def remove_location_filter(driver):
    try:
        location_filter = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "[data-cy='search-query-tag-location'] [data-testid='deleteable']"))
        )
        location_filter.click()
        logging.info("Location filter removed.")

        WebDriverWait(driver, 10).until_not(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-cy='search-query-tag-location']"))
        )
        logging.info("Location filter removal confirmed.")
    except TimeoutException:
        logging.warning("Location filter not found or could not be removed in time.")

def detect_language(text):
    try:
        return detect(text)
    except:
        logging.error("Error in language detection.")
        return "unknown"

def load_existing_urls(file_path):
    existing_urls = set()
    try:
        with open(file_path, 'r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            headers = next(reader, None)
            if headers:
                for row in reader:
                    existing_urls.add(row[0])
        logging.info("Existing URLs loaded successfully.")
    except FileNotFoundError:
        logging.warning("File not found, a new one will be created.")
    return existing_urls

def initialize_scraping():
    existing_urls = load_existing_urls('job_listings.csv')
    file_exists = os.path.exists('job_listings.csv')
    logging.info(f"File exists: {file_exists}, initializing scraping.")
    return existing_urls, file_exists, driver

def collect_job_listings(driver, writer, existing_urls):
    total_urls_collected = 0
    current_page = 1

    job_keywords = ["data-engineer", "big-data-developer", "big-data-engineer", "etl-developer",
                    "data-quality", "data-systems-engineer", "data-architecture", "data-pipeline",
                    "dataengineer", "data-architect", "datalake", "data-warehouse", "data-analyst",
                    "data-platform-engineer", "analytics-engineer", "migration", "big-data"]

    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(5)

        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "article.sc-1d9waxr-0"))
        )

        job_listings = driver.find_elements(By.CSS_SELECTOR, "article.sc-1d9waxr-0")
        urls_collected_this_page = 0

        for job in job_listings:
            job_url = job.find_element(By.CSS_SELECTOR, 'a.sc-1lqq9u1-1').get_attribute('href')
            job_description = job.find_element(By.CSS_SELECTOR, 'p[data-xds="BodyCopy"]').text
            language = detect_language(job_description)

            if language == 'en' and any(keyword in job_url for keyword in job_keywords) and job_url not in existing_urls:
                existing_urls.add(job_url)
                writer.writerow([job_url, language, ''])
                total_urls_collected += 1
                urls_collected_this_page += 1

        logging.info(f"Collected {urls_collected_this_page} jobs from page {current_page}. Total collected: {total_urls_collected}")

        if not navigate_to_next_page(driver, current_page):
            break

        current_page += 1

    return total_urls_collected

def navigate_to_next_page(driver, current_page):
    try:
        next_page_xpath = f"//a[contains(text(),'{current_page + 1}')]"
        next_buttons = driver.find_elements(By.XPATH, next_page_xpath)

        for button in next_buttons:
            if button.is_displayed():
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button)
                WebDriverWait(driver, 10).until(EC.element_to_be_clickable(button))
                button.click()
                time.sleep(3)
                return True

        logging.warning(f"Failed to find button to navigate to page {current_page + 1}.")
        return False

    except NoSuchElementException:
        logging.error("Next page button not found.")
        return False
    except Exception as e:
        logging.error(f"Error navigating to page {current_page + 1}: {e}")
        return False

def scrape_jobs():
    logging.info("Starting job collection...")
    existing_urls, file_exists, driver = initialize_scraping()

    with open('job_listings.csv', 'a' if file_exists else 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(['URL', 'Language', 'Application Sent', 'join_urls'])

        total_urls_collected = collect_job_listings(driver, writer, existing_urls)
        logging.info(f"Job collection complete. Total URLs collected: {total_urls_collected}")


def visit_english_jobs_and_apply():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    with open('job_listings.csv', 'r', newline='', encoding='utf-8') as file:
        rows = list(csv.reader(file))

    headers = rows[0]
    if 'join_urls' not in headers:
        headers.append('join_urls')
    if 'employer_urls' not in headers:
        headers.append('employer_urls')
    data = rows[1:]

    for i, row in enumerate(data):
        if len(row) < len(headers):
            row += [''] * (len(headers) - len(row))

        job_url, language, application_sent, join_urls, employer_urls = row[:5]
        if language == 'en' and (application_sent == '' or application_sent == 'error'):
            logging.info(f"Visiting job listing: {job_url}")
            driver.get(job_url)

            try:
                employer_links = WebDriverWait(driver, 7).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a[data-testid='applyAction']"))
                )
                employer_urls = [link.get_attribute('href') for link in employer_links]
                row[headers.index('employer_urls')] = '|'.join(employer_urls)

                join_com_url = next((url for url in employer_urls if "join.com" in url), '')
                row[headers.index('join_urls')] = join_com_url
                row[2] = 'success' if join_com_url else 'not valid'
                logging.info(f"Status of job {job_url}: {'success' if join_com_url else 'not valid'}")
            except TimeoutException:
                logging.error(f"'Visit employer website' button did not load in time for job: {job_url}")
                row[2] = 'error'

            try:
                WebDriverWait(driver, 7).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "button[data-testid='xing-application-action']"))
                )
                logging.info(f"Found 'Easy apply' button for job: {job_url}")
                row[2] = 'quick_apply'
            except TimeoutException:
                logging.warning(f"'Easy apply' button not found for job: {job_url}")

                # Check if the job posting has been removed
            try:
                expired_message = driver.find_elements(By.XPATH, "//h2[contains(text(), \"This job ad isn't available.\")]")
                if expired_message:
                    logging.info(f"Job {job_url} has been removed from posting.")
                    row[2] = 'expired'
            except NoSuchElementException:
                logging.info(f"Job {job_url} is active.")

            with open('job_listings.csv', 'w', newline='', encoding='utf-8') as file_to_write:
                writer = csv.writer(file_to_write)
                writer.writerow(headers)
                writer.writerows(data)
                
def prompt_for_new_jobs():
    update_jobs = input("Do you want to update the job listings? (yes/no): ")
    if update_jobs.lower() == 'yes':
        logging.info("Updating job listings...")
        scrape_jobs()
    else:
        logging.info("Job listing update canceled.")

def file_exists_and_complete(file_path):
    if not os.path.exists(file_path):
        return False, False

    with open(file_path, 'r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        headers = next(reader, None)
        if headers is None or 'Language' not in headers or 'Application Sent' not in headers:
            return True, False

        for row in reader:
            if row[headers.index('Language')] == 'en' and row[headers.index('Application Sent')] == '':
                return True, False  # Found a row that has not been processed yet

        return True, True  # All rows have been processed


def xing_easy_apply():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    if not os.path.exists('job_listings.csv'):
        logging.error('File job_listings.csv not found.')
        return

    with open('job_listings.csv', 'r', newline='', encoding='utf-8') as file:
        rows = list(csv.reader(file))
        headers = rows[0]
        data = rows[1:]

    logging.info("Starting to process jobs on xing.com...")

    for i, row in enumerate(data):
        if len(row) < len(headers):
            row += [''] * (len(headers) - len(row))

        job_url, language, application_sent, join_com_url = row[:4]
        if language == 'en' and application_sent in ['quick_apply', 'error_easy', 'error_form', 'uncertain']:
            logging.info(f"Processing job on xing.com: {job_url}")
            driver.get(job_url)

            try:
                job_status = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "h2.sc-1gpssxl-0.gPoYAw.sc-1wks242-0.eJwPOg"))
                ).text
                if job_status == "This job ad isn't available.":
                    logging.info(f"Job {job_url} has been removed from posting.")
                    row[headers.index('Application Sent')] = 'expired'
                    continue
            except TimeoutException:
                logging.info("Job status not found, continuing processing.")

            try:
                application_status = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "div[data-xds='ContentBanner']"))
                ).text
                if "You applied for this job" in application_status:
                    logging.info(f"Already applied for job {job_url}.")
                    row[headers.index('Application Sent')] = 'done'
                    continue
            except TimeoutException:
                logging.info("Application status not found, continuing processing.")

            selectors = [
                ".iUTVJn .sc-6z95j0-5",  # Your original selector
                "button[data-testid='xing-application-action']",  # Another example selector
                "//button[contains(text(), 'Apply')]",  # XPath selector
                "//button[contains(text(), 'Easy apply')]",
                "//button[contains(text(), 'Quick apply')]",
            ]

            clicked = False

            for selector in selectors:
                try:
                    if selector.startswith("//"):  # If it's an XPath
                        element = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, selector))
                        )
                    else:  # If it's a CSS selector
                        element = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )

                    if "Apply" in element.text or "Easy apply" in element.text or "Quick apply" in element.text:
                        driver.execute_script("arguments[0].click();", element)
                        time.sleep(random.randint(3,8))
                        logging.info(f"Button found and clicked with selector: {selector}")
                        clicked = True
                        break

                except (TimeoutException, NoSuchElementException):
                    logging.warning(f"Element with selector '{selector}' not found.")

            if not clicked:
                logging.error("Failed to click any of the buttons.")
                row[headers.index('Application Sent')] = 'error_easy'
                continue

            try:
                country_dropdown = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.NAME, "countryCode"))
                )
                select_country = Select(country_dropdown)
                try:
                    select_country.select_by_value(country_code)
                    logging.info("Country code {country_code} selected.")
                except NoSuchElementException:
                    logging.warning("Element with country code {country_code} not found.")

                time.sleep(3)

                phone_input = driver.find_element(By.NAME, "phone")
                phone_input.send_keys(TELEPHONE)
                logging.info("Phone number entered.")

                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(5)

                try:
                    upload_input = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file'][name='fileToUpload']"))
                    )
                    upload_input.send_keys(RESUME_PATH)
                    logging.info(f"Resume uploaded from {RESUME_PATH}.")
                except TimeoutException:
                    logging.error("Failed to find file upload element.")

                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "li.uploads-list-uploads-list-listItem-e46d8dc1"))
                    )
                    logging.info("Resume file successfully uploaded.")
                except TimeoutException:
                    logging.warning("Failed to confirm resume file upload.")

                submit_button = driver.find_element(By.CSS_SELECTOR, "button[data-cy='instant-apply-confirm-button']")
                submit_button.click()
                time.sleep(3)

                try:
                    error_message = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='upload-error-banner']"))
                    )
                    if error_message:
                        logging.error("Error occurred during form submission.")
                        row[headers.index('Application Sent')] = 'uncertain'
                        continue
                except TimeoutException:
                    logging.info("No error message found, continuing processing.")

                try:
                    confirmation_icon = WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "svg[data-xds='IllustrationSpotCheck']"))
                    )
                    confirmation_title = WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located(
                            (By.XPATH, "//h1[contains(text(), 'Application submitted')]"))
                    )
                    confirmation_paragraph = WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located(
                            (By.XPATH, "//p[contains(text(), \"You'll receive an e-mail confirming your application soon.\")]")
                        )
                    )

                    if confirmation_title or confirmation_paragraph or confirmation_icon:
                        logging.info("Application successfully submitted.")
                        row[headers.index('Application Sent')] = 'done'
                    else:
                        logging.warning("Submission status unknown.")
                        row[headers.index('Application Sent')] = 'uncertain'
                except TimeoutException:
                    logging.error("Timeout while waiting for submission confirmation.")
                    row[headers.index('Application Sent')] = 'uncertain'

            except Exception as e:
                logging.error(f"Error while filling out the form: {e}")
                row[headers.index('Application Sent')] = 'error_form'

            finally:
                data[i] = row  # Updating the data row
                with open('job_listings.csv', 'w', newline='', encoding='utf-8') as file_to_write:
                    writer = csv.writer(file_to_write)
                    writer.writerow(headers)
                    writer.writerows(data)
