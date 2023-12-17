from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from config import *
from join import *
from xing import *

start_scraping_process()
login()
visit_english_jobs_and_apply()
xing_easy_apply()
process_join_com_jobs(questions_answers_db, file_path)
