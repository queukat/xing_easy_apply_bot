import csv
import os
import pickle
import random
import time

from langdetect import detect
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait

from config import *


def is_logged_in():
    """Check if the user is logged in by searching for the profile image element."""
    try:
        driver.find_element(By.CSS_SELECTOR, "img[data-testid='top-bar-logo']")
        return True
    except NoSuchElementException:
        return False

def login():
    """Perform login to the site.

    First, it tries to load cookies. If that fails, it proceeds with the standard login process.
    """
    print("Starting login process...")

    # Attempt to load cookies first
    load_cookies(driver, xing_cookies_file_path, "https://www.xing.com/")
    time.sleep(2)  # Allow page to load after setting cookies

    if is_logged_in():
        print("Login successful using cookies.")
        return

    # Standard login with username and password if cookies don't work
    driver.get("https://login.xing.com/")
    time.sleep(2)

    # Attempt to close cookie consent popup
    try:
        consent_button = driver.find_element(By.ID, "accept-button")
        consent_button.click()
        time.sleep(2)  # Wait to ensure the popup is closed
    except Exception as e:
        print("Cookie consent popup not found:", e)

    # Entering login credentials
    driver.find_element(By.ID, "username").send_keys(EMAIL)
    driver.find_element(By.ID, "password").send_keys(PASSWORD)

    # Clicking the login button
    login_button = driver.find_element(By.XPATH, "//button[contains(., 'Entering')]")
    login_button.click()
    time.sleep(2)

    # Save cookies after login
    pickle.dump(driver.get_cookies(), open(xing_cookies_file_path, "wb"))
    print("Login completed successfully.")

def load_cookies(driver, cookies_file_path, url):
    """Load cookies from a file and add them to the browser.

    Args:
        driver: Selenium WebDriver instance.
        cookies_file_path: Path to the file where cookies are stored.
        url: URL to navigate to before setting cookies.
    """
    if os.path.exists(cookies_file_path):
        driver.get(url)
        cookies = pickle.load(open(cookies_file_path, "rb"))
        for cookie in cookies:
            driver.add_cookie(cookie)
        driver.get(url)
        print("Cookies successfully loaded and added.")
    else:
        print("Cookie file not found. Login required.")

def ensure_login_and_navigate_to_jobs():
    """Ensure the user is logged in and navigate to the job listings page.

    If cookies are available, it loads them; otherwise, it performs a login process.
    After login, navigates to the jobs page.
    """
    if os.path.exists(xing_cookies_file_path):
        print("Loading saved cookies...")
        load_cookies(driver, xing_cookies_file_path, "https://www.xing.com/")
        driver.get(url)
        remove_location_filter(driver)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
    else:
        print("Cookies not found, login process required...")
        login()
        driver.get(url)
        remove_location_filter(driver)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
    
    # Wait for the full page load
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, 'content')))
    print("On the job listings page.")


def remove_location_filter(driver):
    """Remove the location filter from the job search page.

    Args:
        driver: Selenium WebDriver instance.
    """
    try:
        # Wait for the location filter removal button to appear
        location_filter = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "[data-cy='tag-location'] [data-testid='delete']"))
        )
        location_filter.click()
        print("Location filter removed.")

        # Optionally, wait for the filter to disappear after removal
        WebDriverWait(driver, 10).until_not(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-cy='tag-location']"))
        )
        print("Location filter removal confirmed.")

    except TimeoutException:
        print("Location filter not found or could not be removed in time.")

def detect_language(text):
    """Detect the language of the given text.

    Args:
        text: String of text to detect the language.

    Returns:
        Detected language code or 'unknown' if detection fails.
    """
    try:
        return detect(text)
    except:
        return "unknown"

def load_existing_urls(file_path):
    """Load existing URLs from a file.

    Args:
        file_path: Path to the CSV file containing URLs.

    Returns:
        A set of URLs.
    """
    existing_urls = set()
    try:
        with open(file_path, 'r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            headers = next(reader, None)  # Skip the header
            if headers:
                for row in reader:
                    existing_urls.add(row[0])  # Assuming URL is in the first column
    except FileNotFoundError:
        print("File not found, a new one will be created.")
    return existing_urls

def initialize_scraping():
    """Initialize the scraping process.

    Returns:
        A tuple containing a set of existing URLs, a boolean indicating if the file exists, and the WebDriver instance.
    """
    existing_urls = load_existing_urls('job_listings.csv')
    file_exists = os.path.exists('job_listings.csv')
    return existing_urls, file_exists, driver
  
def collect_job_listings(driver, writer, existing_urls):
    """Collect job listings from the web page and write them to a CSV file.

    Args:
        driver: Selenium WebDriver instance.
        writer: CSV writer object.
        existing_urls: Set of URLs already collected.

    Returns:
        Total number of URLs collected.
    """
    total_urls_collected = 0
    current_page = 1

    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(5)

        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "article.sc-0"))
        )

        job_listings = driver.find_elements(By.CSS_SELECTOR, "article.sc-0")
        urls_collected_this_page = 0

        for job in job_listings:
            job_url = job.find_element(By.CSS_SELECTOR, 'a.sc-1').get_attribute('href')
            job_description = job.find_element(By.CSS_SELECTOR, 'p[data-xds="Body"]').text
            language = detect_language(job_description)

            if language == 'en' and job_url not in existing_urls:
                existing_urls.add(job_url)
                writer.writerow([job_url, language, ''])
                total_urls_collected += 1
                urls_collected_this_page += 1

        print(f"Collected {urls_collected_this_page} job listings from page {current_page}. Total collected: {total_urls_collected}")

        if not navigate_to_next_page(driver, current_page):
            break

        current_page += 1

    return total_urls_collected

def navigate_to_next_page(driver, current_page):
    """Navigate to the next page of job listings.

    Args:
        driver: Selenium WebDriver instance.
        current_page: Current page number.

    Returns:
        True if navigation is successful, False otherwise.
    """
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

        print(f"Failed to find button to navigate to page {current_page + 1}.")
        return False

    except NoSuchElementException:
        print("Next page button not found.")
        return False
    except Exception as e:
        print(f"Error occurred while navigating to page {current_page + 1}: {e}")
        return False


def scrape_jobs():
    """Main function to start the job scraping process."""
    print("Starting job scraping...")
    existing_urls, file_exists, driver = initialize_scraping()

    with open('job_listings.csv', 'a' if file_exists else 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(['URL', 'Language', 'Application Sent', 'join_urls'])

        total_urls_collected = collect_job_listings(driver, writer, existing_urls)
        print(f"Job scraping completed. Total URLs collected: {total_urls_collected}")

def visit_english_jobs_and_apply():
    """Visit job listings with English descriptions and attempt to apply."""
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

        job_url, language, application_sent = row[:3]
        if language == 'en' and (application_sent == '' or application_sent == 'error'):
            print(f"Visiting job listing: {job_url}")
            driver.get(job_url)

            try:
                employer_links = WebDriverWait(driver, 7).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a[class='employer-link']"))  
                )
                employer_urls = [link.get_attribute('href') for link in employer_links]
                row[headers.index('employer_urls')] = '|'.join(employer_urls)

                join_com_url = next((url for url in employer_urls if "join.com" in url), '')
                row[headers.index('join_urls')] = join_com_url
                row[2] = 'success' if join_com_url else 'not valid'
                print(f"Status of job listing {job_url}: {'success' if join_com_url else 'not valid'}")
                continue
            except TimeoutException:
                print(f"'Visit employer website' button did not load in time for job listing: {job_url}")
                row[2] = 'error'

            try:
                WebDriverWait(driver, 7).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "button[class='apply-now-button']")) 
                )
                print(f"'Easy apply' button found for job listing: {job_url}")
                row[2] = 'quick_apply'
                continue
            except TimeoutException:
                print(f"'Easy apply' button not found for job listing: {job_url}")

                # Check if the job listing is no longer available
            try:
                expired_message = driver.find_elements(By.XPATH,
                                                       "//h2[contains(text(), 'This job ad is not available.')]")  
                if expired_message:
                    print(f"Job listing {job_url} is no longer available.")
                    row[2] = 'expired'
                    continue
            except NoSuchElementException:
                print(f"Job listing {job_url} is active.")

            finally:
                with open('job_listings.csv', 'w', newline='', encoding='utf-8') as file_to_write:
                    writer = csv.writer(file_to_write)
                    writer.writerow(headers)
                    writer.writerows(data)

def prompt_for_new_jobs():
    """Prompt the user to decide whether to update the job listings."""
    update_jobs = input("Would you like to update the job listings? (yes/no): ")
    if update_jobs.lower() == 'yes':
        print("Updating job listings...")
        scrape_jobs()
    else:
        print("Job listings update canceled.")


def file_exists_and_complete(file_path):
    """Check if the file exists and is complete.

    Args:
        file_path: Path to the CSV file.

    Returns:
        A tuple (file_exists, is_complete) indicating if the file exists and is complete.
    """
    if not os.path.exists(file_path):
        return False, False

    with open(file_path, 'r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        headers = next(reader, None)
        if headers is None or 'Language' not in headers or 'Application Sent' not in headers:
            return True, False

        for row in reader:
            if row[headers.index('Language')] == 'en' and row[headers.index('Application Sent')] == '':
                return True, False  # Found an unprocessed row

        return True, True  # All rows are processed


def xing_easy_apply():
    """Process job listings for easy apply on Xing.com."""
    with open('job_listings.csv', 'r', newline='', encoding='utf-8') as file:
        rows = list(csv.reader(file))
        headers = rows[0]
        data = rows[1:]

    print("Beginning to process jobs on xing.com...")

    for i, row in enumerate(data):
        if len(row) < len(headers):
            row.extend([''] * (len(headers) - len(row)))

        job_url, language, application_sent, join_com_url = row[:4]
        if language == 'en' and application_sent in ['quick_apply', 'error_easy', 'error_form', 'uncertain'] and job_url:
            print(f"Processing job listing on xing.com: {job_url}")
            driver.get(job_url)

            # Check the job status
            try:
                job_status = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "h2[class='job-status']"))  
                ).text
                if job_status == "This job ad isn't available.":
                    print(f"Job listing {job_url} is no longer available.")
                    row[headers.index('Application Sent')] = 'expired'
                    continue
            except TimeoutException:
                print("Job status not found, continuing processing.")

            # Check if already applied to this job
            try:
                application_status = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "div[class='application-status']"))  
                ).text
                if "You applied for this job" in application_status:
                    print(f"Already applied for job listing {job_url}.")
                    row[headers.index('Application Sent')] = 'done'
                    continue
            except TimeoutException:
                print("Application status not found, continuing processing.")

            # Search and click the apply button
            selectors = [
                ".generic-apply-button",  
                "button[class='apply-now-button']",  
                "//button[contains(text(), 'Apply')]",  # XPath selector
                "//button[contains(text(), 'Easy apply')]",  # XPath selector
                "//button[contains(text(), 'Quick apply')]",  # XPath selector
            ]

            clicked = False
            for selector in selectors:
                try:
                    element = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, selector)) if selector.startswith("//") else 
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    if "Apply" in element.text or "Easy apply" in element.text or "Quick apply" in element.text:
                        driver.execute_script("arguments[0].click();", element)
                        time.sleep(random.randint(3, 8))
                        print(f"Button clicked with selector: {selector}")
                        clicked = True
                        break
                except (TimeoutException, NoSuchElementException):
                    print(f"Element with selector '{selector}' not found.")

            if not clicked:
                print("Failed to click any of the buttons.")
                row[headers.index('Application Sent')] = 'error_easy'
                continue

            # ... Remaining code for form filling and submission
            # This part includes interactions with various form elements like dropdowns, inputs, and submission buttons
            # The specifics are omitted for brevity and security purposes

            finally:
                data[i] = row  # Update the data row
                # Update the job listings file
                with open('job_listings.csv', 'w', newline='', encoding='utf-8') as file_to_write:
                    writer = csv.writer(file_to_write)
                    writer.writerow(headers)
                    writer.writerows(data)
