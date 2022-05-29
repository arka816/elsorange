powershell "start cmd -v runAs"

cd \Program Files\Orange\Scripts
activate

@echo off
conda install -c jmgeiger elsapy
conda install orange3
conda install orange3-text
conda install numpy
conda install pandas
conda install setuptools

@echo on
cd \github\elsevier
pip install -e .
pause
