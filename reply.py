import csv
import time
from langdetect import detect
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from config import driver, RESUME_PATH, EMAIL, TELEPHONE, FIRST_NAME, LAST_NAME, XING, LINKEDIN

# Load the list of job listings from a file
with open('job_listings.csv', 'r', newline='', encoding='utf-8') as file:
    rows = list(csv.reader(file))
    headers = rows[0]
    data = rows[1:]

print("Starting processing of job listings on reply.com...")

for i, row in enumerate(data):
    if len(row) < len(headers):
        row += [''] * (len(headers) - len(row))

    job_url, language, application_sent, join_com_url, employer_urls = row[:5]

    if language == 'en' and application_sent != 'done' and application_sent != 'not suitable' and employer_urls.startswith("https://www.reply.com/"):
        print(f"Processing job listing: {employer_urls}")

        # Visit the job listing page
        driver.get(employer_urls)
        time.sleep(5)

        try:
            # Check for a 404 page
            if len(driver.find_elements(By.XPATH, "//h1[contains(text(), '404')]")) > 0:
                print(f"Job listing page {job_url} not found (404).")
                row[headers.index('Application Sent')] = 'expired'
                continue
        except Exception as e:
            print(f"Error occurred while processing the job listing: {e}")
            row[headers.index('Application Sent')] = 'error'

        # Check for the "Jetzt bewerben" button
        try:
            apply_button = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//button[contains(., 'Jetzt bewerben')]"))
            )
            print(f"'Jetzt bewerben' button found on the page {job_url}.")

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            # Wait for the job description to appear
            description_element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "article.job-details__section"))
            )
            description_text = description_element.text

            # Check the language of the job description
            if detect(description_text) != 'en':
                print("Job description is not in English.")
                row[headers.index('Application Sent')] = 'not suitable'
                continue

            # Process and submit application
            # Code for submitting application...

            # Mark the record as 'future' or 'done' depending on the outcome
            row[headers.index('Application Sent')] = 'future'  # or 'done'

        except TimeoutException:
            print("Job description not found.")
            row[headers.index('Application Sent')] = 'error'

        # Check for the presence of the form
        try:
            # Smooth scrolling
            for j in range(0, 1000, 100):
                driver.execute_script(f"window.scrollTo(0, {j});")
                time.sleep(0.5)

            form_present = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "form[method='dialog']"))
            )
            print("Form is present on the page.")

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            try:
                cookie_accept_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
                )
                cookie_accept_button.click()
                time.sleep(2)  # Adding a delay after clicking the button
            except TimeoutException:
                print("Cookie accept button not found.")

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            # Fill out the form
            driver.find_element(By.NAME, "firstName").send_keys(FIRST_NAME)
            time.sleep(3)
            driver.find_element(By.NAME, "lastName").send_keys(LAST_NAME)
            driver.find_element(By.NAME, "email").send_keys(EMAIL)
            driver.find_element(By.NAME, "telephone").send_keys(TELEPHONE)
            driver.find_element(By.NAME, "cv").send_keys(RESUME_PATH)
            time.sleep(3)
            driver.find_element(By.NAME, "xing").send_keys(XING)
            driver.find_element(By.NAME, "linkedin").send_keys(LINKEDIN)

            # Activate the checkbox
            checkbox = driver.find_element(By.NAME, "consent")
            if not checkbox.is_selected():
                checkbox.click()

            # Submit the form
            driver.find_element(By.XPATH, "//button[contains(., 'Bewirb dich jetzt')]").click()
            print("Form submitted.")
            time.sleep(3)

            # Mark the record as 'done'
            row[headers.index('Application Sent')] = 'done'

        except TimeoutException:
            print("Form for filling out not found.")
            row[headers.index('Application Sent')] = 'error'

        finally:
            data[i] = row
            # Rewrite the CSV file with updated data
            with open('job_listings.csv', 'w', newline='', encoding='utf-8') as file_to_write:
                writer = csv.writer(file_to_write)
                writer.writerow(headers)
                writer.writerows(data)
