import os

# set up path for chromedriver as an environment variable
chromedriverPath = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "chromedriver.exe")
os.environ['CHROMEDRIVER_PATH'] = chromedriverPath
