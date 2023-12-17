import logging

from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service)

# Путь к файлу с куками Xing и Join.com
xing_cookies_file_path = 'xing_cookies.pkl'
join_com_cookies_file_path = 'join_com_cookies.pkl'


EMAIL_XING = ""
PASSWORD_XING = ""

EMAIL_JOIN = ""
PASSWORD_JOIN = ""

TELEPHONE = f"+......."

FIRST_NAME = ""
LAST_NAME = ""

country_code = ''

XING = "https://www.xing.com/profile/....."

LINKEDIN = "https://www.linkedin.com/......"

RESUME_PATH = "C:/Users/........"
cover_letter_path = "/path/to/your_cover_letter.pdf"

db_file_path = 'questions_answers_db.json'

file_path = 'job_listings.csv'

initial_urls = [

 'https://www.xing.com/jobs/search?country=de.02516e&country=ch.e594f5&country=at.ef7781&country=nl.dcbf70&country=pt.09d37b&country=fr.2180e8&keywords=data&page=2&paging_context=global_search&sort=date', #relevance
 'https://www.xing.com/jobs/search?country=de.02516e&country=ch.e594f5&country=at.ef7781&country=nl.dcbf70&country=pt.09d37b&country=fr.2180e8&country=no.283096&country=es.620a64&country=gb.5b1097&keywords=Data%20Engineer&paging_context=global_search&sort=date',
 'https://www.xing.com/jobs/search?country=de.02516e&country=ch.e594f5&country=at.ef7781&country=nl.dcbf70&country=pt.09d37b&country=fr.2180e8&country=no.283096&country=es.620a64&country=gb.5b1097&keywords=Data%20Engineer&paging_context=global_search&remoteOption=FULL_REMOTE.050e26&sort=date',
 'https://www.xing.com/jobs/search?country=de.02516e&country=ch.e594f5&country=at.ef7781&country=nl.dcbf70&country=pt.09d37b&country=fr.2180e8&country=no.283096&country=es.620a64&country=gb.5b1097&keywords=Data%20Engineer&paging_context=global_search&sort=relevance',
'https://www.xing.com/jobs/search?country=de.02516e&country=at.ef7781&country=ch.e594f5&country=es.620a64&country=fr.2180e8&country=nl.dcbf70&country=ro.58eb9d&keywords=Big%20Data%20Engineer',
'https://www.xing.com/jobs/search?country=de.02516e&country=ch.e594f5&country=at.ef7781&keywords=big%20data'

]

# WebDriver settings
TIMEOUT = 10
WAIT_TIME = 5

# Logging settings
LOG_LEVEL = logging.INFO
