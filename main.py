from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from config import file_path
from join import process_join_com_jobs, questions_answers_db
from softgarden import search_and_collect_jobs
from xing import ensure_login_and_navigate_to_jobs, scrape_jobs, visit_english_jobs_and_apply, xing_easy_apply, login, \
    start_scraping_process
