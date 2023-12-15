import csv
import json
import logging
import os
import pickle
import re
import time

from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait

from config import *  # Import configuration settings

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def auto_login_on_page(driver, email, password, join_com_cookies_file_path, url):
    """
    Automates the login process on a specified page using Selenium WebDriver.

    :param driver: Selenium WebDriver instance.
    :param email: User's email address for login.
    :param password: User's password for login.
    :param join_com_cookies_file_path: Path to the file where cookies are stored.
    :param url: URL of the page to perform the login.
    """
    logging.info("Starting auto-login process on the page: %s", url)
    driver.get(url)

    # Scroll down the page
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(3)

    if is_logged_in(driver):
        logging.info("Already logged in.")
        return

    # Load cookies if the file exists
    if os.path.exists(join_com_cookies_file_path):
        with open(join_com_cookies_file_path, "rb") as file:
            cookies = pickle.load(file)
        for cookie in cookies:
            driver.add_cookie(cookie)
        driver.refresh()
        if is_logged_in(driver):
            logging.info("Logged in using cookies.")
            return
        else:
            logging.info("Cookies loaded, but not logged in. Starting login process.")
    
    # Scroll down the page
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(3)

    # Handling cookies consent and login
    try:
        handle_cookies_consent(driver)
        perform_login(driver, email, password)
        # Save cookies after successful login
        with open(join_com_cookies_file_path, "wb") as file:
            pickle.dump(driver.get_cookies(), file)
        logging.info("Cookies saved after login.")
    except Exception as e:
        logging.error("Error during login: %s", e)

def handle_cookies_consent(driver):
    """
    Handles the cookie consent popup if it appears on the page.

    :param driver: Selenium WebDriver instance.
    """
    try:
        accept_cookies_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "cookiescript_accept"))
        )
        accept_cookies_button.click()
        logging.info("Cookie consent button clicked.")
        time.sleep(1)
    except (NoSuchElementException, TimeoutException):
        logging.warning("Cookie consent button not found or did not load in time.")


def perform_login(driver, email, password):
    """
    Performs the login process by entering email and password and submitting the form.

    :param driver: Selenium WebDriver instance.
    :param email: User's email address for login.
    :param password: User's password for login.
    """
    try:
        email_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "email"))
        )
        email_input.send_keys(email)
        login_with_password_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.sc-jTrPJq.giJXpC"))
        )
        login_with_password_button.click()
        password_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "password"))
        )
        password_input.send_keys(password)
        submit_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']"))
        )
        submit_button.click()
        logging.info("Attempted to log in.")
    except Exception as e:
        logging.error("Error during login attempt: %s", e)


def is_logged_in(driver):
    """
    Checks if the user is already logged in by looking for specific elements on the page.

    :param driver: Selenium WebDriver instance.
    :return: True if logged in, False otherwise.
    """
    logging.info("Checking user's login status.")
    elements_to_check = [
        "a[data-testid='ViewApplicationLink']",  # "View Application" link
        "div[data-testid='ViewApplicationLink']",
        "div[data-testid='AuthorizedCandidateLink']",  # Link to the authorized user's profile
        "a[data-testid='AuthorizedCandidateLink']",
        "a[data-testid='AuthorizedCandidateOnePagerLink']",
        "div[data-testid='AuthorizedCandidateOnePagerLink']",
        "a[data-testid='CompleteApplicationLink']",
        "div[data-testid='CompleteApplicationLink']",
    ]

    for selector in elements_to_check:
        if driver.find_elements(By.CSS_SELECTOR, selector):
            logging.info("Authorization confirmed.")
            return True

    logging.info("Authorization not confirmed.")
    return False


def upload_resume_if_needed(driver, resume_path):
    """
    Checks if resume upload is necessary and performs the upload.

    :param driver: Selenium WebDriver instance.
    :param resume_path: Path to the resume file.
    """
    logging.info("Checking the need to upload a resume.")
    try:
        remove_existing_resume(driver)
        upload_new_resume(driver, resume_path)
    except TimeoutException:
        logging.warning("Failed to find elements for resume upload.")
    except Exception as e:
        logging.error("Error during resume upload: %s", e)

def remove_existing_resume(driver):
    """
    Removes an existing resume if found.

    :param driver: Selenium WebDriver instance.
    """
    try:
        remove_button = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='RemoveButton']"))
        )
        remove_button.click()
        logging.info("Existing resume removed.")
    except TimeoutException:
        logging.info("No existing resume found.")


def upload_new_resume(driver, resume_path):
    """
    Uploads a new resume from the specified path.

    :param driver: Selenium WebDriver instance.
    :param resume_path: Path to the resume file.
    """
    resume_input = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR,
             "div[data-testid='ResumeField'] input[type='file'][accept='.doc, .docx, .pdf, .rtf, .txt']"))
    )
    resume_input.send_keys(resume_path)
    time.sleep(5)  # Pause to allow file upload to complete
    logging.info("Resume uploaded.")


def upload_cover_letter_if_needed(driver, cover_letter_path):
    """
    Checks if a cover letter upload is necessary and performs the upload.

    :param driver: Selenium WebDriver instance.
    :param cover_letter_path: Path to the cover letter file.
    """
    logging.info("Checking the need to upload a cover letter.")
    try:
        if check_existing_cover_letter(driver):
            return
        upload_cover_letter(driver, cover_letter_path)
    except TimeoutException:
        logging.warning("Failed to find elements for cover letter upload.")
    except Exception as e:
        logging.error("Error during cover letter upload: %s", e)


def check_existing_cover_letter(driver):
    """
    Checks if a cover letter is already uploaded.

    :param driver: Selenium WebDriver instance.
    :return: True if a cover letter is already uploaded, False otherwise.
    """
    existing_letter = driver.find_elements(By.CSS_SELECTOR,
                                           "div[data-testid='CoverLetterField'] i[name='CheckCircleFilledIcon']")
    if existing_letter:
        logging.info("Cover letter already uploaded.")
        return True
    return False

def upload_cover_letter(driver, cover_letter_path):
    """
    Uploads a cover letter from the specified path.

    :param driver: Selenium WebDriver instance.
    :param cover_letter_path: Path to the cover letter file.
    """
    cover_letter_input = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file'][accept='.doc, .docx, .pdf, .rtf, .txt']"))
    )
    # cover_letter_input.send_keys(cover_letter_path) # Commented out for example
    logging.info("Cover letter supposedly uploaded.")  # Example log message


def submit_application(driver):
    """
    Initiates the application submission process.

    :param driver: Selenium WebDriver instance.
    :return: The result of the submission process.
    """
    logging.info("Beginning the application submission process.")
    max_attempts = 3  # Maximum number of click attempts

    for attempt in range(1, max_attempts + 1):
        try:
            find_and_click_submit_button(driver)
            time.sleep(5)  # Waiting for the page to update
            return check_submission_status(driver)

        except ElementClickInterceptedException:
            if attempt == max_attempts:
                logging.error("Submit button not clickable after several attempts.")
                return "error"
            logging.warning(f"Button not clicked, attempt {attempt} of {max_attempts}.")
            time.sleep(2)  # Brief pause before the next attempt

        except NoSuchElementException:
            logging.error("Submit button not found.")
            return "error"

        except TimeoutException:
            logging.error("Failed to load page after submission.")
            return "timeout"

    return "error"  # Return "error" if none of the attempts were successful


def find_and_click_submit_button(driver):
    """
    Finds and clicks the submit button on the page.

    :param driver: Selenium WebDriver instance.
    :return: The submit button element.
    """
    submit_button = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit'].sc-jTrPJq.cFoMez"))
    )
    driver.execute_script("arguments[0].click();", submit_button)
    logging.info("Submit button clicked using JavaScript.")
    return submit_button

def wait_for_submission_result(driver, timeout=20):
    """
    Waits for the result of the submission process.

    :param driver: Selenium WebDriver instance.
    :param timeout: Maximum wait time in seconds.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not driver.find_elements(By.CSS_SELECTOR, "div[data-testid='ResumeField'] input[type='file']"):
            logging.info("Page updated after form submission.")
            return
        time.sleep(0.5)  # Delay to avoid active waiting
    logging.error("Timeout while waiting for changes on the page.")


def check_submission_status(driver):
    """
    Checks the status of the application submission.

    :param driver: Selenium WebDriver instance.
    :return: The status of the submission.
    """
    try:
        # Explicitly waiting for the success icon
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//i[contains(@name, 'FlashIcon')]"))
        )
        logging.info("Application successfully submitted. End of process.")
        return "done"
    except TimeoutException:
        # Explicitly waiting for the additional information required icon
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//i[contains(@class, 'sc-iAEyYk') and contains(@class, 'dLwNpu')]/svg[@name='CheckCircleIcon']")
                )
            )
            logging.info("Application submitted but additional information is required.")
            return "form"
        except TimeoutException:
            logging.warning("Submission status unknown.")
            return "unknown"


def is_application_successful_page(driver):
    """
    Checks for elements indicating a successful application submission.

    :param driver: Selenium WebDriver instance.
    :return: True if successful submission elements are found, False otherwise.
    """
    try:
        logging.info("Checking for elements indicating a successful application submission.")
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".jiFMRi"))
        )
        logging.info("Elements of successful application submission detected.")
        return True
    except TimeoutException:
        logging.warning("Elements of successful application submission not detected.")
        return False


def read_job_listings(file_path):
    """
    Reads job listings from a CSV file.

    :param file_path: Path to the CSV file.
    :return: List of rows from the file.
    """
    with open(file_path, 'r', newline='', encoding='utf-8') as file:
        rows = list(csv.reader(file))
    return rows  # Returns a list of rows from the file


def write_job_listings(file_path, headers, data):
    """
    Writes job listings to a CSV file.

    :param file_path: Path to the CSV file.
    :param headers: Column headers for the CSV.
    :param data: Data to be written to the CSV.
    """
    with open(file_path, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(data)


def process_job(row, headers, driver, questions_answers_db):
    """
    Processes a single job listing.

    :param row: The job listing data row.
    :param headers: Column headers for the job listings.
    :param driver: Selenium WebDriver instance.
    :param questions_answers_db: Database of questions and answers for dynamic forms.
    :return: The updated job listing row.
    """
    job_url, language, application_sent, join_com_url = row[:4]

    if not join_com_url:  # Check for empty or missing URL
        logging.warning("URL is missing")
        return row

    # Skip processing if the job does not meet the criteria
    if not (language == 'en' and application_sent not in ['done', 'not valid', 'expired']):
        return row

    logging.info(f"Processing job on join.com: {join_com_url}")
    driver.get(join_com_url)

    # Check if the job listing is archived
    try:
        WebDriverWait(driver, 6).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".sc-hLseeU.Lgmbz"))
        )
        logging.info("Job listing is archived. Moving to the next one.")
        row[headers.index('Application Sent')] = 'expired'
        return row
    except TimeoutException:
        logging.info("Job listing is active. Continuing processing.")

    # Check and perform login if required
    auto_login_on_page(driver, EMAIL_JOIN, PASSWORD_JOIN, join_com_cookies_file_path, join_com_url)

    # Check for the "Complete Application" button
    try:
        WebDriverWait(driver, 6).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[data-testid='CompleteApplicationLink']"))
        )
        complete_app_button = driver.find_element(By.CSS_SELECTOR, "a[data-testid='CompleteApplicationLink']")
        complete_app_button.click()
        logging.info("Moved to completing the unfinished application.")
        fill_dynamic_form(driver, questions_answers_db, db_file_path)
        row[headers.index('Application Sent')] = 'form submitted'
        return row
    except TimeoutException:
        logging.info("'Complete Application' button not found, continuing processing.")

    # Add waiting for the appearance of the "View Application" link
    try:
        WebDriverWait(driver, 6).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 "//a[@data-testid='ViewApplicationLink' and contains(@href, 'https://join.com/candidate/applications/')]"))
        )
        logging.info("Application for this job listing is already submitted.")
        row[headers.index('Application Sent')] = 'done'
        return row
    except TimeoutException:
        logging.info("Link to view the submitted application not found, continuing processing.")

    # Upload resume and cover letter if needed
    upload_resume_if_needed(driver, RESUME_PATH)
    upload_cover_letter_if_needed(driver, cover_letter_path)

    # Submit the application
    response = submit_application(driver)

    # Check the result of the application submission
    if response == "done":
        if is_application_successful_page(driver):
            logging.info("Application successfully submitted and confirmed.")
            row[headers.index('Application Sent')] = 'done'
    elif response == "form":
        # Need to fill out an additional form
        fill_dynamic_form(driver, questions_answers_db, db_file_path)
        row[headers.index('Application Sent')] = 'form submitted'
    elif response in ["error", "timeout"]:
        # An error occurred during the application submission
        logging.error(f"Error in submitting the application: {response}")
        row[headers.index('Application Sent')] = response

    return row  # Return the updated row


def process_join_com_jobs(questions_answers_db, file_path):
    """
    Processes job listings on join.com.

    :param questions_answers_db: Database of questions and answers for dynamic forms.
    :param file_path: Path to the CSV file containing job listings.
    """
    logging.info("Starting processing of jobs on join.com...")
    rows = read_job_listings(file_path)
    headers = rows[0]
    data = rows[1:]

    for i, row in enumerate(data):
        if len(row) < len(headers):
            row += [''] * (len(headers) - len(row))
        updated_row = process_job(row, headers, driver, questions_answers_db)
        data[i] = updated_row

        # Update the file after processing each job listing
        write_job_listings(file_path, headers, data)

        # time.sleep(2)  # Delay to avoid too rapid requests

    logging.info("Job processing completed.")


def fill_dynamic_form(driver, questions_answers_db, db_file_path):
    """
    Fills a dynamic form based on a database of questions and answers.

    :param driver: Selenium WebDriver instance.
    :param questions_answers_db: Database of questions and answers.
    :param db_file_path: Path to the database file.
    """
    question_items = driver.find_elements(By.CSS_SELECTOR, "[data-testid='QuestionItem']")

    for item in question_items:
        question_text = ""
        try:
            # Attempt to find the question text in different elements
            question_text_element = item.find_element(By.CSS_SELECTOR, "span")
            question_text = question_text_element.text if question_text_element.text else item.text

            logging.info(f"Processing question: {question_text}")

            answer = questions_answers_db.get(question_text) or match_question_and_provide_answer(question_text, questions_answers_db)

            if answer:
                process_answer(driver, item, answer, question_text)
                click_outside_of_input_field(driver)  # Click outside the input field to close any popups
            else:
                handle_no_answer(item, questions_answers_db, question_text, db_file_path)

        except NoSuchElementException:
            logging.error(f"Question '{question_text}' not found on the page")

    time.sleep(2)
    check_required_fields(driver, questions_answers_db, db_file_path)
    submit_form(driver)


def click_outside_of_input_field(driver):
    """
    Clicks outside an input field to close any open popups.

    :param driver: Selenium WebDriver instance.
    """
    background_element = driver.find_element(By.TAG_NAME, 'body')
    background_element.click()


def process_answer(driver, item, answer, question_text):
    """
    Processes an answer by filling out the form element.

    :param driver: Selenium WebDriver instance.
    :param item: The form element to be filled.
    :param answer: The answer to be used for filling out the form element.
    :param question_text: The text of the question associated with the form element.
    """
    try:
        fill_field(item, answer)
        logging.info(f"Answer for the question '{question_text}': {answer}")
    except Exception as e:
        logging.error(f"Error filling out answer for {question_text}: {e}")


def handle_no_answer(item, questions_answers_db, question_text, db_file_path):
    """
    Handles cases where no answer is found in the database.

    :param item: The form element.
    :param questions_answers_db: Database of questions and answers.
    :param question_text: The text of the question.
    :param db_file_path: Path to the database file.
    """
    user_answer_format = "Enter your answer: "
    if "checkbox" in item.get_attribute("outerHTML"):
        user_answer_format = "Enter your answer (for multiple choices use format: 'answer1, answer2'): "

    user_answer = input(user_answer_format)
    questions_answers_db[question_text] = user_answer
    fill_field(item, user_answer)
    save_questions_answers_db(db_file_path, questions_answers_db)


def check_required_fields(driver, questions_answers_db, db_file_path):
    """
    Checks and fills out any required fields that are empty.

    :param driver: Selenium WebDriver instance.
    :param questions_answers_db: Database of questions and answers.
    :param db_file_path: Path to the database file.
    """
    required_field_markers = driver.find_elements(By.CSS_SELECTOR, ".LtUSx")

    for marker in required_field_markers:
        question_item = marker.find_element(By.XPATH, "ancestor::div[@data-testid='QuestionItem']")
        input_fields = question_item.find_elements(By.CSS_SELECTOR, "input, textarea, select")

        for input_field in input_fields:
            if input_field.tag_name in ["input", "textarea"]:
                if not input_field.get_attribute('value').strip():
                    logging.warning(f"Required text field not filled: {marker.text}")
                    user_input = input("Enter value for the field: ")
                    questions_answers_db[marker.text] = user_input
                    log_and_send_keys(input_field, user_input)
            elif input_field.tag_name == "select":
                if not Select(input_field).first_selected_option.get_attribute('value').strip():
                    logging.warning(f"No value selected in dropdown: {marker.text}")
                    # Logic to handle dropdown selection could go here

        time.sleep(1)

    save_questions_answers_db(db_file_path, questions_answers_db)


def submit_form(driver):
    """
    Attempts to submit the form.

    :param driver: Selenium WebDriver instance.
    """
    try:
        submit_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
        )
        driver.execute_script("arguments[0].scrollIntoView();", submit_button)
        submit_button.click()
        logging.info("Submit button clicked.")
    except TimeoutException:
        logging.error("Failed to find the submit button. Retry...")
        try:
            submit_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            driver.execute_script("arguments[0].click();", submit_button)
            logging.info("Submit button clicked (retry).")
        except Exception as e:
            logging.error(f"Failed to click submit button: {e}")
            input("Check the page and press Enter to continue...")
    time.sleep(5)


def log_and_click(element):
    """
    Logs and clicks on a specified element.

    :param element: The web element to be clicked.
    """
    try:
        element.click()
        logging.info("Clicked on element: %s", element)
    except Exception as e:
        logging.error("Error clicking on element: %s", e)


def log_and_send_keys(element, keys):
    """
    Logs and sends keys to a specified element.

    :param element: The web element to send keys to.
    :param keys: The keys to send.
    """
    try:
        element.clear()
        element.send_keys(keys)
        logging.info("Sent keys '%s' to element: %s", keys, element)
    except Exception as e:
        logging.error("Error sending keys to element: %s", e)

def find_and_fill_text_input(driver, item, answer):
    """
    Finds and fills a text input or textarea within the specified item.

    :param driver: Selenium WebDriver instance.
    :param item: The web element containing the text input.
    :param answer: The text to be entered into the input field.
    :return: True if a text input is found and filled, False otherwise.
    """
    text_inputs = item.find_elements(By.CSS_SELECTOR, "input[type='text'], textarea")
    if text_inputs:
        log_and_send_keys(text_inputs[0], answer)
        # Additional step to close the calendar if it's opened
        close_calendar(driver)
        return True
    return False


def close_calendar(driver):
    """
    Closes a calendar popup by clicking outside its area.

    :param driver: Selenium WebDriver instance.
    """
    # Might need to select a suitable element or use a different method
    body_element = driver.find_element(By.CSS_SELECTOR, 'body')
    driver.execute_script("arguments[0].click();", body_element)


def find_and_click_radio_button(item, answer):
    """
    Finds and clicks a radio button based on its label text.

    :param item: The web element containing the radio buttons.
    :param answer: The label text of the radio button to be clicked.
    :return: True if a matching radio button is found and clicked, False otherwise.
    """
    radio_labels = item.find_elements(By.CSS_SELECTOR, "label[data-testid='radio']")
    for label in radio_labels:
        radio_text = label.find_element(By.CSS_SELECTOR, "[data-testid='RadioLabel']").text.strip().lower()
        if radio_text == answer.lower():
            log_and_click(label)
            return True
    return False


def find_and_click_checkbox(item, answer):
    """
    Finds and clicks checkboxes based on their label texts.

    :param item: The web element containing the checkboxes.
    :param answer: A comma-separated string of checkbox label texts to be clicked.
    :return: True if all specified checkboxes are found and clicked, False otherwise.
    """
    checkbox_labels = item.find_elements(By.CSS_SELECTOR, "label[data-testid='checkbox']")
    answers = [ans.strip().lower() for ans in answer.split(",")]
    for label in checkbox_labels:
        checkbox_text = label.find_element(By.CSS_SELECTOR, "[data-testid='CheckboxLabel']").text.strip().lower()
        if checkbox_text in answers:
            log_and_click(label)
            return True
    return False


def find_and_click_yes_no_answer(item, answer):
    """
    Finds and clicks a 'Yes' or 'No' answer based on the specified answer.

    :param item: The web element containing the Yes/No answers.
    :param answer: The answer ('Yes' or 'No') to be clicked.
    :return: True if the specified answer is found and clicked, False otherwise.
    """
    yes_no_answers = item.find_elements(By.CSS_SELECTOR, "[data-testid='YesAnswer'], [data-testid='NoAnswer']")
    for element in yes_no_answers:
        text = element.text.strip().lower()
        if text == answer.lower():
            log_and_click(element)
            return True
    return False


def fill_field(driver, item, answer):
    """
    Fills a field based on its type (text input, radio button, checkbox, or Yes/No answer).

    :param driver: Selenium WebDriver instance.
    :param item: The web element containing the field to be filled.
    :param answer: The answer or text to be used for filling out the field.
    """
    if find_and_fill_text_input(driver, item, answer):
        return
    if find_and_click_radio_button(item, answer):
        return
    if find_and_click_checkbox(item, answer):
        return
    if find_and_click_yes_no_answer(item, answer):
        return

    logging.warning("Failed to fill the field for the question: %s", item.text)

def click_element_via_script(driver, element):
    """
    Clicks on an element using JavaScript.

    :param driver: Selenium WebDriver instance.
    :param element: The element to be clicked.
    """
    driver.execute_script("arguments[0].click();", element)

def match_question_and_provide_answer(question_text, questions_answers_db):
    """
    Attempts to find an answer to a question directly from the question text.

    :param question_text: The text of the question to find an answer for.
    :param questions_answers_db: The database of questions and their corresponding answers.
    :return: The answer if found, None otherwise.
    """
    answer = questions_answers_db.get(question_text)

    if answer:
        logging.info(f"Answer found for the question: {question_text}")
        return answer
    else:
        logging.info(f"No answer found for the question: {question_text}")
        return None

def save_questions_answers_db(file_path, db):
    """
    Saves the database of questions and answers to a file.

    :param file_path: Path to the file where the database will be saved.
    :param db: The database of questions and answers to be saved.
    """
    try:
        with open(file_path, 'w') as file:
            json.dump(db, file, indent=4)
        logging.info(f"Database successfully saved to file: {file_path}")
    except Exception as e:
        logging.error(f"Error saving the database: {e}")


def load_questions_answers_db(file_path):
    """
    Loads a database of questions and answers from a file.

    :param file_path: Path to the file from which the database will be loaded.
    :return: The loaded database, or an empty dictionary if the file is not found or has an invalid format.
    """
    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
            logging.info(f"Database successfully loaded from file: {file_path}")
            return data
    except FileNotFoundError:
        logging.warning(f"File not found: {file_path}. Returning an empty dictionary.")
        return {}  # Returns an empty dictionary if the file is not found
    except json.JSONDecodeError:
        logging.error(f"Error reading file: {file_path}. Invalid JSON format.")
        return {}




