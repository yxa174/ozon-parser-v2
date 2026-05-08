import requests
from bs4 import BeautifulSoup

url = "https://ozon.ru"

html = requests.get(url).text
soup = BeautifulSoup(html, "html.parser")

title = soup.find("h2").text
print(title)
