powershell "start cmd -v runAs"

cd \Program Files\Orange\Scripts
activate

@REM @echo off
conda config --set channel_priority false
conda install -y -c jmgeiger elsapy
conda install -y orange3
conda install -y orange3-text
conda install -y numpy
conda install -y pandas
conda install -y setuptools
conda install -y selenium
conda install -c conda-forge -y  tldextract
conda install -c conda-forge -y python-decouple
conda install -c bjrn -y webdriver_manager
conda install -c conda-forge -y watchdog
conda install -c conda-forge -y pypdf2

@REM @echo on
cd %~d0%
pip install -e .
deactivate
echo "finished installing elsorange"
pause
