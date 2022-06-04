powershell "start cmd -v runAs"

cd \Program Files\Orange\Scripts
activate

@REM @echo off
conda config --set channel_priority false
conda install -c jmgeiger elsapy
conda install orange3
conda install orange3-text
conda install numpy
conda install pandas
conda install setuptools
conda install -c conda-forge tldextract
conda install selenium
conda install -c bjrn webdriver_manager
conda install -c conda-forge watchdog
conda install -c conda-forge pypdf2

@REM @echo on
cd %~d0%
pip install -e .
deactivate
echo "finished installing elsorange"
pause
